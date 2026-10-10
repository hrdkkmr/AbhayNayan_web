from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.inference import DEMO_CASES, SAFETY_NOTE, DemoInferenceModel, infer_demo
from app.core.model_adapters import ADAPTERS, CANDIDATE_MODELS, InferenceError, adapter_for
from app.models.schemas import (
    API_CONTRACT_VERSION,
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
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {code: {'model': ErrorResponse} for code in (401, 403, 404, 409, 422, 500, 503)}
STATUS_CODES = {400: 'BAD_REQUEST', 401: 'UNAUTHORIZED', 403: 'FORBIDDEN', 404: 'NOT_FOUND', 405: 'METHOD_NOT_ALLOWED',
                409: 'CONFLICT', 422: 'VALIDATION_ERROR', 500: 'INTERNAL_ERROR', 503: 'SERVICE_UNAVAILABLE'}


class ApiError(Exception):
    """A client-safe error with a stable contract code."""

    def __init__(self, status: int, code: str, message: str, retryable: bool = False, fields: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.retryable, self.fields = status, code, message, retryable, fields or []


def error_body(status: int, code: str, message: str, retryable: bool = False, fields: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {'detail': message, 'error': {'code': code, 'message': message, 'status': status, 'retryable': retryable, 'fields': fields or []},
            'api_contract_version': API_CONTRACT_VERSION}


def validation_fields(errors: list[Any]) -> list[dict[str, Any]]:
    # Field paths and messages only; submitted values are never echoed back (they may be identifying).
    return [{'loc': [str(part) for part in e.get('loc', ())], 'message': str(e.get('msg', '')).removeprefix('Value error, ')[:200],
             'type': str(e.get('type', ''))} for e in errors]


@asynccontextmanager
async def lifespan(_: FastAPI):
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
    return JSONResponse(status_code=exc.status, content=error_body(exc.status, exc.code, exc.message, exc.retryable, exc.fields))


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
        'optional_tflite': {'available': False, 'reason': 'No validated model artifact or model-specific tensor adapter is bundled.'},
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
        'capture': {'mode': 'browser-local', 'backend_receives_images': False},
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
def create_screening(request: ScreeningCreateRequest) -> ScreeningRecord:
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
    return {'quality_gate': True, 'opencv_features': True, 'image_upload_api': False,
            'reason': 'Camera frames stay in the browser. Backend image uploads are intentionally disabled by default.'}


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
        if path.startswith('api/') or '.' in Path(path).name:
            raise ApiError(404, 'NOT_FOUND', 'Not found.')
        return FileResponse(WEB_DIR / 'index.html')
