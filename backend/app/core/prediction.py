"""Prediction envelope `abhaynayan.prediction/2.0.0` (docs/prediction_contract.md) for the research image routes.

Builds and validates envelopes without extra dependencies. The validator mirrors §11 of the contract and the
Android `PredictionInvariants`; both are tested against the documented examples. A route never returns an
envelope that fails validation.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any

SCHEMA = 'abhaynayan.prediction/2.0.0'
CONTRACT_VERSION = '2.0.0'
REASON_CODES = frozenset({
    'INPUT_EMPTY', 'INPUT_DECODE_FAILED', 'INPUT_FORMAT_UNSUPPORTED', 'INPUT_TOO_SMALL', 'INPUT_TOO_LARGE',
    'MODALITY_UNSUPPORTED', 'MODALITY_UNVERIFIED', 'QUALITY_FAILED', 'CAPTURE_RETRY_LIMIT',
    'INPUT_OUT_OF_DISTRIBUTION', 'TARGET_REGION_INCOMPATIBLE', 'POPULATION_UNSUPPORTED', 'CONTEXT_MISSING',
    'MODEL_MISSING', 'MODEL_DISABLED', 'RUNTIME_UNAVAILABLE', 'MODEL_INCOMPATIBLE', 'MODEL_INTEGRITY_FAILED',
    'MODEL_REVOKED', 'NOT_APPROVED_FOR_INTENDED_USE', 'NO_VALIDATED_MODEL_FOR_TASK', 'OUTPUT_IMPLAUSIBLE',
    'INFERENCE_RUNTIME_ERROR', 'OUTPUT_NON_FINITE', 'TIMEOUT', 'INTERNAL_ERROR',
})
STATUSES = ('estimated', 'unable_to_estimate', 'error', 'synthetic_fixture')
TASK_UNIT = {'hemoglobin_from_palpebral_conjunctiva': 'g/dL', 'newborn_jaundice_dataset_class': 'score', 'bilirubin_from_skin': 'mg/dL'}
ACCEPTED_SITE = {'hemoglobin_from_palpebral_conjunctiva': 'palpebral_conjunctiva_segmented',
                 'newborn_jaundice_dataset_class': 'newborn_skin_whole_view'}
MODEL_STATUSES = ('synthetic_fixture', 'research_only', 'approved_for_intended_use')
SOURCES = ('edge', 'backend', 'fixture', 'none')
# Legacy 1.x error codes of the image routes → contract reason codes.
LEGACY_TO_REASON = {
    'EMPTY_IMAGE': 'INPUT_EMPTY', 'CORRUPT_IMAGE': 'INPUT_DECODE_FAILED', 'UNSUPPORTED_MEDIA_TYPE': 'INPUT_FORMAT_UNSUPPORTED',
    'IMAGE_TOO_SMALL': 'INPUT_TOO_SMALL', 'IMAGE_TOO_LARGE': 'INPUT_TOO_LARGE', 'IMAGE_QUALITY_REJECTED': 'QUALITY_FAILED',
    'OUTPUT_OUT_OF_RANGE': 'OUTPUT_IMPLAUSIBLE', 'MODEL_UNAVAILABLE': 'MODEL_MISSING', 'MODEL_DISABLED': 'MODEL_DISABLED',
    'RUNTIME_UNAVAILABLE': 'RUNTIME_UNAVAILABLE', 'MODEL_INCOMPATIBLE': 'MODEL_INCOMPATIBLE',
    'MODEL_INTEGRITY_FAILED': 'MODEL_INTEGRITY_FAILED', 'INFERENCE_FAILED': 'INFERENCE_RUNTIME_ERROR',
    'ORIENTATION_UNKNOWN': 'MODALITY_UNVERIFIED', 'TARGET_REGION_INCOMPATIBLE': 'TARGET_REGION_INCOMPATIBLE',
    'MODALITY_UNSUPPORTED': 'MODALITY_UNSUPPORTED', 'INPUT_OUT_OF_DISTRIBUTION': 'INPUT_OUT_OF_DISTRIBUTION',
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def check(check_id: str, measured: Any, threshold: Any, comparator: str, passed: bool) -> dict[str, Any]:
    return {'check_id': check_id, 'measured': measured, 'threshold': threshold, 'comparator': comparator, 'passed': bool(passed)}


def warning(code: str, severity: str, software_version: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {'code': code, 'severity': severity,
            'origin': {'source': 'backend', 'component': 'inference-service', 'software_version': software_version},
            'created_at': _now(), 'params': params or {}}


def build(*, status: str, reason_code: str | None, task: str, input_info: dict[str, Any], quality: dict[str, Any],
          compatibility: dict[str, Any], estimate: dict[str, Any] | None, model: dict[str, Any] | None, source: str,
          warnings: list[dict[str, Any]], software_version: str) -> dict[str, Any]:
    env = {
        'schema': SCHEMA, 'result_id': f'prd-{uuid.uuid4()}', 'trace_id': str(uuid.uuid4()),
        'status': status, 'reason_code': reason_code, 'screening_type': task,
        'workflow': 'maternal_anemia' if task == 'hemoglobin_from_palpebral_conjunctiva' else 'neonatal_jaundice',
        'input': input_info, 'input_quality': quality, 'input_compatibility': compatibility,
        'estimate': estimate, 'model': model, 'inference_source': source, 'warnings': warnings, 'created_at': _now(),
        'producer': {'component': 'backend', 'software_version': software_version, 'platform': 'python-3', 'contract_version': CONTRACT_VERSION},
    }
    problems = violations(env)
    if problems:  # a programming error; never return an invalid envelope
        raise ValueError(f'invalid prediction envelope: {problems}')
    return env


def violations(e: dict[str, Any]) -> list[str]:
    """Contract §11. Empty list = valid. Unknown enum values fail closed."""
    v: list[str] = []
    if e.get('schema') != SCHEMA:
        v.append('unknown schema')
    rid, tid = str(e.get('result_id', '')), str(e.get('trace_id', ''))
    if not rid.startswith('prd-') or not _uuid4(rid[4:]):
        v.append('result_id')
    if not _uuid4(tid):
        v.append('trace_id')
    status, task, source = e.get('status'), e.get('screening_type'), e.get('inference_source')
    if status not in STATUSES:
        return v + ['unknown status']
    if task not in TASK_UNIT:
        return v + ['unknown screening_type']
    if source not in SOURCES:
        return v + ['unknown inference_source']
    model = e.get('model')
    model_status = model.get('model_status') if isinstance(model, dict) else None
    if model is not None and model_status not in MODEL_STATUSES:
        return v + ['unknown model_status']
    reason, est = e.get('reason_code'), e.get('estimate')
    if reason is not None and reason not in REASON_CODES:
        v.append('unknown reason_code')
    codes = [w.get('code') for w in e.get('warnings') or []]
    if not isinstance(e.get('warnings'), list):
        v.append('warnings missing')
    if status in ('unable_to_estimate', 'error'):
        if est is not None:
            v.append(f'{status} must not carry an estimate')
        if reason is None:
            v.append(f'{status} needs reason_code')
    elif status == 'estimated':
        if est is None:
            v.append('estimated needs estimate')
        if reason is not None:
            v.append('estimated must not have reason_code')
        if model_status not in ('research_only', 'approved_for_intended_use'):
            v.append('estimated needs a research or approved model')
        if source not in ('edge', 'backend'):
            v.append('estimated needs edge/backend source')
        if (e.get('input_quality') or {}).get('status') != 'passed':
            v.append('estimated needs passed quality')
        if (e.get('input_compatibility') or {}).get('status') != 'compatible':
            v.append('estimated needs compatible input')
        if (e.get('input') or {}).get('body_site') != ACCEPTED_SITE.get(task):
            v.append('body_site not accepted for task')
        if task == 'bilirubin_from_skin':
            v.append('bilirubin can never be estimated in schema 2.0')
        if model_status == 'research_only' and 'RESEARCH_ONLY_NOT_VALIDATED' not in codes:
            v.append('research estimate without its warning')
    else:  # synthetic_fixture
        if est is None:
            v.append('fixture needs its fixed value')
        if source != 'fixture' or model_status != 'synthetic_fixture':
            v.append('fixture must be labelled as fixture')
        if 'SYNTHETIC_FIXTURE_NOT_A_MEASUREMENT' not in codes:
            v.append('fixture without its warning')
    if isinstance(est, dict):
        value = est.get('value')
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            v.append('non-finite estimate')
        if est.get('unit') != TASK_UNIT[task]:
            v.append('unit does not match task')
    return v


def _uuid4(text: str) -> bool:
    try:
        u = uuid.UUID(text)
    except ValueError:
        return False
    return u.version == 4 and str(u) == text
