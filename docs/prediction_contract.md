# Prediction contract (`abhaynayan.prediction/2.0.0`)

Status: **Design (Phase 3, 24 October 2026). Not implemented.** Implementation: backend in Phase 7, Android in Phases 6–7. Related: [record_contract.md](record_contract.md), [capture_protocols.md](capture_protocols.md), [security_and_permissions.md](security_and_permissions.md), [model_audit.md](model_audit.md).

This contract defines one result envelope that every screening module returns, whether it runs on the phone or on the server. It does not make models interchangeable. Each envelope names exactly one task, one input modality and one model, and readers must check those fields before using a value.

## 1. Why a new major version

Contract 1.x (`backend/app/models/schemas.py`, `API_CONTRACT_VERSION = '1.1.0'`) cannot express the outcomes the audit requires:

| 1.x limitation | Evidence | 2.0 change |
|---|---|---|
| `ScreeningResult.estimate` is a required `float` and `extra='forbid'` | `schemas.py` | `estimate` is `null` unless `status` is `estimated` or `synthetic_fixture` |
| Failure exists only as an HTTP error body; nothing is saved | `main.py::_run_image_model` | Outcomes are envelopes, so they can be saved and synced |
| OOD and research warnings are free-text lists or transient UI state | audit M3 | Structured, append-only `warnings[]` that is persisted |
| `screening_type` names a clinical workflow (`maternal_anemia`), not the model's task or input | `schemas.py` | `screening_type` names the task; `workflow` keeps the clinical context |
| Quality and suitability are mixed up (all 54 app-style crops "passed") | audit §5.1 | `input_quality` and `input_compatibility` are separate blocks |

Contract 1.x endpoints stay in place, unchanged, until both clients have migrated (§10).

## 2. Envelope fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema` | const `"abhaynayan.prediction/2.0.0"` | yes | Envelope schema version. Readers dispatch on it |
| `result_id` | string `prd-<uuid4>` | yes | Stable identity of this outcome; generated once, where inference ran |
| `trace_id` | string, uuid4 | yes | Random correlation ID. **Never derived from a patient, record, device or image** |
| `status` | enum §3 | yes | |
| `reason_code` | enum §4, or `null` | iff status ∉ {`estimated`, `synthetic_fixture`} | Stable, machine-readable cause |
| `screening_type` | enum §5 | yes | The model task, e.g. `hemoglobin_from_palpebral_conjunctiva` |
| `workflow` | `maternal_anemia` \| `neonatal_jaundice` | yes | Clinical workflow that requested it (the 1.x `screening_type`) |
| `input` | object §6 | yes | What was actually supplied: modality, body site, source, protocol, orientation handling |
| `input_quality` | object §7 | yes | Photographic checks only (blur, exposure, glare…). Says nothing about suitability |
| `input_compatibility` | object §7 | yes | Whether this input is inside the model's supported domain (modality, region, distribution, population) |
| `estimate` | object or `null` | see §8 | `value`, `unit`, `display_precision`, `uncertainty` |
| `model` | object or `null` | when a model was selected | `model_id`, `model_version`, `artifact_sha256`, `feature_contract`, `runtime`, `model_status`, `model_card_ref` |
| `inference_source` | `edge` \| `backend` \| `fixture` \| `none` | yes | Where the outcome was produced. `none` = no model was run |
| `warnings` | array §9 | yes (may be empty) | Persistent, append-only |
| `created_at` | RFC 3339 UTC | yes | When the outcome was produced (device clock for edge, flagged if implausible) |
| `producer` | object | yes | `component`, `software_version`, `platform`, `contract_version` |

Deliberately **not** in the envelope: patient name, phone, location, the image, image hashes, free-text notes, LLM text. Subject linkage lives in the record ([record_contract.md](record_contract.md)), not in the prediction.

## 3. `status`

| Value | Meaning | `estimate` | `reason_code` |
|---|---|---|---|
| `estimated` | A model ran on a compatible, quality-passing input and produced a plausible output | required | `null` |
| `unable_to_estimate` | The system worked correctly and **declined**: bad, unsupported or out-of-domain input, missing/disabled/incompatible model, unsupported population, or insufficient evidence for this use | **must be `null`** | required |
| `error` | Unexpected failure: runtime exception, non-finite output, timeout, internal fault | **must be `null`** | required |
| `synthetic_fixture` | A fixed demonstration value, not inference. Allowed only for a server-created synthetic test subject under the `synthetic_test` permission ([security_and_permissions.md §6](security_and_permissions.md)) | required (fixture value) | `null` |

A fourth status is added beyond the three requested because a fixture is not an estimate. Labelling it `estimated` would repeat the confusion this project has worked to avoid. The current code already keeps fixtures separate (`DEMO_SYNTHETIC`).

There is no "low-confidence estimate" status. If the evidence is not good enough for a value, the status is `unable_to_estimate`.

## 4. `reason_code`

Grouped so that the seven distinctions the brief requires stay separate. Codes are stable: they may be added but never renamed or reused.

| Category | Code | Status | Recapture helps? | Source in today's code |
|---|---|---|---|---|
| Invalid input | `INPUT_EMPTY` | unable | yes | `EMPTY_IMAGE` |
| | `INPUT_DECODE_FAILED` | unable | yes | `CORRUPT_IMAGE` |
| | `INPUT_FORMAT_UNSUPPORTED` | unable | yes | `UNSUPPORTED_MEDIA_TYPE` |
| | `INPUT_TOO_SMALL` / `INPUT_TOO_LARGE` | unable | yes | `IMAGE_TOO_SMALL` / `IMAGE_TOO_LARGE` |
| Unsupported modality | `MODALITY_UNSUPPORTED` | unable | only with the right protocol | new. E.g. a sclera image sent to a skin-trained task (audit M1) |
| | `MODALITY_UNVERIFIED` | unable | yes | new: the body-site check could not confirm the target (H1) |
| Quality failure | `QUALITY_FAILED` | unable | yes | `IMAGE_QUALITY_REJECTED`; details in `input_quality.checks` |
| | `CAPTURE_RETRY_LIMIT` | unable | no (stop and refer) | new ([capture_protocols.md](capture_protocols.md)) |
| Out of domain | `INPUT_OUT_OF_DISTRIBUTION` | unable | sometimes | today only a warning (H2). **Becomes blocking** |
| | `TARGET_REGION_INCOMPATIBLE` | unable | no | new: e.g. a whole-eye rectangle where the model needs a segmented conjunctiva (H3) |
| Unsupported population | `POPULATION_UNSUPPORTED` | unable | no | new: e.g. pregnancy, age outside the model card |
| | `CONTEXT_MISSING` | unable | after entering data | `Age in hours is required` |
| Missing model | `MODEL_MISSING` | unable | no | `MODEL_UNAVAILABLE`, absent asset |
| | `MODEL_DISABLED` | unable | no | flag/toggle off |
| | `RUNTIME_UNAVAILABLE` | unable | no | `RUNTIME_UNAVAILABLE` (ONNX) |
| Incompatible model | `MODEL_INCOMPATIBLE` | unable | no | wrong feature contract, shape, type |
| | `MODEL_INTEGRITY_FAILED` | unable | no | SHA-256 mismatch, missing pin (M4) |
| | `MODEL_REVOKED` | unable | no | new: registry tombstone |
| Insufficient evidence | `NOT_APPROVED_FOR_INTENDED_USE` | unable | no | research model requested outside an authorized research context (replaces the checkbox, M5) |
| | `NO_VALIDATED_MODEL_FOR_TASK` | unable | no | `DISABLED_NO_VALID_MODEL`; bilirubin today |
| Output rejected | `OUTPUT_IMPLAUSIBLE` | unable | no | `OUTPUT_OUT_OF_RANGE` (2–25 g/dL; discard, never clamp) |
| System error | `INFERENCE_RUNTIME_ERROR` | error | retry | `INFERENCE_FAILED` |
| | `OUTPUT_NON_FINITE` | error | retry | non-finite output |
| | `TIMEOUT` / `INTERNAL_ERROR` | error | retry | |

**Implementation note (Phase 5):** both pipelines evaluate body-site *verification* inside the compatibility block, after quality and the distribution check, so a refused envelope still reports the quality and range results. The reason code is still `MODALITY_UNVERIFIED`. No verifier is installed anywhere, so no app capture or server upload is ever `estimated` today.

**Persisting failed attempts (Q9, Phase 6, Android):**
- **Before analysis starts** (capture rejected, retry limit, camera or permission problem, cancellation): no analysis outcome is created. The existing `CAPTURE_RETRY_LIMIT` record remains the one explicit no-photo record.
- **After analysis starts, then fails:** the app saves a record with the status this table assigns. That is `error` for `INFERENCE_RUNTIME_ERROR`, `OUTPUT_NON_FINITE`, `TIMEOUT` and `INTERNAL_ERROR`, and `unable_to_estimate` for `OUTPUT_IMPLAUSIBLE` and `MODEL_INTEGRITY_FAILED`.
  - The record never has an estimate.
  - It is never copied from an earlier result.
  - It is never relabelled to another status.
  - It keeps the capture's provenance.
- **Storage:** the record is saved atomically. If saving fails, the screen says nothing was recorded. If no contract-valid envelope can be built, nothing is saved.

**Evaluation order** (first failure wins, and nothing later runs): authorization → input validity → modality → quality → model availability and integrity → compatibility/population → evidence/approval → inference → output validation. A quality pass never skips the compatibility check.

## 5. `screening_type` (task) and the modules that exist

| `screening_type` | Workflow | Accepted `input.modality` / `body_site` | Unit | Models today |
|---|---|---|---|---|
| `hemoglobin_from_palpebral_conjunctiva` | `maternal_anemia` | `photo` / `palpebral_conjunctiva_segmented` | g/dL | `hb-ridge-cf` (edge), `hb-hgb-cf` (backend). Both research-only; licence gate not passed |
| `newborn_jaundice_dataset_class` | `neonatal_jaundice` | `photo` / `newborn_skin_whole_view` (NJN framing; [capture_protocols.md §3.3](capture_protocols.md)) | none (score 0–1) | `njn-logreg-cf` (edge), `njn-mnv3-logreg` (backend). Research-only. **Not bilirubin** |
| `bilirubin_from_skin` | `neonatal_jaundice` | `photo` / `newborn_skin_forehead` or `newborn_skin_sternum` | mg/dL | **none; blocked, no labels**. Always `NO_VALIDATED_MODEL_FOR_TASK` |

A task never borrows another task's model, and the jaundice-class score never fills `bilirubin_from_skin` (already enforced in `EdgeModelsTest`).

## 6. `input`

```text
input: {
  modality: "photo" | "document" | "synthetic_test_image",
  body_site: "palpebral_conjunctiva_segmented" | "palpebral_conjunctiva_guide_crop" | "sclera_guide_crop"
           | "newborn_skin_whole_view" | "newborn_skin_forehead" | "newborn_skin_sternum" | "unknown",
  body_site_verification: { method: "protocol_declared" | "user_confirmed" | "detector:<id>@<ver>", status: "verified" | "unverified" | "failed" },
  source: "camera" | "gallery" | "upload" | "synthetic",
  capture_protocol: { id, version } | null,
  orientation: { exif_tag: int | null, applied: "exif_transpose" | "sensor_rotation" | "none_needed" | "unknown" },
  width, height, valid_pixel_count
}
```

`body_site` records **what the input actually is**, not what was hoped for. Today's Android camera path produces `palpebral_conjunctiva_guide_crop` or `sclera_guide_crop`. Neither is accepted by any existing model, so the result is `TARGET_REGION_INCOMPATIBLE` / `MODALITY_UNSUPPORTED` until Phase 5 provides a compatible path. `protocol_declared` / `user_confirmed` alone never counts as `verified` for modalities where the audit showed the risk (H1).

## 7. `input_quality` vs `input_compatibility`

Both have the form `{status, rules_version, checks: [{check_id, measured, threshold, comparator, passed}]}`.

- `input_quality.status`: `passed` | `failed` | `not_assessed`. Photographic properties only: valid pixels, exposure, clipping/glare, sharpness, motion.
- `input_compatibility.status`: `compatible` | `incompatible` | `not_assessed`. Domain properties: body-site verification, required segmentation, feature ranges vs `model.training.feature_min/max` (cf-v1 OOD check), population constraints.

Rules:

1. `estimated` requires `input_quality.status == "passed"` **and** `input_compatibility.status == "compatible"`.
2. A quality pass is never reported as evidence that the image suits the model. The 54/54 app-style crops that passed quality were incompatible ([model_audit.md §5.1](model_audit.md)).
3. Every threshold carries `rules_version`. Thresholds are engineering heuristics until calibrated ([capture_protocols.md §4](capture_protocols.md)).
4. **Any** out-of-range feature → `incompatible` → `INPUT_OUT_OF_DISTRIBUTION` (margin from the model card, today 10 % of the training range). This replaces today's "show the value with a note".

## 8. `estimate`

```text
estimate: { value: number, unit: "g/dL" | "mg/dL" | "score", display_precision: int,
            uncertainty: { kind: "none" | "prediction_interval" | "calibrated_probability", ... } }
```

- Present only for `estimated` and `synthetic_fixture`. Validators reject `value` on any other status, and reject non-finite numbers.
- The unit must equal the task's unit (§5). There is no implicit conversion; g/L or µmol/L inputs belong to lab ingestion ([record_contract.md §4](record_contract.md)).
- `uncertainty.kind = "none"` is honest and allowed. A classifier score is **not** clinical accuracy or a probability of disease. `calibrated_probability` may be used only if the model card documents calibration on held-out data, and even then it describes the dataset label, not a diagnosis.
- `display_precision` is fixed per task (Hb 1 decimal; score 2 decimals) so reports cannot imply false precision.

## 9. `warnings[]`

```text
{ code, severity: "info" | "caution" | "blocking", origin: { source: "edge" | "backend" | "server_annotation",
  component, software_version }, created_at, params: { …non-identifying… } }
```

| Code | Severity | When |
|---|---|---|
| `RESEARCH_ONLY_NOT_VALIDATED` | caution | every `estimated` result with `model_status = research_only` |
| `SYNTHETIC_FIXTURE_NOT_A_MEASUREMENT` | caution | every `synthetic_fixture` |
| `INPUT_OUT_OF_DISTRIBUTION` | blocking | with that reason code; `params.features` lists up to 10 feature names |
| `ORIENTATION_UNKNOWN` | caution | upload without a usable orientation tag where the model is not rotation-invariant |
| `DEVICE_CLOCK_SUSPECT` | info | edge `created_at` > 5 min in the future, or earlier than the app build date |
| `MODEL_REVOKED_AFTER_RESULT` | caution | added later as a server annotation; the original envelope is unchanged |
| `LEGACY_WARNINGS_NOT_RECORDED` | caution | migrated 1.x/Room v2 records, which never stored OOD state (§10) |
| `UNKNOWN_WARNING_CODE` | caution | display-only fallback when a reader meets a newer code |

Rules: warnings are **append-only**. Nothing deletes or edits one, including sync, migration, export, LLM processing and app updates. A reader that does not recognise a code still shows it, as "Unrecognised warning: CODE", rather than dropping it. Messages are rendered from `code` + `params` through reviewed copy, so warning text is never free text stored in the envelope.

### Offline warning, later synced

1. The edge produces the envelope with `origin.source = "edge"` and stores it immutably in Room ([record_contract.md §3](record_contract.md)).
2. Sync sends the envelope byte-for-byte inside the record. The server re-validates the §11 invariants. If they fail, it **rejects** the record (it stays on the phone as `FAILED` with the server's code); it never repairs or strips it.
3. The server stores it verbatim. It may add warnings only as `server_annotation` entries in a separate annotation list linked by `result_id` (for example `MODEL_REVOKED_AFTER_RESULT`). The original envelope bytes and their SHA-256 are kept, so tampering is detectable.
4. If the app is updated before sync, the stored envelope keeps its original `schema`, `producer.software_version` and warnings. The new app version must send it as stored and must not re-run inference to "refresh" it.

## 10. Versioning and old records

- `schema` is stamped on every envelope. Readers keep a decoder for every published version. MINOR versions only add optional fields or enum values; MAJOR versions get a new `schema` value and a written migration.
- Migration **wraps** old data and never rewrites it. Mapping from today's data:

| Legacy | 2.0 envelope |
|---|---|
| 1.x `ScreeningResult`, `provenance = DEMO_SYNTHETIC` | `status = synthetic_fixture`, `inference_source = fixture`, `model_status = synthetic_fixture`, warning `SYNTHETIC_FIXTURE_NOT_A_MEASUREMENT` |
| Room v2 row, `resultMode = DISABLED_NO_VALID_MODEL`, `estimate = null` | `status = unable_to_estimate`, `reason_code = NO_VALIDATED_MODEL_FOR_TASK`, `inference_source = none` |
| Room v2 row, `resultMode = EXPERIMENTAL_RESEARCH_ONLY` with an estimate | `status = estimated`, `model_status = research_only`, warnings `RESEARCH_ONLY_NOT_VALIDATED` + `LEGACY_WARNINGS_NOT_RECORDED`; `input_compatibility.status = not_assessed` |
| `/api/ml/*` 1.1 response | not persisted today, so nothing to migrate |

- **Model no longer available:** the model registry keeps a permanent tombstone (id, version, SHA-256, model card, lifecycle history). An old result stays readable and keeps its value. If the model was revoked, the display adds the `MODEL_REVOKED_AFTER_RESULT` annotation. Nothing re-runs inference on old images, which are not retained.

## 11. Invariants enforced by validators (server and Android)

1. `status ∈ {unable_to_estimate, error}` ⇒ `estimate == null` ∧ `reason_code != null`.
2. `status == estimated` ⇒ `estimate != null` ∧ `model != null` ∧ `model.model_status ∈ {research_only, approved_for_intended_use}` ∧ `inference_source ∈ {edge, backend}` ∧ quality `passed` ∧ compatibility `compatible`.
3. `status == synthetic_fixture` ⇒ `inference_source == fixture` ∧ `model.model_status == synthetic_fixture`.
4. `model_status == research_only` ⇒ `warnings` contains `RESEARCH_ONLY_NOT_VALIDATED`.
5. `estimate.unit` equals the task unit; `value` is finite and inside the model card's plausible range.
6. `screening_type` and `input.body_site` must form a pair listed in §5; anything else ⇒ `MODALITY_UNSUPPORTED`.
7. Unknown enum value in `status`, `screening_type`, `model_status` or `inference_source` ⇒ reject (fail closed). Unknown `warnings[].code` ⇒ keep and display generically.
8. An LLM never produces or edits an envelope. Explanations are a separate object that references `result_id`. A validator rejects explanation text containing a number + unit that is absent from the envelope, or any value for a result whose status is not `estimated` / `synthetic_fixture` ([architecture.md §4.11](architecture.md)).

## 12. Model lifecycle

The envelope's `model.model_status` is the **release status** at inference time. The lifecycle **stage** lives in the model registry. Neither alone implies the other.

```text
proposed → data_licence_verified → trained → evaluated_held_out → integration_tested
        → research_only (release status)  → approved_for_intended_use (release status)
side states: suspended (temporarily blocked) · revoked (never runs again; tombstone kept) · retired (superseded; tombstone kept)
```

| Stage | Gate (evidence required, recorded in the registry) |
|---|---|
| `data_licence_verified` | Original publisher, licence text, consent scope and redistribution terms recorded ([DATA_PROVENANCE.md §6](DATA_PROVENANCE.md)). **No current dataset has passed this.** |
| `trained` | Training config, data manifest hash, seed, environment and code commit saved; patient-level split (or documented grouping when no IDs exist) **created before fitting** |
| `evaluated_held_out` | Selection recorded before a single test run (as `ml/runs/*/selection.json` does today); metrics with CIs; subgroup and external-site results; **evaluation in the app's own input format** (the step whose absence the audit exposed) |
| `integration_tested` | Model metadata + SHA-256 pin; input/output schema checks; golden-vector parity edge ↔ Python; all §11 invariants and the Phase 3 acceptance tests for the module pass |
| `research_only` | May run only for an authorized research operator in an approved study context ([security_and_permissions.md §5](security_and_permissions.md)). Not bundled in distributed builds while the data licence gate is open (audit M7) |
| `approved_for_intended_use` | Independent clinical validation in the intended population with the app's capture protocol, an approved intended-use statement, the regulatory position documented, and named sign-off. **A remote config change can never move a model here.** It needs a signed model release ([architecture.md §4.14](architecture.md)) |

Where today's models stand: `hb-*` and `njn-*` reached `trained` → `evaluated_held_out` **without** passing `data_licence_verified`, and they fail the app-input evaluation. They stay limited to developer machines with the research switches off by default. Bilirubin is `proposed` and blocked at data.

**Criteria for `unable_to_estimate`**: any §4 code. **Approval gate for patient-facing clinical estimates**: only `approved_for_intended_use` models, on compatible inputs, for subjects in the approved population, may produce an `estimated` result shown to a patient, caregiver or clinician outside a research context.

## 13. JSON examples

The examples are **schema illustrations, not real model results**. Example 1 describes a hypothetical model that does not exist. The others reuse real model IDs only to show their structure.

### 13.1 Hypothetical approved model, successful estimate

```json
{
  "schema": "abhaynayan.prediction/2.0.0",
  "result_id": "prd-0b7c2f0e-6a52-4c1e-9a77-3a9d1f2b8c41",
  "trace_id": "5f0d6c1e-2b8a-4f3e-9c7d-1a2b3c4d5e6f",
  "status": "estimated",
  "reason_code": null,
  "screening_type": "hemoglobin_from_palpebral_conjunctiva",
  "workflow": "maternal_anemia",
  "input": {
    "modality": "photo",
    "body_site": "palpebral_conjunctiva_segmented",
    "body_site_verification": {"method": "detector:hypothetical-conj-seg@1.0.0", "status": "verified"},
    "source": "camera",
    "capture_protocol": {"id": "anemia-palpebral", "version": "2.0.0"},
    "orientation": {"exif_tag": null, "applied": "sensor_rotation"},
    "width": 640, "height": 480, "valid_pixel_count": 5120
  },
  "input_quality": {"status": "passed", "rules_version": "quality-anemia-2.0.0", "checks": [
    {"check_id": "sharpness_laplacian_var", "measured": 41.2, "threshold": 2.0, "comparator": ">=", "passed": true}
  ]},
  "input_compatibility": {"status": "compatible", "rules_version": "compat-anemia-2.0.0", "checks": [
    {"check_id": "feature_range_cf_v1", "measured": 0, "threshold": 0, "comparator": "<=", "passed": true}
  ]},
  "estimate": {"value": 11.4, "unit": "g/dL", "display_precision": 1,
               "uncertainty": {"kind": "prediction_interval", "level": 0.9, "lower": 9.9, "upper": 12.9}},
  "model": {"model_id": "hypothetical-hb-approved", "model_version": "3.0.0",
            "artifact_sha256": {"model.json": "0000000000000000000000000000000000000000000000000000000000000000"},
            "feature_contract": "cf-v2", "runtime": "kotlin-linear-cf-v2",
            "model_status": "approved_for_intended_use", "model_card_ref": "docs/model_cards/hypothetical-hb-approved.md"},
  "inference_source": "edge",
  "warnings": [],
  "created_at": "2027-01-15T09:30:00Z",
  "producer": {"component": "android-app", "software_version": "1.0.0", "platform": "android-36", "contract_version": "2.0.0"}
}
```

### 13.2 `unable_to_estimate`: unsupported modality (sclera photo sent to the skin-trained jaundice-class task)

```json
{
  "schema": "abhaynayan.prediction/2.0.0",
  "result_id": "prd-2c1d9a4b-7e3f-4a6b-8c2d-9e0f1a2b3c4d",
  "trace_id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
  "status": "unable_to_estimate",
  "reason_code": "MODALITY_UNSUPPORTED",
  "screening_type": "newborn_jaundice_dataset_class",
  "workflow": "neonatal_jaundice",
  "input": {
    "modality": "photo", "body_site": "sclera_guide_crop",
    "body_site_verification": {"method": "protocol_declared", "status": "unverified"},
    "source": "camera", "capture_protocol": {"id": "legacy-sclera", "version": "1.0.0"},
    "orientation": {"exif_tag": null, "applied": "sensor_rotation"},
    "width": 461, "height": 154, "valid_pixel_count": 4410
  },
  "input_quality": {"status": "passed", "rules_version": "quality-legacy-1.0.0", "checks": []},
  "input_compatibility": {"status": "incompatible", "rules_version": "compat-njn-1.0.0", "checks": [
    {"check_id": "task_body_site_pair", "measured": "sclera_guide_crop", "threshold": "newborn_skin_whole_view", "comparator": "==", "passed": false}
  ]},
  "estimate": null,
  "model": {"model_id": "njn-logreg-cf", "model_version": "1.0.0-research",
            "artifact_sha256": {"model.json": "742fa42bddef2f90ec22ac91a6b8cd23a62cd9d287d06e0d9aa4c5c571bb95cc"},
            "feature_contract": "cf-v1", "runtime": "kotlin-linear-cf-v1", "model_status": "research_only",
            "model_card_ref": "docs/model_cards/njn-logreg-cf.md"},
  "inference_source": "none",
  "warnings": [],
  "created_at": "2026-10-24T12:00:00Z",
  "producer": {"component": "android-app", "software_version": "0.4.0-demo", "platform": "android-36", "contract_version": "2.0.0"}
}
```

### 13.3 Missing model (bilirubin: no model exists)

```json
{
  "schema": "abhaynayan.prediction/2.0.0",
  "result_id": "prd-3d4e5f6a-7b8c-4d9e-8f0a-1b2c3d4e5f6a",
  "trace_id": "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e",
  "status": "unable_to_estimate",
  "reason_code": "NO_VALIDATED_MODEL_FOR_TASK",
  "screening_type": "bilirubin_from_skin",
  "workflow": "neonatal_jaundice",
  "input": {
    "modality": "photo", "body_site": "newborn_skin_sternum",
    "body_site_verification": {"method": "user_confirmed", "status": "unverified"},
    "source": "camera", "capture_protocol": {"id": "newborn-skin", "version": "1.0.0"},
    "orientation": {"exif_tag": null, "applied": "sensor_rotation"},
    "width": 640, "height": 480, "valid_pixel_count": 0
  },
  "input_quality": {"status": "not_assessed", "rules_version": "quality-newborn-1.0.0", "checks": []},
  "input_compatibility": {"status": "not_assessed", "rules_version": "compat-none", "checks": []},
  "estimate": null,
  "model": null,
  "inference_source": "none",
  "warnings": [],
  "created_at": "2026-10-24T12:05:00Z",
  "producer": {"component": "android-app", "software_version": "0.4.0-demo", "platform": "android-36", "contract_version": "2.0.0"}
}
```

### 13.4 Input-quality failure (glare), backend

```json
{
  "schema": "abhaynayan.prediction/2.0.0",
  "result_id": "prd-4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b",
  "trace_id": "c3d4e5f6-a7b8-4c9d-8e0f-2a3b4c5d6e7f",
  "status": "unable_to_estimate",
  "reason_code": "QUALITY_FAILED",
  "screening_type": "hemoglobin_from_palpebral_conjunctiva",
  "workflow": "maternal_anemia",
  "input": {
    "modality": "photo", "body_site": "palpebral_conjunctiva_segmented",
    "body_site_verification": {"method": "protocol_declared", "status": "unverified"},
    "source": "upload", "capture_protocol": null,
    "orientation": {"exif_tag": 1, "applied": "exif_transpose"},
    "width": 800, "height": 1067, "valid_pixel_count": 812
  },
  "input_quality": {"status": "failed", "rules_version": "quality-server-1.0.0", "checks": [
    {"check_id": "clipped_fraction", "measured": 0.31, "threshold": 0.25, "comparator": "<=", "passed": false},
    {"check_id": "sharpness_laplacian_var", "measured": 18.4, "threshold": 2.0, "comparator": ">=", "passed": true}
  ]},
  "input_compatibility": {"status": "not_assessed", "rules_version": "compat-anemia-1.0.0", "checks": []},
  "estimate": null,
  "model": {"model_id": "hb-hgb-cf", "model_version": "1.0.0-research",
            "artifact_sha256": {"hb_hgb_cf_v1.json": "f2b1798fb074600f1d800d82c9b015d0f3a32c096ac49037dda2df1cd886af39"},
            "feature_contract": "cf-v1", "runtime": "python-trees-json", "model_status": "research_only",
            "model_card_ref": "docs/model_cards/hb-hgb-cf.md"},
  "inference_source": "none",
  "warnings": [],
  "created_at": "2026-10-24T12:10:00Z",
  "producer": {"component": "backend", "software_version": "0.4.0", "platform": "python-3.13", "contract_version": "2.0.0"}
}
```

### 13.5 Research result with a persistent warning (research operator, research study context)

```json
{
  "schema": "abhaynayan.prediction/2.0.0",
  "result_id": "prd-5f6a7b8c-9d0e-4f1a-8b2c-3d4e5f6a7b8c",
  "trace_id": "d4e5f6a7-b8c9-4d0e-9f1a-3b4c5d6e7f80",
  "status": "estimated",
  "reason_code": null,
  "screening_type": "hemoglobin_from_palpebral_conjunctiva",
  "workflow": "maternal_anemia",
  "input": {
    "modality": "photo", "body_site": "palpebral_conjunctiva_segmented",
    "body_site_verification": {"method": "dataset_mask", "status": "verified"},
    "source": "upload", "capture_protocol": null,
    "orientation": {"exif_tag": null, "applied": "none_needed"},
    "width": 800, "height": 1067, "valid_pixel_count": 6230
  },
  "input_quality": {"status": "passed", "rules_version": "quality-server-1.0.0", "checks": [
    {"check_id": "clipped_fraction", "measured": 0.04, "threshold": 0.25, "comparator": "<=", "passed": true}
  ]},
  "input_compatibility": {"status": "compatible", "rules_version": "compat-anemia-1.0.0", "checks": [
    {"check_id": "feature_range_cf_v1", "measured": 0, "threshold": 0, "comparator": "<=", "passed": true}
  ]},
  "estimate": {"value": 12.6, "unit": "g/dL", "display_precision": 1, "uncertainty": {"kind": "none"}},
  "model": {"model_id": "hb-hgb-cf", "model_version": "1.0.0-research",
            "artifact_sha256": {"hb_hgb_cf_v1.json": "f2b1798fb074600f1d800d82c9b015d0f3a32c096ac49037dda2df1cd886af39"},
            "feature_contract": "cf-v1", "runtime": "python-trees-json", "model_status": "research_only",
            "model_card_ref": "docs/model_cards/hb-hgb-cf.md"},
  "inference_source": "backend",
  "warnings": [
    {"code": "RESEARCH_ONLY_NOT_VALIDATED", "severity": "caution",
     "origin": {"source": "backend", "component": "inference-service", "software_version": "0.4.0"},
     "created_at": "2026-10-24T12:15:00Z", "params": {}}
  ],
  "created_at": "2026-10-24T12:15:00Z",
  "producer": {"component": "backend", "software_version": "0.4.0", "platform": "python-3.13", "contract_version": "2.0.0"}
}
```

Example 13.5's value is illustrative: no request was run to produce it. Its body site is `segmented` because the input is an expert-masked research image. That is the only input format on which the audit found these models to carry signal.

## 14. JSON Schema (draft 2020-12)

The examples above validate against this schema. It encodes invariants 1–4 and 6 directly. Invariant 5 (plausible range) and 8 (LLM) need registry data and are enforced in code.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "abhaynayan.prediction/2.0.0",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema", "result_id", "trace_id", "status", "reason_code", "screening_type", "workflow", "input",
               "input_quality", "input_compatibility", "estimate", "model", "inference_source", "warnings", "created_at", "producer"],
  "properties": {
    "schema": {"const": "abhaynayan.prediction/2.0.0"},
    "result_id": {"type": "string", "pattern": "^prd-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"},
    "trace_id": {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"},
    "status": {"enum": ["estimated", "unable_to_estimate", "error", "synthetic_fixture"]},
    "reason_code": {"oneOf": [{"type": "null"}, {"enum": [
      "INPUT_EMPTY", "INPUT_DECODE_FAILED", "INPUT_FORMAT_UNSUPPORTED", "INPUT_TOO_SMALL", "INPUT_TOO_LARGE",
      "MODALITY_UNSUPPORTED", "MODALITY_UNVERIFIED", "QUALITY_FAILED", "CAPTURE_RETRY_LIMIT",
      "INPUT_OUT_OF_DISTRIBUTION", "TARGET_REGION_INCOMPATIBLE", "POPULATION_UNSUPPORTED", "CONTEXT_MISSING",
      "MODEL_MISSING", "MODEL_DISABLED", "RUNTIME_UNAVAILABLE", "MODEL_INCOMPATIBLE", "MODEL_INTEGRITY_FAILED",
      "MODEL_REVOKED", "NOT_APPROVED_FOR_INTENDED_USE", "NO_VALIDATED_MODEL_FOR_TASK", "OUTPUT_IMPLAUSIBLE",
      "INFERENCE_RUNTIME_ERROR", "OUTPUT_NON_FINITE", "TIMEOUT", "INTERNAL_ERROR"]}]},
    "screening_type": {"enum": ["hemoglobin_from_palpebral_conjunctiva", "newborn_jaundice_dataset_class", "bilirubin_from_skin"]},
    "workflow": {"enum": ["maternal_anemia", "neonatal_jaundice"]},
    "input": {
      "type": "object", "additionalProperties": false,
      "required": ["modality", "body_site", "body_site_verification", "source", "capture_protocol", "orientation", "width", "height", "valid_pixel_count"],
      "properties": {
        "modality": {"enum": ["photo", "document", "synthetic_test_image"]},
        "body_site": {"enum": ["palpebral_conjunctiva_segmented", "palpebral_conjunctiva_guide_crop", "sclera_guide_crop",
                               "newborn_skin_whole_view", "newborn_skin_forehead", "newborn_skin_sternum", "unknown"]},
        "body_site_verification": {"type": "object", "additionalProperties": false, "required": ["method", "status"],
          "properties": {"method": {"type": "string", "pattern": "^(protocol_declared|user_confirmed|dataset_mask|detector:[A-Za-z0-9._-]+@[0-9A-Za-z.+-]+)$"},
                         "status": {"enum": ["verified", "unverified", "failed"]}}},
        "source": {"enum": ["camera", "gallery", "upload", "synthetic"]},
        "capture_protocol": {"oneOf": [{"type": "null"}, {"type": "object", "additionalProperties": false, "required": ["id", "version"],
          "properties": {"id": {"type": "string", "maxLength": 64}, "version": {"type": "string", "maxLength": 32}}}]},
        "orientation": {"type": "object", "additionalProperties": false, "required": ["exif_tag", "applied"],
          "properties": {"exif_tag": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 1, "maximum": 8}]},
                         "applied": {"enum": ["exif_transpose", "sensor_rotation", "none_needed", "unknown"]}}},
        "width": {"type": "integer", "minimum": 0}, "height": {"type": "integer", "minimum": 0},
        "valid_pixel_count": {"type": "integer", "minimum": 0}
      }
    },
    "input_quality": {"$ref": "#/$defs/checkBlock"},
    "input_compatibility": {"$ref": "#/$defs/checkBlock"},
    "estimate": {"oneOf": [{"type": "null"}, {
      "type": "object", "additionalProperties": false, "required": ["value", "unit", "display_precision", "uncertainty"],
      "properties": {
        "value": {"type": "number"},
        "unit": {"enum": ["g/dL", "mg/dL", "score"]},
        "display_precision": {"type": "integer", "minimum": 0, "maximum": 3},
        "uncertainty": {"type": "object", "required": ["kind"],
          "properties": {"kind": {"enum": ["none", "prediction_interval", "calibrated_probability"]}}}
      }}]},
    "model": {"oneOf": [{"type": "null"}, {
      "type": "object", "additionalProperties": false,
      "required": ["model_id", "model_version", "artifact_sha256", "feature_contract", "runtime", "model_status", "model_card_ref"],
      "properties": {
        "model_id": {"type": "string", "maxLength": 64}, "model_version": {"type": "string", "maxLength": 32},
        "artifact_sha256": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
        "feature_contract": {"type": "string"}, "runtime": {"type": "string"},
        "model_status": {"enum": ["synthetic_fixture", "research_only", "approved_for_intended_use"]},
        "model_card_ref": {"type": ["string", "null"]}
      }}]},
    "inference_source": {"enum": ["edge", "backend", "fixture", "none"]},
    "warnings": {"type": "array", "items": {
      "type": "object", "additionalProperties": false, "required": ["code", "severity", "origin", "created_at", "params"],
      "properties": {
        "code": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{2,63}$"},
        "severity": {"enum": ["info", "caution", "blocking"]},
        "origin": {"type": "object", "additionalProperties": false, "required": ["source", "component", "software_version"],
          "properties": {"source": {"enum": ["edge", "backend", "server_annotation"]}, "component": {"type": "string"}, "software_version": {"type": "string"}}},
        "created_at": {"type": "string", "format": "date-time"},
        "params": {"type": "object"}
      }}},
    "created_at": {"type": "string", "format": "date-time"},
    "producer": {"type": "object", "additionalProperties": false, "required": ["component", "software_version", "platform", "contract_version"],
      "properties": {"component": {"enum": ["android-app", "backend", "pwa"]}, "software_version": {"type": "string"},
                     "platform": {"type": "string"}, "contract_version": {"const": "2.0.0"}}}
  },
  "allOf": [
    {"if": {"properties": {"status": {"enum": ["unable_to_estimate", "error"]}}},
     "then": {"properties": {"estimate": {"type": "null"}, "reason_code": {"type": "string"}}}},
    {"if": {"properties": {"status": {"const": "estimated"}}},
     "then": {"properties": {
       "estimate": {"type": "object"}, "reason_code": {"type": "null"},
       "model": {"type": "object", "properties": {"model_status": {"enum": ["research_only", "approved_for_intended_use"]}}},
       "inference_source": {"enum": ["edge", "backend"]},
       "input_quality": {"properties": {"status": {"const": "passed"}}},
       "input_compatibility": {"properties": {"status": {"const": "compatible"}}}}}},
    {"if": {"properties": {"status": {"const": "synthetic_fixture"}}},
     "then": {"properties": {"estimate": {"type": "object"}, "reason_code": {"type": "null"}, "inference_source": {"const": "fixture"},
       "model": {"type": "object", "properties": {"model_status": {"const": "synthetic_fixture"}}}}}},
    {"if": {"required": ["model"], "properties": {"model": {"type": "object", "properties": {"model_status": {"const": "research_only"}}}, "status": {"const": "estimated"}}},
     "then": {"properties": {"warnings": {"contains": {"properties": {"code": {"const": "RESEARCH_ONLY_NOT_VALIDATED"}}}}}}},
    {"if": {"properties": {"screening_type": {"const": "hemoglobin_from_palpebral_conjunctiva"}, "status": {"const": "estimated"}}},
     "then": {"properties": {"input": {"properties": {"body_site": {"const": "palpebral_conjunctiva_segmented"}}}, "estimate": {"properties": {"unit": {"const": "g/dL"}}}}}},
    {"if": {"properties": {"screening_type": {"const": "newborn_jaundice_dataset_class"}, "status": {"const": "estimated"}}},
     "then": {"properties": {"input": {"properties": {"body_site": {"const": "newborn_skin_whole_view"}}}, "estimate": {"properties": {"unit": {"const": "score"}}}}}},
    {"if": {"properties": {"screening_type": {"const": "bilirubin_from_skin"}}},
     "then": {"properties": {"status": {"enum": ["unable_to_estimate", "error", "synthetic_fixture"]}}}}
  ],
  "$defs": {
    "checkBlock": {"type": "object", "additionalProperties": false, "required": ["status", "rules_version", "checks"],
      "properties": {
        "status": {"enum": ["passed", "failed", "compatible", "incompatible", "not_assessed"]},
        "rules_version": {"type": "string"},
        "checks": {"type": "array", "items": {"type": "object", "additionalProperties": false,
          "required": ["check_id", "measured", "threshold", "comparator", "passed"],
          "properties": {"check_id": {"type": "string"}, "measured": {}, "threshold": {}, "comparator": {"enum": [">=", "<=", "==", "in"]}, "passed": {"type": "boolean"}}}}
      }}
  }
}
```

The last `allOf` clause encodes "bilirubin can never be estimated" in the schema. (Refined in Phase 5: `synthetic_fixture` is also allowed for this task, because the app's explicitly selected newborn demo fixtures are not inference; `estimated` remains impossible.) When a validated bilirubin model exists, that clause changes in a MAJOR schema revision, a deliberate and reviewable step, rather than through configuration.

## 15. HTTP mapping (backend, contract 2.0)

| Outcome | HTTP | Body |
|---|---|---|
| `estimated`, `unable_to_estimate` for any input/model/evidence reason | 200 | envelope |
| request unauthenticated / forbidden / rate-limited | 401 / 403 / 429 | standard error body; **no envelope** (no inference was attempted) |
| body too large before read, wrong content type | 413 / 415 | standard error body |
| `error` | 500 / 503 | standard error body **plus** `prediction` = the envelope (`status = error`), so clients can persist the attempt |

Returning 200 for `unable_to_estimate` is intentional. It is a correct, final answer that clients must save and display, not a transport failure to retry.
