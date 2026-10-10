from __future__ import annotations

import numpy as np
import pytest

from app.core.inference import DEMO_CASES, DemoInferenceModel, infer_demo
from app.core.vision import (
    AmbientLightCorrector,
    ConjunctivaROIExtractor,
    ScleraROIExtractor,
    assess_quality,
    blur_score,
    color_normalize,
    extract_color_features,
)
from app.models.schemas import PatientSync, ScreeningResult
from app.services.fhir import FHIRGenerator
from app.services.gemini import parse_gemini_text
from app.services.language import local_counsel


def test_all_demo_fixtures_are_synthetic_and_require_confirmation():
    for kind, cases in DEMO_CASES.items():
        for case_id in cases:
            result = infer_demo(kind, case_id)
            assert result['synthetic'] is True
            assert result['requires_confirmation'] is True
            assert result['model_mode'] == 'DEMO'


def test_demo_case_id_must_match_task():
    with pytest.raises(ValueError):
        infer_demo('maternal_anemia', 'jaundice-escalate')


def test_demo_model_never_converts_features_to_measurement():
    with pytest.raises(ValueError, match='Select a named'):
        DemoInferenceModel().predict({'red_pct': 32.1})


def test_quality_ready_requires_manual_region_confirmation():
    ready = assess_quality(126, 0.8, 0.05, region_confirmed=True)
    blocked = assess_quality(126, 0.8, 0.05, region_confirmed=False)
    assert ready.ready is True
    assert blocked.ready is False
    assert 0 <= ready.quality_score <= 1


def test_quality_flags_low_light_and_motion():
    report = assess_quality(10, 0.8, 0.9, region_confirmed=True)
    assert report.ready is False
    assert any('dark' in reason.lower() for reason in report.reasons)
    assert any('movement' in reason.lower() for reason in report.reasons)


def test_quality_flags_blur():
    report = assess_quality(128, 0.01, 0.01, region_confirmed=True)
    assert report.ready is False
    assert any('blurred' in reason.lower() for reason in report.reasons)


def test_conjunctiva_roi_uses_manual_center_guide():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    extracted = ConjunctivaROIExtractor().extract(image)
    assert extracted['roi'].shape[:2] == (50, 89)
    assert extracted['metadata']['landmark_detected'] is False
    assert extracted['metadata']['source'] == 'MANUAL_CENTER_GUIDE'


def test_sclera_roi_respects_confirmed_bbox():
    image = np.zeros((80, 90, 3), dtype=np.uint8)
    extracted = ScleraROIExtractor().extract(image, (10, 12, 25, 20))
    assert extracted['roi'].shape == (20, 25, 3)
    assert extracted['metadata']['source'] == 'USER_CONFIRMED_BBOX'


def test_roi_rejects_empty_image():
    with pytest.raises(ValueError):
        ConjunctivaROIExtractor().extract(np.array([]))


def test_color_normalization_keeps_shape_and_dtype():
    image = np.full((32, 40, 3), (50, 80, 110), dtype=np.uint8)
    normalized = color_normalize(image)
    assert normalized.shape == image.shape
    assert normalized.dtype == np.uint8


def test_color_features_are_bounded_and_explicitly_exploratory():
    image = np.zeros((20, 20, 3), dtype=np.uint8)
    image[:] = (40, 120, 200)
    features = extract_color_features(image)
    assert 0 <= features['red_pct'] <= 100
    assert 0 <= features['green_pct'] <= 100
    assert 0 <= features['blue_pct'] <= 100
    assert 'not calibrated' in features['feature_note']


def test_color_features_reject_empty_roi():
    with pytest.raises(ValueError):
        extract_color_features(np.array([]))


def test_blur_score_handles_empty_and_textured_frames():
    assert blur_score(np.array([])) == 0
    rng = np.random.default_rng(4)
    texture = rng.integers(0, 255, (80, 80, 3), dtype=np.uint8)
    assert blur_score(texture) > 0


def test_ambient_corrector_without_flash_is_explicit():
    result = AmbientLightCorrector().correct(np.ones((10, 10, 3), dtype=np.uint8))
    assert result['available'] is False
    assert result['corrected'] is False
    assert 'unavailable' in result['message'].lower()


def test_ambient_corrector_rejects_shape_mismatch_gracefully():
    ambient = np.zeros((10, 10, 3), dtype=np.uint8)
    flash = np.zeros((11, 10, 3), dtype=np.uint8)
    result = AmbientLightCorrector().correct(ambient, flash)
    assert result['corrected'] is False
    assert 'dimensions differ' in result['message'].lower()


def test_ambient_corrector_same_shape_returns_demo_differential():
    ambient = np.zeros((10, 10, 3), dtype=np.uint8)
    flash = np.full((10, 10, 3), 42, dtype=np.uint8)
    result = AmbientLightCorrector().correct(ambient, flash)
    assert result['available'] is True
    assert result['corrected'] is True
    assert 'not clinically calibrated' in result['message'].lower()


def test_patient_ids_reject_names_and_spaces():
    with pytest.raises(ValueError):
        PatientSync(patient_id='Rani Kumari')
    assert PatientSync(patient_id='ABH-2026-0001').demo is True


def test_screening_unit_must_match_workflow():
    with pytest.raises(ValueError):
        ScreeningResult(screening_type='maternal_anemia', estimate=12, unit='mg/dL', risk_category='DEMO', confidence=.5, quality_score=.5)


def test_fhir_bundle_contains_expected_resource_types_and_preliminary_obs():
    result = infer_demo('maternal_anemia', 'maternal-normal')
    bundle = FHIRGenerator().generate_bundle({'patient_id': 'ABH-0001'}, result, screening_id='screen-0001')
    resources = [x['resource'] for x in bundle['entry']]
    assert [x['resourceType'] for x in resources] == ['Patient', 'Encounter', 'Observation', 'DiagnosticReport']
    obs = resources[2]
    assert obs['status'] == 'preliminary'
    assert 'synthetic' in obs['note'][0]['text'].lower()


def test_fhir_observation_ids_are_unique_per_screening():
    result = infer_demo('maternal_anemia', 'maternal-normal')
    gen = FHIRGenerator()
    first = gen.generate_bundle({'patient_id': 'ABH-0001'}, result, screening_id='screen-1')
    second = gen.generate_bundle({'patient_id': 'ABH-0001'}, result, screening_id='screen-2')
    ids = [[e['resource']['id'] for e in b['entry'] if e['resource']['resourceType'] == 'Observation'][0] for b in (first, second)]
    assert ids[0].startswith('obs-screen-1-')
    assert ids[1].startswith('obs-screen-2-')
    assert ids[0] != ids[1]
    assert all(len(value) <= 64 for value in ids)


def test_local_counsel_supported_language_and_safety():
    result = local_counsel('neonatal_jaundice', 'bho', 'DEMO_ESCALATE')
    assert result['language'] == 'bho'
    assert result['mode'] == 'LOCAL_FALLBACK'
    assert result['referral_required'] is True
    assert 'इलाज' in result['safety_note']


def test_local_counsel_unknown_language_falls_back_to_english():
    result = local_counsel('maternal_anemia', 'xx')
    assert result['language'] == 'en'


def test_gemini_parser_accepts_safe_structured_counsel():
    payload = '''{"summary":"Synthetic prototype estimate only, not a diagnosis.","risk_explanation":"Demo tag only; clinical confirmation is needed.","counselling_script":"Arrange appropriate testing and clinician review.","recommended_next_step":"Confirm using local protocol.","referral_required":false,"urgency":"ROUTINE_REVIEW","language":"en","safety_note":"Do not use this estimate to change treatment."}'''
    result = parse_gemini_text(payload, 'en', 'maternal_anemia', 'DEMO_MODERATE')
    assert result is not None
    assert result.mode == 'GEMINI'


def test_gemini_parser_rejects_diagnosis_claim_and_wrong_language():
    unsafe = '''{"summary":"You have anemia.","risk_explanation":"Demo.","counselling_script":"See a clinician.","recommended_next_step":"Confirm.","referral_required":false,"urgency":"ROUTINE_REVIEW","language":"en","safety_note":"Not a diagnosis."}'''
    assert parse_gemini_text(unsafe, 'en', 'maternal_anemia', 'DEMO_LOW') is None
    safe_wrong_language = '''{"summary":"Résumé.","risk_explanation":"Démo.","counselling_script":"Confirmer.","recommended_next_step":"Clinicien.","referral_required":false,"urgency":"ROUTINE_REVIEW","language":"fr","safety_note":"Pas un diagnostic."}'''
    assert parse_gemini_text(safe_wrong_language, 'en', 'maternal_anemia', 'DEMO_LOW') is None
