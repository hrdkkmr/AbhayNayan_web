"""Authentication, authorization and rate limiting of research inference routes (audit M5/M6;
AC-SEC-08, AC-SEC-09, AC-SEC-10, AC-STAT-03). Uses server-issued test tokens only; no external identity provider."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.core import auth, config
from app.core.ratelimit import Limiter
from app.main import app
from app.services import gemini, store
from conftest import TEST_SIGNING_KEY, research_token_headers
from test_ml import conjunctiva_like, fake_registry, png_bytes  # noqa: F401

IMAGE_ROUTES = ['/api/ml/hemoglobin', '/api/ml/neonatal-jaundice-class']
MODEL_SCREENING = {'patient': {'patient_id': 'ABH-SEC-1', 'demo': True}, 'screening_type': 'maternal_anemia', 'inference_mode': 'MODEL'}
PNG = {'Content-Type': 'image/png'}


@pytest.fixture
def anon(tmp_path, monkeypatch):
    """Unauthenticated client on a server whose signing key is configured and research flag is ON."""
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(gemini, 'API_KEY', '')
    monkeypatch.setenv('ABHAYNAYAN_SESSION_SIGNING_KEY', TEST_SIGNING_KEY)
    monkeypatch.setenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', '1')
    with TestClient(app) as c:
        yield c


def b64(obj) -> str:
    raw = obj if isinstance(obj, bytes) else json.dumps(obj, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def forge(header: dict, claims: dict, key: str = TEST_SIGNING_KEY) -> str:
    signing_input = f'{b64(header)}.{b64(claims)}'
    sig = hmac.new(key.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f'{signing_input}.{b64(sig)}'


def good_claims(**over) -> dict:
    now = int(time.time())
    c = {'iss': auth.ISSUER, 'aud': auth.AUDIENCE, 'sub': 'usr-forger-0001', 'roles': ['research_operator'],
         'iat': now, 'nbf': now, 'exp': now + 300, 'jti': 'jti-0123456789'}
    c.update(over)
    return c


def bearer(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


# ----- unauthenticated access ---------------------------------------------------------------------

@pytest.mark.parametrize('route', IMAGE_ROUTES)
def test_image_routes_require_authentication_even_with_flag_on(anon, route):
    r = anon.post(route, content=png_bytes(conjunctiva_like()), headers=PNG)
    assert r.status_code == 401 and r.json()['error']['code'] == 'UNAUTHENTICATED'
    assert r.headers['WWW-Authenticate'] == 'Bearer'
    assert 'estimate' not in r.json() and 'score' not in r.json()


def test_model_mode_screening_requires_authentication(anon):
    r = anon.post('/api/screenings', json=MODEL_SCREENING)
    assert r.status_code == 401 and r.json()['error']['code'] == 'UNAUTHENTICATED'
    assert anon.get('/api/dashboard').json()['total_screenings'] == 0


def test_demo_mode_and_offline_sync_paths_unchanged_without_login(anon):
    r = anon.post('/api/screenings', json={'patient': {'patient_id': 'ABH-SEC-2', 'demo': True}, 'screening_type': 'maternal_anemia',
                                           'inference_mode': 'DEMO', 'case_id': 'maternal-normal'})
    assert r.status_code == 200 and r.json()['result']['provenance'] == 'DEMO_SYNTHETIC'


def test_authentication_is_checked_before_body_size_and_flag(anon, monkeypatch):
    monkeypatch.delenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS')
    r = anon.post('/api/ml/hemoglobin', content=b'\x89PNG\r\n\x1a\n', headers={**PNG, 'Content-Length': str(50 * 1024 * 1024)})
    assert r.status_code == 401  # neither 413 nor 503: the flag state is not revealed to anonymous callers


@pytest.mark.parametrize('value', ['', 'Bearer', 'Bearer   ', 'Basic dXNlcjpwYXNz', 'Token abc', 'bearer'])
def test_malformed_authorization_header(anon, value):
    r = anon.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, 'Authorization': value})
    assert r.status_code == 401 and r.json()['error']['code'] == 'UNAUTHENTICATED'


def test_client_supplied_identity_is_ignored(anon, monkeypatch):
    spoof = {'X-User-Id': 'usr-admin-00000001', 'X-Role': 'research_operator', 'X-Forwarded-User': 'admin'}
    r = anon.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **spoof})
    assert r.status_code == 401
    patient = research_token_headers(monkeypatch, roles=('patient',), user_id='usr-patient-0001')
    r = anon.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **patient, **spoof})
    assert r.status_code == 403 and r.json()['error']['code'] == 'FORBIDDEN'
    r = anon.post('/api/screenings', json={**MODEL_SCREENING, 'patient': {'patient_id': 'ABH-SEC-3', 'demo': True}}, headers={**patient, **spoof})
    assert r.status_code == 403


# ----- invalid and expired tokens -----------------------------------------------------------------

INVALID = {
    'garbage': lambda: 'not-a-token',
    'two_parts': lambda: 'a.b',
    'alg_none': lambda: f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(good_claims())}.",
    'alg_hs512': lambda: forge({'alg': 'HS512', 'typ': 'JWT'}, good_claims()),
    'extra_kid': lambda: forge({'alg': 'HS256', 'typ': 'JWT', 'kid': '../../etc'}, good_claims()),
    'wrong_key': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(), key='another-signing-key-Z9xQ7mW2vB4nK8pL3'),
    'wrong_iss': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(iss='accounts.google.com')),
    'wrong_aud': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(aud='other-api')),
    'missing_exp': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, {k: v for k, v in good_claims().items() if k != 'exp'}),
    'ttl_too_long': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(exp=int(time.time()) + 13 * 3600)),
    'future_iat': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(iat=int(time.time()) + 3600, nbf=int(time.time()) + 3600, exp=int(time.time()) + 3900)),
    'bad_sub': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(sub='admin')),
    'unknown_role': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(roles=['superuser'])),
    'roles_string': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(roles='research_operator')),
    'bool_exp': lambda: forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(exp=True)),
    'too_long': lambda: 'a' * 5000 + '.b.c',
}


@pytest.mark.parametrize('name', sorted(INVALID))
def test_invalid_tokens_rejected_with_one_message(anon, name):
    r = anon.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **bearer(INVALID[name]())})
    assert r.status_code == 401 and r.json()['error']['code'] == 'TOKEN_INVALID'
    assert r.json()['error']['message'] == 'The access token is not valid.'


def test_tampered_payload_cannot_escalate_role(anon, monkeypatch):
    token = auth.issue('usr-patient-0002', ['patient'], 300, key=TEST_SIGNING_KEY)
    head, _, sig = token.split('.')
    escalated = f"{head}.{b64(good_claims(sub='usr-patient-0002'))}.{sig}"
    r = anon.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **bearer(escalated)})
    assert r.status_code == 401 and r.json()['error']['code'] == 'TOKEN_INVALID'


def test_expired_token(anon):
    old = int(time.time()) - 3600
    token = forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(iat=old, nbf=old, exp=old + 600))
    r = anon.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **bearer(token)})
    assert r.status_code == 401 and r.json()['error']['code'] == 'TOKEN_EXPIRED'
    assert r.headers['WWW-Authenticate'] == 'Bearer'


def test_token_within_clock_skew_still_valid(monkeypatch):
    monkeypatch.setenv('ABHAYNAYAN_SESSION_SIGNING_KEY', TEST_SIGNING_KEY)
    config.reload()
    now = int(time.time())
    p = auth.verify(auth.issue('usr-skew-00000001', ['research_operator'], 120, key=TEST_SIGNING_KEY, now=now - 150), now=now)
    assert p.user_id == 'usr-skew-00000001'


@pytest.mark.parametrize('role', ['patient', 'caregiver', 'clinician', 'org_admin', 'synthetic_test', 'platform_operator'])
def test_valid_token_without_research_role_is_forbidden(anon, monkeypatch, role):
    headers = research_token_headers(monkeypatch, roles=(role,), user_id='usr-other-role-01')
    for route in IMAGE_ROUTES:
        r = anon.post(route, content=png_bytes(conjunctiva_like()), headers={**PNG, **headers})
        assert r.status_code == 403 and r.json()['error']['code'] == 'FORBIDDEN'


@pytest.mark.usefixtures('test_body_site_verifier')
def test_research_role_and_flag_both_required(anon, monkeypatch, fake_registry):
    fake_registry()
    headers = research_token_headers(monkeypatch)
    ok = anon.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={**PNG, **headers})
    assert ok.status_code == 200 and ok.json()['provenance'] == 'EXPERIMENTAL_RESEARCH_ONLY'
    monkeypatch.delenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS')
    off = anon.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={**PNG, **headers})
    assert off.status_code == 503 and off.json()['error']['code'] == 'MODEL_DISABLED'  # the flag stays a kill switch


def test_no_signing_key_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.delenv('ABHAYNAYAN_SESSION_SIGNING_KEY', raising=False)
    monkeypatch.setenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', '1')
    with TestClient(app) as c:
        forged = forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(), key='')
        for headers in ({}, bearer(forged)):
            r = c.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **headers})
            assert r.status_code in (401, 503)
            assert r.status_code == 401 or r.json()['error']['code'] == 'AUTH_NOT_CONFIGURED'
        assert c.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **bearer(forged)}).json()['error']['code'] == 'AUTH_NOT_CONFIGURED'


def test_weak_signing_key_is_never_used(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setenv('ABHAYNAYAN_SESSION_SIGNING_KEY', 'change-me-change-me-change-me-change-me')
    with TestClient(app) as c:
        forged = forge({'alg': 'HS256', 'typ': 'JWT'}, good_claims(), key='change-me-change-me-change-me-change-me')
        r = c.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **bearer(forged)})
        assert r.status_code == 503 and r.json()['error']['code'] == 'AUTH_NOT_CONFIGURED'


def test_issue_refuses_bad_parameters(monkeypatch):
    monkeypatch.setenv('ABHAYNAYAN_SESSION_SIGNING_KEY', TEST_SIGNING_KEY)
    config.reload()
    for kwargs in ({'user_id': 'bob', 'roles': ['patient'], 'ttl_seconds': 60},
                   {'user_id': 'usr-valid-0001', 'roles': ['root'], 'ttl_seconds': 60},
                   {'user_id': 'usr-valid-0001', 'roles': [], 'ttl_seconds': 60},
                   {'user_id': 'usr-valid-0001', 'roles': ['patient'], 'ttl_seconds': 10 ** 6}):
        with pytest.raises(ValueError):
            auth.issue(**kwargs)


def test_tokens_never_appear_in_logs(anon, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    token = INVALID['wrong_key']()
    anon.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **bearer(token)})
    good = research_token_headers(monkeypatch)['Authorization']
    anon.post('/api/ml/hemoglobin', content=b'not an image', headers={**PNG, 'Authorization': good})
    text = caplog.text
    assert token not in text and good.split()[1] not in text and TEST_SIGNING_KEY not in text


# ----- rate limiting ------------------------------------------------------------------------------

def test_per_user_minute_limit_with_retry_after(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setenv('ABHAYNAYAN_IMAGE_RATE_PER_MINUTE', '2')
    a = research_token_headers(monkeypatch, user_id='usr-limit-user-a')
    b = research_token_headers(monkeypatch, user_id='usr-limit-user-b')
    with TestClient(app) as c:
        codes = [c.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **a}).status_code for _ in range(3)]
        assert codes[:2] == [503, 503] and codes[2] == 429  # flag off: counted, then limited
        r = c.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **a})
        assert r.json()['error']['code'] == 'RATE_LIMITED' and r.json()['error']['retryable'] is True
        assert 1 <= int(r.headers['Retry-After']) <= 60
        assert c.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **b}).status_code == 503  # other users unaffected
        assert c.post('/api/screenings', json=MODEL_SCREENING, headers=a).status_code == 429  # one budget for research routes


def test_repeated_auth_failures_from_one_ip_are_throttled(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setenv('ABHAYNAYAN_AUTH_FAILURES_PER_MINUTE_PER_IP', '3')
    good = research_token_headers(monkeypatch)
    with TestClient(app) as c:
        for _ in range(3):
            assert c.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **bearer('junk.junk.junk')}).status_code == 401
        blocked = c.post('/api/ml/hemoglobin', content=b'x', headers={**PNG, **good})
        assert blocked.status_code == 429 and 'Retry-After' in blocked.headers
        assert 'token' not in blocked.json()['error']['message'].lower()


def test_limiter_windows_expire_and_day_limit_applies():
    t = [0.0]
    lim = Limiter(per_minute=2, per_day=3, max_concurrent=5, auth_failures_per_minute=5, clock=lambda: t[0])
    for _ in range(2):
        assert lim.acquire('u').allowed
        lim.release('u')
    assert lim.acquire('u').reason == 'per_minute'
    t[0] = 61.0
    assert lim.acquire('u').allowed
    lim.release('u')
    t[0] = 200.0
    d = lim.acquire('u')
    assert not d.allowed and d.reason == 'per_day' and d.retry_after_seconds > 60
    t[0] = 86_401.0
    assert lim.acquire('u').allowed


def test_limiter_concurrency_cap_and_release():
    lim = Limiter(per_minute=100, per_day=100, max_concurrent=2, auth_failures_per_minute=5)
    assert lim.acquire('u').allowed and lim.acquire('u').allowed
    assert lim.acquire('u').reason == 'concurrency'
    lim.release('u')
    assert lim.acquire('u').allowed


def test_limiter_is_exact_under_concurrent_threads():
    lim = Limiter(per_minute=25, per_day=1000, max_concurrent=1000, auth_failures_per_minute=5)
    allowed = []
    barrier = threading.Barrier(40)

    def worker():
        barrier.wait()
        for _ in range(5):
            allowed.append(lim.acquire('shared').allowed)
    threads = [threading.Thread(target=worker) for _ in range(40)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sum(allowed) == 25 and len(allowed) == 200


@pytest.mark.usefixtures('test_body_site_verifier')
def test_concurrency_slot_released_after_errors(anon, monkeypatch, fake_registry):
    fake_registry()
    monkeypatch.setenv('ABHAYNAYAN_IMAGE_MAX_CONCURRENT', '1')
    config.reload()
    import app.main as main
    monkeypatch.setattr(main, '_limiter', None)
    headers = research_token_headers(monkeypatch)
    for _ in range(3):  # failing requests (bad image) must not leak the single slot
        assert anon.post('/api/ml/hemoglobin', content=b'bad', headers={**PNG, **headers}).status_code == 415
    assert anon.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={**PNG, **headers}).status_code == 200


def test_operator_cli_issues_verifiable_token_and_refuses_weak_key(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('issue_access_token', Path(__file__).resolve().parents[1] / 'scripts' / 'issue_access_token.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setenv('ABHAYNAYAN_SESSION_SIGNING_KEY', TEST_SIGNING_KEY)
    assert cli.main(['--user', 'usr-cli-operator-1', '--role', 'research_operator', '--ttl', '120']) == 0
    token = capsys.readouterr().out.strip()
    assert auth.verify(token).has_role('research_operator')
    monkeypatch.setenv('ABHAYNAYAN_SESSION_SIGNING_KEY', 'change-me-change-me-change-me-change-me')
    assert cli.main(['--user', 'usr-cli-operator-1', '--role', 'research_operator']) == 2
    err = capsys.readouterr().err
    assert 'PLACEHOLDER' in err and 'change-me' not in err
