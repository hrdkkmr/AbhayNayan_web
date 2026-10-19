from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.inference import DEMO_CASES, SAFETY_NOTE, DemoInferenceModel, infer_demo
from app.models.schemas import (
    DashboardResponse,
    FHIRRequest,
    GeminiCounselRequest,
    GeminiCounselResponse,
    HealthResponse,
    PatientSync,
    ReferralRequest,
    ScreeningCreateRequest,
    ScreeningRecord,
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init_db()
    yield


app = FastAPI(
    title='AbhayNayan Prototype API',
    version='0.1.0',
    description='Offline-first hackathon demo API. Synthetic estimates only; not for diagnosis or treatment.',
    lifespan=lifespan,
)

origins = [x.strip() for x in os.getenv('ABHAYNAYAN_ALLOW_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',') if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=['GET', 'POST', 'OPTIONS'], allow_headers=['Content-Type'])


@app.get('/api/health', response_model=HealthResponse, tags=['system'])
def health() -> HealthResponse:
    return HealthResponse(gemini_configured=gemini.gemini_configured())


@app.get('/api/model/status', tags=['system'])
def model_status() -> dict[str, Any]:
    research_path = PROJECT_DIR / 'models' / 'anemia_color_baseline.json'
    try:
        research = json.loads(research_path.read_text())
    except (OSError, json.JSONDecodeError):
        research = None
    return {
        'active_inference': DEMO_MODEL.get_model_info(),
        'optional_tflite': {'available': False, 'reason': 'No approved model artifact or model-specific tensor adapter is bundled.'},
        'research_baseline': research,
        'research_baseline_enabled_for_screening': False,
        'safety_note': SAFETY_NOTE,
    }


@app.get('/api/demo/cases', tags=['screenings'])
def demo_cases() -> dict[str, Any]:
    return {
        'mode': 'DEMO', 'synthetic': True,
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
        'inference': {'mode': 'DEMO', 'uses_patient_pixels_for_estimate': False},
        'counselling': {'mode': 'Gemini optional; local deterministic language fallback'},
        'storage': {'browser': 'IndexedDB/localStorage', 'backend': 'SQLite demo store'},
        'note': SAFETY_NOTE,
    }


@app.post('/api/screenings', response_model=ScreeningRecord, tags=['screenings'])
def create_screening(request: ScreeningCreateRequest) -> ScreeningRecord:
    # The API can only attach its fixed synthetic fixtures to an explicitly demo profile.
    if not request.patient.demo:
        raise HTTPException(status_code=422, detail='Synthetic fixtures cannot be attached to a real/local patient profile.')
    try:
        DEMO_MODEL.load()
        result_data = infer_demo(request.screening_type, request.case_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    screening_id = request.id or f'scr-{uuid4().hex[:16]}'
    created_at = result_data['generated_at']
    bundle = FHIR.generate_bundle(
        {'patient_id': request.patient.patient_id, 'sex': 'unknown'}, result_data,
        {'worker_id': request.worker_id, 'phc': request.phc}, screening_id,
    )
    record = ScreeningRecord(
        id=screening_id,
        patient=request.patient,
        result=result_data,
        worker_id=request.worker_id,
        phc=request.phc,
        village=request.village,
        created_at=created_at,
        sync_status='synced',
        fhir_bundle=bundle,
    )
    store.upsert_screening(record)
    # Idempotency: a repeated client ID returns the originally stored, stable record.
    saved = store.get_screening(screening_id)
    return ScreeningRecord.model_validate(saved) if saved else record


@app.get('/api/screenings', response_model=list[ScreeningRecord], tags=['screenings'])
def list_screenings(limit: int = Query(default=100, ge=1, le=500)) -> list[ScreeningRecord]:
    return [ScreeningRecord.model_validate(x) for x in store.get_screenings(limit)]


@app.get('/api/screenings/{screening_id}', response_model=ScreeningRecord, tags=['screenings'])
def get_screening(screening_id: str) -> ScreeningRecord:
    saved = store.get_screening(screening_id)
    if not saved:
        raise HTTPException(status_code=404, detail='Screening not found.')
    return ScreeningRecord.model_validate(saved)


@app.post('/api/sync', response_model=SyncResponse, tags=['sync'])
def sync_records(request: SyncRequest) -> SyncResponse:
    accepted, duplicates, synced = 0, 0, []
    for record in request.records:
        if not record.patient.demo or not record.result.synthetic or record.result.model_mode != 'DEMO':
            raise HTTPException(status_code=422, detail='This prototype sync endpoint accepts synthetic demo records only.')
        # Client-generated arbitrary FHIR could accidentally contain identifying data; regenerate it server-side.
        result = record.result.model_dump(mode='json')
        bundle = FHIR.generate_bundle(
            {'patient_id': record.patient.patient_id}, result,
            {'worker_id': record.worker_id, 'phc': record.phc}, record.id,
        )
        clean_record = record.model_copy(update={'fhir_bundle': bundle, 'sync_status': 'synced'})
        inserted = store.upsert_screening(clean_record)
        if inserted:
            accepted += 1
        else:
            duplicates += 1
        synced.append(record.id)
    return SyncResponse(accepted=accepted, duplicate=duplicates, synced_ids=synced)


@app.get('/api/dashboard', response_model=DashboardResponse, tags=['dashboard'])
def dashboard() -> DashboardResponse:
    return DashboardResponse(**store.dashboard_summary())


@app.get('/api/patients', tags=['dashboard'])
def patients() -> list[dict[str, Any]]:
    return store.get_patients()


@app.get('/api/referrals', tags=['referrals'])
def referrals(limit: int = Query(default=100, ge=1, le=500)) -> list[dict[str, Any]]:
    return store.get_referrals(limit)


@app.post('/api/counselling', response_model=GeminiCounselResponse, tags=['counselling'])
async def counselling(request: GeminiCounselRequest) -> GeminiCounselResponse:
    return await gemini.counsel(request)


@app.post('/api/fhir', tags=['interop'])
def fhir_bundle(request: FHIRRequest) -> dict[str, Any]:
    if not request.result.synthetic:
        raise HTTPException(status_code=422, detail='Only synthetic demonstration outputs can be exported by this prototype.')
    if request.patient.get('demo') is not True:
        raise HTTPException(status_code=422, detail='FHIR export accepts synthetic demo profiles only; use local export for local-only records.')
    sensitive_fields = {'name', 'birthdate', 'birth_date', 'telecom', 'phone', 'email', 'photo', 'address', 'village', 'identifier'}
    if sensitive_fields.intersection(str(key).lower() for key in request.patient):
        raise HTTPException(status_code=422, detail='Send only a pseudonymous patient_id to the server. Create detailed FHIR exports locally.')
    patient_id = request.patient.get('patient_id') or request.patient.get('id')
    if not patient_id:
        raise HTTPException(status_code=422, detail='A pseudonymous patient_id is required.')
    try:
        PatientSync(patient_id=str(patient_id), demo=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail='A pseudonymous alphanumeric patient_id is required.') from exc
    return FHIR.generate_bundle({'patient_id': str(patient_id)}, request.result.model_dump(mode='json'), request.worker, request.screening_id)


@app.post('/api/referrals', tags=['referrals'])
def create_referral(request: ReferralRequest) -> dict[str, Any]:
    record = request.screening
    if not record.patient.demo or not record.result.synthetic or record.result.model_mode != 'DEMO':
        raise HTTPException(status_code=422, detail='Only fixed synthetic demo screening referrals are supported.')
    if not store.get_screening(record.id):
        clean_bundle = FHIR.generate_bundle({'patient_id': record.patient.patient_id}, record.result.model_dump(mode='json'),
                                            {'worker_id': record.worker_id, 'phc': record.phc}, record.id)
        record = record.model_copy(update={'fhir_bundle': clean_bundle})
        store.upsert_screening(record)
    payload = request.model_dump(mode='json')
    created = store.create_referral(request.id, record.id, payload)
    return {'id': request.id, 'screening_id': record.id, 'created': created, 'pdf_url': f'/api/referrals/{request.id}/pdf',
            'note': 'Prototype referral brief; not a diagnosis.'}


@app.get('/api/referrals/{referral_id}/pdf', tags=['referrals'], responses={200: {'content': {'application/pdf': {}}}})
def referral_pdf(referral_id: str) -> Response:
    referral = next((item for item in store.get_referrals() if item['id'] == referral_id), None)
    if not referral:
        raise HTTPException(status_code=404, detail='Referral not found.')
    try:
        pdf = build_referral_pdf(referral['payload'])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Referral PDF generation failed ({type(exc).__name__}).') from exc
    return Response(content=pdf, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="abhaynayan-{referral_id}.pdf"'})


@app.get('/api/vision/capabilities', tags=['vision'])
def vision_capabilities() -> dict[str, Any]:
    return {'quality_gate': True, 'opencv_features': True, 'image_upload_api': False,
            'reason': 'Camera frames stay in the browser. Backend image uploads are intentionally disabled by default.'}


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
            raise HTTPException(status_code=404, detail='Not found.')
        return FileResponse(WEB_DIR / 'index.html')
