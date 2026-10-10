"""Separate maternal-anemia and neonatal-jaundice inference adapters.

Every adapter fails closed: a missing, disabled, or unsuitable model raises a typed
`InferenceError` and never falls back to a synthetic value. Model status values are the
ones defined in docs/ML_MODEL_CARD.md.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[3]
ANEMIA_BASELINE_PATH = PROJECT_DIR / 'models' / 'anemia_color_baseline.json'
EXPERIMENTAL_ANEMIA_FLAG = 'ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA'


class InferenceError(Exception):
    """Client-safe inference failure. `code` is part of the API contract; no paths or internals."""

    def __init__(self, code: str, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class ModelCard:
    adapter_id: str
    screening_type: str
    target: str
    unit: str
    status: str
    model_version: str | None
    reason: str
    inference_location: str
    limitations: tuple[str, ...] = ()
    evaluation: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            'adapter_id': self.adapter_id, 'screening_type': self.screening_type, 'target': self.target,
            'unit': self.unit, 'status': self.status, 'model_version': self.model_version,
            'reason': self.reason, 'inference_location': self.inference_location,
            'limitations': list(self.limitations), 'evaluation': self.evaluation,
        }


class ScreeningAdapter:
    screening_type: str = ''

    def card(self) -> ModelCard:
        raise NotImplementedError

    def enabled(self) -> bool:
        return self.card().status in {'EXPERIMENTAL_RESEARCH_ONLY', 'VALIDATED_FOR_INTENDED_USE'}

    def infer(self, features: Any) -> dict[str, Any]:
        raise NotImplementedError


def _env_flag(name: str) -> bool:
    return os.getenv(name, '').strip().lower() in {'1', 'true', 'yes'}


class MaternalAnemiaAdapter(ScreeningAdapter):
    """Research-only Ridge colour baseline; disabled unless an operator opts in explicitly.

    The artifact maps three dataset-supplied colour percentages to Hb (g/dL). The ROI,
    device, and lighting that produced those percentages are undocumented, so camera-derived
    features from this app are rejected as unsupported input even when the adapter is enabled.
    """
    screening_type = 'maternal_anemia'

    def __init__(self, artifact_path: Path = ANEMIA_BASELINE_PATH) -> None:
        self.artifact_path = artifact_path

    def _artifact(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.artifact_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        required = {'features', 'mean', 'scale', 'coefficients_scaled', 'intercept', 'unit'}
        if not required.issubset(data) or data['unit'] != 'g/dL' or len(data['features']) != 3:
            return None
        if not all(len(data[k]) == 3 for k in ('mean', 'scale', 'coefficients_scaled')) or any(s <= 0 for s in data['scale']):
            return None
        return data

    def card(self) -> ModelCard:
        artifact = self._artifact()
        limitations = (
            'Research-only. Not validated for screening, diagnosis, triage, or treatment.',
            'Trained on 104 rows of precomputed colour percentages from an undocumented ROI/device pipeline.',
            'Camera-derived features from this app are not equivalent inputs and are rejected.',
            'Grouped CV offers no extra leakage protection: every subject name is unique in the source file.',
        )
        if artifact is None:
            return ModelCard('anemia-ridge-color-baseline', self.screening_type, 'hemoglobin concentration', 'g/dL',
                             'DISABLED_NO_VALID_MODEL', None, 'Research artifact missing or malformed.', 'none', limitations)
        version = f"ridge-color-{artifact.get('version', 'unknown')}"
        if not _env_flag(EXPERIMENTAL_ANEMIA_FLAG):
            return ModelCard('anemia-ridge-color-baseline', self.screening_type, 'hemoglobin concentration', 'g/dL',
                             'DISABLED_NO_VALID_MODEL', version,
                             'No validated anemia model. The research baseline is disabled by default.',
                             'none', limitations, artifact.get('metrics', {}))
        return ModelCard('anemia-ridge-color-baseline', self.screening_type, 'hemoglobin concentration', 'g/dL',
                         'EXPERIMENTAL_RESEARCH_ONLY', version,
                         'Operator-enabled research baseline for controlled demonstrations with research-dataset features only.',
                         'server', limitations, artifact.get('metrics', {}))

    def infer(self, features: Any) -> dict[str, Any]:
        card = self.card()
        if not self.enabled():
            raise InferenceError('MODEL_DISABLED', card.reason)
        artifact = self._artifact()
        if artifact is None:  # card() already checks, but the file may change between calls
            raise InferenceError('MODEL_UNAVAILABLE', 'Model artifact could not be loaded.')
        if features is None:
            raise InferenceError('INVALID_INPUT', 'Colour features are required for this model.', 422)
        if features.feature_source != 'research_dataset_precomputed':
            raise InferenceError('UNSUPPORTED_INPUT', 'Camera-pipeline features are not a supported input for this research baseline.', 422)
        vector = [features.red_pct, features.green_pct, features.blue_pct]
        if not all(math.isfinite(v) for v in vector) or abs(sum(vector) - 100.0) > 0.5:
            raise InferenceError('INVALID_INPUT', 'Colour percentages must be finite and sum to 100.', 422)
        try:
            value = artifact['intercept'] + sum(c * (x - m) / s for c, x, m, s in
                                                zip(artifact['coefficients_scaled'], vector, artifact['mean'], artifact['scale']))
        except (TypeError, ValueError) as exc:
            raise InferenceError('INFERENCE_FAILED', 'The model could not process this input.') from exc
        if not math.isfinite(value):
            raise InferenceError('INFERENCE_FAILED', 'The model returned a non-finite value.')
        return {
            'screening_type': self.screening_type, 'estimate': round(float(value), 1), 'unit': 'g/dL',
            'risk_category': 'RESEARCH_UNCLASSIFIED', 'confidence': None, 'quality_score': None,
            'requires_confirmation': True, 'model_mode': 'EXPERIMENTAL', 'synthetic': False,
            'provenance': 'EXPERIMENTAL_RESEARCH_ONLY', 'model_version': card.model_version,
            'case_id': None, 'case_label': None, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'limitations': list(card.limitations),
            'safety_note': ('Experimental research output from a non-validated model. Not a hemoglobin measurement. '
                            'Do not use for any care decision; confirm with appropriate laboratory testing.'),
        }


class NeonatalJaundiceAdapter(ScreeningAdapter):
    """No bilirubin model exists: the only image set has no linked serum-bilirubin labels."""
    screening_type = 'neonatal_jaundice'

    def card(self) -> ModelCard:
        return ModelCard('neonatal-bilirubin', self.screening_type, 'total serum bilirubin', 'mg/dL',
                         'DISABLED_NO_VALID_MODEL', None,
                         'No bilirubin-labelled ground truth is available; no model has been trained or validated.',
                         'none', ('The neonatal image archive (478 JPEGs) contains no label table.',
                                  'An anemia model must never be reused for bilirubin.'))

    def infer(self, features: Any) -> dict[str, Any]:
        raise InferenceError('MODEL_DISABLED', self.card().reason)


ADAPTERS: dict[str, ScreeningAdapter] = {
    'maternal_anemia': MaternalAnemiaAdapter(),
    'neonatal_jaundice': NeonatalJaundiceAdapter(),
}


def adapter_for(screening_type: str) -> ScreeningAdapter:
    adapter = ADAPTERS.get(screening_type)
    if adapter is None:
        raise InferenceError('INVALID_INPUT', 'Unsupported screening type.', 422)
    return adapter


# Candidate models inspected during the audit, including ones with no artifact (never loadable).
CANDIDATE_MODELS: list[dict[str, Any]] = [
    {'id': 'demo-fixtures', 'status': 'DEMO_SYNTHETIC', 'target': 'none (fixed values)', 'artifact': 'backend/app/core/inference.py',
     'note': 'Fixed demonstration values; never presented as inference.'},
    {'id': 'anemia-ridge-color-baseline', 'status': 'EXPERIMENTAL_RESEARCH_ONLY', 'target': 'Hb g/dL',
     'artifact': 'models/anemia_color_baseline.json',
     'note': 'Disabled at runtime unless ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA=1; accepts research-dataset features only.'},
    {'id': 'notebook-mobilenetv3-hb', 'status': 'DISABLED_NO_VALID_MODEL', 'target': 'Hb g/dL', 'artifact': None,
     'note': 'Notebook test R2 -0.197 (worse than predicting the mean); saved .keras file is not in the repository or Drive.'},
    {'id': 'notebook-color-random-forest', 'status': 'DISABLED_NO_VALID_MODEL', 'target': 'Hb g/dL', 'artifact': None,
     'note': 'Notebook test R2 -0.345 on 10 test patients; no artifact.'},
    {'id': 'neonatal-bilirubin', 'status': 'DISABLED_NO_VALID_MODEL', 'target': 'bilirubin mg/dL', 'artifact': None,
     'note': 'No bilirubin labels exist for the available images.'},
]
