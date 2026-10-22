"""API contract 1.0 checks shared with the Android client (docs/API_CONTRACT.md)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import model_adapters
from app.core.model_adapters import InferenceError, MaternalAnemiaAdapter, NeonatalJaundiceAdapter
from app.main import app
from app.models.schemas import API_CONTRACT_VERSION, AnemiaFeatureInput, ScreeningResult
from app.services import gemini, store
from app.services.fhir import FHIRGenerator
from app.core.inference import infer_demo

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / 'docs' / 'API_CONTRACT.md')


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(gemini, 'API_KEY', '')
    monkeypatch.delenv(model_adapters.EXPERIMENTAL_ANEMIA_FLAG, raising=False)
    with TestClient(app) as test_client:
        yield test_client


def demo_record(record_id='scr-c-1', case='maternal-normal', estimate=11.8):
    return {
        'id': record_id, 'patient': {'patient_id': 'ABH-2026-0100', 'demo': True},
        'result': {'screening_type': 'maternal_anemia', 'estimate': estimate, 'unit': 'g/dL', 'risk_category': 'DEMO_LOW',
                   'model_mode': 'DEMO', 'synthetic': True, 'provenance': 'DEMO_SYNTHETIC', 'case_id': case,
                   'generated_at': datetime.now(timezone.utc).isoformat()},
        'created_at': datetime.now(timezone.utc).isoformat(), 'sync_status': 'queued',
    }


def research_features(**overrides):
    base = {'red_pct': 45.6, 'green_pct': 28.9, 'blue_pct': 25.5, 'feature_source': 'research_dataset_precomputed'}
    return {**base, **overrides}


# ---- contract metadata and error envelope -------------------------------------------------

def test_contract_version_in_health_and_header(client):
    response = client.get('/api/health')
    assert response.json()['api_contract_version'] == API_CONTRACT_VERSION
    assert response.headers['X-AbhayNayan-Contract-Version'] == API_CONTRACT_VERSION
    assert response.json()['gemini_model_configured'] in (True, False)


def test_contract_document_declares_current_version():
    assert DOC.exists()
    assert f'Contract version: `{API_CONTRACT_VERSION}`' in DOC.read_text(encoding='utf-8')


def test_validation_error_uses_envelope_with_string_detail_and_no_echoed_values(client):
    response = client.post('/api/screenings', json={'patient': {'patient_id': 'Rani Kumari 9876543210'},
                                                    'screening_type': 'maternal_anemia', 'case_id': 'maternal-normal'})
    body = response.json()
    assert response.status_code == 422
    assert isinstance(body['detail'], str)
    assert body['error']['code'] == 'VALIDATION_ERROR'
    assert body['error']['fields'][0]['loc'][-1] == 'patient_id'
    assert '9876543210' not in response.text  # submitted values are never echoed


def test_not_found_uses_envelope(client):
    body = client.get('/api/screenings/missing-id').json()
    assert body['error'] == {'code': 'NOT_FOUND', 'message': 'Screening not found.', 'status': 404, 'retryable': False, 'fields': []}


def test_unknown_api_path_uses_envelope(client):
    response = client.get('/api/does-not-exist')
    assert response.status_code == 404
    assert response.json()['error']['status'] == 404


def test_openapi_lists_all_contract_routes(client):
    paths = client.get('/openapi.json').json()['paths']
    for path in ['/api/health', '/api/model/status', '/api/demo/cases', '/api/screenings', '/api/screenings/{screening_id}',
                 '/api/sync', '/api/dashboard', '/api/patients', '/api/counselling', '/api/fhir', '/api/referrals',
                 '/api/referrals/{referral_id}/pdf', '/api/admin/usage']:
        assert path in paths, path


# ---- provenance and demo fixtures ----------------------------------------------------------

def test_demo_result_has_provenance_and_no_invented_confidence(client):
    record = client.post('/api/screenings', json={'id': 'scr-prov', 'patient': {'patient_id': 'ABH-2026-0101'},
                                                  'screening_type': 'neonatal_jaundice', 'case_id': 'jaundice-review',
                                                  'context': {'infant_age_hours': 40}}).json()
    assert record['result']['provenance'] == 'DEMO_SYNTHETIC'
    assert record['result']['confidence'] is None
    assert record['result']['quality_score'] is None
    assert record['result']['model_version'] == 'fixed-demo-fixtures-v1'
    assert record['context']['infant_age_hours'] == 40
    assert record['id_origin'] == 'client'


def test_server_generated_ids_are_distinguishable(client):
    record = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-2026-0102'},
                                                  'screening_type': 'maternal_anemia', 'case_id': 'maternal-normal'}).json()
    assert record['id'].startswith('srv-')
    assert record['id_origin'] == 'server'


def test_result_schema_rejects_mixed_provenance():
    with pytest.raises(ValueError, match='must agree'):
        ScreeningResult(screening_type='maternal_anemia', estimate=11, unit='g/dL', risk_category='DEMO_LOW',
                        synthetic=True, model_mode='DEMO', provenance='EXPERIMENTAL_RESEARCH_ONLY')
    with pytest.raises(ValueError, match='must agree'):
        ScreeningResult(screening_type='maternal_anemia', estimate=11, unit='g/dL', risk_category='X',
                        synthetic=False, model_mode='DEMO', provenance='VALIDATED_FOR_INTENDED_USE')


def test_demo_mode_requires_case_and_rejects_features(client):
    missing = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-1'}, 'screening_type': 'maternal_anemia'})
    assert missing.status_code == 422
    with_features = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-1'}, 'screening_type': 'maternal_anemia',
                                                         'case_id': 'maternal-normal', 'features': research_features()})
    assert with_features.status_code == 422


def test_demo_fixture_rejects_real_profile_with_code(client):
    body = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-1', 'demo': False},
                                                'screening_type': 'maternal_anemia', 'case_id': 'maternal-normal'}).json()
    assert body['error']['code'] == 'DEMO_FIXTURE_REQUIRES_DEMO_PROFILE'


def test_same_id_with_different_content_is_conflict_not_overwrite(client):
    base = {'id': 'scr-conflict', 'patient': {'patient_id': 'ABH-2026-0103'}, 'screening_type': 'maternal_anemia'}
    assert client.post('/api/screenings', json={**base, 'case_id': 'maternal-normal'}).status_code == 200
    second = client.post('/api/screenings', json={**base, 'case_id': 'maternal-high'})
    assert second.status_code == 409
    assert second.json()['error']['code'] == 'ID_CONFLICT'
    assert client.get('/api/screenings/scr-conflict').json()['result']['case_id'] == 'maternal-normal'


# ---- model adapter states ------------------------------------------------------------------

def test_model_mode_disabled_by_default_returns_structured_503(client):
    response = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-1'}, 'screening_type': 'maternal_anemia',
                                                    'inference_mode': 'MODEL', 'features': research_features()})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'MODEL_DISABLED'
    assert 'DISABLED_NO_VALID_MODEL' in response.json()['detail']
    assert client.get('/api/dashboard').json()['total_screenings'] == 0


def test_bilirubin_model_is_never_available_even_with_anemia_flag(client, monkeypatch):
    monkeypatch.setenv(model_adapters.EXPERIMENTAL_ANEMIA_FLAG, '1')
    response = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-1'}, 'screening_type': 'neonatal_jaundice',
                                                    'inference_mode': 'MODEL', 'features': research_features()})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'MODEL_DISABLED'
    assert NeonatalJaundiceAdapter().card().status == 'DISABLED_NO_VALID_MODEL'


def test_experimental_anemia_adapter_labels_output(client, monkeypatch):
    monkeypatch.setenv(model_adapters.EXPERIMENTAL_ANEMIA_FLAG, '1')
    record = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-R-1', 'demo': True}, 'screening_type': 'maternal_anemia',
                                                  'inference_mode': 'MODEL', 'features': research_features()}).json()
    result = record['result']
    assert result['provenance'] == 'EXPERIMENTAL_RESEARCH_ONLY'
    assert result['synthetic'] is False and result['model_mode'] == 'EXPERIMENTAL'
    assert result['unit'] == 'g/dL' and result['confidence'] is None
    assert result['model_version'].startswith('ridge-color-')
    assert 'not a hemoglobin measurement' in result['safety_note'].lower()
    obs = next(e['resource'] for e in record['fhir_bundle']['entry'] if e['resource']['resourceType'] == 'Observation')
    assert obs['meta']['tag'][0]['code'] == 'experimental-research-only'
    assert 'Experimental' in obs['code']['text']
    status = client.get('/api/model/status').json()
    assert status['adapters']['maternal_anemia']['status'] == 'EXPERIMENTAL_RESEARCH_ONLY'
    assert status['research_baseline_enabled_for_screening'] is True


def test_experimental_adapter_rejects_camera_features_and_real_profiles(client, monkeypatch):
    monkeypatch.setenv(model_adapters.EXPERIMENTAL_ANEMIA_FLAG, '1')
    camera = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-R-2'}, 'screening_type': 'maternal_anemia',
                                                  'inference_mode': 'MODEL', 'features': research_features(feature_source='camera_pipeline')})
    assert camera.status_code == 422 and camera.json()['error']['code'] == 'UNSUPPORTED_INPUT'
    real = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-R-3', 'demo': False}, 'screening_type': 'maternal_anemia',
                                                'inference_mode': 'MODEL', 'features': research_features()})
    assert real.status_code == 422 and real.json()['error']['code'] == 'EXPERIMENTAL_REQUIRES_RESEARCH_PROFILE'
    bad_sum = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-R-4'}, 'screening_type': 'maternal_anemia',
                                                   'inference_mode': 'MODEL', 'features': research_features(red_pct=10)})
    assert bad_sum.status_code == 422 and bad_sum.json()['error']['code'] == 'INVALID_INPUT'
    missing = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-R-5'}, 'screening_type': 'maternal_anemia',
                                                   'inference_mode': 'MODEL'})
    assert missing.json()['error']['code'] == 'INVALID_INPUT'


def test_missing_or_malformed_artifact_disables_adapter_without_leaking_paths(tmp_path, monkeypatch):
    monkeypatch.setenv(model_adapters.EXPERIMENTAL_ANEMIA_FLAG, '1')
    missing = MaternalAnemiaAdapter(tmp_path / 'nope.json')
    assert missing.card().status == 'DISABLED_NO_VALID_MODEL'
    with pytest.raises(InferenceError) as info:
        missing.infer(AnemiaFeatureInput(**research_features()))
    assert info.value.code == 'MODEL_DISABLED'
    assert str(tmp_path) not in info.value.message
    bad = tmp_path / 'bad.json'
    bad.write_text(json.dumps({'features': ['a'], 'unit': 'mg/dL'}))
    assert MaternalAnemiaAdapter(bad).card().status == 'DISABLED_NO_VALID_MODEL'


def test_model_status_lists_candidate_models_and_no_paths(client):
    status = client.get('/api/model/status').json()
    ids = {c['id']: c['status'] for c in status['candidate_models']}
    assert ids['neonatal-bilirubin'] == 'DISABLED_NO_VALID_MODEL'
    assert ids['notebook-mobilenetv3-hb'] == 'DISABLED_NO_VALID_MODEL'
    assert ids['demo-fixtures'] == 'DEMO_SYNTHETIC'
    assert status['adapters']['maternal_anemia']['status'] == 'DISABLED_NO_VALID_MODEL'
    assert str(ROOT) not in json.dumps(status)


# ---- sync semantics ------------------------------------------------------------------------

def test_sync_reports_per_record_results_and_does_not_block_batch(client):
    bad = demo_record('scr-bad'); bad['patient']['patient_id'] = 'Not A Pseudonym'
    response = client.post('/api/sync', json={'records': [demo_record('scr-good'), bad]}).json()
    assert response['accepted'] == 1 and response['rejected'] == 1
    assert response['synced_ids'] == ['scr-good']
    assert [r['status'] for r in response['results']] == ['accepted', 'rejected']
    assert response['results'][1]['error']['code'] == 'VALIDATION_ERROR'


def test_sync_retry_is_duplicate_and_changed_content_is_conflict(client):
    client.post('/api/sync', json={'records': [demo_record('scr-retry')]})
    retry = client.post('/api/sync', json={'records': [demo_record('scr-retry')]}).json()
    assert retry['duplicate'] == 1 and retry['synced_ids'] == ['scr-retry']
    changed = client.post('/api/sync', json={'records': [demo_record('scr-retry', case='maternal-high', estimate=7.8)]}).json()
    assert changed['conflict'] == 1 and changed['synced_ids'] == []
    assert client.get('/api/screenings/scr-retry').json()['result']['estimate'] == 11.8
    assert client.get('/api/dashboard').json()['total_screenings'] == 1


def test_sync_accepts_legacy_records_with_placeholder_confidence(client):
    legacy = demo_record('scr-legacy')
    legacy['result'].update({'confidence': 0.82, 'quality_score': 0.91})
    del legacy['result']['provenance']
    assert client.post('/api/sync', json={'records': [legacy]}).json()['accepted'] == 1


def test_dashboard_reports_provenance_and_does_not_fake_pending_sync(client):
    client.post('/api/sync', json={'records': [demo_record('scr-dash')]})
    data = client.get('/api/dashboard').json()
    assert data['pending_sync'] is None
    assert data['by_provenance'] == {'DEMO_SYNTHETIC': 1}
    assert data['by_type'] == {'maternal_anemia': 1}


def test_existing_database_is_migrated_with_provenance_column(tmp_path, monkeypatch):
    import sqlite3
    db_path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE screenings (id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, screening_type TEXT NOT NULL, estimate REAL NOT NULL, '
                   'unit TEXT NOT NULL, risk_category TEXT NOT NULL, confidence REAL NOT NULL, quality_score REAL NOT NULL, model_mode TEXT NOT NULL, '
                   'synthetic INTEGER NOT NULL, worker_id TEXT NOT NULL, phc TEXT NOT NULL, village TEXT, created_at TEXT NOT NULL, payload_json TEXT NOT NULL)')
    monkeypatch.setattr(store, 'DB_PATH', db_path)
    store.init_db()
    with sqlite3.connect(db_path) as db:
        assert 'provenance' in {row[1] for row in db.execute('PRAGMA table_info(screenings)')}


# ---- FHIR and referral ---------------------------------------------------------------------

def test_fhir_synthetic_bundle_is_marked_test_data_without_lab_coding():
    bundle = FHIRGenerator().generate_bundle({'patient_id': 'ABH-1'}, infer_demo('maternal_anemia', 'maternal-normal'), screening_id='s-1')
    obs = next(e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Observation')
    report = next(e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'DiagnosticReport')
    assert obs['meta']['security'][0]['code'] == 'HTEST'
    assert report['meta']['security'][0]['code'] == 'HTEST'
    assert 'coding' not in obs['code']  # no LOINC laboratory code for a non-measured value
    assert obs['valueQuantity'] == {'value': 11.8, 'unit': 'g/dL', 'system': 'http://unitsofmeasure.org', 'code': 'g/dL'}
    assert 'interpretation' not in obs
    assert 'not measured' in obs['code']['text']
    assert 'component' not in obs  # no fabricated confidence/quality components


def test_fhir_bundle_has_no_empty_arrays():
    bundle = FHIRGenerator().generate_bundle({'patient_id': 'ABH-1'}, infer_demo('neonatal_jaundice', 'jaundice-review'), screening_id='s-2')

    def walk(node):
        if isinstance(node, list):
            assert node, 'FHIR forbids empty arrays'
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
    walk(bundle)


def test_referral_pdf_shows_provenance_mode_and_timestamp(client):
    screening = client.post('/api/screenings', json={'id': 'scr-ref-prov', 'patient': {'patient_id': 'ABH-2026-0110'},
                                                     'screening_type': 'neonatal_jaundice', 'case_id': 'jaundice-review',
                                                     'context': {'infant_age_hours': 30}}).json()
    created = client.post('/api/referrals', json={'id': 'ref-prov', 'screening': screening, 'counselling_mode': 'LOCAL_FALLBACK'}).json()
    assert created['provenance'] == 'DEMO_SYNTHETIC'
    stored = store.get_referral('ref-prov')['payload']
    assert stored['generated_at'] and stored['counselling_mode'] == 'LOCAL_FALLBACK'
    pdf = client.get(created['pdf_url'])
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF-')


def test_referral_rejects_client_claimed_model_result(client):
    record = demo_record('scr-fake-model')
    record['result'].update({'synthetic': False, 'model_mode': 'EXPERIMENTAL', 'provenance': 'EXPERIMENTAL_RESEARCH_ONLY'})
    response = client.post('/api/referrals', json={'id': 'ref-fake', 'screening': record})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'REFERRAL_RESULT_NOT_ACCEPTED'


def test_release_package_excludes_raw_data_and_weights():
    import importlib.util
    spec = importlib.util.spec_from_file_location('package_release', ROOT / 'scripts' / 'package_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for rel in ['data/raw/Anemia_Dataset.csv', 'data/private/x.jpg', 'archive.zip', 'NJN.rar', 'models/m.tflite', 'models/m.keras', 'notes.xlsx', 'Anemia_Dataset.csv',
                'models/hb_ridge_cf_v1.json', 'models/njn_mnv3_logreg_v1.onnx', 'models/njn_logreg_cf_v1.json', '.venv-ml/x.py',
                'ml/runs/hb-v1/test_predicted_vs_measured.png', 'data/private/hb_manifest.csv']:
        assert module.is_excluded(ROOT / rel), rel
    for rel in ['data/DATASET_MANIFEST.json', 'models/anemia_color_baseline.json', 'docs/API_CONTRACT.md', 'data/derived/approved.csv',
                'models/MODEL_REGISTRY.json', 'ml/splits/njn_v1.json', 'ml/runs/hb-v1/final_results.json', 'tests/fixtures/ml_golden/golden_cf_v1.json']:
        assert not module.is_excluded(ROOT / rel), rel


def test_dataset_manifest_marks_nothing_publicly_redistributable():
    manifest = json.loads((ROOT / 'data' / 'DATASET_MANIFEST.json').read_text(encoding='utf-8'))
    assert len(manifest['files']) == 5
    assert all(f['approved_for_public_redistribution'] is False for f in manifest['files'])
