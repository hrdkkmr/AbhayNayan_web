"""GET /api/ready (audit L1; AC-MOD-01, AC-MOD-02 backend, AC-MOD-06)."""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.main import app
from app.ml import registry as R
from app.services import gemini, store
from conftest import TEST_SIGNING_KEY, research_token_headers
from test_ml import conjunctiva_like, fake_linear, png_bytes, write_registry


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(gemini, 'API_KEY', '')
    for name in ('GEMINI_API_KEY', 'GEMINI_MODEL', 'ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', 'ABHAYNAYAN_ENV'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('ABHAYNAYAN_SESSION_SIGNING_KEY', TEST_SIGNING_KEY)
    with TestClient(app) as c:
        yield c


def use_registry(monkeypatch, path):
    reg = R.Registry(path)
    import app.main as main
    monkeypatch.setattr(main, 'REGISTRY', reg)
    monkeypatch.setattr(R, 'REGISTRY', reg)
    return reg


def fake_models(tmp_path):
    d = tmp_path / 'models'
    d.mkdir()
    return write_registry(d, {'hb-hgb-cf': {'task': 'hemoglobin', 'contents': {'hb.json': fake_linear(12.0)}},
                              'njn-mnv3-logreg': {'task': 'neonatal_jaundice_class', 'contents': {'njn.json': fake_linear(0.0, logistic=True)}}})


def test_normal_startup_is_operational_with_clinical_inference_disabled(client):
    r = client.get('/api/ready')
    b = r.json()
    assert r.status_code == 200 and b['status'] in ('ready', 'degraded')
    assert b['clinical_inference'] == {'status': 'disabled', 'reason_code': 'NO_VALIDATED_MODEL_FOR_TASK', 'validated_tasks': []}
    assert b['components']['research_inference']['status'] == 'disabled'
    assert b['components']['database']['status'] == 'ok'
    assert b['components']['integrations']['authentication'] == 'configured'
    assert b['components']['integrations']['gemini'] == 'not_configured'  # unconfigured is never reported as healthy
    for entry in b['components']['models'].values():
        assert entry['validation_status'] == 'RESEARCH_ONLY'  # readiness never implies validation


def test_body_contains_no_paths_or_secrets(client, tmp_path):
    text = client.get('/api/ready').text
    assert TEST_SIGNING_KEY not in text and str(tmp_path) not in text
    assert ':\\' not in text and '/models/' not in text and 'Traceback' not in text


def test_absent_models_are_reported_and_not_fatal(client, tmp_path, monkeypatch):
    d = fake_models(tmp_path)
    for name in ('hb.json', 'njn.json'):
        (d / name).unlink()
    use_registry(monkeypatch, d)
    r = client.get('/api/ready')
    b = r.json()
    assert r.status_code == 200 and b['status'] == 'ready'  # optional research models may be absent (e.g. Docker image)
    hb = b['components']['models']['hb-hgb-cf']
    assert hb == {**hb, 'artifacts': 'missing', 'checksum': 'not_checked', 'loadable': False, 'reason_code': 'MODEL_UNAVAILABLE'}


def test_checksum_mismatch_blocks_loading_and_degrades(client, tmp_path, monkeypatch):
    d = fake_models(tmp_path)
    reg = use_registry(monkeypatch, d)
    (d / 'hb.json').write_text(json.dumps(fake_linear(99.0)))  # tampered after pinning
    b = client.get('/api/ready').json()
    hb = b['components']['models']['hb-hgb-cf']
    assert hb['checksum'] == 'mismatch' and hb['loadable'] is False and hb['reason_code'] == 'MODEL_INTEGRITY_FAILED'
    assert b['status'] == 'degraded'
    monkeypatch.setenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', '1')
    with pytest.raises(R.ModelError) as e:
        reg.served('hemoglobin')
    assert e.value.code == 'MODEL_INTEGRITY_FAILED'
    r = client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()),
                    headers={'Content-Type': 'image/png', **research_token_headers(monkeypatch)})
    assert r.status_code == 503 and r.json()['error']['code'] == 'MODEL_INTEGRITY_FAILED' and 'estimate' not in r.json()


def test_incompatible_artifact_reported(client, tmp_path, monkeypatch):
    d = tmp_path / 'models'
    d.mkdir()
    write_registry(d, {'hb-hgb-cf': {'task': 'hemoglobin', 'contents': {'hb.json': fake_linear(12.0, feature_version='cf-v0')}}})
    use_registry(monkeypatch, d)
    hb = client.get('/api/ready').json()['components']['models']['hb-hgb-cf']
    assert hb['checksum'] == 'verified' and hb['loadable'] is False and hb['reason_code'] == 'MODEL_INCOMPATIBLE'


def test_restored_artifact_is_reverified_without_restart(client, tmp_path, monkeypatch):
    d = fake_models(tmp_path)
    use_registry(monkeypatch, d)
    good = (d / 'hb.json').read_bytes()
    (d / 'hb.json').unlink()
    assert client.get('/api/ready').json()['components']['models']['hb-hgb-cf']['reason_code'] == 'MODEL_UNAVAILABLE'
    (d / 'hb.json').write_bytes(good)
    st = (d / 'hb.json').stat()
    os.utime(d / 'hb.json', ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    hb = client.get('/api/ready').json()['components']['models']['hb-hgb-cf']
    assert hb['loadable'] is True and hb['checksum'] == 'verified'


def test_research_flag_reported_but_clinical_inference_stays_disabled(client, monkeypatch):
    monkeypatch.setenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', '1')
    b = client.get('/api/ready').json()
    assert b['components']['research_inference']['status'] == 'enabled'
    assert b['clinical_inference']['status'] == 'disabled'


def test_database_unavailable_is_not_ready(client, monkeypatch):
    def boom():
        raise OSError('disk gone at C:/secret/path')
    monkeypatch.setattr(store, 'ping', boom)
    r = client.get('/api/ready')
    assert r.status_code == 503 and r.json()['status'] == 'not_ready'
    assert r.json()['components']['database']['status'] == 'unavailable' and 'secret' not in r.text


def test_invalid_development_configuration_is_visible(client, monkeypatch):
    monkeypatch.setenv('ABHAYNAYAN_SESSION_SIGNING_KEY', 'change-me-please-change-me-please-123')
    monkeypatch.setenv('GEMINI_API_KEY', 'present-without-model')
    config.reload()
    b = client.get('/api/ready').json()
    problems = {(p['variable'], p['code']) for p in b['components']['configuration']['problems']}
    assert ('ABHAYNAYAN_SESSION_SIGNING_KEY', 'PLACEHOLDER') in problems
    assert b['components']['integrations']['authentication'] == 'not_configured'
    assert b['components']['integrations']['gemini'] == 'misconfigured' and b['status'] == 'degraded'
    assert 'change-me-please' not in json.dumps(b) and 'present-without-model' not in json.dumps(b)


def test_health_endpoint_unchanged(client):
    b = client.get('/api/health').json()
    assert b['status'] == 'ok' and 'No clinical inference' in b['note']
