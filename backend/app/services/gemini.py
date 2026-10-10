from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.models.schemas import GeminiCounselRequest, GeminiCounselResponse
from app.services.language import local_counsel

API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash').strip()
BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/models'

RESPONSE_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'summary': {'type': 'STRING'},
        'risk_explanation': {'type': 'STRING'},
        'counselling_script': {'type': 'STRING'},
        'recommended_next_step': {'type': 'STRING'},
        'referral_required': {'type': 'BOOLEAN'},
        'urgency': {'type': 'STRING', 'enum': ['ROUTINE_REVIEW', 'PROMPT_CLINICIAN_REVIEW', 'HIGH_PRIORITY_REVIEW', 'DEMO_ONLY']},
        'language': {'type': 'STRING', 'enum': ['en', 'hi', 'bho']},
        'safety_note': {'type': 'STRING'},
    },
    'required': ['summary', 'risk_explanation', 'counselling_script', 'recommended_next_step', 'referral_required', 'urgency', 'language', 'safety_note'],
}

# Phrases suggesting a diagnosis/treatment claim or fabricated biomarker output force a deterministic fallback.
_UNSAFE = re.compile(r'\b(cure|diagnosed with|you have (?:anemia|anaemia|jaundice)|this is (?:anemia|anaemia|jaundice)|confirmed anemia|confirmed anaemia|confirmed jaundice|prescribe|take \d+|\d+\s*mg|start medication|stop medication|normal result|all clear|no disease)\b', re.I)
_UNSAFE_HI = re.compile(r'(पक्का निदान|दवा की खुराक|मिलीग्राम|ठीक हो गया|कोई बीमारी नहीं|सब सामान्य)')


def gemini_configured() -> bool:
    return bool(API_KEY)


def _fallback(req: GeminiCounselRequest) -> GeminiCounselResponse:
    body = local_counsel(req.screening_type, req.language, req.risk_category)
    body['mode'] = 'LOCAL_FALLBACK'
    return GeminiCounselResponse(**body)


def _safe_text(text: Any) -> bool:
    value = str(text or '')
    return len(value) <= 1400 and not _UNSAFE.search(value) and not _UNSAFE_HI.search(value)


def parse_gemini_text(text: str, expected_language: str, screening_type: str, risk_category: str) -> GeminiCounselResponse | None:
    try:
        raw = str(text).strip().replace('```json', '').replace('```', '').strip()
        start, end = raw.find('{'), raw.rfind('}')
        if start < 0 or end < start:
            return None
        payload = json.loads(raw[start:end + 1])
        for key in ('summary', 'risk_explanation', 'counselling_script', 'recommended_next_step', 'safety_note'):
            if not _safe_text(payload.get(key)):
                return None
        if payload.get('language') != expected_language:
            return None
        if str(payload.get('urgency')) not in {'ROUTINE_REVIEW', 'PROMPT_CLINICIAN_REVIEW', 'HIGH_PRIORITY_REVIEW', 'DEMO_ONLY'}:
            return None
        payload['mode'] = 'GEMINI'
        response = GeminiCounselResponse.model_validate(payload)
        # Risk flags cannot be lowered by the model.
        risk = risk_category.upper()
        if any(flag in risk for flag in ('HIGH', 'ESCALATE', 'REVIEW')):
            response.referral_required = True
            response.urgency = 'DEMO_ONLY' if risk.startswith('DEMO') else 'PROMPT_CLINICIAN_REVIEW'
        return response
    except (ValueError, TypeError, ValidationError, KeyError):
        return None


async def counsel(req: GeminiCounselRequest) -> GeminiCounselResponse:
    # Personal identifiers and images are not accepted by this request schema.
    if not API_KEY:
        return _fallback(req)
    language_names = {'en': 'English', 'hi': 'Hindi', 'bho': 'Bhojpuri'}
    minimal_context = {
        'screening_type': req.screening_type,
        'prototype_estimate': req.estimate,
        'unit': req.unit,
        'demo_risk_tag': req.risk_category,
        'confidence_score': req.confidence,
        'quality_score': req.quality_score,
        'pregnancy': req.pregnancy,
        'gestational_week': req.gestational_week,
        'infant_age_hours': req.infant_age_hours,
    }
    prompt = (
        'You are a cautious counseling-language assistant in a hackathon prototype, not a clinician. '
        'Use only the supplied structured fields. The numeric estimate and category are synthetic prototype/demo values, not clinical truth. '
        'Never diagnose, invent symptoms/history, invent a measurement, provide medication advice or dosing, or override a clinician. '
        'Explain that clinical confirmation and local protocol are required. For neonatal jaundice, do not infer urgency from a bilirubin number alone; age in hours and clinical context matter. '
        f'Write entirely in {language_names.get(req.language, "English")}. Use short, clear language for a community health worker. '
        'Return only the requested JSON object.'
    )
    body = {
        'systemInstruction': {'parts': [{'text': prompt}]},
        'contents': [{'role': 'user', 'parts': [{'text': json.dumps(minimal_context, ensure_ascii=False)}]}],
        'generationConfig': {'temperature': 0.15, 'maxOutputTokens': 420, 'responseMimeType': 'application/json', 'responseSchema': RESPONSE_SCHEMA},
    }
    url = f'{BASE_URL}/{quote(MODEL, safe="")}:generateContent'
    try:
        async with httpx.AsyncClient(timeout=18.0) as client:
            response = await client.post(url, headers={'Content-Type': 'application/json', 'x-goog-api-key': API_KEY}, json=body)
        if response.status_code != 200:
            return _fallback(req)
        data = response.json()
        text = ''.join(part.get('text', '') for part in data.get('candidates', [{}])[0].get('content', {}).get('parts', []))
        parsed = parse_gemini_text(text, req.language, req.screening_type, req.risk_category)
        return parsed if parsed is not None else _fallback(req)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return _fallback(req)
