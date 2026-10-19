from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ScreeningType = Literal['maternal_anemia', 'neonatal_jaundice']
LanguageCode = Literal['en', 'hi', 'bho']


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HealthResponse(BaseModel):
    status: Literal['ok'] = 'ok'
    service: str = 'abhaynayan-demo-api'
    mode: Literal['PROTOTYPE_DEMO'] = 'PROTOTYPE_DEMO'
    gemini_configured: bool
    database: str = 'sqlite-demo'
    note: str = 'No clinical inference is performed by the API.'


class ScreeningResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    screening_type: ScreeningType
    estimate: float
    unit: Literal['g/dL', 'mg/dL']
    risk_category: str = Field(max_length=48)
    confidence: float = Field(ge=0, le=1)
    quality_score: float = Field(ge=0, le=1)
    requires_confirmation: bool = True
    model_mode: str = Field(default='DEMO', max_length=40)
    synthetic: bool = True
    case_id: str | None = Field(default=None, max_length=64)
    case_label: str | None = Field(default=None, max_length=100)
    generated_at: datetime = Field(default_factory=utc_now)
    safety_note: str = Field(default='Synthetic prototype estimate only; confirm with appropriate clinical testing.', max_length=500)

    @field_validator('estimate')
    @classmethod
    def finite_estimate(cls, value: float) -> float:
        if value != value or value in (float('inf'), float('-inf')):
            raise ValueError('estimate must be finite')
        return value

    @model_validator(mode='after')
    def matching_unit(self) -> 'ScreeningResult':
        expected = 'g/dL' if self.screening_type == 'maternal_anemia' else 'mg/dL'
        if self.unit != expected:
            raise ValueError(f'{self.screening_type} requires unit {expected}')
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


class ScreeningCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str | None = Field(default=None, min_length=1, max_length=96)
    patient: PatientSync
    screening_type: ScreeningType
    case_id: str = Field(min_length=1, max_length=64)
    worker_id: str = Field(default='demo-worker', max_length=64)
    phc: str = Field(default='Demo PHC', max_length=100)
    village: str | None = Field(default=None, max_length=100)

    @field_validator('id')
    @classmethod
    def safe_screening_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value):
            raise ValueError('id must contain only letters, numbers, dot, underscore, or hyphen')
        return value


class ScreeningRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=96)
    patient: PatientSync
    result: ScreeningResult
    worker_id: str = Field(default='demo-worker', max_length=64)
    phc: str = Field(default='Demo PHC', max_length=100)
    village: str | None = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=utc_now)
    sync_status: Literal['queued', 'synced'] = 'queued'
    fhir_bundle: dict[str, Any] | None = None

    @field_validator('id')
    @classmethod
    def safe_record_id(cls, value: str) -> str:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value):
            raise ValueError('id must contain only letters, numbers, dot, underscore, or hyphen')
        return value

    @field_validator('village')
    @classmethod
    def no_phone_or_long_text(cls, value: str | None) -> str | None:
        if value and len(value) > 100:
            raise ValueError('village too long')
        return value


class SyncRequest(BaseModel):
    records: list[ScreeningRecord] = Field(max_length=100)


class SyncResponse(BaseModel):
    accepted: int
    duplicate: int
    synced_ids: list[str]
    server_time: datetime = Field(default_factory=utc_now)
    note: str = 'Demo sync only; use de-identified records.'


class ReferralRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=96)
    screening: ScreeningRecord
    worker_name: str = Field(default='Demo ASHA Worker', max_length=100)
    language: LanguageCode = 'en'
    counselling: str = Field(default='', max_length=2000)
    next_step: str = Field(default='', max_length=500)

    @field_validator('id')
    @classmethod
    def safe_referral_id(cls, value: str) -> str:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value):
            raise ValueError('id must contain only letters, numbers, dot, underscore, or hyphen')
        return value


class GeminiCounselRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    screening_type: ScreeningType
    estimate: float
    unit: Literal['g/dL', 'mg/dL']
    risk_category: str = Field(max_length=48)
    confidence: float = Field(ge=0, le=1)
    quality_score: float = Field(ge=0, le=1)
    language: LanguageCode = 'en'
    pregnancy: bool | None = None
    gestational_week: int | None = Field(default=None, ge=1, le=45)
    infant_age_hours: int | None = Field(default=None, ge=0, le=8760)

    @field_validator('estimate')
    @classmethod
    def finite_counselling_estimate(cls, value: float) -> float:
        if value != value or value in (float('inf'), float('-inf')):
            raise ValueError('estimate must be finite')
        return value

    @model_validator(mode='after')
    def matching_counselling_unit(self) -> 'GeminiCounselRequest':
        expected = 'g/dL' if self.screening_type == 'maternal_anemia' else 'mg/dL'
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
    mode: Literal['GEMINI', 'LOCAL_FALLBACK', 'GEMINI_RECOVERED'] = 'LOCAL_FALLBACK'


class FHIRRequest(BaseModel):
    patient: dict[str, Any]
    result: ScreeningResult
    worker: dict[str, Any] = Field(default_factory=dict)
    screening_id: str = Field(min_length=1, max_length=96)


class DashboardResponse(BaseModel):
    total_screenings: int
    referrals: int
    pending_sync: int
    today_screenings: int
    records: list[dict[str, Any]]
    mode: str = 'DEMO'
