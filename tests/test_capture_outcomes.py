"""Phase 5: contract 2.0 envelopes on the research routes; quality is separate from compatibility; fail closed.

Synthetic software fixtures only; nothing here is evidence of clinical accuracy.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core import prediction as P
from app.main import app
from app.services import gemini, store
from conftest import research_token_headers
from test_ml import conjunctiva_like, fake_linear, fake_registry, png_bytes  # noqa: F401

DOC = Path(__file__).resolve().parents[1] / 'docs' / 'prediction_contract.md'
BLOCKS = [json.loads(b) for b in re.findall(r'```json\n(.*?)```', DOC.read_text(encoding='utf-8'), re.S)]
EXAMPLES = [b for b in BLOCKS if b.get('schema') == P.SCHEMA]
SCHEMA = next(b for b in BLOCKS if b.get('$schema'))
PNG = {'Content-Type': 'image/png'}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(gemini, 'API_KEY', '')
    monkeypatch.setenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', '1')
    headers = research_token_headers(monkeypatch)
    with TestClient(app) as c:
        c.headers.update(headers)
        yield c


def pink_noise(masked: bool, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rgb = np.clip(rng.normal((200, 110, 120), 12, (240, 320, 3)), 0, 255).astype(np.uint8)
    if not masked:
        return rgb
    alpha = np.zeros((240, 320), np.uint8)
    alpha[40:200, 40:280] = 255
    return np.dstack([rgb, alpha])


def valid(env: dict) -> dict:
    assert P.violations(env) == [], P.violations(env)
    return env


# ----- contract: the Python validator agrees with the documented examples ------------------------------

def test_documented_examples_are_valid():
    assert len(EXAMPLES) == 5
    for e in EXAMPLES:
        assert P.violations(e) == []


VALUE = {'value': 12.0, 'unit': 'g/dL', 'display_precision': 1, 'uncertainty': {'kind': 'none'}}
NEGATIVES = {
    'unable carrying a value': (3, lambda e: e.update(estimate=VALUE)),
    'unable without reason': (2, lambda e: e.update(reason_code=None)),
    'research warning stripped': (4, lambda e: e.update(warnings=[])),
    'estimate on incompatible input': (4, lambda e: e['input_compatibility'].update(status='incompatible')),
    'Hb estimate from a guide crop': (4, lambda e: e['input'].update(body_site='palpebral_conjunctiva_guide_crop')),
    'estimate after quality failure': (4, lambda e: e['input_quality'].update(status='failed')),
    'unknown model_status': (0, lambda e: e['model'].update(model_status='validated')),
    'unknown status': (0, lambda e: e.update(status='estimated_low_confidence')),
    'research labelled as fixture': (4, lambda e: e.update(inference_source='fixture')),
    'unit mismatch': (0, lambda e: e['estimate'].update(unit='mg/dL')),
    'non-finite value': (0, lambda e: e['estimate'].update(value=float('nan'))),
    'bilirubin estimate': (2, lambda e: e.update(status='estimated', reason_code=None, inference_source='edge',
                                                 estimate={**VALUE, 'unit': 'mg/dL'}, model=EXAMPLES[0]['model'])),
}


@pytest.mark.parametrize('name', sorted(NEGATIVES))
def test_violations_rejected(name):
    idx, mutate = NEGATIVES[name]
    e = copy.deepcopy(EXAMPLES[idx])
    mutate(e)
    assert P.violations(e), name


def test_build_refuses_to_emit_an_invalid_envelope():
    with pytest.raises(ValueError):
        P.build(status='unable_to_estimate', reason_code=None, task='hemoglobin_from_palpebral_conjunctiva', input_info=EXAMPLES[1]['input'],
                quality=EXAMPLES[1]['input_quality'], compatibility=EXAMPLES[1]['input_compatibility'], estimate=None, model=None,
                source='none', warnings=[], software_version='t')


# ----- routes: every refusal says why, carries no value, and validates -----------------------------------

def test_opaque_upload_is_target_region_incompatible_for_hb(client, fake_registry):
    fake_registry()
    for img in (pink_noise(masked=False), conjunctiva_like()[..., :3].copy()):  # app-style rectangle crop / opaque photo
        r = client.post('/api/ml/hemoglobin', content=png_bytes(img), headers=PNG)
        b = r.json()
        assert r.status_code == 422 and b['error']['code'] == 'TARGET_REGION_INCOMPATIBLE' and 'estimate' not in b
        env = valid(b['prediction'])
        assert env['status'] == 'unable_to_estimate' and env['estimate'] is None and env['reason_code'] == 'TARGET_REGION_INCOMPATIBLE'


def test_masked_crop_is_unsupported_for_the_whole_photo_classifier(client, fake_registry):
    fake_registry()
    r = client.post('/api/ml/neonatal-jaundice-class', content=png_bytes(conjunctiva_like()), headers=PNG)
    assert r.status_code == 422 and r.json()['error']['code'] == 'MODALITY_UNSUPPORTED' and 'score' not in r.json()
    assert valid(r.json()['prediction'])['reason_code'] == 'MODALITY_UNSUPPORTED'


@pytest.mark.parametrize('route,img', [('/api/ml/hemoglobin', lambda: pink_noise(masked=True)),
                                       ('/api/ml/neonatal-jaundice-class', lambda: pink_noise(masked=False))])
def test_quality_pass_does_not_imply_compatibility_and_noise_is_never_scored(client, fake_registry, route, img):
    # Without a verifier the server fails closed even when quality, mask and distribution checks all pass (audit H1).
    fake_registry()
    r = client.post(route, content=png_bytes(img()), headers=PNG)
    b = r.json()
    assert r.status_code == 422 and b['error']['code'] == 'MODALITY_UNVERIFIED'
    env = valid(b['prediction'])
    assert env['input_quality']['status'] == 'passed' and env['input_compatibility']['status'] == 'incompatible'
    assert env['estimate'] is None and 'estimate' not in b and 'score' not in b
    failed = [c['check_id'] for c in env['input_compatibility']['checks'] if not c['passed']]
    assert failed == ['body_site_verified']


def test_quality_failure_envelope_lists_the_failed_check(client, fake_registry):
    fake_registry()
    flat = np.full((64, 64, 4), 128, np.uint8)
    flat[:8, :, 3] = 0
    b = client.post('/api/ml/hemoglobin', content=png_bytes(flat), headers=PNG).json()
    env = valid(b['prediction'])
    assert env['reason_code'] == 'QUALITY_FAILED' and env['input_quality']['status'] == 'failed'
    assert 'sharpness_laplacian_var' in [c['check_id'] for c in env['input_quality']['checks'] if not c['passed']]


@pytest.mark.parametrize('data,ctype,reason', [(b'', 'image/png', 'INPUT_EMPTY'), (b'\x89PNG\r\n\x1a\n' + b'\x00' * 40, 'image/png', 'INPUT_DECODE_FAILED'),
                                               (b'hello', 'text/plain', 'INPUT_FORMAT_UNSUPPORTED')])
def test_invalid_input_envelopes(client, fake_registry, data, ctype, reason):
    fake_registry()
    b = client.post('/api/ml/hemoglobin', content=data, headers={'Content-Type': ctype}).json()
    assert valid(b['prediction'])['reason_code'] == reason


@pytest.mark.usefixtures('test_body_site_verifier')
def test_verified_research_estimate_carries_provenance_and_warning(client, fake_registry):
    reg = fake_registry()
    b = client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers=PNG).json()
    env = valid(b['prediction'])
    assert env['status'] == 'estimated' and env['estimate']['value'] == b['estimate'] == 12.0
    assert env['model']['model_status'] == 'research_only' and env['inference_source'] == 'backend'
    assert env['model']['artifact_sha256'] == reg.get('hb-hgb-cf').sha256
    assert [w['code'] for w in env['warnings']] == ['RESEARCH_ONLY_NOT_VALIDATED']
    assert env['input']['body_site_verification']['status'] == 'verified'


@pytest.mark.usefixtures('test_body_site_verifier')
def test_model_failure_is_status_error_without_value(client, fake_registry, monkeypatch):
    reg = fake_registry()
    monkeypatch.setattr(reg.get('hb-hgb-cf'), 'runner', lambda *_: (_ for _ in ()).throw(RuntimeError('x')))
    b = client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers=PNG).json()
    env = valid(b['prediction'])
    assert env['status'] == 'error' and env['reason_code'] == 'INFERENCE_RUNTIME_ERROR' and env['estimate'] is None


def test_envelopes_match_the_documented_json_schema(client, fake_registry, test_body_site_verifier):
    jsonschema = pytest.importorskip('jsonschema')  # in the research venv only; requirements.txt does not include it
    validator = jsonschema.Draft202012Validator(SCHEMA)
    fake_registry()
    bodies = [client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers=PNG).json(),
              client.post('/api/ml/hemoglobin', content=png_bytes(pink_noise(False)), headers=PNG).json(),
              client.post('/api/ml/neonatal-jaundice-class', content=png_bytes(conjunctiva_like()), headers=PNG).json()]
    for b in bodies:
        errors = list(validator.iter_errors(b['prediction']))
        assert not errors, errors[0].message


# ----- existing safeguards still come first, and research stays off by default --------------------------

def test_unauthenticated_and_disabled_requests_carry_no_envelope(tmp_path, monkeypatch, fake_registry):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', '1')
    headers = research_token_headers(monkeypatch)
    fake_registry()
    with TestClient(app) as c:
        anon = c.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers=PNG)
        assert anon.status_code == 401 and 'prediction' not in anon.json()
        big = c.post('/api/ml/hemoglobin', content=b'\x89PNG\r\n\x1a\n', headers={**PNG, **headers, 'Content-Length': str(50 * 1024 * 1024)})
        assert big.status_code == 413
        monkeypatch.delenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS')
        off = c.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={**PNG, **headers})
        assert off.status_code == 503 and off.json()['error']['code'] == 'MODEL_DISABLED' and 'prediction' not in off.json()


def test_research_switches_default_off(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    for flag in ('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', 'ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA'):
        monkeypatch.delenv(flag, raising=False)
    with TestClient(app) as c:
        ready = c.get('/api/ready').json()
        assert ready['components']['research_inference']['status'] == 'disabled'
        assert ready['clinical_inference']['status'] == 'disabled'


def test_legacy_model_mode_never_returns_a_number(client):
    r = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-P5-1', 'demo': True}, 'screening_type': 'neonatal_jaundice',
                                             'inference_mode': 'MODEL'})
    assert r.status_code == 503 and r.json()['error']['code'] == 'MODEL_DISABLED' and 'result' not in r.json()
