"""Gemini counselling with mocked provider responses. No live API key or network is used."""
from __future__ import annotations

import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import gemini, store

FAKE_KEY = 'test-key-not-real-0123456789'
MODEL = 'gemini-test-model'
REQUEST = {'screening_type': 'maternal_anemia', 'estimate': 9.4, 'unit': 'g/dL', 'risk_category': 'DEMO_MODERATE', 'language': 'en'}
SAFE_EN = {'summary': 'This is a synthetic prototype value, not a diagnosis.',
           'risk_explanation': 'The demo tag is only a software example.',
           'counselling_script': 'Please arrange a confirmation test at the health centre.', 'language': 'en'}
ADMIN = 'admin-token-for-tests-1234'


def model_ok(_request):
    return httpx.Response(200, json={'name': f'models/{MODEL}', 'supportedGenerationMethods': ['generateContent', 'countTokens']})


def generate(payload=SAFE_EN, usage=..., finish='STOP', status=200, raw=None):
    if raw is not None:
        return httpx.Response(status, content=raw)
    body = {'candidates': [{'content': {'parts': [{'text': json.dumps(payload, ensure_ascii=False)}], 'role': 'model'}, 'finishReason': finish}],
            'modelVersion': 'gemini-test-model-001', 'responseId': 'resp-1'}
    if usage is ...:
        usage = {'promptTokenCount': 210, 'candidatesTokenCount': 64, 'totalTokenCount': 300, 'thoughtsTokenCount': 26}
    if usage is not None:
        body['usageMetadata'] = usage
    return httpx.Response(status, json=body)


@pytest.fixture
def provider(monkeypatch, tmp_path):
    """Install a mock transport. Tests set `provider.handler` to control generateContent."""
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'gem.sqlite3')
    monkeypatch.setattr(gemini, 'API_KEY', FAKE_KEY)
    monkeypatch.setattr(gemini, 'MODEL', MODEL)
    monkeypatch.setenv('ABHAYNAYAN_ADMIN_TOKEN', ADMIN)
    gemini.reset_state()

    class Provider:
        calls: list[httpx.Request] = []
        handler = staticmethod(lambda request: generate())
        model_handler = staticmethod(model_ok)

    state = Provider()
    state.calls = []

    def route(request: httpx.Request) -> httpx.Response:
        state.calls.append(request)
        if request.url.path.endswith(':generateContent'):
            return state.handler(request)
        return state.model_handler(request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(gemini.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(route), **kw))
    with TestClient(app) as client:
        state.client = client
        yield state
    gemini.reset_state()


def post(provider, **overrides):
    return provider.client.post('/api/counselling', json={**REQUEST, **overrides}).json()


def usage(provider):
    return provider.client.get('/api/admin/usage', headers={'Authorization': f'Bearer {ADMIN}'}).json()


def generate_calls(provider):
    return [c for c in provider.calls if c.url.path.endswith(':generateContent')]


def test_successful_call_records_provider_reported_usage(provider):
    body = post(provider)
    assert body['mode'] == 'GEMINI' and body['fallback_reason'] is None and body['model_id'] == MODEL
    report = usage(provider)
    assert report['provider_requests'] == 1 and report['provider_successful'] == 1
    assert report['tokens_provider_reported'] == {'prompt': 210, 'output_candidates': 64, 'thoughts': 26, 'cached': None,
                                                  'tool_use_prompt': None, 'total': 300}
    assert report['avg_tokens_per_successful_request']['total'] == 300.0
    assert report['model_versions_reported'] == ['gemini-test-model-001']
    assert report['estimated_cost'] is None
    assert report['latency_ms']['count'] == 1


def test_safety_fields_always_come_from_deterministic_copy(provider):
    provider.handler = lambda r: generate({**SAFE_EN, 'recommended_next_step': 'No need to test.', 'urgency': 'ROUTINE_REVIEW',
                                           'referral_required': False, 'safety_note': 'All fine.'})
    body = post(provider, risk_category='DEMO_HIGH')
    assert body['mode'] == 'GEMINI'
    assert body['referral_required'] is True and body['urgency'] == 'DEMO_ONLY'
    assert 'confirm' in body['recommended_next_step'].lower()
    assert body['safety_note'] != 'All fine.'


def test_missing_usage_metadata_is_recorded_as_unavailable_not_estimated(provider):
    provider.handler = lambda r: generate(usage=None)
    assert post(provider)['mode'] == 'GEMINI'
    report = usage(provider)
    assert report['tokens_provider_reported']['total'] is None
    assert report['requests_missing_usage_metadata'] == 1
    assert report['avg_tokens_per_successful_request']['total'] is None


def test_partial_usage_metadata_keeps_missing_fields_null():
    data = {'usageMetadata': {'promptTokenCount': 12, 'totalTokenCount': 'bad', 'candidatesTokenCount': True}}
    extracted = gemini.extract_usage(data)
    assert extracted['prompt_tokens'] == 12
    assert extracted['total_tokens'] is None and extracted['candidates_tokens'] is None
    assert extracted['usage_available'] is True
    assert gemini.extract_usage({})['usage_available'] is False
    assert gemini.extract_usage(None)['usage_available'] is False


@pytest.mark.parametrize('status,error,code', [
    (429, {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', 'message': 'Too many requests',
                     'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure',
                                  'violations': [{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel'}]}]}}, 'RATE_LIMITED'),
    (429, {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', 'message': 'Quota exceeded',
                     'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure',
                                  'violations': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel'}]}]}}, 'QUOTA_EXHAUSTED'),
    (500, {'error': {'code': 500, 'status': 'INTERNAL'}}, 'PROVIDER_ERROR'),
    (503, {'error': {'code': 503, 'status': 'UNAVAILABLE'}}, 'PROVIDER_ERROR'),
    (403, {'error': {'code': 403, 'status': 'PERMISSION_DENIED'}}, 'AUTH_ERROR'),
])
def test_provider_errors_fall_back_with_classified_reason(provider, status, error, code):
    provider.handler = lambda r: httpx.Response(status, json=error)
    body = post(provider)
    assert body['mode'] == 'LOCAL_FALLBACK' and body['fallback_reason'] == code
    report = usage(provider)
    assert report['outcomes'] == {code: 1} and report['provider_failed_or_rejected'] == 1


def test_unavailable_model_is_detected_before_generation(provider):
    provider.model_handler = lambda r: httpx.Response(404, json={'error': {'code': 404, 'status': 'NOT_FOUND'}})
    body = post(provider)
    assert body['fallback_reason'] == 'MODEL_UNAVAILABLE'
    assert generate_calls(provider) == []
    assert usage(provider)['outcomes'] == {'MODEL_CHECK_MODEL_UNAVAILABLE': 1}


def test_model_without_generate_content_is_rejected(provider):
    provider.model_handler = lambda r: httpx.Response(200, json={'name': 'm', 'supportedGenerationMethods': ['embedContent']})
    assert post(provider)['fallback_reason'] == 'MODEL_UNSUPPORTED'


def test_timeout_falls_back(provider):
    def boom(request):
        raise httpx.ReadTimeout('timed out', request=request)
    provider.handler = boom
    assert post(provider)['fallback_reason'] == 'TIMEOUT'
    assert usage(provider)['outcomes'] == {'TIMEOUT': 1}


def test_network_error_falls_back(provider):
    def boom(request):
        raise httpx.ConnectError('down', request=request)
    provider.handler = boom
    assert post(provider)['fallback_reason'] == 'NETWORK_ERROR'


@pytest.mark.parametrize('response,code', [
    (lambda r: generate(raw=b'<html>not json</html>'), 'MALFORMED_RESPONSE'),
    (lambda r: httpx.Response(200, json={'candidates': []}), 'MALFORMED_RESPONSE'),
    (lambda r: httpx.Response(200, json={'promptFeedback': {'blockReason': 'SAFETY'}}), 'BLOCKED_BY_PROVIDER'),
    (lambda r: generate({'summary': 'x'}), 'LANGUAGE_MISMATCH'),
    (lambda r: generate({**SAFE_EN, 'summary': 'You have anemia.'}), 'UNSAFE_OR_INCOMPLETE_OUTPUT'),
    (lambda r: generate({**SAFE_EN, 'counselling_script': ''}), 'UNSAFE_OR_INCOMPLETE_OUTPUT'),
    (lambda r: generate(finish='MAX_TOKENS'), 'INCOMPLETE_OUTPUT'),
])
def test_malformed_unsafe_or_incomplete_output_falls_back(provider, response, code):
    provider.handler = response
    body = post(provider)
    assert body['mode'] == 'LOCAL_FALLBACK' and body['fallback_reason'] == code


def test_hindi_request_rejects_latin_only_output(provider):
    provider.handler = lambda r: generate({**SAFE_EN, 'language': 'hi'})
    body = post(provider, language='hi')
    assert body['fallback_reason'] == 'LANGUAGE_MISMATCH' and body['language'] == 'hi'
    assert 'प्रोटोटाइप' in body['summary']


def test_tokens_are_recorded_even_when_output_is_rejected(provider):
    provider.handler = lambda r: generate({**SAFE_EN, 'summary': 'This is anemia.'})
    post(provider)
    report = usage(provider)
    assert report['provider_successful'] == 0
    assert report['tokens_provider_reported']['total'] == 300


def test_missing_key_and_missing_model_never_call_provider(provider, monkeypatch):
    monkeypatch.setattr(gemini, 'MODEL', '')
    assert post(provider)['fallback_reason'] == 'MODEL_NOT_CONFIGURED'
    monkeypatch.setattr(gemini, 'API_KEY', '')
    assert post(provider)['fallback_reason'] == 'NO_API_KEY'
    assert provider.calls == []
    report = usage(provider)
    assert report['provider_requests'] == 0 and report['served_without_provider_call'] == 2


def test_retry_with_same_request_id_does_not_call_provider_twice(provider):
    first = post(provider, provenance='EXPERIMENTAL_RESEARCH_ONLY', request_id='req-12345678')
    second = post(provider, provenance='EXPERIMENTAL_RESEARCH_ONLY', request_id='req-12345678')
    assert first['summary'] == second['summary']
    assert len(generate_calls(provider)) == 1
    assert usage(provider)['outcomes'] == {'OK': 1, 'IDEMPOTENT_REPLAY': 1}


def test_demo_inputs_are_cached_but_non_demo_inputs_are_not(provider):
    post(provider); post(provider)
    assert len(generate_calls(provider)) == 1
    post(provider, provenance='EXPERIMENTAL_RESEARCH_ONLY'); post(provider, provenance='EXPERIMENTAL_RESEARCH_ONLY')
    assert len(generate_calls(provider)) == 3


def test_request_sends_no_identifiers_and_bounded_output(provider):
    post(provider, infant_age_hours=None)
    sent = json.loads(generate_calls(provider)[0].content)
    assert sent['generationConfig']['maxOutputTokens'] == gemini.MAX_OUTPUT_TOKENS
    text = json.dumps(sent)
    for forbidden in ('patient_id', 'name', 'phone', 'image', 'ABH-'):
        assert forbidden not in text
    assert generate_calls(provider)[0].headers['x-goog-api-key'] == FAKE_KEY
    assert 'key=' not in str(generate_calls(provider)[0].url)  # key travels in a header, not the URL


def test_counselling_rejects_identifying_fields(provider):
    response = provider.client.post('/api/counselling', json={**REQUEST, 'patient_name': 'Rani'})
    assert response.status_code == 422
    assert provider.calls == []


def test_logs_and_telemetry_never_contain_key_or_prompt_content(provider, caplog):
    caplog.set_level(logging.DEBUG)
    post(provider)
    provider.handler = lambda r: httpx.Response(500, json={'error': {'message': f'echo {FAKE_KEY}'}})
    post(provider, provenance='EXPERIMENTAL_RESEARCH_ONLY')
    assert FAKE_KEY not in caplog.text
    assert 'counselling-language assistant' not in caplog.text
    rows = json.dumps(store.get_llm_usage())
    assert FAKE_KEY not in rows and SAFE_EN['summary'] not in rows and '9.4' not in rows


def test_admin_usage_requires_token_and_is_disabled_without_one(provider, monkeypatch):
    assert provider.client.get('/api/admin/usage').status_code == 401
    assert provider.client.get('/api/admin/usage', headers={'Authorization': 'Bearer wrong-token-xxxxxxxx'}).status_code == 401
    bad = provider.client.get('/api/admin/usage?since=yesterday', headers={'Authorization': f'Bearer {ADMIN}'})
    assert bad.status_code == 422
    monkeypatch.setenv('ABHAYNAYAN_ADMIN_TOKEN', '')
    disabled = provider.client.get('/api/admin/usage', headers={'Authorization': f'Bearer {ADMIN}'})
    assert disabled.status_code == 403 and disabled.json()['error']['code'] == 'ADMIN_DISABLED'


def test_usage_report_period_filter(provider):
    post(provider)
    future = provider.client.get('/api/admin/usage?since=2999-01-01T00:00:00Z', headers={'Authorization': f'Bearer {ADMIN}'}).json()
    assert future['counselling_requests'] == 0
    assert future['tokens_provider_reported']['total'] is None


@pytest.mark.parametrize('text,safe', [
    ('The prototype value is 12.8 mg/dL and needs confirmation.', True),
    ('The prototype value is 12.8 mg / dL.', True),
    ('यह प्रोटोटाइप मान 12.8 मिलीग्राम प्रति डेसीलीटर है।', True),
    ('Give 50 mg of iron daily.', False),
    ('Take 2 tablets.', False),
    ('दवा 100 मिलीग्राम दें।', False),
])
def test_safety_filter_allows_units_but_blocks_doses(text, safe):
    assert gemini._safe_text(text) is safe


def test_defaults_leave_room_for_thinking_tokens():
    # Live measurement: ~490-920 thinking tokens per call; a 512 budget truncated every answer.
    assert gemini.MAX_OUTPUT_TOKENS >= 2048 or 'GEMINI_MAX_OUTPUT_TOKENS' in __import__('os').environ
