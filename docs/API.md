# AbhayNayan prototype API

Base URL in local development: `http://localhost:8000`. The PWA and API are served same-origin. This is a hackathon/demo service, not a production health-information exchange. OpenAPI/Swagger is available at `/docs` and the JSON schema at `/openapi.json`.

## Global safety and privacy contract

- All screening endpoints currently use fixed synthetic fixtures. There is no active clinical inference model.
- The backend does not provide an image-upload route. Camera frames and optical features stay in the browser.
- Send pseudonymous alphanumeric IDs only; do not send patient names, phone numbers, exact birth dates, images, or direct identifiers.
- Sync and FHIR export accept synthetic demo results only. The server regenerates the FHIR bundle during sync rather than trusting a client-supplied bundle.
- Gemini is optional and server-side. If the key is unset, a timeout occurs, or generated text fails schema/safety checks, deterministic local-language text is returned.
- Every number/category is a demonstration fixture, not a lab value, diagnosis, validated risk classification, or treatment threshold.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health, prototype mode, key-configured boolean (never the key) |
| `GET` | `/api/model/status` | Active demo inference status, disabled research baseline, safety note |
| `GET` | `/api/demo/cases` | Fixed maternal and neonatal synthetic fixtures |
| `GET` | `/api/pipeline` | Current data boundary and pipeline capability description |
| `GET` | `/api/vision/capabilities` | Confirms local-only image processing and disabled server upload |
| `POST` | `/api/screenings` | Create/read-back an idempotent synthetic demo screening |
| `GET` | `/api/screenings?limit=100` | List pseudonymous server demo records |
| `GET` | `/api/screenings/{id}` | Retrieve one pseudonymous server demo record |
| `POST` | `/api/sync` | Idempotently sync up to 100 queued synthetic records per request |
| `GET` | `/api/dashboard` | Server-side synthetic demo counts and recent records |
| `GET` | `/api/patients` | Pseudonymous IDs and aggregate per-ID counts only |
| `POST` | `/api/counselling` | Optional Gemini structured counselling or deterministic fallback |
| `POST` | `/api/fhir` | Return a preliminary FHIR R4-style demonstration Bundle |
| `GET` | `/api/referrals` | List prototype referral briefs |
| `POST` | `/api/referrals` | Save a synthetic referral brief |
| `GET` | `/api/referrals/{id}/pdf` | Download the server-generated PDF brief |

## Create a screening

`POST /api/screenings`

```json
{
  "id": "scr-demo-001",
  "patient": { "patient_id": "ABH-2026-0001", "demo": true },
  "screening_type": "maternal_anemia",
  "case_id": "maternal-moderate",
  "worker_id": "demo-worker",
  "phc": "Demo PHC"
}
```

`screening_type` is `maternal_anemia` or `neonatal_jaundice`. Obtain valid `case_id` values from `/api/demo/cases`. A client `id` may be supplied for idempotency; repeating the same ID returns the stored record. The result includes `synthetic: true`, `model_mode: "DEMO"`, a safety note, and a FHIR-style bundle. It is not calculated from image pixels. The API rejects `patient.demo: false`; the browser also blocks fixture estimates for local-only profiles.

## Offline sync

`POST /api/sync`

Body: `{ "records": [ <ScreeningRecord>, ... ] }`, max 100 records. Each record must contain a valid pseudonymous `patient.patient_id`, `patient.demo: true`, and a result where `synthetic: true` and `model_mode: "DEMO"`. Unknown fields are rejected by schema validation. Duplicate IDs are reported as duplicates rather than inserted again. Client FHIR bundles are discarded and regenerated server-side. The response reports `accepted`, `duplicate`, `synced_ids`, and server time.

## Counselling

`POST /api/counselling`

```json
{
  "screening_type": "neonatal_jaundice",
  "estimate": 18.0,
  "unit": "mg/dL",
  "risk_category": "DEMO_ESCALATE",
  "confidence": 0.76,
  "quality_score": 0.88,
  "language": "hi",
  "infant_age_hours": 42
}
```

Allowed language codes: `en`, `hi`, `bho`. The optional Gemini adapter uses a server environment key only, sends no image or patient identifier, requests structured JSON, validates the result, rejects unsafe text, and falls back to local deterministic copy on error. A Gemini response is not a clinician and cannot establish diagnosis, triage, thresholds, or treatment. The neonatal fallback explicitly avoids a treatment threshold because age in hours, gestational age, and clinical condition matter.

## FHIR demonstration export

`POST /api/fhir` accepts a pseudonymous `patient_id`, `patient.demo: true`, a `screening_id`, and a synthetic `ScreeningResult`; local-only profiles and identifying patient fields are rejected. It returns a `Bundle` containing Patient, Encounter, Observation, and DiagnosticReport resources. Observation and report status are `preliminary`; resources include prototype/synthetic tags and a clear note. This is a demonstration mapping, not a validated interoperability implementation or an assertion of clinical measurement provenance.

## Referral PDF

`POST /api/referrals` accepts a `ReferralRequest`, saves the pseudonymous screening if needed, and returns a PDF URL. Only explicitly synthetic demo profiles with a `DEMO` fixture result are allowed. The PDF includes patient ID (not patient name), model mode, demo tag, recommended next step, and safety wording. When the API is offline, the web app can still use its local print view and the browser's “Save as PDF” function.

## Errors

- `422` — invalid payload, unsupported fixture, non-synthetic result, identifying fields in FHIR request, or invalid pseudonymous ID.
- `404` — unknown screening/referral ID.
- `500` — unexpected server/PDF error. No API key or raw image is returned in the response.

## Database and operation

SQLite location defaults to `backend/data/abhaynayan.sqlite3`; override with `ABHAYNAYAN_DB_PATH`. Use a private persistent volume and a managed secret store for real deployments. No authentication, authorization, audit-grade retention, clinical governance, or production security review is provided in this prototype.
