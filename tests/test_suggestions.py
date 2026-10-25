"""POST /api/suggestions: Agent37 suggestions after an Android result, with fallback and strict input."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.assistant import agent37, service, suggestions
from app.main import app

KEY = 'sk_live_' + 'pytestonly0123456789abcd'
INSTANCE = 'https://abcde12345.agent37.app'
BODY = {'screening_type': 'maternal_anemia', 'result': 'likely', 'probability': 0.72, 'hemoglobin_g_dl': 10.1,
        'urgency': 'PROMPT_CLINICIAN_REVIEW', 'danger_signs': [], 'language': 'hi', 'pregnancy': True, 'gestational_week': 24}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    for name in ('AGENT37_API_KEY', 'AGENT37_INSTANCE_URL'):
        monkeypatch.delenv(name, raising=False)
    service.reset_state()
    yield
    service.reset_state()


def _agent37(monkeypatch, reply: dict, seen: list):
    monkeypatch.setenv('AGENT37_API_KEY', KEY)
    monkeypatch.setenv('AGENT37_INSTANCE_URL', INSTANCE)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=reply)

    original = agent37.ask
    monkeypatch.setattr(agent37, 'ask', lambda config, prompt, **kw: original(config, prompt, **{**kw, 'transport': httpx.MockTransport(handler)}))


def test_not_configured_returns_fallback():
    r = TestClient(app).post('/api/suggestions', json=BODY)
    assert r.status_code == 200
    data = r.json()
    assert data['source'] == 'FALLBACK' and data['fallback_reason'] == 'AGENT37_NOT_CONFIGURED'
    assert data['language'] == 'hi' and len(data['suggestions']) >= 2


def test_agent37_reply_is_parsed_and_prompt_has_no_identifiers(monkeypatch):
    seen: list = []
    text = 'Here: ' + json.dumps({'summary': 'S', 'explanation': 'E', 'suggestions': ['a', 'b', 'c'], 'next_step': 'N', 'safety_note': 'Z'})
    _agent37(monkeypatch, {'status': 'completed', 'output_text': text}, seen)
    data = TestClient(app).post('/api/suggestions', json=BODY).json()
    assert data['source'] == 'AGENT37' and data['suggestions'] == ['a', 'b', 'c'] and data['language'] == 'hi'
    prompt = seen[0]['input']
    assert 'probability 72%' in prompt and '10.1 g/dL' in prompt and 'Hindi' in prompt


def test_malformed_agent37_output_falls_back(monkeypatch):
    _agent37(monkeypatch, {'status': 'completed', 'output_text': 'no json here'}, [])
    data = TestClient(app).post('/api/suggestions', json=BODY).json()
    assert data['source'] == 'FALLBACK' and data['fallback_reason'] == 'PROVIDER_MALFORMED_OUTPUT'


@pytest.mark.parametrize('extra', [{'name': 'Sita'}, {'patient_id': 'ABH-1'}, {'probability': 1.5}, {'danger_signs': ['UNKNOWN']}])
def test_unknown_or_invalid_fields_are_rejected(extra):
    assert TestClient(app).post('/api/suggestions', json={**BODY, **extra}).status_code == 422


def test_danger_signs_reach_the_prompt():
    r = suggestions.SuggestionRequest(**{**BODY, 'danger_signs': ['MATERNAL_BLEEDING'], 'urgency': 'URGENT_REFERRAL'})
    p = suggestions.prompt(r)
    assert 'vaginal bleeding' in p and 'urgent referral' in p
