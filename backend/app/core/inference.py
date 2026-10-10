from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Fixed demonstration values. They carry no confidence or quality score: a fixture has neither.
DEMO_CASES: dict[str, dict[str, dict[str, Any]]] = {
    'maternal_anemia': {
        'maternal-normal': {'estimate': 11.8, 'unit': 'g/dL', 'risk_category': 'DEMO_LOW', 'label': 'Normal-like (synthetic)'},
        'maternal-moderate': {'estimate': 9.4, 'unit': 'g/dL', 'risk_category': 'DEMO_MODERATE', 'label': 'Moderate-risk-like (synthetic)'},
        'maternal-high': {'estimate': 7.8, 'unit': 'g/dL', 'risk_category': 'DEMO_HIGH', 'label': 'Higher-review (synthetic)'},
    },
    'neonatal_jaundice': {
        'jaundice-review': {'estimate': 12.8, 'unit': 'mg/dL', 'risk_category': 'DEMO_REVIEW', 'label': 'Review case (synthetic)'},
        'jaundice-escalate': {'estimate': 18.0, 'unit': 'mg/dL', 'risk_category': 'DEMO_ESCALATE', 'label': 'Escalation-like (synthetic)'},
    },
}
DEMO_MODEL_VERSION = 'fixed-demo-fixtures-v1'

SAFETY_NOTE = ('Synthetic demonstration estimate only. Not a diagnosis or validated clinical measurement. '
               'Confirm with appropriate clinical testing and local protocol.')


def infer_demo(screening_type: str, case_id: str) -> dict[str, Any]:
    case = DEMO_CASES.get(screening_type, {}).get(case_id)
    if not case:
        raise ValueError('Unsupported synthetic demo case for screening type.')
    return {
        'screening_type': screening_type,
        'estimate': case['estimate'], 'unit': case['unit'],
        'risk_category': case['risk_category'], 'confidence': None, 'quality_score': None,
        'requires_confirmation': True, 'model_mode': 'DEMO', 'synthetic': True,
        'provenance': 'DEMO_SYNTHETIC', 'model_version': DEMO_MODEL_VERSION, 'case_id': case_id,
        'case_label': case['label'], 'generated_at': datetime.now(timezone.utc).isoformat(),
        'limitations': ['Fixed demonstration value; not computed from any image, feature, or person.'],
        'safety_note': SAFETY_NOTE,
    }


class DemoInferenceModel:
    """Named-fixture selector. It has no predict-from-features path by design."""

    def predict(self, features: dict[str, float]) -> dict[str, Any]:
        raise ValueError('Select a named synthetic demo case; optical features are not converted to a clinical estimate.')

    def get_model_info(self) -> dict[str, Any]:
        return {'mode': 'DEMO', 'status': 'DEMO_SYNTHETIC', 'name': 'Deterministic synthetic cases',
                'model_version': DEMO_MODEL_VERSION, 'trained_model_present': False,
                'uses_patient_pixels_for_estimate': False, 'safety_note': SAFETY_NOTE}
