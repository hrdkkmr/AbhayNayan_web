from __future__ import annotations

import hmac
import json
import logging
import math
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import auth, config, prediction as P
from app.core.auth import AuthError, Principal
from app.core.inference import DEMO_CASES, SAFETY_NOTE, DemoInferenceModel, infer_demo
from app.core.ratelimit import Limiter
from app.core.model_adapters import ADAPTERS, CANDIDATE_MODELS, InferenceError, adapter_for
from app.ml import features as ml_features, imageio, quality as ml_quality
from app.ml.registry import HB_PLAUSIBLE, IMAGE_MODELS_FLAG, REGISTRY, SERVED as SERVED_BY_TASK, ModelError, flag_enabled
from app.assistant import service as assistant
from app.models.schemas import (
    API_CONTRACT_VERSION,
    AssistantAskRequest,
    DashboardResponse,
    ErrorResponse,
    FHIRRequest,
    GeminiCounselRequest,
    GeminiCounselResponse,
    HealthResponse,
    PatientSync,
    ReferralRequest,
    ScreeningCreateRequest,
    ScreeningRecord,
    SyncItemResult,
    SyncRequest,
    SyncResponse,
)
from app.services import gemini, store
from app.services.fhir import FHIRGenerator
from app.services.referral_pdf import build_referral_pdf

PROJECT_DIR = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_DIR / 'web-dashboard'
FHIR = FHIRGenerator()
DEMO_MODEL = DemoInferenceModel()
logger = logging.getLogger('abhaynayan.api')
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {code: {'model': ErrorResponse} for code in (401, 403, 404, 409, 413, 415, 422, 429, 500, 503)}
STATUS_CODES = {400: 'BAD_REQUEST', 401: 'UNAUTHORIZED', 403: 'FORBIDDEN', 404: 'NOT_FOUND', 405: 'METHOD_NOT_ALLOWED',
                409: 'CONFLICT', 413: 'PAYLOAD_TOO_LARGE', 415: 'UNSUPPORTED_MEDIA_TYPE', 422: 'VALIDATION_ERROR', 429: 'RATE_LIMITED',
                500: 'INTERNAL_ERROR', 503: 'SERVICE_UNAVAILABLE'}
RESEARCH_ROLE = 'research_operator'
_limiter: Limiter | None = None


class ApiError(Exception):
    """A client-safe error with a stable contract code."""

    def __init__(self, status: int, code: str, message: str, retryable: bool = False, fields: list[dict[str, Any]] | None = None,
                 headers: dict[str, str] | None = None, extra: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.retryable, self.fields = status, code, message, retryable, fields or []
        self.headers = headers
        self.extra = extra


def error_body(status: int, code: str, message: str, retryable: bool = False, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {'detail': message, 'error': {'code': code, 'message': message, 'status': status, 'retryable': retryable, 'fields': fields or []},
            'api_contract_version': API_CONTRACT_VERSION}


def validation_fields(errors: list[Any]) -> list[dict[str, Any]]:
    # Field paths and messages only; submitted values are never echoed back (they may be identifying).
    return [{'loc': [str(part) for part in e.get('loc', ())], 'message': str(e.get('msg', '')).removeprefix('Value error, ')[:200],
             'type': str(e.get('type', ''))} for e in errors]


def limiter() -> Limiter:
    global _limiter
    if _limiter is None:
        s = config.get()
        _limiter = Limiter(s.image_rate_per_minute, s.image_rate_per_day, s.image_max_concurrent, s.auth_failures_per_minute_per_ip)
    return _limiter


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _limiter
    # Invalid production configuration stops the start here (names and codes only; values are never printed).
    config.validate_for_startup(config.reload())
    _limiter = None
    store.init_db()
    yield


app = FastAPI(
    title='AbhayNayan Prototype API',
    version=API_CONTRACT_VERSION,
    description='Offline-first prototype API. Synthetic estimates by default; not for diagnosis or treatment. Contract: docs/API_CONTRACT.md.',
    lifespan=lifespan,
)

origins = [x.strip() for x in os.getenv('ABHAYNAYAN_ALLOW_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',') if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=['GET', 'POST', 'OPTIONS'],
                   allow_headers=['Content-Type', 'Authorization'], expose_headers=['X-AbhayNayan-Contract-Version'])


@app.middleware('http')
async def contract_header(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['X-AbhayNayan-Contract-Version'] = API_CONTRACT_VERSION
        response.headers.setdefault('Cache-Control', 'no-store')
    return response


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    content = error_body(exc.status, exc.code, exc.message, exc.retryable, exc.fields)
    if exc.extra:
        content.update(exc.extra)  # e.g. `prediction`: the contract 2.0 envelope of a refused or failed inference
    return JSONResponse(status_code=exc.status, content=content, headers=exc.headers)


@app.exception_handler(AuthError)
async def auth_error_handler(_: Request, exc: AuthError) -> JSONResponse:
    headers = {'WWW-Authenticate': 'Bearer'} if exc.status == 401 else None
    return JSONResponse(status_code=exc.status, content=error_body(exc.status, exc.code, exc.message), headers=headers)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else 'Request failed.'
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.status_code, STATUS_CODES.get(exc.status_code, 'HTTP_ERROR'), message))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = validation_fields(exc.errors())
    first = fields[0]['message'] if fields else 'Invalid request.'
    return JSONResponse(status_code=422, content=error_body(422, 'VALIDATION_ERROR', f'Invalid request: {first}', fields=fields))


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error('unhandled error type=%s', type(exc).__name__)  # no message: it may contain paths or payload data
    return JSONResponse(status_code=500, content=error_body(500, 'INTERNAL_ERROR', 'Unexpected server error.', retryable=True))


@app.get('/api/health', response_model=HealthResponse, tags=['system'])
def health() -> HealthResponse:
    return HealthResponse(gemini_configured=gemini.gemini_configured(), gemini_model_configured=gemini.model_configured())


# ----- authentication and rate limiting for research inference (docs/security_and_permissions.md §5, §7) -----

def _client_ip(request: Request) -> str:
    return request.client.host if request.client else 'unknown'


def authorize_research(request: Request) -> Principal:
    """Verified research-operator identity, or a contract error. Order: IP failure limit → token → role.

    Identity comes only from a server-signed bearer token. Client headers, body fields and the
    `patient.demo` flag are never consulted. The operator flag remains a separate kill switch.
    """
    lim, ip = limiter(), _client_ip(request)
    blocked = lim.failures_exceeded(ip)
    if not blocked.allowed:
        raise ApiError(429, 'RATE_LIMITED', 'Too many requests. Try again later.', retryable=True,
                       headers={'Retry-After': str(blocked.retry_after_seconds)})
    try:
        principal = auth.verify(auth.bearer_token(request.headers.get('authorization')))
    except AuthError as exc:
        if exc.status == 401:
            lim.record_failure(ip)
        raise
    if not principal.has_role(RESEARCH_ROLE):
        raise ApiError(403, 'FORBIDDEN', 'This account is not permitted to run research models.')
    return principal


@asynccontextmanager
async def _rate_limited(principal: Principal):
    lim = limiter()
    decision = lim.acquire(principal.user_id)
    if not decision.allowed:
        raise ApiError(429, 'RATE_LIMITED', 'Too many requests. Try again later.', retryable=True,
                       headers={'Retry-After': str(decision.retry_after_seconds)})
    try:
        yield
    finally:
        lim.release(principal.user_id)


def _rate_limited_sync(principal: Principal):
    """Synchronous variant for def-routes: returns a release callback."""
    lim = limiter()
    decision = lim.acquire(principal.user_id)
    if not decision.allowed:
        raise ApiError(429, 'RATE_LIMITED', 'Too many requests. Try again later.', retryable=True,
                       headers={'Retry-After': str(decision.retry_after_seconds)})
    return lambda: lim.release(principal.user_id)


# ----- readiness -------------------------------------------------------------------------------

def _integration_state(key_set: bool, model_set: bool) -> str:
    if key_set and model_set:
        return 'configured'
    return 'misconfigured' if key_set or model_set else 'not_configured'


@app.get('/api/ready', tags=['system'])
def ready() -> JSONResponse:
    """Component readiness. 200 = operational (`ready` or `degraded`); 503 = `not_ready`.

    Operational does not mean any clinical inference is available: `clinical_inference` reports that
    separately, and today it is always disabled (no validated model exists). Codes only; no paths or secrets.
    """
    settings = config.get()
    errors = [p.as_dict() for p in settings.problems if p.severity == 'error']
    warnings = [p.as_dict() for p in settings.problems if p.severity == 'warning']
    configuration = {'status': 'invalid' if errors else ('warnings' if warnings else 'ok'), 'environment': settings.environment,
                     'problems': errors + warnings}
    try:
        store.ping()
        database = {'status': 'ok', 'kind': 'sqlite'}
    except Exception:  # noqa: BLE001 - reported as a state, details never exposed
        database = {'status': 'unavailable', 'kind': 'sqlite'}
    models = {mid: REGISTRY.diagnose(mid) for mid in REGISTRY.registered_ids()}
    for mid, entry in models.items():
        entry['served_by_backend'] = mid in set(SERVED_BY_TASK.values())
    research_on = flag_enabled()
    validated = [a.screening_type for a in ADAPTERS.values() if a.card().status == 'VALIDATED_FOR_INTENDED_USE']
    gemini_state = _integration_state(settings.gemini_key_set, settings.gemini_model_set)
    integrations = {
        'authentication': 'configured' if settings.auth_configured else 'not_configured',
        'gemini': gemini_state,
        'admin_usage_report': 'configured' if settings.admin_token_set else 'not_configured',
        'rate_limiter': {'backend': 'memory', 'scope': 'single_process', 'workers_declared': settings.worker_count},
        'assistant': {'enabled': assistant.enabled(), 'provider': assistant.provider(),
                      'agent37': assistant.agent37.config_problem() or 'configured'},
    }
    model_faults = [e for e in models.values() if e.get('reason_code') in ('MODEL_INTEGRITY_FAILED', 'MODEL_INCOMPATIBLE')]
    if (errors and settings.environment == 'production') or database['status'] != 'ok':
        status = 'not_ready'
    elif model_faults or gemini_state == 'misconfigured' or errors:
        status = 'degraded'
    else:
        status = 'ready'
    body = {
        'status': status,
        'api_contract_version': API_CONTRACT_VERSION,
        'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'clinical_inference': {'status': 'enabled' if validated else 'disabled',
                               'reason_code': None if validated else 'NO_VALIDATED_MODEL_FOR_TASK',
                               'validated_tasks': validated},
        'components': {
            'application': {'status': 'ok'},
            'configuration': configuration,
            'database': database,
            'research_inference': {'status': 'enabled' if research_on else 'disabled', 'flag': IMAGE_MODELS_FLAG,
                                   'requires_role': RESEARCH_ROLE,
                                   'note': 'Research-only models; never clinical output.'},
            'models': models,
            'integrations': integrations,
        },
    }
    return JSONResponse(status_code=503 if status == 'not_ready' else 200, content=body)


def _research_artifact() -> dict[str, Any] | None:
    try:
        return json.loads((PROJECT_DIR / 'models' / 'anemia_color_baseline.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


@app.get('/api/model/status', tags=['system'])
def model_status() -> dict[str, Any]:
    adapters = {kind: adapter.card().as_dict() for kind, adapter in ADAPTERS.items()}
    return {
        'api_contract_version': API_CONTRACT_VERSION,
        'active_inference': DEMO_MODEL.get_model_info(),
        'adapters': adapters,
        'candidate_models': CANDIDATE_MODELS,
        'optional_tflite': {'available': False, 'reason': 'No TFLite model is served. Research image models are JSON/ONNX; see image_models.'},
        'image_models': REGISTRY.status(),
        'image_models_enabled': flag_enabled(),
        'research_baseline': _research_artifact(),
        'research_baseline_enabled_for_screening': ADAPTERS['maternal_anemia'].enabled(),
        'safety_note': SAFETY_NOTE,
    }


@app.get('/api/demo/cases', tags=['screenings'])
def demo_cases() -> dict[str, Any]:
    return {
        'mode': 'DEMO', 'synthetic': True, 'provenance': 'DEMO_SYNTHETIC',
        'cases': {
            kind: [{'id': case_id, 'label': item['label'], 'estimate': item['estimate'], 'unit': item['unit'],
                   'risk_category': item['risk_category']} for case_id, item in cases.items()]
            for kind, cases in DEMO_CASES.items()
        },
        'note': 'Fixed synthetic fixtures; not inferred from patient pixels.',
    }


@app.get('/api/pipeline', tags=['system'])
def pipeline_status() -> dict[str, Any]:
    return {
        'capture': {'mode': 'browser-local', 'backend_receives_images': flag_enabled(),
                    'image_retention': 'none: research image endpoints decode in memory and discard the bytes'},
        'roi': {'mode': 'manual-guide', 'landmarks_available': False},
        'features': {'mode': 'experimental-color-features', 'camera_color_calibrated': False},
        'inference': {'mode': 'DEMO', 'uses_patient_pixels_for_estimate': False,
                      'adapters': {kind: adapter.card().status for kind, adapter in ADAPTERS.items()}},
        'counselling': {'mode': 'Gemini optional; local deterministic language fallback'},
        'storage': {'browser': 'IndexedDB/localStorage', 'backend': 'SQLite demo store'},
        'note': SAFETY_NOTE,
    }


def _bundle_for(record_like: dict[str, Any], screening_id: str) -> dict[str, Any]:
    return FHIR.generate_bundle({'patient_id': record_like['patient_id']}, record_like['result'],
                                {'worker_id': record_like.get('worker_id'), 'phc': record_like.get('phc')}, screening_id)


@app.post('/api/screenings', response_model=ScreeningRecord, tags=['screenings'], responses=ERROR_RESPONSES)
def create_screening(request: ScreeningCreateRequest, http_request: Request) -> ScreeningRecord:
    if request.inference_mode != 'DEMO':
        # MODEL mode reaches research adapters: same authentication, role and rate limit as the image routes.
        release = _rate_limited_sync(authorize_research(http_request))
        try:
            return _create_screening(request)
        finally:
            release()
    return _create_screening(request)


def _create_screening(request: ScreeningCreateRequest) -> ScreeningRecord:
    if request.inference_mode == 'DEMO':
        # The API can only attach its fixed synthetic fixtures to an explicitly demo profile.
        if not request.patient.demo:
            raise ApiError(422, 'DEMO_FIXTURE_REQUIRES_DEMO_PROFILE', 'Synthetic fixtures cannot be attached to a real/local patient profile.')
        try:
            result_data = infer_demo(request.screening_type, request.case_id or '')
        except ValueError as exc:
            raise ApiError(422, 'UNKNOWN_DEMO_CASE', str(exc)) from exc
    else:
        adapter = adapter_for(request.screening_type)
        if not adapter.enabled():
            card = adapter.card()
            raise ApiError(503, 'MODEL_DISABLED', f'{card.status}: {card.reason}')
        if adapter.card().status != 'VALIDATED_FOR_INTENDED_USE' and not request.patient.demo:
            raise ApiError(422, 'EXPERIMENTAL_REQUIRES_RESEARCH_PROFILE',
                           'Experimental research output can only be attached to a demo/research profile, never a real patient.')
        try:
            result_data = adapter.infer(request.features)
        except InferenceError as exc:
            raise ApiError(exc.status, exc.code, exc.message) from exc
    id_origin = 'client' if request.id else 'server'
    screening_id = request.id or f'srv-{uuid4().hex[:16]}'
    record = ScreeningRecord(
        id=screening_id, patient=request.patient, result=result_data, context=request.context,
        worker_id=request.worker_id, phc=request.phc, village=request.village,
        created_at=result_data['generated_at'], id_origin=id_origin, sync_status='synced',
        fhir_bundle=_bundle_for({'patient_id': request.patient.patient_id, 'result': result_data,
                                 'worker_id': request.worker_id, 'phc': request.phc}, screening_id),
    )
    status = store.upsert_screening_status(record)
    if status == 'conflict':
        raise ApiError(409, 'ID_CONFLICT', 'A different screening already uses this id. Generate a new client id.')
    # Idempotency: a repeated client ID with the same content returns the originally stored record.
    saved = store.get_screening(screening_id)
    return ScreeningRecord.model_validate(saved) if saved else record


@app.get('/api/screenings', response_model=list[ScreeningRecord], tags=['screenings'])
def list_screenings(limit: int = Query(default=100, ge=1, le=500)) -> list[ScreeningRecord]:
    return [ScreeningRecord.model_validate(x) for x in store.get_screenings(limit)]


@app.get('/api/screenings/{screening_id}', response_model=ScreeningRecord, tags=['screenings'], responses=ERROR_RESPONSES)
def get_screening(screening_id: str) -> ScreeningRecord:
    saved = store.get_screening(screening_id)
    if not saved:
        raise ApiError(404, 'NOT_FOUND', 'Screening not found.')
    return ScreeningRecord.model_validate(saved)


def _sync_one(raw: dict[str, Any]) -> SyncItemResult:
    raw_id = raw.get('id') if isinstance(raw.get('id'), str) else None
    try:
        record = ScreeningRecord.model_validate(raw)
    except ValidationError as exc:
        fields = validation_fields(exc.errors())
        return SyncItemResult(id=raw_id, status='rejected', error={'code': 'VALIDATION_ERROR', 'status': 422, 'fields': fields,
                                                                   'message': f"Invalid record: {fields[0]['message'] if fields else 'schema error'}"})
    result = record.result.model_dump(mode='json')
    if record.result.provenance != 'DEMO_SYNTHETIC' or not record.patient.demo:
        # Only fixed demo fixtures may be created on a device. Model outputs are produced server-side.
        existing = store.get_screening(record.id)
        if existing and existing['result'].get('provenance') == record.result.provenance and existing['result']['estimate'] == record.result.estimate:
            return SyncItemResult(id=record.id, status='duplicate')
        return SyncItemResult(id=record.id, status='rejected', error={
            'code': 'CLIENT_RESULT_NOT_ACCEPTED', 'status': 422,
            'message': 'This sync endpoint accepts synthetic demo records only; model outputs are created by POST /api/screenings.'})
    # Client-generated FHIR could contain identifying data; regenerate it server-side.
    bundle = _bundle_for({'patient_id': record.patient.patient_id, 'result': result, 'worker_id': record.worker_id, 'phc': record.phc}, record.id)
    status = store.upsert_screening_status(record.model_copy(update={'fhir_bundle': bundle, 'sync_status': 'synced'}))
    if status == 'conflict':
        return SyncItemResult(id=record.id, status='conflict', error={
            'code': 'ID_CONFLICT', 'status': 409, 'message': 'The server already holds a different record with this id; the server copy is kept.'})
    return SyncItemResult(id=record.id, status=status)  # type: ignore[arg-type]


@app.post('/api/sync', response_model=SyncResponse, tags=['sync'], responses=ERROR_RESPONSES)
def sync_records(request: SyncRequest) -> SyncResponse:
    results = [_sync_one(raw) for raw in request.records]
    count = lambda s: sum(1 for r in results if r.status == s)  # noqa: E731
    return SyncResponse(accepted=count('accepted'), duplicate=count('duplicate'), conflict=count('conflict'), rejected=count('rejected'),
                        synced_ids=[r.id for r in results if r.status in ('accepted', 'duplicate') and r.id], results=results)


@app.get('/api/dashboard', response_model=DashboardResponse, tags=['dashboard'])
def dashboard() -> DashboardResponse:
    return DashboardResponse(**store.dashboard_summary())


@app.get('/api/patients', tags=['dashboard'])
def patients() -> list[dict[str, Any]]:
    return store.get_patients()


@app.get('/api/referrals', tags=['referrals'])
def referrals(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return store.get_referrals(limit)


@app.post('/api/counselling', response_model=GeminiCounselResponse, tags=['counselling'], responses=ERROR_RESPONSES)
async def counselling(request: GeminiCounselRequest) -> GeminiCounselResponse:
    return await gemini.counsel(request)


@app.get('/api/assistant', tags=['assistant'])
def assistant_status() -> dict[str, Any]:
    """Assistant availability and knowledge-base version. Never includes credentials or the provider URL."""
    return assistant.status()


@app.post('/api/assistant/ask', tags=['assistant'], responses=ERROR_RESPONSES)
async def assistant_ask(body: AssistantAskRequest, request: Request) -> dict[str, Any]:
    """General, non-clinical information from the curated knowledge base (docs/build2026/assistant.md)."""
    if not assistant.enabled():
        raise ApiError(503, 'ASSISTANT_DISABLED', 'The help assistant is switched off on this server.', retryable=False)
    decision = assistant.check_rate(_client_ip(request))
    if not decision.allowed:
        raise ApiError(429, 'RATE_LIMITED', 'Too many questions. Try again in a minute.', retryable=True,
                       headers={'Retry-After': str(decision.retry_after_seconds)})
    return await assistant.ask(body.question)


@app.post('/api/fhir', tags=['interop'], responses=ERROR_RESPONSES)
def fhir_bundle(request: FHIRRequest) -> dict[str, Any]:
    if not request.result.synthetic:
        raise ApiError(422, 'CLIENT_RESULT_NOT_ACCEPTED', 'Only synthetic demonstration outputs can be exported by this prototype.')
    if request.patient.get('demo') is not True:
        raise ApiError(422, 'DEMO_PROFILE_REQUIRED', 'FHIR export accepts synthetic demo profiles only; use local export for local-only records.')
    sensitive_fields = {'name', 'birthdate', 'birth_date', 'telecom', 'phone', 'email', 'photo', 'address', 'village', 'identifier'}
    if sensitive_fields.intersection(str(key).lower() for key in request.patient):
        raise ApiError(422, 'IDENTIFYING_FIELDS_REJECTED', 'Send only a pseudonymous patient_id to the server. Create detailed FHIR exports locally.')
    patient_id = request.patient.get('patient_id') or request.patient.get('id')
    if not patient_id:
        raise ApiError(422, 'VALIDATION_ERROR', 'A pseudonymous patient_id is required.')
    try:
        PatientSync(patient_id=str(patient_id), demo=True)
    except ValidationError as exc:
        raise ApiError(422, 'VALIDATION_ERROR', 'A pseudonymous alphanumeric patient_id is required.') from exc
    return FHIR.generate_bundle({'patient_id': str(patient_id)}, request.result.model_dump(mode='json'), request.worker, request.screening_id)


@app.post('/api/referrals', tags=['referrals'], responses=ERROR_RESPONSES)
def create_referral(request: ReferralRequest) -> dict[str, Any]:
    record = request.screening
    stored = store.get_screening(record.id)
    is_demo = record.patient.demo and record.result.synthetic and record.result.model_mode == 'DEMO'
    if not is_demo:
        # A non-demo referral must point at a result the server itself produced.
        if not stored or stored['result'].get('provenance') != record.result.provenance:
            raise ApiError(422, 'REFERRAL_RESULT_NOT_ACCEPTED', 'Only fixed synthetic demo screening referrals or server-generated results are supported.')
    elif not stored:
        clean_bundle = _bundle_for({'patient_id': record.patient.patient_id, 'result': record.result.model_dump(mode='json'),
                                    'worker_id': record.worker_id, 'phc': record.phc}, record.id)
        record = record.model_copy(update={'fhir_bundle': clean_bundle})
        if store.upsert_screening_status(record) == 'conflict':
            raise ApiError(409, 'ID_CONFLICT', 'A different screening already uses this id.')
    if stored:
        record = ScreeningRecord.model_validate(stored)
    payload = request.model_dump(mode='json')
    payload['screening'] = record.model_dump(mode='json')
    payload['generated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    created = store.create_referral(request.id, record.id, payload)
    return {'id': request.id, 'screening_id': record.id, 'created': created, 'pdf_url': f'/api/referrals/{request.id}/pdf',
            'provenance': record.result.provenance, 'note': 'Prototype referral brief; not a diagnosis.'}


@app.get('/api/referrals/{referral_id}/pdf', tags=['referrals'], responses={200: {'content': {'application/pdf': {}}}, **ERROR_RESPONSES})
def referral_pdf(referral_id: str) -> Response:
    referral = store.get_referral(referral_id)
    if not referral:
        raise ApiError(404, 'NOT_FOUND', 'Referral not found.')
    try:
        pdf = build_referral_pdf(referral['payload'])
    except Exception as exc:
        logger.error('referral pdf failed type=%s', type(exc).__name__)
        raise ApiError(500, 'PDF_GENERATION_FAILED', 'Referral PDF generation failed.', retryable=True) from exc
    safe_name = ''.join(c for c in referral_id if c.isalnum() or c in '-_.')[:96]
    return Response(content=pdf, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="abhaynayan-{safe_name}.pdf"'})


@app.get('/api/vision/capabilities', tags=['vision'])
def vision_capabilities() -> dict[str, Any]:
    enabled = flag_enabled()
    return {'quality_gate': True, 'opencv_features': True, 'image_upload_api': enabled,
            'image_upload_endpoints': ['/api/ml/hemoglobin', '/api/ml/neonatal-jaundice-class'] if enabled else [],
            'reason': ('Research image endpoints are enabled by the operator; images are processed in memory and never stored.' if enabled else
                       'Camera frames stay in the browser. Backend image uploads are disabled by default '
                       f'(operator flag {IMAGE_MODELS_FLAG}).')}


# ----- research image models (contract 1.1.0) ---------------------------------------------------------
# Raw PNG/JPEG request bodies, processed in memory only: bytes are never stored, logged or forwarded.

IMAGE_REQUEST_BODY = {'content': {'image/png': {'schema': {'type': 'string', 'format': 'binary'}},
                                  'image/jpeg': {'schema': {'type': 'string', 'format': 'binary'}}}, 'required': True}
# Tasks whose model is not rotation-invariant (cnn-v1). cf-v1 colour features are nearly invariant (audit §5.2).
ORIENTATION_SENSITIVE_TASKS = frozenset({'neonatal_jaundice_class'})
ML_SAFETY_NOTE = ('Experimental research output from a model trained on a small public dataset. Not a measurement or diagnosis; '
                  'do not use for any care decision. Confirm with appropriate laboratory testing.')


def _served_model(task: str):
    try:
        return REGISTRY.served(task)
    except ModelError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc


async def _read_bounded(request: Request) -> bytes:
    limit = config.get().max_image_bytes
    too_large = 'The image is larger than this server accepts.'
    declared = request.headers.get('content-length')
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, 'IMAGE_TOO_LARGE', too_large)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ApiError(413, 'IMAGE_TOO_LARGE', too_large)
        chunks.append(chunk)
    return b''.join(chunks)


# Contract 2.0 task per research route, and the only body site each model accepts (docs/prediction_contract.md §5).
TASK_OF = {'hemoglobin': 'hemoglobin_from_palpebral_conjunctiva', 'neonatal_jaundice_class': 'newborn_jaundice_dataset_class'}
ACCEPTED_SITE = {'hemoglobin': 'palpebral_conjunctiva_segmented', 'neonatal_jaundice_class': 'newborn_skin_whole_view'}
SOFTWARE_VERSION = f'backend-api-{API_CONTRACT_VERSION}'
# Body-site verifier: returns True (verified), False (checked and failed) or None (no verifier). **None is installed**:
# no licensed, validated detector exists, and masked random noise passes every other gate (20/20 in the Phase 5 probe).
# So the research routes fail closed with MODALITY_UNVERIFIED. Tests replace this to exercise the model path.
BODY_SITE_VERIFIER = lambda site, image: None  # noqa: E731
RUNTIME_OF = {'GRADIENT_BOOSTED_TREES_JSON': 'python-trees-json', 'LINEAR_COLOUR_REGRESSOR': 'python-linear-json',
              'LOGISTIC_COLOUR_CLASSIFIER': 'python-linear-json', 'ONNX_CNN_CLASSIFIER': 'onnxruntime-cpu'}


class _Outcome:
    """Collects what is known about one research request and turns it into a valid contract 2.0 envelope."""

    def __init__(self, task: str) -> None:
        self.task, self.site = task, 'unknown'
        self.image, self.orientation = None, None
        self.verification = {'method': 'protocol_declared', 'status': 'unverified'}
        self.quality = {'status': 'not_assessed', 'rules_version': 'quality-server-1.0.0', 'checks': []}
        self.compat = {'status': 'not_assessed', 'rules_version': 'compat-server-1.0.0', 'checks': []}

    def input_info(self) -> dict[str, Any]:
        img, o = self.image, self.orientation
        return {'modality': 'photo', 'body_site': self.site,
                'body_site_verification': dict(self.verification),
                'source': 'upload', 'capture_protocol': None,
                'orientation': {'exif_tag': o.exif_tag if o is not None and o.exif_tag in range(1, 9) else None,
                                'applied': o.applied if o is not None else 'unknown'},
                'width': int(img.shape[1]) if img is not None else 0, 'height': int(img.shape[0]) if img is not None else 0,
                'valid_pixel_count': 0}

    def envelope(self, status: str, reason: str | None, estimate=None, model=None, source='none', warnings=None) -> dict[str, Any]:
        return P.build(status=status, reason_code=reason, task=TASK_OF[self.task], input_info=self.input_info(),
                       quality=self.quality, compatibility=self.compat, estimate=estimate, model=model, source=source,
                       warnings=warnings or [], software_version=SOFTWARE_VERSION)

    def refuse(self, http: int, legacy_code: str, message: str, reason: str, *, error: bool = False, retryable: bool = False,
               fields=None, warnings=None) -> ApiError:
        env = self.envelope('error' if error else 'unable_to_estimate', reason, warnings=warnings)
        return ApiError(http, legacy_code, message, retryable=retryable, fields=fields, extra={'prediction': env})


def _model_ref(model) -> dict[str, Any]:
    meta = model.meta
    return {'model_id': model.model_id, 'model_version': model.version, 'artifact_sha256': dict(model.sha256),
            'feature_contract': meta.get('feature_version') or 'cnn-v1', 'runtime': RUNTIME_OF.get(meta.get('artifact_type'), 'unknown'),
            'model_status': 'research_only', 'model_card_ref': f'docs/model_cards/{model.model_id}.md'}


def _run_image_model(task: str, data: bytes, content_type: str | None) -> dict[str, Any]:
    """Gate order (contract §4): decode → orientation → modality/region → quality → compatibility (distribution) → inference
    → output validation. Every refusal after the model check carries `prediction` (status unable_to_estimate or error);
    no value is ever returned with an error."""
    t0 = time.perf_counter()
    model = _served_model(task)
    out = _Outcome(task)
    try:
        decoded = imageio.decode_image(data, content_type, config.get().max_image_bytes)
    except imageio.ImageInputError as exc:
        raise out.refuse(exc.status, exc.code, exc.message, P.LEGACY_TO_REASON.get(exc.code, 'INPUT_DECODE_FAILED')) from exc
    image = decoded.pixels
    out.image, out.orientation = image, decoded.orientation
    orientation_warning = decoded.orientation.status == 'invalid'
    if orientation_warning and task in ORIENTATION_SENSITIVE_TASKS:
        # The CNN is not rotation-invariant (audit M2): an unreadable orientation tag means the input is unknown.
        raise out.refuse(422, 'ORIENTATION_UNKNOWN', 'The image orientation metadata could not be read; no prediction was made.',
                         'MODALITY_UNVERIFIED')

    # Modality / region. Research operators upload dataset images; the server cannot verify anatomy, so only the image
    # *form* each model was trained on is accepted: Hb models need an expert-segmented crop (transparent background);
    # the NJN model was trained on whole opaque newborn photos. App-style rectangle crops are refused (audit H3).
    masked = image.shape[2] == 4 and bool((image[..., 3] < ml_features.ALPHA_MIN).any())
    region_check = P.check('segmentation_mask_present', masked, task == 'hemoglobin', '==', masked == (task == 'hemoglobin'))
    out.compat = {**out.compat, 'checks': [region_check]}
    if task == 'hemoglobin' and not masked:
        out.compat['status'] = 'incompatible'
        raise out.refuse(422, 'TARGET_REGION_INCOMPATIBLE', 'This model needs an expert-segmented conjunctiva image (transparent '
                         'background). Rectangle crops and whole photos are not compatible; no prediction was made.', 'TARGET_REGION_INCOMPATIBLE')
    if task != 'hemoglobin' and masked:
        out.compat['status'] = 'incompatible'
        raise out.refuse(422, 'MODALITY_UNSUPPORTED', 'This model was trained on whole newborn photos; masked crops are not '
                         'compatible. No prediction was made.', 'MODALITY_UNSUPPORTED')
    out.site = ACCEPTED_SITE[task]

    t_decode = time.perf_counter()
    quality = ml_quality.assess(image)
    m = quality.metrics
    out.quality = {'status': 'passed' if quality.passed else 'failed', 'rules_version': 'quality-server-1.0.0', 'checks': [
        P.check('valid_pixels', m['valid_pixels'], ml_features.MIN_VALID_PIXELS, '>=', 'TOO_FEW_USABLE_PIXELS' not in quality.issues),
        P.check('valid_fraction', m['valid_fraction'], ml_quality.MIN_VALID_FRACTION, '>=', 'TARGET_REGION_TOO_SMALL_OR_DARK' not in quality.issues),
        P.check('clipped_fraction', m['clipped_fraction'], ml_quality.MAX_CLIPPED_FRACTION, '<=', 'OVEREXPOSED_OR_GLARE' not in quality.issues),
        P.check('mean_brightness', m['mean_brightness'], ml_quality.MIN_MEAN_V, '>=', 'TOO_DARK' not in quality.issues),
        P.check('sharpness_laplacian_var', m['sharpness'], ml_quality.MIN_SHARPNESS, '>=', 'BLURRED_OR_FLAT' not in quality.issues),
    ]}
    if not quality.passed:
        raise out.refuse(422, 'IMAGE_QUALITY_REJECTED', 'The image did not pass the quality checks; no prediction was made.', 'QUALITY_FAILED',
                         fields=[{'loc': ['image'], 'message': issue, 'type': 'quality'} for issue in quality.issues])
    try:
        fr = ml_features.extract(image)
    except ml_features.FeatureError as exc:
        out.quality['status'] = 'failed'
        raise out.refuse(422, 'IMAGE_QUALITY_REJECTED', str(exc), 'QUALITY_FAILED') from exc

    # Out-of-distribution inputs give no value (contract decision D3; audit H2).
    ood = model.out_of_range_features(fr.vector)
    range_check = P.check('feature_range_cf_v1', len(ood), 0, '<=', not ood)
    out.compat = {**out.compat, 'checks': [region_check, range_check]}
    if ood:
        out.compat['status'] = 'incompatible'
        raise out.refuse(422, 'INPUT_OUT_OF_DISTRIBUTION', 'The image is outside the range of images the model was trained on; '
                         'no prediction was made.', 'INPUT_OUT_OF_DISTRIBUTION',
                         fields=[{'loc': ['image'], 'message': name, 'type': 'out_of_distribution'} for name in ood[:10]],
                         warnings=[P.warning('INPUT_OUT_OF_DISTRIBUTION', 'blocking', SOFTWARE_VERSION, {'features': ood[:10]})])
    verified = BODY_SITE_VERIFIER(ACCEPTED_SITE[task], image)
    verify_check = P.check('body_site_verified', 'no verifier installed' if verified is None else bool(verified), True, '==', verified is True)
    out.compat = {**out.compat, 'checks': [region_check, range_check, verify_check]}
    if verified is not True:
        out.compat['status'] = 'incompatible'
        out.verification = {'method': 'protocol_declared' if verified is None else 'detector:server-verifier@0',
                            'status': 'unverified' if verified is None else 'failed'}
        raise out.refuse(422, 'MODALITY_UNVERIFIED', 'The server cannot confirm that this image shows the body area the model '
                         'needs; no prediction was made.', 'MODALITY_UNVERIFIED')
    out.verification = {'method': 'detector:server-verifier@0', 'status': 'verified'}
    out.compat['status'] = 'compatible'
    try:
        raw = model.predict(image, fr)
    except ModelError as exc:
        raise out.refuse(exc.status, exc.code, exc.message, P.LEGACY_TO_REASON.get(exc.code, 'INFERENCE_RUNTIME_ERROR'),
                         error=exc.status >= 500) from exc
    except Exception as exc:  # never fall back to a value
        logger.error('image inference failed task=%s type=%s', task, type(exc).__name__)
        raise out.refuse(500, 'INFERENCE_FAILED', 'The model could not process this image; no value was produced.',
                         'INFERENCE_RUNTIME_ERROR', error=True, retryable=True) from exc
    if not math.isfinite(raw):
        raise out.refuse(500, 'INFERENCE_FAILED', 'The model returned a non-finite value; no value was produced.', 'OUTPUT_NON_FINITE',
                         error=True, retryable=True)
    legacy_warnings = ['RESEARCH_ONLY_NOT_VALIDATED']
    env_warnings = [P.warning('RESEARCH_ONLY_NOT_VALIDATED', 'caution', SOFTWARE_VERSION)]
    if orientation_warning:
        legacy_warnings.append('ORIENTATION_UNKNOWN')
        env_warnings.append(P.warning('ORIENTATION_UNKNOWN', 'caution', SOFTWARE_VERSION))
    meta = model.meta
    result: dict[str, Any] = {
        'task': task, 'status': 'OK', 'provenance': 'EXPERIMENTAL_RESEARCH_ONLY', 'synthetic': False,
        'model_id': model.model_id, 'model_version': model.version, 'feature_version': ml_features.FEATURE_VERSION,
        'warnings': legacy_warnings, 'out_of_distribution_features': [],
        'quality': quality.as_dict(),
        'input': {'width': int(image.shape[1]), 'height': int(image.shape[0]), 'channels': int(image.shape[2]),
                  'valid_pixels': fr.valid_pixels, 'image_retained': False, 'orientation': decoded.orientation.as_dict()},
        'intended_input': meta.get('intended_input') or meta.get('task'),
        'evaluation_summary': meta.get('evaluation'),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'safety_note': ML_SAFETY_NOTE,
    }
    if task == 'hemoglobin':
        lo, hi = HB_PLAUSIBLE
        if not lo <= raw <= hi:
            raise out.refuse(422, 'OUTPUT_OUT_OF_RANGE', 'The model output was outside the physiological range and was discarded.',
                             'OUTPUT_IMPLAUSIBLE')
        value = round(raw, 1)
        result.update({'estimate': value, 'unit': 'g/dL', 'confidence': None,
                       'interpretation': 'No anemia category is given: no threshold is validated for the intended population.'})
        estimate = {'value': value, 'unit': 'g/dL', 'display_precision': 1, 'uncertainty': {'kind': 'none'}}
    else:
        if not 0.0 <= raw <= 1.0:
            raise out.refuse(500, 'INFERENCE_FAILED', 'The model returned an invalid score; no value was produced.', 'OUTPUT_IMPLAUSIBLE',
                             error=True, retryable=True)
        thr = float(meta['operating_threshold'])
        result.update({'score': round(raw, 4), 'unit': None, 'research_threshold': round(thr, 4),
                       'dataset_class_at_research_threshold': 'jaundice_like' if raw >= thr else 'normal_like',
                       'interpretation': ('Score for the NJN dataset class "jaundice". It is NOT a bilirubin value and the '
                                          'threshold is a research operating point, not a clinical cut-off.')})
        estimate = {'value': round(raw, 4), 'unit': 'score', 'display_precision': 2, 'uncertainty': {'kind': 'none'}}
    result['prediction'] = out.envelope('estimated', None, estimate=estimate, model=_model_ref(model), source='backend', warnings=env_warnings)
    result['timing_ms'] = {'decode': round((t_decode - t0) * 1000, 2), 'total': round((time.perf_counter() - t0) * 1000, 2)}
    return result


@app.get('/api/ml/models', tags=['research-models'])
def ml_models() -> dict[str, Any]:
    return {'api_contract_version': API_CONTRACT_VERSION, 'enabled': flag_enabled(), 'flag': IMAGE_MODELS_FLAG,
            'models': REGISTRY.status(), 'bilirubin_mg_dl_model': 'DISABLED_NO_VALID_MODEL (no measured bilirubin labels)',
            'safety_note': ML_SAFETY_NOTE}


@app.post('/api/ml/hemoglobin', tags=['research-models'], responses=ERROR_RESPONSES, openapi_extra={'requestBody': IMAGE_REQUEST_BODY})
async def ml_hemoglobin(request: Request) -> dict[str, Any]:
    """Research-only Hb (g/dL) from a segmented palpebral-conjunctiva image. Requires a research-operator token
    and the operator flag; authentication and rate limits are checked before the body is read."""
    return await _protected_image_route(request, 'hemoglobin')


@app.post('/api/ml/neonatal-jaundice-class', tags=['research-models'], responses=ERROR_RESPONSES,
          openapi_extra={'requestBody': IMAGE_REQUEST_BODY})
async def ml_neonatal_jaundice_class(request: Request) -> dict[str, Any]:
    """Research-only NJN dataset-class score (jaundice vs normal). Not bilirubin. Requires a research-operator token
    and the operator flag."""
    return await _protected_image_route(request, 'neonatal_jaundice_class')


async def _protected_image_route(request: Request, task: str) -> dict[str, Any]:
    principal = authorize_research(request)
    async with _rate_limited(principal):
        _served_model(task)  # 503 MODEL_DISABLED before reading the body
        data = await _read_bounded(request)
        return await run_in_threadpool(_run_image_model, task, data, request.headers.get('content-type'))


def _parse_iso(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ApiError(422, 'VALIDATION_ERROR', f'{name} must be an ISO-8601 timestamp.') from exc
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


@app.get('/api/admin/usage', tags=['admin'], responses=ERROR_RESPONSES)
def admin_usage(since: str | None = None, until: str | None = None, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Aggregate Gemini usage for operators. Requires ABHAYNAYAN_ADMIN_TOKEN; disabled when unset."""
    expected = os.getenv('ABHAYNAYAN_ADMIN_TOKEN', '').strip()
    if len(expected) < 16:
        raise ApiError(403, 'ADMIN_DISABLED', 'The usage report is disabled. Set ABHAYNAYAN_ADMIN_TOKEN (16+ characters) on the server.')
    supplied = (authorization or '').removeprefix('Bearer ').strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise ApiError(401, 'UNAUTHORIZED', 'A valid admin bearer token is required.')
    return gemini.usage_report(_parse_iso(since, 'since'), _parse_iso(until, 'until'))


# Serve the PWA from the same origin as the API. This also avoids a permissive cross-origin API setup.
if WEB_DIR.exists():
    app.mount('/css', StaticFiles(directory=WEB_DIR / 'css'), name='css')
    app.mount('/js', StaticFiles(directory=WEB_DIR / 'js'), name='js')
    app.mount('/assets', StaticFiles(directory=WEB_DIR / 'assets'), name='assets')
    if (PROJECT_DIR / 'docs').exists():
        app.mount('/docs', StaticFiles(directory=PROJECT_DIR / 'docs'), name='project-docs')

    @app.get('/manifest.webmanifest', include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(WEB_DIR / 'manifest.webmanifest', media_type='application/manifest+json')

    @app.get('/sw.js', include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(WEB_DIR / 'sw.js', media_type='application/javascript')

    @app.get('/', include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(WEB_DIR / 'index.html')

    @app.get('/{path:path}', include_in_schema=False)
    def spa_fallback(path: str) -> Response:
        # Only use the fallback for extensionless navigation paths; preserve API and file 404s.
        if path.startswith('api/') and any(getattr(r, 'path', None) == f'/{path}' for r in app.routes):
            # The catch-all would otherwise turn "wrong method on a real API route" into a 404.
            raise ApiError(405, 'METHOD_NOT_ALLOWED', 'Method not allowed for this endpoint.')
        if path.startswith('api/') or '.' in Path(path).name:
            raise ApiError(404, 'NOT_FOUND', 'Not found.')
        return FileResponse(WEB_DIR / 'index.html')
