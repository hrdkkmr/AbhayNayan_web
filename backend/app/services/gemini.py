"""Optional server-side Gemini wording for non-diagnostic counselling.

Safety-critical content (urgency, referral flag, next step, safety note) always comes from the
deterministic reviewed copy in `language.py`; Gemini may only reword the explanatory text.
Every request records provider-reported token usage (never prompts, outputs, or keys).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.models.schemas import GeminiCounselRequest, GeminiCounselResponse
from app.services import store
from app.services.language import local_counsel

logger = logging.getLogger('abhaynayan.gemini')

API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
# No default model ID: an operator must choose one from current provider documentation.
MODEL = os.getenv('GEMINI_MODEL', '').strip()
BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/models'
# Measured 10 Oct 2026 on gemini-3.8-flash: 8-20+ s (Hindi/Bhojpuri slower) and ~550-920 thinking tokens per counselling call.
# Thinking tokens count against maxOutputTokens, so 512 truncated every answer (finishReason MAX_TOKENS).
TIMEOUT_SECONDS = float(os.getenv('GEMINI_TIMEOUT_SECONDS', '25') or 25)
MAX_OUTPUT_TOKENS = int(os.getenv('GEMINI_MAX_OUTPUT_TOKENS', '2048') or 2048)
MODEL_CHECK_TTL_OK = 600.0
MODEL_CHECK_TTL_FAIL = 60.0
IDEMPOTENCY_TTL = 900.0
DEMO_CACHE_TTL = 6 * 3600.0
REWORDABLE = ('summary', 'risk_explanation', 'counselling_script')

RESPONSE_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'summary': {'type': 'STRING'},
        'risk_explanation': {'type': 'STRING'},
        'counselling_script': {'type': 'STRING'},
        'language': {'type': 'STRING', 'enum': ['en', 'hi', 'bho']},
    },
    'required': ['summary', 'risk_explanation', 'counselling_script', 'language'],
}

# Phrases suggesting a diagnosis/treatment claim or fabricated biomarker output force a deterministic fallback.
# Dose patterns ("50 mg") are blocked, but the bilirubin unit itself ("12.8 mg/dL") is allowed.
_UNSAFE = re.compile(r'\b(cure|diagnosed with|you have (?:anemia|anaemia|jaundice)|this is (?:anemia|anaemia|jaundice)|confirmed anemia|confirmed anaemia|confirmed jaundice|prescribe|take \d+|\d+\s*mg(?!\s*/\s*d[Ll])|start medication|stop medication|normal result|all clear|no disease)\b', re.I)
_UNSAFE_HI = re.compile(r'(पक्का निदान|दवा की खुराक|मिलीग्राम(?!\s*(?:प्रति|/)\s*(?:डेसीलीटर|डीएल|dL))|ठीक हो गया|कोई बीमारी नहीं|सब सामान्य)')
_DEVANAGARI = re.compile(r'[ऀ-ॿ]')

_model_check: dict[str, Any] = {}
_idempotent: dict[str, tuple[float, GeminiCounselResponse]] = {}
_inflight: dict[str, asyncio.Future] = {}
_demo_cache: dict[str, tuple[float, GeminiCounselResponse]] = {}


def gemini_configured() -> bool:
    return bool(API_KEY)


def model_configured() -> bool:
    return bool(MODEL)


def reset_state() -> None:
    """Clear in-memory caches (tests and configuration changes)."""
    _model_check.clear(); _idempotent.clear(); _inflight.clear(); _demo_cache.clear()


def _fallback(req: GeminiCounselRequest, reason: str) -> GeminiCounselResponse:
    body = local_counsel(req.screening_type, req.language, req.risk_category)
    body['mode'] = 'LOCAL_FALLBACK'
    body['fallback_reason'] = reason
    return GeminiCounselResponse(**body)


def _safe_text(text: Any) -> bool:
    value = str(text or '')
    return 0 < len(value.strip()) <= 1400 and not _UNSAFE.search(value) and not _UNSAFE_HI.search(value)


def _parse(text: str, expected_language: str, screening_type: str, risk_category: str) -> tuple[GeminiCounselResponse | None, str]:
    try:
        raw = str(text).strip().replace('```json', '').replace('```', '').strip()
        start, end = raw.find('{'), raw.rfind('}')
        if start < 0 or end < start:
            return None, 'MALFORMED_OUTPUT'
        payload = json.loads(raw[start:end + 1])
        if not isinstance(payload, dict):
            return None, 'MALFORMED_OUTPUT'
        if payload.get('language') != expected_language:
            return None, 'LANGUAGE_MISMATCH'
        for key in REWORDABLE:
            if not _safe_text(payload.get(key)):
                return None, 'UNSAFE_OR_INCOMPLETE_OUTPUT'
        if expected_language in {'hi', 'bho'} and not all(_DEVANAGARI.search(str(payload[k])) for k in REWORDABLE):
            return None, 'LANGUAGE_MISMATCH'
        # Deterministic, reviewed copy owns urgency, referral, next step, and safety note.
        body = local_counsel(screening_type, expected_language, risk_category)
        body.update({key: str(payload[key]).strip() for key in REWORDABLE})
        body['mode'] = 'GEMINI'
        body['fallback_reason'] = None
        return GeminiCounselResponse.model_validate(body), 'OK'
    except (ValueError, TypeError, ValidationError, KeyError):
        return None, 'MALFORMED_OUTPUT'


def parse_gemini_text(text: str, expected_language: str, screening_type: str, risk_category: str) -> GeminiCounselResponse | None:
    return _parse(text, expected_language, screening_type, risk_category)[0]


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def extract_usage(data: Any) -> dict[str, Any]:
    """Provider-reported token counts only. Missing fields stay None (unavailable), never estimated."""
    meta = data.get('usageMetadata') if isinstance(data, dict) else None
    if not isinstance(meta, dict):
        meta = {}
    usage = {
        'prompt_tokens': _int_or_none(meta.get('promptTokenCount')),
        'candidates_tokens': _int_or_none(meta.get('candidatesTokenCount')),
        'total_tokens': _int_or_none(meta.get('totalTokenCount')),
        'cached_tokens': _int_or_none(meta.get('cachedContentTokenCount')),
        'thoughts_tokens': _int_or_none(meta.get('thoughtsTokenCount')),
        'tool_use_prompt_tokens': _int_or_none(meta.get('toolUsePromptTokenCount')),
    }
    usage['usage_available'] = any(v is not None for v in usage.values())
    model_version = data.get('modelVersion') if isinstance(data, dict) else None
    usage['model_version'] = str(model_version)[:80] if isinstance(model_version, str) else None
    return usage


def classify_error(status: int, data: Any) -> str:
    error = data.get('error', {}) if isinstance(data, dict) else {}
    error = error if isinstance(error, dict) else {}
    text = json.dumps(error).lower()
    if status == 429 or error.get('status') == 'RESOURCE_EXHAUSTED':
        # Gemini uses 429 for both; per-day / billing quota violations mean the quota is exhausted.
        return 'QUOTA_EXHAUSTED' if ('perday' in text or 'billing' in text or 'per_day' in text) else 'RATE_LIMITED'
    if status in (401, 403):
        return 'AUTH_ERROR'
    if status == 404:
        return 'MODEL_UNAVAILABLE'
    if status == 400:
        return 'INVALID_REQUEST_OR_MODEL'
    if status >= 500:
        return 'PROVIDER_ERROR'
    return 'PROVIDER_ERROR'


def _record(event: dict[str, Any]) -> None:
    base = {'request_type': 'counselling', 'model_id': MODEL or None, 'created_at': datetime.now(timezone.utc).isoformat()}
    try:
        store.record_llm_usage({**base, **event})
    except Exception:  # telemetry must never break counselling
        logger.warning('usage telemetry write failed')
    # Log outcome metadata only: no key, prompt, response text, or patient data.
    logger.info('gemini outcome=%s provider_called=%s http=%s latency_ms=%s',
                event.get('outcome_code'), event.get('provider_called'), event.get('http_status'), event.get('latency_ms'))


async def _verify_model(client: httpx.AsyncClient) -> str | None:
    """Return None when the configured model is available for generateContent, else an error code."""
    now = time.monotonic()
    cached = _model_check.get(MODEL)
    if cached and now - cached['at'] < (MODEL_CHECK_TTL_OK if cached['code'] is None else MODEL_CHECK_TTL_FAIL):
        return cached['code']
    code: str | None
    try:
        response = await client.get(f'{BASE_URL}/{quote(MODEL, safe="")}', headers={'x-goog-api-key': API_KEY})
        data = response.json() if response.content else {}
        if response.status_code == 200:
            methods = data.get('supportedGenerationMethods') if isinstance(data, dict) else None
            code = None if not isinstance(methods, list) or 'generateContent' in methods else 'MODEL_UNSUPPORTED'
        else:
            code = classify_error(response.status_code, data)
    except httpx.TimeoutException:
        return 'TIMEOUT'  # transient; not cached
    except (httpx.HTTPError, ValueError):
        return 'NETWORK_ERROR'
    _model_check[MODEL] = {'code': code, 'at': now}
    return code


def _context(req: GeminiCounselRequest) -> dict[str, Any]:
    return {
        'screening_type': req.screening_type, 'value_provenance': req.provenance,
        'prototype_estimate': req.estimate, 'unit': req.unit, 'demo_risk_tag': req.risk_category,
        'pregnancy': req.pregnancy, 'gestational_week': req.gestational_week, 'infant_age_hours': req.infant_age_hours,
    }


async def _call_provider(req: GeminiCounselRequest) -> GeminiCounselResponse:
    language_names = {'en': 'English', 'hi': 'Hindi', 'bho': 'Bhojpuri'}
    prompt = (
        'You are a cautious counselling-language assistant in a prototype, not a clinician. '
        'Use only the supplied structured fields. The numeric estimate is a synthetic or research-only value, not clinical truth. '
        'Never diagnose, invent symptoms or history, invent a measurement, give medication advice or dosing, set urgency, or override a clinician. '
        'Explain that clinical confirmation and local protocol are required. For neonatal jaundice, do not infer urgency from a number; age in hours and clinical context matter. '
        f'Write entirely in {language_names[req.language]} for a community health worker, in short sentences. '
        'Return only the requested JSON object.'
    )
    body = {
        'systemInstruction': {'parts': [{'text': prompt}]},
        'contents': [{'role': 'user', 'parts': [{'text': json.dumps(_context(req), ensure_ascii=False)}]}],
        'generationConfig': {'temperature': 0.15, 'maxOutputTokens': MAX_OUTPUT_TOKENS,
                             'responseMimeType': 'application/json', 'responseSchema': RESPONSE_SCHEMA},
    }
    meta = {'screening_type': req.screening_type, 'language': req.language}
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        check = await _verify_model(client)
        if check is not None:
            _record({**meta, 'provider_called': False, 'outcome_code': f'MODEL_CHECK_{check}'})
            return _fallback(req, check)
        started = time.perf_counter()
        try:
            response = await client.post(f'{BASE_URL}/{quote(MODEL, safe="")}:generateContent',
                                         headers={'Content-Type': 'application/json', 'x-goog-api-key': API_KEY}, json=body)
        except httpx.TimeoutException:
            _record({**meta, 'provider_called': True, 'outcome_code': 'TIMEOUT', 'latency_ms': int((time.perf_counter() - started) * 1000)})
            return _fallback(req, 'TIMEOUT')
        except httpx.HTTPError:
            _record({**meta, 'provider_called': True, 'outcome_code': 'NETWORK_ERROR', 'latency_ms': int((time.perf_counter() - started) * 1000)})
            return _fallback(req, 'NETWORK_ERROR')
    latency = int((time.perf_counter() - started) * 1000)
    try:
        data = response.json()
    except ValueError:
        data = None
    usage = extract_usage(data)
    event = {**meta, **usage, 'provider_called': True, 'http_status': response.status_code, 'latency_ms': latency}
    if response.status_code != 200:
        code = classify_error(response.status_code, data)
        _record({**event, 'outcome_code': code})
        return _fallback(req, code)
    if not isinstance(data, dict):
        _record({**event, 'outcome_code': 'MALFORMED_RESPONSE'})
        return _fallback(req, 'MALFORMED_RESPONSE')
    candidates = data.get('candidates')
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        blocked = isinstance(data.get('promptFeedback'), dict) and data['promptFeedback'].get('blockReason')
        code = 'BLOCKED_BY_PROVIDER' if blocked else 'MALFORMED_RESPONSE'
        _record({**event, 'outcome_code': code})
        return _fallback(req, code)
    finish = candidates[0].get('finishReason')
    event['finish_reason'] = str(finish)[:40] if finish else None
    if finish == 'MAX_TOKENS':
        _record({**event, 'outcome_code': 'INCOMPLETE_OUTPUT'})
        return _fallback(req, 'INCOMPLETE_OUTPUT')
    parts = (candidates[0].get('content') or {}).get('parts') if isinstance(candidates[0].get('content'), dict) else None
    text = ''.join(p.get('text', '') for p in parts if isinstance(p, dict) and not p.get('thought')) if isinstance(parts, list) else ''
    parsed, code = _parse(text, req.language, req.screening_type, req.risk_category)
    _record({**event, 'outcome_code': code})
    if parsed is None:
        return _fallback(req, code)
    parsed.model_id = MODEL
    return parsed


async def counsel(req: GeminiCounselRequest) -> GeminiCounselResponse:
    # The request schema accepts no names, phone numbers, images, or free text.
    meta = {'screening_type': req.screening_type, 'language': req.language}
    if not API_KEY:
        _record({**meta, 'provider_called': False, 'outcome_code': 'NO_API_KEY'})
        return _fallback(req, 'NO_API_KEY')
    if not MODEL:
        _record({**meta, 'provider_called': False, 'outcome_code': 'MODEL_NOT_CONFIGURED'})
        return _fallback(req, 'MODEL_NOT_CONFIGURED')
    now = time.monotonic()
    for cache in (_idempotent, _demo_cache):
        for key in [k for k, (t, _) in cache.items() if now - t > (IDEMPOTENCY_TTL if cache is _idempotent else DEMO_CACHE_TTL)]:
            cache.pop(key, None)
    if req.request_id:
        if req.request_id in _idempotent:
            _record({**meta, 'provider_called': False, 'outcome_code': 'IDEMPOTENT_REPLAY'})
            return _idempotent[req.request_id][1].model_copy()
        if req.request_id in _inflight:
            return (await asyncio.shield(_inflight[req.request_id])).model_copy()
    # Only fixed demo inputs are cached across users; patient-specific outputs never are.
    demo_key = None
    if req.provenance == 'DEMO_SYNTHETIC':
        demo_key = hashlib.sha256(json.dumps([MODEL, req.language, _context(req)], sort_keys=True).encode()).hexdigest()
        if demo_key in _demo_cache:
            _record({**meta, 'provider_called': False, 'outcome_code': 'DEMO_CACHE_HIT'})
            return _demo_cache[demo_key][1].model_copy()
    future: asyncio.Future | None = None
    if req.request_id:
        future = asyncio.get_running_loop().create_future()
        _inflight[req.request_id] = future
    try:
        result = await _call_provider(req)
    except Exception:  # never surface internals; deterministic copy remains available
        logger.warning('gemini counselling failed unexpectedly')
        result = _fallback(req, 'PROVIDER_ERROR')
    finally:
        if req.request_id:
            _inflight.pop(req.request_id, None)
    if future is not None and not future.done():
        future.set_result(result)
    # Only provider-accepted wording is replayed. Caching a fallback (quota, timeout) would pin the client's
    # request_id (cns-<screening>-<lang>) to deterministic copy for the whole TTL, even after the provider recovers.
    if req.request_id and result.mode == 'GEMINI':
        _idempotent[req.request_id] = (time.monotonic(), result)
    if demo_key and result.mode == 'GEMINI':
        _demo_cache[demo_key] = (time.monotonic(), result)
    return result.model_copy()


def usage_report(since: str | None = None, until: str | None = None) -> dict[str, Any]:
    rows = store.get_llm_usage(since, until)
    called = [r for r in rows if r['provider_called']]
    ok = [r for r in called if r['outcome_code'] == 'OK']

    def total(field: str, subset: list[dict[str, Any]]) -> int | None:
        values = [r[field] for r in subset if r[field] is not None]
        return sum(values) if values else None

    with_usage = [r for r in ok if r['usage_available']]
    latencies = sorted(r['latency_ms'] for r in called if r['latency_ms'] is not None)
    outcomes: dict[str, int] = {}
    for r in rows:
        outcomes[r['outcome_code']] = outcomes.get(r['outcome_code'], 0) + 1
    avg = (lambda field: round(sum(r[field] for r in with_usage if r[field] is not None) / len([r for r in with_usage if r[field] is not None]), 1)
           if any(r[field] is not None for r in with_usage) else None)
    return {
        'period': {'since': since or (rows[0]['created_at'] if rows else None), 'until': until or (rows[-1]['created_at'] if rows else None)},
        'models': sorted({r['model_id'] for r in rows if r['model_id']}),
        'model_versions_reported': sorted({r['model_version'] for r in rows if r['model_version']}),
        'counselling_requests': len(rows),
        'provider_requests': len(called),
        'provider_successful': len(ok),
        'provider_failed_or_rejected': len(called) - len(ok),
        'served_without_provider_call': len(rows) - len(called),
        'outcomes': outcomes,
        'tokens_provider_reported': {
            'prompt': total('prompt_tokens', called), 'output_candidates': total('candidates_tokens', called),
            'thoughts': total('thoughts_tokens', called), 'cached': total('cached_tokens', called),
            'tool_use_prompt': total('tool_use_prompt_tokens', called), 'total': total('total_tokens', called),
        },
        'requests_missing_usage_metadata': len([r for r in called if not r['usage_available']]),
        'avg_tokens_per_successful_request': {'prompt': avg('prompt_tokens'), 'output_candidates': avg('candidates_tokens'), 'total': avg('total_tokens')},
        'latency_ms': {'count': len(latencies), 'mean': round(sum(latencies) / len(latencies), 1) if latencies else None,
                       'p50': latencies[len(latencies) // 2] if latencies else None, 'max': latencies[-1] if latencies else None},
        'estimated_cost': None,
        'notes': ['Token counts are provider-reported usageMetadata values; null means the provider did not report the field.',
                  'Cost is not computed: no verified pricing data is configured for this deployment.'],
    }
