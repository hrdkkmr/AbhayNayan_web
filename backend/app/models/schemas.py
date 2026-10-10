from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Shared web/Android contract version. Bump MINOR for additive fields, MAJOR for breaking changes.
API_CONTRACT_VERSION = '1.0.0'

ScreeningType = Literal['maternal_anemia', 'neonatal_jaundice']
LanguageCode = Literal['en', 'hi', 'bho']
# Where a numeric value came from. A DEMO fixture is never presented as inference.
Provenance = Literal['DEMO_SYNTHETIC', 'EXPERIMENTAL_RESEARCH_ONLY', 'VALIDATED_FOR_INTENDED_USE']
# Integration status of a candidate model (see docs/ML_MODEL_CARD.md).
ModelStatusCode = Literal['VALIDATED_FOR_INTENDED_USE', 'EXPERIMENTAL_RESEARCH_ONLY', 'DISABLED_NO_VALID_MODEL', 'DEMO_SYNTHETIC']
CounselMode = Literal['GEMINI', 'LOCAL_FALLBACK', 'GEMINI_RECOVERED']

_SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}')
EXPECTED_UNIT = {'maternal_anemia': 'g/dL', 'neonatal_jaundice': 'mg/dL'}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_id(value: str | None) -> str | None:
    if value is not None and not _SAFE_ID.fullmatch(value):
        raise ValueError('id must contain only letters, numbers, dot, underscore, or hyphen')
    return value


def _finite(value: float | None) -> float | None:
    if value is not None and (value != value or value in (float('inf'), float('-inf'))):
        raise ValueError('value must be finite')
    return value


class ErrorBody(BaseModel):
    code: str
    message: str
    status: int
    retryable: bool = False
    fields: list[dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Every non-2xx /api response. `detail` mirrors `error.message` for older clients."""
    detail: str
    error: ErrorBody
    api_contract_version: str = API_CONTRACT_VERSION


class HealthResponse(BaseModel):
    status: Literal['ok'] = 'ok'
    service: str = 'abhaynayan-demo-api'
    mode: Literal['PROTOTYPE_DEMO'] = 'PROTOTYPE_DEMO'
    api_contract_version: str = API_CONTRACT_VERSION
    gemini_configured: bool
    gemini_model_configured: bool = False
    database: str = 'sqlite-demo'
    note: str = 'No clinical inference is performed by the API.'


class ScreeningResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    screening_type: ScreeningType
    estimate: float
    unit: Literal['g/dL', 'mg/dL']
    risk_category: str = Field(max_length=48)
    # None means "not produced": demo fixtures and uncalibrated models have no meaningful confidence.
    confidence: float | None = Field(default=None, ge=0, le=1)
    quality_score: float | None = Field(default=None, ge=0, le=1)
    requires_confirmation: bool = True
    model_mode: str = Field(default='DEMO', max_length=40)
    synthetic: bool = True
    provenance: Provenance = 'DEMO_SYNTHETIC'
    model_version: str | None = Field(default=None, max_length=80)
    case_id: str | None = Field(default=None, max_length=64)
    case_label: str | None = Field(default=None, max_length=100)
    generated_at: datetime = Field(default_factory=utc_now)
    limitations: list[str] = Field(default_factory=list, max_length=12)
    safety_note: str = Field(default='Synthetic prototype estimate only; confirm with appropriate clinical testing.', max_length=500)

    @field_validator('estimate')
    @classmethod
    def finite_estimate(cls, value: float) -> float:
        return _finite(value)  # type: ignore[return-value]

    @model_validator(mode='after')
    def matching_unit_and_provenance(self) -> 'ScreeningResult':
        expected = EXPECTED_UNIT[self.screening_type]
        if self.unit != expected:
            raise ValueError(f'{self.screening_type} requires unit {expected}')
        # Synthetic fixtures, DEMO mode and DEMO_SYNTHETIC provenance must always agree.
        if self.synthetic != (self.provenance == 'DEMO_SYNTHETIC') or self.synthetic != (self.model_mode == 'DEMO'):
            raise ValueError('synthetic, model_mode=DEMO and provenance=DEMO_SYNTHETIC must agree')
        return self


class PatientSync(BaseModel):
    model_config = ConfigDict(extra='forbid')
    patient_id: str = Field(min_length=1, max_length=64)
    demo: bool = True

    @field_validator('patient_id')
    @classmethod
    def pseudonymous_id_only(cls, value: str) -> str:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value):
            raise ValueError('patient_id must be a pseudonymous alphanumeric ID, not a name or phone number')
        return value


class ScreeningContext(BaseModel):
    """Minimal, non-identifying clinical context captured with a screening."""
    model_config = ConfigDict(extra='forbid')
    infant_age_hours: int | None = Field(default=None, ge=0, le=8760)
    gestational_week: int | None = Field(default=None, ge=1, le=45)
    pregnancy: bool | None = None


class AnemiaFeatureInput(BaseModel):
    """Research-only input for the experimental anemia colour baseline."""
    model_config = ConfigDict(extra='forbid')
    red_pct: float = Field(ge=0, le=100)
    green_pct: float = Field(ge=0, le=100)
    blue_pct: float = Field(ge=0, le=100)
    # Only features produced by the research dataset's own pipeline are supported.
    feature_source: Literal['research_dataset_precomputed', 'camera_pipeline']


class ScreeningCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str | None = Field(default=None, min_length=1, max_length=96)
    patient: PatientSync
    screening_type: ScreeningType
    inference_mode: Literal['DEMO', 'MODEL'] = 'DEMO'
    case_id: str | None = Field(default=None, min_length=1, max_length=64)
    features: AnemiaFeatureInput | None = None
    context: ScreeningContext | None = None
    worker_id: str = Field(default='demo-worker', max_length=64)
    phc: str = Field(default='Demo PHC', max_length=100)
    village: str | None = Field(default=None, max_length=100)

    @field_validator('id')
    @classmethod
    def safe_id(cls, value: str | None) -> str | None:
        return _safe_id(value)

    @model_validator(mode='after')
    def mode_inputs(self) -> 'ScreeningCreateRequest':
        if self.inference_mode == 'DEMO' and not self.case_id:
            raise ValueError('case_id is required when inference_mode is DEMO')
        if self.inference_mode == 'DEMO' and self.features is not None:
            raise ValueError('features are not accepted in DEMO mode; a fixture never consumes measurements')
        return self


class ScreeningRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=96)
    patient: PatientSync
    result: ScreeningResult
    context: ScreeningContext | None = None
    worker_id: str = Field(default='demo-worker', max_length=64)
    phc: str = Field(default='Demo PHC', max_length=100)
    village: str | None = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=utc_now)
    id_origin: Literal['client', 'server'] = 'client'
    sync_status: Literal['queued', 'synced'] = 'queued'
    fhir_bundle: dict[str, Any] | None = None

    @field_validator('id')
    @classmethod
    def safe_id(cls, value: str | None) -> str | None:
        return _safe_id(value)


class SyncRequest(BaseModel):
    # Records are validated one by one so one malformed record cannot block the whole outbox.
    records: list[dict[str, Any]] = Field(max_length=100)


class SyncItemResult(BaseModel):
    id: str | None
    status: Literal['accepted', 'duplicate', 'conflict', 'rejected']
    error: ErrorBody | None = None


class SyncResponse(BaseModel):
    accepted: int
    duplicate: int
    conflict: int = 0
    rejected: int = 0
    synced_ids: list[str]
    results: list[SyncItemResult] = Field(default_factory=list)
    server_time: datetime = Field(default_factory=utc_now)
    api_contract_version: str = API_CONTRACT_VERSION
    note: str = 'Demo sync only; use de-identified records.'


class ReferralRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=96)
    screening: ScreeningRecord
    worker_name: str = Field(default='Demo ASHA Worker', max_length=100)
    language: LanguageCode = 'en'
    counselling: str = Field(default='', max_length=2000)
    counselling_mode: CounselMode = 'LOCAL_FALLBACK'
    next_step: str = Field(default='', max_length=500)
    reason: Literal['SCREENING_CONFIRMATION', 'WORKER_CONCERN', 'CAREGIVER_REQUEST'] = 'SCREENING_CONFIRMATION'

    @field_validator('id')
    @classmethod
    def safe_id(cls, value: str | None) -> str | None:
        return _safe_id(value)


class GeminiCounselRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    screening_type: ScreeningType
    estimate: float
    unit: Literal['g/dL', 'mg/dL']
    risk_category: str = Field(max_length=48)
    confidence: float | None = Field(default=None, ge=0, le=1)
    quality_score: float | None = Field(default=None, ge=0, le=1)
    provenance: Provenance = 'DEMO_SYNTHETIC'
    language: LanguageCode = 'en'
    pregnancy: bool | None = None
    gestational_week: int | None = Field(default=None, ge=1, le=45)
    infant_age_hours: int | None = Field(default=None, ge=0, le=8760)
    # Optional client idempotency key: a retry with the same key never triggers a second provider call.
    request_id: str | None = Field(default=None, min_length=8, max_length=96)

    @field_validator('request_id')
    @classmethod
    def safe_request_id(cls, value: str | None) -> str | None:
        return _safe_id(value)

    @field_validator('estimate')
    @classmethod
    def finite_counselling_estimate(cls, value: float) -> float:
        return _finite(value)  # type: ignore[return-value]

    @model_validator(mode='after')
    def matching_counselling_unit(self) -> 'GeminiCounselRequest':
        expected = EXPECTED_UNIT[self.screening_type]
        if self.unit != expected:
            raise ValueError(f'{self.screening_type} requires unit {expected}')
        return self


class GeminiCounselResponse(BaseModel):
    summary: str
    risk_explanation: str
    counselling_script: str
    recommended_next_step: str
    referral_required: bool
    urgency: Literal['ROUTINE_REVIEW', 'PROMPT_CLINICIAN_REVIEW', 'HIGH_PRIORITY_REVIEW', 'DEMO_ONLY']
    language: LanguageCode
    safety_note: str
    mode: CounselMode = 'LOCAL_FALLBACK'
    # Why the deterministic copy was used (None when Gemini wording was accepted).
    fallback_reason: str | None = None
    model_id: str | None = None
    protocol_id: str = 'ABN-INTERIM-CONFIRM-v1'
    generated_at: datetime = Field(default_factory=utc_now)


class FHIRRequest(BaseModel):
    patient: dict[str, Any]
    result: ScreeningResult
    worker: dict[str, Any] = Field(default_factory=dict)
    screening_id: str = Field(min_length=1, max_length=96)


class DashboardResponse(BaseModel):
    total_screenings: int
    referrals: int
    # The server cannot see a device's outbox; device queues are reported by each client.
    pending_sync: int | None = None
    today_screenings: int
    by_provenance: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    records: list[dict[str, Any]]
    mode: str = 'DEMO'
