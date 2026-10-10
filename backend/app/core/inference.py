from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEMO_CASES: dict[str, dict[str, dict[str, Any]]] = {
    'maternal_anemia': {
        'maternal-normal': {'estimate': 11.8, 'unit': 'g/dL', 'risk_category': 'DEMO_LOW', 'confidence': 0.82, 'quality_score': 0.91, 'label': 'Normal-like (synthetic)'},
        'maternal-moderate': {'estimate': 9.4, 'unit': 'g/dL', 'risk_category': 'DEMO_MODERATE', 'confidence': 0.82, 'quality_score': 0.91, 'label': 'Moderate-risk-like (synthetic)'},
        'maternal-high': {'estimate': 7.8, 'unit': 'g/dL', 'risk_category': 'DEMO_HIGH', 'confidence': 0.79, 'quality_score': 0.90, 'label': 'Higher-review (synthetic)'},
    },
    'neonatal_jaundice': {
        'jaundice-review': {'estimate': 12.8, 'unit': 'mg/dL', 'risk_category': 'REQUIRES_REVIEW', 'confidence': 0.79, 'quality_score': 0.90, 'label': 'Review case (synthetic)'},
        'jaundice-escalate': {'estimate': 18.0, 'unit': 'mg/dL', 'risk_category': 'DEMO_ESCALATE', 'confidence': 0.76, 'quality_score': 0.88, 'label': 'Escalation-like (synthetic)'},
    },
}

SAFETY_NOTE = ('Synthetic demonstration estimate only. Not a diagnosis or validated clinical measurement. '
               'Confirm with appropriate clinical testing and local protocol.')


def infer_demo(screening_type: str, case_id: str) -> dict[str, Any]:
    case = DEMO_CASES.get(screening_type, {}).get(case_id)
    if not case:
        raise ValueError('Unsupported synthetic demo case for screening type.')
    return {
        'screening_type': screening_type,
        'estimate': case['estimate'], 'unit': case['unit'],
        'risk_category': case['risk_category'], 'confidence': case['confidence'],
        'quality_score': case['quality_score'], 'requires_confirmation': True,
        'model_mode': 'DEMO', 'synthetic': True, 'case_id': case_id,
        'case_label': case['label'], 'generated_at': datetime.now(timezone.utc).isoformat(),
        'safety_note': SAFETY_NOTE,
    }


@dataclass
class ModelStatus:
    available: bool
    mode: str
    model_name: str
    reason: str


class BiomarkerModel:
    """Replaceable inference interface. Demo values never consume a patient image."""

    def load(self) -> ModelStatus:
        raise NotImplementedError

    def predict(self, features: dict[str, float]) -> dict[str, Any]:
        raise NotImplementedError

    def get_model_info(self) -> dict[str, Any]:
        raise NotImplementedError


class MobileNetV3SmallModel(BiomarkerModel):
    def __init__(self, model_path: str | Path, task: str) -> None:
        self.model_path = Path(model_path)
        self.task = task
        self._interpreter = None
        self._status = ModelStatus(False, 'MODEL_MISSING', 'MobileNetV3-Small INT8', 'No approved .tflite model supplied.')

    def load(self) -> ModelStatus:
        if not self.model_path.exists():
            self._status = ModelStatus(False, 'MODEL_MISSING', 'MobileNetV3-Small INT8', 'Model file not found; deterministic demo mode remains active.')
            return self._status
        try:
            from tflite_runtime.interpreter import Interpreter  # optional runtime
            interpreter = Interpreter(model_path=str(self.model_path))
            interpreter.allocate_tensors()
            self._interpreter = interpreter
            self._status = ModelStatus(True, 'TFLITE', 'MobileNetV3-Small INT8', 'TFLite interpreter loaded. Clinical validity is not implied.')
        except Exception as exc:  # no model/runtime may not break the app
            self._status = ModelStatus(False, 'MODEL_UNAVAILABLE', 'MobileNetV3-Small INT8', f'TFLite runtime unavailable: {type(exc).__name__}.')
        return self._status

    def predict(self, features: dict[str, float]) -> dict[str, Any]:
        if not self._interpreter:
            raise RuntimeError('A valid, approved TFLite model is not loaded.')
        # A real model-specific tensor adapter must be selected together with its documented model card.
        raise NotImplementedError('Model input/output adapter is intentionally not guessed without an approved model artifact.')

    def get_model_info(self) -> dict[str, Any]:
        return {'task': self.task, 'path': str(self.model_path), **self._status.__dict__}


class DemoInferenceModel(BiomarkerModel):
    def load(self) -> ModelStatus:
        return ModelStatus(True, 'DEMO', 'Deterministic synthetic cases', 'Outputs are fixed by selected demo case, not inferred from a patient photo.')

    def predict(self, features: dict[str, float]) -> dict[str, Any]:
        raise ValueError('Select a named synthetic demo case; optical features are not converted to a clinical estimate.')

    def get_model_info(self) -> dict[str, Any]:
        return {'mode': 'DEMO', 'name': 'Deterministic synthetic cases', 'trained_model_present': False,
                'uses_patient_pixels_for_estimate': False, 'safety_note': SAFETY_NOTE}
