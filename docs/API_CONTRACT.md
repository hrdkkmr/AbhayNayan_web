# AbhayNayan API contract

Contract version: `1.0.0` · Applies to: FastAPI backend in this repository, the PWA in `web-dashboard/`, and the Android app (`shubhamcore/AbhayNayan_apk`).

The machine-readable schema is served at `/openapi.json` (interactive at `/docs`). The Pydantic models in [`backend/app/models/schemas.py`](../backend/app/models/schemas.py) are the source of truth. If this document and the code disagree, the code wins; please report the mismatch. Examples below were captured from the running API.

> **Safety boundary.** No endpoint returns a validated hemoglobin or bilirubin measurement. Every value is either a fixed `DEMO_SYNTHETIC` fixture or, only when an operator enables it, an `EXPERIMENTAL_RESEARCH_ONLY` research output. Clients must show the provenance label next to every value.

## 1. Versioning

- Every `/api/*` response has the header `X-AbhayNayan-Contract-Version: 1.0.0`. `GET /api/health` also returns `api_contract_version`.
- **MINOR** (`1.x.0`): additive only. New optional request fields, new response fields, new enum values in *response-only* fields, or new endpoints. Clients must ignore unknown response fields.
- **MAJOR** (`2.0.0`): removing or renaming fields, tightening validation, changing types or semantics, or adding enum values that clients must send. A major change ships with a migration note in this file and in [ANDROID_INTEGRATION.md](ANDROID_INTEGRATION.md), and is announced to the Android developer before merge.
- Request models reject unknown fields (`extra = forbid`). A client must not send a field before the server version that accepts it is deployed. Check `api_contract_version` from `/api/health`.

### Changes in 1.0.0 (from the unversioned 0.1 prototype)

| Change | Compatibility |
|---|---|
| Every error now uses the envelope in §3. `detail` is always a string | Old clients reading `detail` keep working; validation errors no longer return a list |
| `result.confidence` and `result.quality_score` are nullable; demo fixtures return `null` | Clients must handle `null`. Old values (0.82 etc.) were placeholders, not measurements |
| New `result.provenance`, `result.model_version`, `result.limitations` | Optional on input (default `DEMO_SYNTHETIC`) |
| `/api/sync` validates each record independently and returns `results[]`, `conflict`, `rejected` | Behaviour change: one bad record no longer fails the batch with 422 |
| A re-used `id` with different content returns `409 ID_CONFLICT` (create) or `conflict` (sync), not a silent duplicate | Behaviour change |
| Neonatal demo tag `REQUIRES_REVIEW` renamed `DEMO_REVIEW` | Old tag still accepted (free string) |
| Server-generated IDs use the prefix `srv-`; records carry `id_origin` | Additive |
| New optional `context`, `inference_mode`, `features`, `request_id`, `counselling_mode`, `reason` | Additive |
| New `GET /api/admin/usage` | Additive |
| `GEMINI_MODEL` has no default; Gemini stays off until an operator sets it | Server configuration only |

## 2. Shared types

| Type | Values / rule |
|---|---|
| `screening_type` | `maternal_anemia` · `neonatal_jaundice` |
| `unit` | `g/dL` for `maternal_anemia`; `mg/dL` for `neonatal_jaundice` (enforced) |
| `provenance` | `DEMO_SYNTHETIC` · `EXPERIMENTAL_RESEARCH_ONLY` · `VALIDATED_FOR_INTENDED_USE` (nothing produces the last one today) |
| Model status | `VALIDATED_FOR_INTENDED_USE` · `EXPERIMENTAL_RESEARCH_ONLY` · `DISABLED_NO_VALID_MODEL` · `DEMO_SYNTHETIC` |
| `model_mode` | `DEMO` for fixtures, `EXPERIMENTAL` for research output. Rule: `synthetic == (provenance == DEMO_SYNTHETIC) == (model_mode == DEMO)` |
| `language` | `en` · `hi` · `bho` |
| IDs (`id`, referral `id`, `request_id`) | `^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$`. `request_id` is 8–96 chars |
| `patient.patient_id` | `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`. Pseudonymous only: never a name, phone number, or Aadhaar/ABHA number |
| Timestamps | ISO-8601 with timezone. The server emits UTC (`Z`) |
| `context.infant_age_hours` | integer 0–8760, hours since birth |
| `context.gestational_week` | integer 1–45 |
| `confidence`, `quality_score` | `null` or 0–1. `null` means *not produced*; never substitute a number |

### `ScreeningResult`

```json
{
  "screening_type": "neonatal_jaundice",
  "estimate": 12.8,
  "unit": "mg/dL",
  "risk_category": "DEMO_REVIEW",
  "confidence": null,
  "quality_score": null,
  "requires_confirmation": true,
  "model_mode": "DEMO",
  "synthetic": true,
  "provenance": "DEMO_SYNTHETIC",
  "model_version": "fixed-demo-fixtures-v1",
  "case_id": "jaundice-review",
  "case_label": "Review case (synthetic)",
  "generated_at": "2026-10-10T08:12:13.593243Z",
  "limitations": ["Fixed demonstration value; not computed from any image, feature, or person."],
  "safety_note": "Synthetic demonstration estimate only. Not a diagnosis or validated clinical measurement. Confirm with appropriate clinical testing and local protocol."
}
```

Required on input: `screening_type`, `estimate` (finite), `unit`, `risk_category` (≤48 chars). All other fields have the defaults shown in `schemas.py`. `risk_category` is a **prototype tag**, not a clinical category. Demo tags always start with `DEMO_`.

### `ScreeningRecord`

```json
{
  "id": "scr-7f3c2a9e-demo",
  "patient": { "patient_id": "ABH-2026-0001", "demo": true },
  "result": { "...": "ScreeningResult" },
  "context": { "infant_age_hours": 36, "gestational_week": null, "pregnancy": null },
  "worker_id": "demo-worker",
  "phc": "Demo PHC",
  "village": null,
  "created_at": "2026-10-10T08:12:13.593243Z",
  "id_origin": "client",
  "sync_status": "synced",
  "fhir_bundle": { "resourceType": "Bundle", "...": "server-generated" }
}
```

`sync_status` on the wire is only `queued` or `synced`. Clients keep the richer local status in §6. Clients must send `fhir_bundle: null`; the server always regenerates it.

## 3. Errors

Every non-2xx `/api` response:

```json
{
  "detail": "Invalid request: patient_id must be a pseudonymous alphanumeric ID, not a name or phone number",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request: patient_id must be a pseudonymous alphanumeric ID, not a name or phone number",
    "status": 422,
    "retryable": false,
    "fields": [{ "loc": ["body", "patient", "patient_id"], "message": "patient_id must be ...", "type": "value_error" }]
  },
  "api_contract_version": "1.0.0"
}
```

Branch on `error.code`, not on message text. Submitted values are never echoed. Messages never include file paths, stack traces, or keys.

| HTTP | `error.code` | Meaning | Client action |
|---|---|---|---|
| 401 | `UNAUTHORIZED` | Missing/invalid admin token | Re-enter token |
| 403 | `ADMIN_DISABLED` | Usage report not enabled on server | None |
| 404 | `NOT_FOUND` | Unknown screening/referral/path | None |
| 409 | `ID_CONFLICT` | Same `id`, different content already stored | Generate a new id; keep local copy; flag `conflict` |
| 422 | `VALIDATION_ERROR` | Schema violation (`fields` lists paths) | Fix input; do not retry unchanged |
| 422 | `UNKNOWN_DEMO_CASE` | `case_id` not valid for `screening_type` | Use `/api/demo/cases` |
| 422 | `DEMO_FIXTURE_REQUIRES_DEMO_PROFILE` | Fixture requested for `patient.demo=false` | Never attach fixtures to real profiles |
| 422 | `EXPERIMENTAL_REQUIRES_RESEARCH_PROFILE` | Research output requested for a real profile | Not allowed |
| 422 | `INVALID_INPUT` / `UNSUPPORTED_INPUT` | Model input missing, malformed, or of an unsupported source | Do not retry unchanged |
| 422 | `CLIENT_RESULT_NOT_ACCEPTED` / `REFERRAL_RESULT_NOT_ACCEPTED` | Client claimed a non-demo result the server did not produce | Not allowed |
| 422 | `IDENTIFYING_FIELDS_REJECTED`, `DEMO_PROFILE_REQUIRED` | `/api/fhir` guards | Export locally instead |
| 500 | `INTERNAL_ERROR`, `PDF_GENERATION_FAILED` | Server fault (`retryable: true`) | Retry with backoff |
| 503 | `MODEL_DISABLED` | Requested adapter is not enabled (`retryable: false`) | Show "no validated model"; never fall back to a fixture silently |

Transport failures (no response, timeout) are always retryable.

## 4. Endpoints

Data class: **demo** = synthetic fixtures only; **experimental** = research output when enabled; **ops** = operational metadata. No endpoint accepts real clinical data in this prototype.

| Method · Path | Purpose | Auth | Data class | Idempotency |
|---|---|---|---|---|
| `GET /api/health` | Status, contract version, Gemini configured flags (never the key) | none | ops | safe |
| `GET /api/model/status` | Adapter model cards, candidate-model inventory, research metrics | none | ops | safe |
| `GET /api/demo/cases` | Fixture catalogue | none | demo | safe |
| `GET /api/pipeline`, `GET /api/vision/capabilities` | Capability flags (no image upload exists) | none | ops | safe |
| `POST /api/screenings` | Create a screening (DEMO fixture or MODEL adapter) | none | demo / experimental | client `id` |
| `GET /api/screenings?limit=1..500` · `GET /api/screenings/{id}` | Read stored records | none | demo / experimental | safe |
| `POST /api/sync` | Upload ≤100 queued demo records | none | demo | per-record `id` |
| `GET /api/dashboard` · `GET /api/patients` | Aggregates (pseudonymous IDs only) | none | demo | safe |
| `POST /api/counselling` | Counselling copy (deterministic, optional Gemini wording) | none | demo / experimental | `request_id` |
| `POST /api/fhir` | FHIR R4-style bundle for a demo result | none | demo | pure function |
| `GET /api/referrals` · `POST /api/referrals` · `GET /api/referrals/{id}/pdf` | Referral briefs | none | demo / experimental | referral `id` |
| `GET /api/admin/usage?since&until` | Gemini usage report | `Authorization: Bearer <ABHAYNAYAN_ADMIN_TOKEN>` | ops (aggregate) | safe |

**Authentication.** Apart from the admin report, the prototype has **no authentication or authorization**. Do not expose it to the public internet or use it for real patients. A production deployment needs per-worker authentication, role-based access and an audit trail. That is a MAJOR contract change.

### 4.1 `POST /api/screenings`

DEMO request:

```json
{
  "id": "scr-7f3c2a9e-demo",
  "patient": { "patient_id": "ABH-2026-0001", "demo": true },
  "screening_type": "neonatal_jaundice",
  "inference_mode": "DEMO",
  "case_id": "jaundice-review",
  "context": { "infant_age_hours": 36 },
  "worker_id": "demo-worker",
  "phc": "Demo PHC"
}
```

- `inference_mode`: `DEMO` (default) requires `case_id` and forbids `features`. `MODEL` routes to the adapter for the `screening_type`.
- `features` (MODEL only, maternal anemia research baseline): `{ "red_pct", "green_pct", "blue_pct", "feature_source" }`. Percentages are 0–100 and must sum to 100 ±0.5. `feature_source` must be `research_dataset_precomputed`; `camera_pipeline` is rejected with `UNSUPPORTED_INPUT` because app camera features are not equivalent to the training features.
- There is **no image field**. Images never leave the device.
- Response: `ScreeningRecord` (example in §2). With no `id`, the server assigns `srv-<16 hex>` and `id_origin: "server"`.
- Idempotency: repeating the same `id` with the same content returns the stored record unchanged. The same `id` with different content returns `409 ID_CONFLICT`.
- With the current deployment, `MODEL` mode returns:

```json
{ "detail": "DISABLED_NO_VALID_MODEL: No validated anemia model. The research baseline is disabled by default.",
  "error": { "code": "MODEL_DISABLED", "message": "...", "status": 503, "retryable": false, "fields": [] },
  "api_contract_version": "1.0.0" }
```

### 4.2 `POST /api/sync`

Request: `{ "records": [ScreeningRecord, ...] }`, at most 100. More than 100 returns a request-level 422. Each record is validated on its own:

```json
{
  "accepted": 0, "duplicate": 1, "conflict": 1, "rejected": 1,
  "synced_ids": ["scr-7f3c2a9e-demo"],
  "results": [
    { "id": "scr-7f3c2a9e-demo", "status": "duplicate", "error": null },
    { "id": "scr-7f3c2a9e-demo", "status": "conflict", "error": { "code": "ID_CONFLICT", "status": 409, "retryable": false, "message": "...", "fields": [] } },
    { "id": "scr-bad", "status": "rejected", "error": { "code": "VALIDATION_ERROR", "status": 422, "message": "Invalid record: Field required", "fields": [{ "loc": ["patient"], "message": "Field required", "type": "missing" }] } }
  ],
  "server_time": "2026-10-10T08:12:13.633846Z",
  "api_contract_version": "1.0.0",
  "note": "Demo sync only; use de-identified records."
}
```

| `status` | Meaning | Client action |
|---|---|---|
| `accepted` | Stored now | Remove from outbox; mark `synced` |
| `duplicate` | Identical record already stored (a safe retry) | Remove from outbox; mark `synced` |
| `conflict` | Different record already uses this id; **server copy kept** (first write wins) | Remove from outbox; mark `conflict`; keep local copy; never auto-overwrite |
| `rejected` | Fails validation or is not a client-creatable record | Remove from outbox; mark `rejected`; keep local copy |

Only `DEMO_SYNTHETIC` records with `patient.demo = true` can be created through sync. A non-demo record is accepted as `duplicate` only if the server already holds that exact server-produced result. "Identical" compares patient_id, screening_type, estimate, unit, case_id, provenance and model_version.

### 4.3 `POST /api/counselling`

```json
{
  "screening_type": "neonatal_jaundice", "estimate": 12.8, "unit": "mg/dL",
  "risk_category": "DEMO_REVIEW", "confidence": null, "quality_score": null,
  "provenance": "DEMO_SYNTHETIC", "language": "en",
  "pregnancy": null, "gestational_week": null, "infant_age_hours": 36,
  "request_id": "cns-scr-7f3c2a9e-demo-en"
}
```

Response (this one came from a server without a key):

```json
{
  "summary": "This is a synthetic prototype estimate, not a serum bilirubin result or diagnosis.",
  "risk_explanation": "Newborn review depends on age in hours, gestational age, symptoms, and local protocol. This demo does not calculate a treatment threshold.",
  "counselling_script": "Please arrange prompt review by a qualified clinician and confirm with the appropriate test. ...",
  "recommended_next_step": "Seek clinician review and confirm with appropriate bilirubin testing under local newborn-care protocol.",
  "referral_required": true,
  "urgency": "DEMO_ONLY",
  "language": "en",
  "safety_note": "Do not use this demo value to delay care or decide treatment.",
  "mode": "LOCAL_FALLBACK",
  "fallback_reason": "NO_API_KEY",
  "model_id": null,
  "protocol_id": "ABN-INTERIM-CONFIRM-v1",
  "generated_at": "2026-10-10T08:12:13.646932Z"
}
```

- `urgency`, `referral_required`, `recommended_next_step` and `safety_note` **always** come from the reviewed deterministic copy (`backend/app/services/language.py`). Gemini may only reword `summary`, `risk_explanation` and `counselling_script`.
- `mode`: `GEMINI` (AI wording accepted) or `LOCAL_FALLBACK`. Possible `fallback_reason` values: `NO_API_KEY`, `MODEL_NOT_CONFIGURED`, `MODEL_UNAVAILABLE`, `MODEL_UNSUPPORTED`, `INVALID_REQUEST_OR_MODEL`, `AUTH_ERROR`, `RATE_LIMITED`, `QUOTA_EXHAUSTED`, `TIMEOUT`, `NETWORK_ERROR`, `PROVIDER_ERROR`, `MALFORMED_RESPONSE`, `MALFORMED_OUTPUT`, `BLOCKED_BY_PROVIDER`, `INCOMPLETE_OUTPUT`, `LANGUAGE_MISMATCH`, `UNSAFE_OR_INCOMPLETE_OUTPUT`. This endpoint never returns an error for provider problems.
- `request_id`: a retry with the same key within 15 minutes returns the first response without a new provider call. Recommended form: `cns-<screening id>-<language>`.
- Clients should ship the same deterministic copy offline. The Android app already has English/Hindi/Bhojpuri strings.

### 4.4 Referrals

`POST /api/referrals`:

```json
{
  "id": "ref-0001",
  "screening": { "...": "ScreeningRecord" },
  "worker_name": "Demo ASHA Worker",
  "language": "en",
  "counselling": "Please arrange prompt review ...",
  "counselling_mode": "LOCAL_FALLBACK",
  "next_step": "Seek clinician review ...",
  "reason": "SCREENING_CONFIRMATION"
}
```

`reason` ∈ `SCREENING_CONFIRMATION`, `WORKER_CONCERN`, `CAREGIVER_REQUEST`. Response:

```json
{ "id": "ref-0001", "screening_id": "scr-7f3c2a9e-demo", "created": true, "pdf_url": "/api/referrals/ref-0001/pdf",
  "provenance": "DEMO_SYNTHETIC", "note": "Prototype referral brief; not a diagnosis." }
```

Repeating an `id` returns `created: false` (idempotent). The PDF shows: patient ID (never name), screening type, result provenance, mode and model version, result timestamp, newborn age or gestational week when present, confidence and quality (or "Not available"), referral reason, counselling source, brief timestamp, and the safety notice.

### 4.5 `GET /api/dashboard`

```json
{ "total_screenings": 1, "referrals": 1, "pending_sync": null, "today_screenings": 1,
  "by_provenance": { "DEMO_SYNTHETIC": 1 }, "by_type": { "neonatal_jaundice": 1 }, "records": [], "mode": "DEMO" }
```

`pending_sync` is always `null`: the server cannot see device outboxes. Each client reports its own queue.

### 4.6 `GET /api/model/status`

Returns `adapters.{maternal_anemia,neonatal_jaundice}`, each with `adapter_id`, `target`, `unit`, `status`, `model_version`, `reason`, `inference_location` (`none` · `server` · `device`), `limitations[]` and `evaluation{}`. It also returns `candidate_models[]` (every model inspected, with status) and `research_baseline`. Clients should read adapter `status` before offering a MODEL action, and show the `reason` when it is not enabled.

### 4.7 `GET /api/admin/usage`

See [TOKEN_USAGE.md](TOKEN_USAGE.md). Returns `403 ADMIN_DISABLED` unless `ABHAYNAYAN_ADMIN_TOKEN` (16+ characters) is set, and `401` without a matching bearer token. `since`/`until` must be ISO-8601.

## 5. FHIR

`POST /api/fhir` and every stored `fhir_bundle` return a `Bundle` (`type: collection`) of Patient, Encounter, Observation and DiagnosticReport. Observation and DiagnosticReport have `status: preliminary`. Rules:

- `Observation.code` is **text only**. No LOINC laboratory code is used, because the value is not a laboratory measurement.
- Synthetic and experimental resources carry `meta.security` = `http://terminology.hl7.org/CodeSystem/v3-ActReason|HTEST` (test health data), plus a `urn:abhaynayan:provenance` tag.
- The prototype tag sits in `Observation.note`, not `interpretation`. No confidence/quality components are emitted.
- `valueQuantity` uses UCUM `g/dL` or `mg/dL`.
- The bundle is not validated against any FHIR profile. It is **not** ABDM/NDHM-conformant and must not be submitted to a health information exchange.

## 6. Offline and retry rules (web and Android)

Local status values, shared by both clients:

| Local `sync_status` | Meaning | In outbox? |
|---|---|---|
| `queued` | Saved locally, not yet acknowledged (may carry `last_sync_error`, `sync_attempts`) | yes |
| `synced` | Server acknowledged as `accepted` or `duplicate` | no |
| `failed` | Reserved for clients that need it; the PWA keeps transport failures as `queued` + `last_sync_error` | yes |
| `rejected` | Server will never accept it; local copy kept | no |
| `conflict` | Server holds a different record with this id; local copy kept | no |

1. Generate the record `id` on the device once (`scr-<uuid v4>`) and reuse it for every retry, create or sync.
2. Write locally first, then enqueue. Never delete a local record because a request failed.
3. Remove an outbox item only on `accepted`, `duplicate`, `rejected` or `conflict` for that exact id.
4. On transport errors, HTTP 5xx or `retryable: true`, keep the item queued, increment `sync_attempts`, and retry with backoff. The PWA retries when the user presses Sync; Android should use WorkManager with exponential backoff.
5. Never run two sync loops at once.
6. Strip local-only fields before upload: names, capture audit, sync metadata, local FHIR. Send `fhir_bundle: null`.
7. Synthetic demo records must stay visibly labelled everywhere they appear: lists, PDFs, exports.
