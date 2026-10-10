from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import gemini, store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(gemini, 'API_KEY', '')
    with TestClient(app) as test_client:
        yield test_client


def valid_sync_record(record_id='scr-offline-1', screening_type='maternal_anemia', case='maternal-normal'):
    values = {
        'maternal-normal': (11.8, 'g/dL', 'DEMO_LOW'),
        'maternal-moderate': (9.4, 'g/dL', 'DEMO_MODERATE'),
        'maternal-high': (7.8, 'g/dL', 'DEMO_HIGH'),
        'jaundice-review': (12.8, 'mg/dL', 'REQUIRES_REVIEW'),
        'jaundice-escalate': (18.0, 'mg/dL', 'DEMO_ESCALATE'),
    }
    estimate, unit, risk = values[case]
    return {
        'id': record_id,
        'patient': {'patient_id': 'ABH-2026-0099', 'demo': True},
        'result': {
            'screening_type': screening_type, 'estimate': estimate, 'unit': unit,
            'risk_category': risk, 'confidence': 0.8, 'quality_score': 0.9,
            'requires_confirmation': True, 'model_mode': 'DEMO', 'synthetic': True,
            'case_id': case, 'case_label': 'Synthetic test',
            'generated_at': datetime.now(timezone.utc).isoformat(),
        },
        'worker_id': 'demo-worker', 'phc': 'Demo PHC', 'created_at': datetime.now(timezone.utc).isoformat(),
        'sync_status': 'queued',
    }


def test_health_is_prototype_and_key_not_exposed(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json()['mode'] == 'PROTOTYPE_DEMO'
    assert response.json()['gemini_configured'] is False
    assert 'api_key' not in response.text.lower()


def test_demo_cases_mark_synthetic(client):
    data = client.get('/api/demo/cases').json()
    assert data['synthetic'] is True
    assert len(data['cases']['maternal_anemia']) == 3
    assert len(data['cases']['neonatal_jaundice']) == 2
    assert 'pixels' in data['note']


def test_create_maternal_screening_returns_safety_and_fhir(client):
    response = client.post('/api/screenings', json={
        'id': 'scr-test-maternal', 'patient': {'patient_id': 'ABH-2026-0001'},
        'screening_type': 'maternal_anemia', 'case_id': 'maternal-moderate',
    })
    assert response.status_code == 200
    record = response.json()
    assert record['result']['estimate'] == 9.4
    assert record['result']['synthetic'] is True
    assert 'not a diagnosis' in record['result']['safety_note'].lower()
    assert record['fhir_bundle']['resourceType'] == 'Bundle'
    assert record['sync_status'] == 'synced'


def test_create_neonatal_screening_uses_mg_dl(client):
    response = client.post('/api/screenings', json={
        'patient': {'patient_id': 'ABH-2026-0002'}, 'screening_type': 'neonatal_jaundice',
        'case_id': 'jaundice-escalate',
    })
    assert response.status_code == 200
    assert response.json()['result']['unit'] == 'mg/dL'
    assert response.json()['result']['risk_category'] == 'DEMO_ESCALATE'


def test_create_screening_rejects_real_or_local_profile(client):
    response = client.post('/api/screenings', json={
        'patient': {'patient_id': 'ABH-2026-0002', 'demo': False},
        'screening_type': 'maternal_anemia', 'case_id': 'maternal-normal',
    })
    assert response.status_code == 422
    assert 'real/local patient' in response.json()['detail']
    assert client.get('/api/dashboard').json()['total_screenings'] == 0


def test_unknown_case_rejected(client):
    response = client.post('/api/screenings', json={
        'patient': {'patient_id': 'ABH-2026-0003'}, 'screening_type': 'maternal_anemia', 'case_id': 'unknown',
    })
    assert response.status_code == 422


def test_request_rejects_image_or_extra_phi_field(client):
    response = client.post('/api/screenings', json={
        'patient': {'patient_id': 'ABH-2026-0004'}, 'screening_type': 'maternal_anemia',
        'case_id': 'maternal-normal', 'image_base64': 'not-uploaded',
    })
    assert response.status_code == 422


def test_patient_id_must_be_pseudonymous(client):
    response = client.post('/api/screenings', json={
        'patient': {'patient_id': 'Rani Kumari'}, 'screening_type': 'maternal_anemia', 'case_id': 'maternal-normal',
    })
    assert response.status_code == 422


def test_screening_create_is_idempotent_for_supplied_id(client):
    payload = {'id': 'scr-idempotent', 'patient': {'patient_id': 'ABH-2026-0005'},
               'screening_type': 'maternal_anemia', 'case_id': 'maternal-normal'}
    first = client.post('/api/screenings', json=payload).json()
    second = client.post('/api/screenings', json=payload).json()
    assert first['id'] == second['id']
    assert first['created_at'] == second['created_at']
    assert client.get('/api/dashboard').json()['total_screenings'] == 1


def test_get_screening_and_404(client):
    record = client.post('/api/screenings', json={
        'id': 'scr-detail', 'patient': {'patient_id': 'ABH-2026-0006'},
        'screening_type': 'maternal_anemia', 'case_id': 'maternal-normal'}).json()
    assert client.get('/api/screenings/scr-detail').json()['id'] == record['id']
    assert client.get('/api/screenings/nope').status_code == 404


def test_sync_accepts_and_marks_record(client):
    response = client.post('/api/sync', json={'records': [valid_sync_record()]})
    assert response.status_code == 200
    assert response.json()['accepted'] == 1
    assert response.json()['synced_ids'] == ['scr-offline-1']
    assert client.get('/api/screenings/scr-offline-1').json()['sync_status'] == 'synced'


def test_sync_is_idempotent(client):
    record = valid_sync_record()
    first = client.post('/api/sync', json={'records': [record]}).json()
    second = client.post('/api/sync', json={'records': [record]}).json()
    assert first['accepted'] == 1
    assert second['duplicate'] == 1


def test_sync_rejects_non_synthetic_output(client):
    record = valid_sync_record()
    record['result']['synthetic'] = False
    record['result']['model_mode'] = 'TFLITE'
    response = client.post('/api/sync', json={'records': [record]})
    assert response.status_code == 422


def test_sync_rejects_non_demo_patient(client):
    record = valid_sync_record()
    record['patient']['demo'] = False
    response = client.post('/api/sync', json={'records': [record]})
    assert response.status_code == 422


def test_sync_rejects_more_than_100_records(client):
    response = client.post('/api/sync', json={'records': [valid_sync_record(str(i)) for i in range(101)]})
    assert response.status_code == 422


def test_dashboard_counts_screenings_and_referrals(client):
    client.post('/api/screenings', json={'id': 'scr-dashboard', 'patient': {'patient_id': 'ABH-2026-0010'},
                                        'screening_type': 'maternal_anemia', 'case_id': 'maternal-high'})
    data = client.get('/api/dashboard').json()
    assert data['total_screenings'] == 1
    assert data['today_screenings'] == 1
    assert data['referrals'] == 0


def test_patients_endpoint_contains_pseudonymous_ids(client):
    client.post('/api/screenings', json={'id': 'scr-patients', 'patient': {'patient_id': 'ABH-2026-0011'},
                                        'screening_type': 'maternal_anemia', 'case_id': 'maternal-normal'})
    data = client.get('/api/patients').json()
    assert data[0]['patient_id'] == 'ABH-2026-0011'
    assert 'name' not in data[0]


def test_counselling_uses_local_fallback_without_key(client):
    response = client.post('/api/counselling', json={
        'screening_type': 'maternal_anemia', 'estimate': 9.4, 'unit': 'g/dL',
        'risk_category': 'DEMO_MODERATE', 'confidence': 0.82, 'quality_score': 0.9, 'language': 'hi',
    })
    assert response.status_code == 200
    assert response.json()['mode'] == 'LOCAL_FALLBACK'
    assert response.json()['language'] == 'hi'
    assert 'प्रोटोटाइप' in response.json()['summary']


def test_counselling_handles_bhojpuri(client):
    response = client.post('/api/counselling', json={
        'screening_type': 'neonatal_jaundice', 'estimate': 18, 'unit': 'mg/dL',
        'risk_category': 'DEMO_ESCALATE', 'confidence': 0.76, 'quality_score': 0.88, 'language': 'bho', 'infant_age_hours': 42,
    })
    assert response.status_code == 200
    assert response.json()['language'] == 'bho'
    assert response.json()['referral_required'] is True


def test_counselling_rejects_out_of_range_confidence(client):
    response = client.post('/api/counselling', json={
        'screening_type': 'maternal_anemia', 'estimate': 9.4, 'unit': 'g/dL',
        'risk_category': 'DEMO_MODERATE', 'confidence': 1.5, 'quality_score': 0.9,
    })
    assert response.status_code == 422


def test_counselling_rejects_mismatched_measurement_unit(client):
    response = client.post('/api/counselling', json={
        'screening_type': 'maternal_anemia', 'estimate': 9.4, 'unit': 'mg/dL',
        'risk_category': 'DEMO_MODERATE', 'confidence': 0.8, 'quality_score': 0.9,
    })
    assert response.status_code == 422


def test_counselling_rejects_newborn_age_out_of_range(client):
    response = client.post('/api/counselling', json={
        'screening_type': 'neonatal_jaundice', 'estimate': 12.8, 'unit': 'mg/dL',
        'risk_category': 'REQUIRES_REVIEW', 'confidence': 0.8, 'quality_score': 0.9,
        'infant_age_hours': 9000,
    })
    assert response.status_code == 422


def test_fhir_endpoint_returns_preliminary_bundle(client):
    response = client.post('/api/fhir', json={
        'patient': {'patient_id': 'ABH-2026-0020', 'demo': True}, 'screening_id': 'screen-20',
        'result': {'screening_type': 'maternal_anemia', 'estimate': 11.8, 'unit': 'g/dL',
                   'risk_category': 'DEMO_LOW', 'confidence': 0.82, 'quality_score': 0.91,
                   'synthetic': True, 'model_mode': 'DEMO'},
    })
    assert response.status_code == 200
    bundle = response.json()
    assert bundle['resourceType'] == 'Bundle'
    types = [entry['resource']['resourceType'] for entry in bundle['entry']]
    assert types == ['Patient', 'Encounter', 'Observation', 'DiagnosticReport']
    obs = next(x['resource'] for x in bundle['entry'] if x['resource']['resourceType'] == 'Observation')
    assert obs['status'] == 'preliminary'
    assert 'synthetic' in obs['note'][0]['text'].lower()


def test_fhir_rejects_non_synthetic(client):
    response = client.post('/api/fhir', json={
        'patient': {'patient_id': 'ABH-2026-0021', 'demo': True}, 'screening_id': 'screen-21',
        'result': {'screening_type': 'maternal_anemia', 'estimate': 11.8, 'unit': 'g/dL',
                   'risk_category': 'LOW', 'confidence': 0.82, 'quality_score': 0.91,
                   'synthetic': False, 'model_mode': 'TFLITE'},
    })
    assert response.status_code == 422


def test_fhir_rejects_non_demo_patient_profile(client):
    response = client.post('/api/fhir', json={
        'patient': {'patient_id': 'ABH-2026-0021', 'demo': False}, 'screening_id': 'screen-real-profile',
        'result': {'screening_type': 'maternal_anemia', 'estimate': 11.8, 'unit': 'g/dL',
                   'risk_category': 'DEMO_LOW', 'confidence': 0.82, 'quality_score': 0.91,
                   'synthetic': True, 'model_mode': 'DEMO'},
    })
    assert response.status_code == 422
    assert 'synthetic demo profiles only' in response.json()['detail']


def test_fhir_rejects_identifying_patient_fields(client):
    response = client.post('/api/fhir', json={
        'patient': {'patient_id': 'ABH-2026-0022', 'demo': True, 'name': 'Real Person'}, 'screening_id': 'screen-22',
        'result': {'screening_type': 'maternal_anemia', 'estimate': 11.8, 'unit': 'g/dL',
                   'risk_category': 'DEMO_LOW', 'confidence': 0.82, 'quality_score': 0.91,
                   'synthetic': True, 'model_mode': 'DEMO'},
    })
    assert response.status_code == 422


def test_referral_rejects_non_demo_patient_profile(client):
    record = valid_sync_record(record_id='scr-real-referral')
    record['patient']['demo'] = False
    response = client.post('/api/referrals', json={'id': 'ref-real-profile', 'screening': record})
    assert response.status_code == 422
    assert 'fixed synthetic demo' in response.json()['detail']
    assert client.get('/api/referrals').json() == []


def test_referral_pdf_flow(client):
    screening = client.post('/api/screenings', json={
        'id': 'scr-referral', 'patient': {'patient_id': 'ABH-2026-0030'},
        'screening_type': 'neonatal_jaundice', 'case_id': 'jaundice-review'}).json()
    payload = {'id': 'referral-30', 'screening': screening, 'language': 'en',
               'worker_name': 'Demo ASHA Worker', 'next_step': 'Confirm with clinician review.',
               'counselling': 'Synthetic demo value only; not a diagnosis.'}
    created = client.post('/api/referrals', json=payload)
    assert created.status_code == 200
    pdf = client.get(created.json()['pdf_url'])
    assert pdf.status_code == 200
    assert pdf.content.startswith(b'%PDF-')
    assert 'application/pdf' in pdf.headers['content-type']


def test_referral_pdf_404(client):
    assert client.get('/api/referrals/no-such-referral/pdf').status_code == 404


def test_referral_duplicate_id_is_idempotent(client):
    screening = client.post('/api/screenings', json={'id': 'scr-ref-dup', 'patient': {'patient_id': 'ABH-2026-0031'},
                                                     'screening_type': 'maternal_anemia', 'case_id': 'maternal-high'}).json()
    payload = {'id': 'ref-dup', 'screening': screening}
    assert client.post('/api/referrals', json=payload).json()['created'] is True
    assert client.post('/api/referrals', json=payload).json()['created'] is False


def test_model_status_explains_disabled_research(client):
    response = client.get('/api/model/status')
    assert response.status_code == 200
    assert response.json()['research_baseline_enabled_for_screening'] is False
    assert response.json()['active_inference']['uses_patient_pixels_for_estimate'] is False


def test_pipeline_explicitly_says_no_image_upload(client):
    response = client.get('/api/pipeline').json()
    assert response['capture']['backend_receives_images'] is False
    assert response['inference']['uses_patient_pixels_for_estimate'] is False


def test_vision_capabilities_says_upload_disabled(client):
    data = client.get('/api/vision/capabilities').json()
    assert data['image_upload_api'] is False


def test_web_shell_served_same_origin(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'AbhayNayan' in response.text


def test_static_app_module_served(client):
    response = client.get('/js/app.js')
    assert response.status_code == 200
    assert 'initialize' in response.text.lower() or 'main' in response.text.lower()


def test_unknown_extension_path_404(client):
    assert client.get('/not-a-file.json').status_code == 404
