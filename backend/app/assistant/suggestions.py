"""Post-result suggestions for the Android app, written by the Agent37 assistant (POST /api/suggestions).

The request carries only the structured screening answer and workflow fields (no photo, name, nickname or IDs).
Agent37 is asked for a small JSON object in the requested language; the reply is parsed and length-checked, and any
failure (not configured, timeout, malformed output) returns `source: FALLBACK` with deterministic English text, which
the app replaces with its own on-device wording. Referral urgency is never taken from this text.
"""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.assistant import agent37

LANGUAGE_NAMES = {'en': 'English', 'hi': 'Hindi (Devanagari script)', 'bho': 'Bhojpuri (Devanagari script)'}
DANGER_SIGN_TEXT = {
    'MATERNAL_BREATHLESS': 'breathless at rest or with light work',
    'MATERNAL_FAINTING': 'fainting, dizziness or extreme tiredness',
    'MATERNAL_PALPITATIONS': 'fast or pounding heartbeat',
    'MATERNAL_BLEEDING': 'vaginal bleeding',
    'NEWBORN_YELLOW_PALMS_SOLES': 'yellow palms or soles',
    'NEWBORN_POOR_FEEDING': 'not feeding well',
    'NEWBORN_LETHARGIC': 'very sleepy, hard to wake or floppy',
    'NEWBORN_CONVULSIONS': 'convulsions',
    'NEWBORN_FEVER_OR_COLD': 'fever or feels cold',
}
MAX_FIELD = 600
MAX_SUGGESTION = 300


class SuggestionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    screening_type: Literal['maternal_anemia', 'neonatal_jaundice']
    result: Literal['likely', 'unlikely']
    probability: float = Field(ge=0, le=1)
    hemoglobin_g_dl: float | None = Field(default=None, ge=2, le=25)
    urgency: Literal['URGENT_REFERRAL', 'PROMPT_CLINICIAN_REVIEW', 'CONFIRMATORY_TESTING']
    danger_signs: list[Literal[tuple(DANGER_SIGN_TEXT)]] = Field(default_factory=list, max_length=9)  # type: ignore[valid-type]
    language: Literal['en', 'hi', 'bho'] = 'en'
    pregnancy: bool | None = None
    gestational_week: int | None = Field(default=None, ge=1, le=45)
    infant_age_hours: int | None = Field(default=None, ge=0, le=672)
    visible_jaundice: bool | None = None


def _facts(r: SuggestionRequest) -> str:
    condition = 'anemia' if r.screening_type == 'maternal_anemia' else 'newborn jaundice'
    lines = [f'Screening: {condition} from a phone photo ({"lower eyelid" if r.screening_type == "maternal_anemia" else "newborn skin"}).',
             f'Answer: {condition} {r.result}, probability {round(r.probability * 100)}%.']
    if r.hemoglobin_g_dl is not None:
        lines.append(f'Estimated hemoglobin: {r.hemoglobin_g_dl:.1f} g/dL (screening estimate, typical error about 1.3 g/dL).')
    if r.pregnancy is not None:
        lines.append(f'Pregnant: {"yes" if r.pregnancy else "no"}' + (f', week {r.gestational_week}' if r.gestational_week else '') + '.')
    if r.infant_age_hours is not None:
        lines.append(f'Baby age: {r.infant_age_hours} hours.')
    if r.visible_jaundice is not None:
        lines.append(f'Yellow colour visible to the health worker: {"yes" if r.visible_jaundice else "no"}.')
    lines.append('Danger signs: ' + (', '.join(DANGER_SIGN_TEXT[d] for d in r.danger_signs) or 'none recorded') + '.')
    lines.append(f'Next step already decided by protocol rules: {r.urgency.replace("_", " ").lower()}.')
    return '\n'.join(lines)


def prompt(r: SuggestionRequest) -> str:
    return (
        'You support an ASHA community health worker in India right after a phone screening. Write practical, kind, '
        'plain-language suggestions for the worker to share with the family.\n'
        f'{_facts(r)}\n\n'
        'Rules: this is a screening estimate, not a diagnosis; always say to confirm with a blood test '
        '(hemoglobin for anemia, bilirubin for jaundice). Never contradict or lower the protocol next step; if there '
        'are danger signs, the first suggestion is urgent referral. Do not name medicine doses; say "as advised by the '
        'health worker or doctor". Give diet, feeding, follow-up and warning-sign advice suited to rural India. '
        f'Write every text field in {LANGUAGE_NAMES[r.language]}.\n'
        'Reply with ONLY a JSON object, no markdown, with keys: "summary" (1 sentence), "explanation" (1-2 sentences), '
        '"suggestions" (3 to 5 short strings), "next_step" (1 sentence), "safety_note" (1 sentence).'
    )


def fallback(r: SuggestionRequest, reason: str) -> dict:
    anemia = r.screening_type == 'maternal_anemia'
    test = 'hemoglobin blood test' if anemia else 'bilirubin test'
    likely = r.result == 'likely'
    return {
        'summary': f'The photo suggests {"anemia" if anemia else "jaundice"} is {"likely" if likely else "unlikely"} '
                   f'(probability {round(r.probability * 100)}%).',
        'explanation': 'This is a screening estimate from a photo, not a diagnosis.',
        'suggestions': [f'Arrange a {test} to confirm.', 'Follow the local protocol and the next step shown in the app.'],
        'next_step': f'Confirm with a {test}.',
        'safety_note': 'Danger signs always need urgent referral.',
        'language': r.language, 'source': 'FALLBACK', 'fallback_reason': reason,
    }


def parse(text: str, language: str) -> dict | None:
    """The first JSON object in the reply, with the expected keys and sane lengths; None otherwise."""
    match = re.search(r'\{.*\}', text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    out: dict = {}
    for key in ('summary', 'explanation', 'next_step', 'safety_note'):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > MAX_FIELD:
            return None
        out[key] = value.strip()
    items = data.get('suggestions')
    if not isinstance(items, list):
        return None
    items = [s.strip() for s in items if isinstance(s, str) and s.strip() and len(s) <= MAX_SUGGESTION][:6]
    if len(items) < 2:
        return None
    out['suggestions'] = items
    return {**out, 'language': language, 'source': 'AGENT37', 'fallback_reason': None}


async def suggest(r: SuggestionRequest, *, transport=None) -> dict:
    config = agent37.load_config()
    if config is None:
        return fallback(r, 'AGENT37_' + (agent37.config_problem() or 'NOT_CONFIGURED'))
    result = await agent37.ask(config, prompt(r), kb_version='suggestions-v1', transport=transport)
    if not result.ok or not result.output_text:
        return fallback(r, result.reason or 'PROVIDER_FAILED')
    return parse(result.output_text, r.language) or fallback(r, 'PROVIDER_MALFORMED_OUTPUT')
