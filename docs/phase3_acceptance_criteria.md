# Phase 3 acceptance criteria

Status: **Criteria written in Phase 3. Statuses below record what has actually been implemented and run.** A criterion is "Satisfied" only when its test exists and passed in a recorded run. "Emulator" means an emulator run only; no physical-device test has been done. No criterion has been externally (clinically) reviewed.

## Status after Phase 6 (24 October 2026)

Only criteria whose status changed in Phase 6 are listed. Encryption criteria were not in the Phase 3 list; they are tracked in [ADR-005](adr/ADR-005-local-encryption.md) "Verification". "Instrumented" means `SecureDatabaseInstrumentedTest` on the `abhay_api36` emulator (API 36), not a physical phone.

| Criterion | Status | Evidence / gap |
|---|---|---|
| AC-PRED-05 `error` persisted | **Satisfied (unit) / not reachable in the UI** | Q9 decided (prediction_contract.md §4). `failedAnalysisCarriesAValidNoValueRecord`, `unexpectedAnalysisErrorBuildsAnErrorRecordOnlyForSystemErrors`, `failedAttemptRecordStateIsTrackedWithoutAValue`. The view model saves the record atomically and reports a save failure. No production input reaches a model, so the error path could not be triggered on the emulator |
| AC-REC-01 save keeps warnings | **Satisfied (instrumented)** | the record, envelope SHA-256 and `record_warnings` are written in one transaction. After a restart, `verifiedRecord` returns the identical envelope, the index equals the envelope's warnings, and the integrity is `VerifiedSinceSave` |
| AC-REC-02 sync keeps warnings | **Blocked** | no compatible endpoint (API_CONTRACT.md §7, proposed). Envelope sync stays disabled (`OutcomeSyncTest`) and no outcome record is shown as synced |
| AC-REC-03 server never repairs | **Partially** | `verify_item` rejects every tampering case without modifying the item (`test_tampering_is_detected_not_repaired`); the device marks integrity failures `FAILED` and never sends them (`recordThatFailsItsIntegrityCheckIsNeverSentOrRepaired`). No server route yet |
| AC-REC-04 app update before sync | **Satisfied (instrumented + emulator)** | a v3 envelope's bytes, SHA-256, duplicate warnings and every v3 column are identical after plaintext v3 → encrypted v4. The installed Phase 5 app on the emulator upgraded with all 5 records |
| AC-REC-06 legacy records display | **Partially** | legacy rows are labelled `LEGACY_NO_OUTCOME` / `LEGACY_OUTCOME_V3`, shown as "older record, history not verifiable" with "Not recorded" fields, and nothing is inferred (instrumented and emulator). `legacy_source` wrapping is not implemented (record 2.0 restructuring) |
| AC-REC-07 unknown versions fail safe | **Partially** | an unknown hash version is shown as "created by a newer app version" and never as verified (`legacyRecordsAreNeverReportedAsVerifiedSinceSave`). The unknown envelope schema display is unchanged |
| AC-OFF-01 full local workflow without network | **Partially** | records are read, saved and reported from the encrypted local store with no network dependency (instrumented `freshStoreIsEncryptedAndSurvivesRestart`; an emulator flow saved a new record). Not yet run in airplane mode with a network-call counter |
| AC-OFF-03 queue survives restarts | **Partially** | records and sync states survive a forced stop on the emulator (6 records). The sync-exactly-once part needs the live e2e run |
| AC-OFF-04 backend failure is safe | **Satisfied** | the existing MockBackend tests (500, timeout, malformed) plus instrumented `networkFailureDuringSyncNeitherErasesNorChangesRecords` (count, envelope bytes and integrity unchanged) |
| AC-MIG-01 1.x clients keep working | **Satisfied** | the full Python, Node and Android suites pass, and the API contract is still 1.3.0 |

## Status after Phase 5 (24 October 2026)

| Criterion | Status | Evidence / gap |
|---|---|---|
| AC-CAP-01 noise never estimated | **Partially** | Android `pinkNoisePassesQualityButNeverReachesTheModel` (opaque pink noise passes quality, model never called); backend opaque and masked pink noise refused (`test_quality_pass_does_not_imply_compatibility_and_noise_is_never_scored`); flat and white images rejected by quality. Uniform, Gaussian and gradient sets not yet added |
| AC-CAP-02 unsupported modalities | **Partially** | sclera, eyelid crop and skin patches refused by the NJN task; masked crops refused by the NJN route; opaque uploads refused by the Hb route. Document-image case not tested |
| AC-CAP-03 measured rejection rate | **Blocked** | needs the documented negative-modality set |
| AC-CAP-04 app-style crops incompatible | **Satisfied (one-off run on private data)** | 54/54 held-out app-style crops → `TARGET_REGION_INCOMPATIBLE` through the real route; the segmented variant gives 44 estimates, MAE 1.31, only with a test verifier (production: `MODALITY_UNVERIFIED`). Automated synthetic regression: `test_opaque_upload_is_target_region_incompatible_for_hb`, Android `appStyleGuideCropIsAlwaysIneligibleForHb` |
| AC-CAP-05 camera crops never reach the Hb model | **Satisfied** | spy tests (`calls == 0`) in `CaptureOutcomeTest`, `WorkflowEngineTest.syntheticChartNeverReachesAResearchModel` |
| AC-CAP-06 / 07 orientation | **Satisfied** (Phase 4) | plus `ExifOrientationReaderTest`; orientation recorded in every envelope |
| AC-CAP-08 single-frame selection | **Deferred** | multi-frame capture not implemented (capture_protocols.md, Phase 5 status) |
| AC-CAP-09 retry limit | **Satisfied (unit + emulator)** | `WorkflowTransitionsTest`; emulator: 3 rejected captures → limit card → `CAPTURE_RETRY_LIMIT` record saved, no estimate |
| AC-CAP-10 danger signs override | **Partially** | `ReferralRules` unchanged and tested (`ClinicalTest`); not parameterised over envelope statuses |
| AC-CAP-11 quality ≠ suitability | **Satisfied** | envelope `input_quality.status = passed` with `input_compatibility.status = incompatible` asserted on Android and backend |
| AC-PRED-01 schema examples | **Satisfied** | Python validator, Kotlin `PredictionContractTest`, JSON Schema (`.venv-ml`; skipped where `jsonschema` is absent) |
| AC-PRED-02 invariants in code | **Satisfied** | 12 deliberate violations rejected by both validators; live route envelopes validated against the documented JSON Schema |
| AC-PRED-03 discard, never clamp | **Satisfied** | backend `OUTPUT_OUT_OF_RANGE` / `OUTPUT_IMPLAUSIBLE`; Android `OUTPUT_IMPLAUSIBLE` |
| AC-PRED-04 evaluation order | **Partially** | implemented in both pipelines; tested for disabled + incompatible (reports `MODEL_DISABLED`) and real profile + research (`NOT_APPROVED_FOR_INTENDED_USE`); no full table-driven test |
| AC-PRED-05 `error` persisted | **Partially / open conflict** | backend 500 bodies carry `prediction.status = error`. Android does **not** save failed inferences (no record is created, following the Phase 5 rule that a failed attempt must not create a record). Needs a decision |
| AC-PRED-06 backend never overwrites edge | **Not applicable yet** | the app never calls backend inference |
| AC-MOD-01 / 02 missing, mismatched model | **Satisfied** (Phase 4) | reason codes now reach the envelope (`missingAndTamperedModelsGiveTheirReasonCodes`) |
| AC-STAT-03 flags are kill switches | **Satisfied (backend)** | unchanged |
| AC-STAT-05 local toggle grants nothing | **Partially** | on every camera or gallery input the toggle now has no effect (no compatible input); the toggle itself remains until Phase 8 |
| AC-STAT-06 defaults off | **Partially** | server tested; emulator AVD retains an older opted-in setting, so no fresh-install observation |
| AC-REC-01 save keeps warnings | **Partially** | envelope stored verbatim in Room v3 `predictionJson`, emulator-checked for one record; no derived warning index or SHA check (Phase 6) |
| AC-REC-02 sync keeps warnings | **Not implemented** | envelopes are not synced (contract 1.x); Phase 6 |
| AC-REC-04 app update before sync | **Partially** | Room 2→3 migration keeps rows unchanged (`verify_room_migration.py`; emulator upgrade with 4 existing records) |
| AC-REC-05 export and report keep warnings | **Partially** | PDF/text report prints outcome and every warning (`warningsSurviveIntoTheReport`); FHIR export and an export validator not yet updated |
| AC-REC-06 legacy records display | **Partially** | v2 rows display as "Not recorded", plus `LEGACY_WARNINGS_NOT_RECORDED` for experimental rows; full wrap with `legacy_source` in Phase 6 |
| AC-REC-07 unknown versions fail safe | **Partially** | unknown warning codes displayed generically; unknown-schema display not implemented |
| AC-SEC-09 / 10 | **Satisfied** (Phase 4, re-run) | |
| AC-MIG-01 1.x clients keep working | **Satisfied** | contract 1.3.0 additive for Android/PWA flows; all 1.x tests pass |
| AC-MIG-02 1.x → 2.0 mapping | **Partially** | display mapping only |

Everything else keeps its Phase 3 status (not implemented) and planned phase.

Conventions: *Layer* = where the test runs (`py` = backend pytest, `kt` = Android JVM unit test, `inst` = Android instrumentation/emulator, `web` = Node/JSDOM, `e2e` = live server + client). *Data* = what the test may use. Tests that use real research images run only on machines holding the gitignored artifacts and are reported separately from synthetic/mocked tests. Every test states whether it used a real trained model or a mock.

## 1. Inputs, modality and capture (AC-CAP)

| ID | Requirement | Test and pass condition | Layer | Phase | Finding |
|---|---|---|---|---|---|
| AC-CAP-01 | Random noise never gets an estimate | Seeded uniform, Gaussian and "pink" noise (the audit's `rng(0)` image), solid colours and gradients sent to every task, edge and backend → `status = unable_to_estimate`, `reason_code ∈ {MODALITY_UNVERIFIED, QUALITY_FAILED, INPUT_OUT_OF_DISTRIBUTION}`, `estimate = null` for 100 % of the synthetic set | py, kt | 5, 7 | H1 |
| AC-CAP-02 | Unsupported modalities are refused | Skin to the anemia task, sclera/eye to `newborn_jaundice_dataset_class`, a document image to both → `MODALITY_UNSUPPORTED` or `MODALITY_UNVERIFIED`, no value | py, kt | 5, 7 | H1, M1 |
| AC-CAP-03 | Negative-modality rejection is **measured, not assumed** | Documented negative set ([capture_protocols.md §4](capture_protocols.md)); the report states the rejection rate per category with a 95 % CI. Pass = report produced and committed. No minimum rate is claimed until agreed | py | 5 | H1 |
| AC-CAP-04 | App-style anemia crops are incompatible | `scripts/audit/probe_input_domain.py` variant B (guide crop) through the new pipeline → 54/54 `unable_to_estimate`, `TARGET_REGION_INCOMPATIBLE` (or `INPUT_OUT_OF_DISTRIBUTION`); variant A unchanged (still estimable in research context, metrics identical to `ml/runs/hb-v1`) | py (real artifacts) | 7 | H2, H3 |
| AC-CAP-05 | Android camera crops never reach the Hb model | `WorkflowEngine` with a camera-source frame and the research toggle on → no call to `estimateGramsPerDecilitre` (spy), result `TARGET_REGION_INCOMPATIBLE` | kt | 5, 7 | H3 |
| AC-CAP-06 | Orientation consistency | Each fixture image encoded in all 8 EXIF orientations → after decode, cf-v1 features equal within 1e-6 and CNN input tensors byte-identical, on server (`imageio.decode`), training reader (`read_path`) and Android (`ExifInterface` path) | py, kt | 4 | M2 |
| AC-CAP-07 | Orientation-sensitive models refuse unknown orientation | JPEG with a corrupt orientation tag → CNN tasks `MODALITY_UNVERIFIED`; cf-v1 tasks proceed with `ORIENTATION_UNKNOWN` warning | py | 4 | M2 |
| AC-CAP-08 | Single-frame selection, no output-shopping | Burst of 5 synthetic frames with known sharpness → selected index = sharpest passing frame; model invoked **exactly once** (spy) | kt | 5 | — |
| AC-CAP-09 | Retry limit | 3 failing bursts → `CAPTURE_RETRY_LIMIT`; 4th capture attempt not offered in the same attempt; referral line shown | kt, inst | 5 | — |
| AC-CAP-10 | Danger signs override everything | Any `DangerSign` for the workflow → `URGENT_REFERRAL` shown before and after capture, for every envelope status including `estimated` | kt | 5 | — |
| AC-CAP-11 | Quality ≠ suitability | An image that passes all quality checks but fails compatibility → envelope has `input_quality.status = passed`, `input_compatibility.status = incompatible`, no value; UI copy does not call it "suitable" | kt, web | 5, 7 | H2 |

## 2. Prediction contract (AC-PRED)

| ID | Requirement | Test and pass condition | Layer | Phase |
|---|---|---|---|---|
| AC-PRED-01 | Schema examples valid | All examples in [prediction_contract.md §13](prediction_contract.md) validate against §14 (jsonschema) | py | 7 |
| AC-PRED-02 | Invariants enforced in code | Server and Kotlin validators reject: value on `unable_to_estimate`/`error`; missing `reason_code`; `estimated` without model; research estimate without `RESEARCH_ONLY_NOT_VALIDATED`; bilirubin `estimated`; unknown `status`/`model_status`; unit mismatch; non-finite value | py, kt | 7 |
| AC-PRED-03 | Plausibility discards, never clamps | Model stub returning 30 g/dL and −1 → `OUTPUT_IMPLAUSIBLE`, no value; no output equals a range boundary | py, kt | 7 |
| AC-PRED-04 | Evaluation order | Inputs failing two gates report the **earlier** gate's code (table-driven) | py | 7 |
| AC-PRED-05 | `error` is persisted | Model stub raising → HTTP 500 body contains `prediction.status = error`; Android saves it | py, kt | 7 |
| AC-PRED-06 | Backend never overwrites edge | Record with edge envelope + later backend inference → two entries in `predictions[]`, edge bytes unchanged | py, kt | 7 |

## 3. Models and artifacts (AC-MOD)

| ID | Requirement | Test and pass condition | Layer | Phase | Finding |
|---|---|---|---|---|---|
| AC-MOD-01 | Missing model | Remove each artifact → `MODEL_MISSING`, no value, readiness endpoint shows the reason | py, kt | 4, 7 | L1 |
| AC-MOD-02 | Checksum mismatch | Flip one byte in each artifact (Hb **and jaundice class**) → `MODEL_INTEGRITY_FAILED` | py, kt | 7 | M4 |
| AC-MOD-03 | Unsigned or wrongly signed manifest | Bundle with a bad signature → not loaded, previous model kept | kt, py | 12 | — |
| AC-MOD-04 | Incompatible contract | Wrong `feature_contract`, input shape, runtime or unit → `MODEL_INCOMPATIBLE` | py, kt | 7 | — |
| AC-MOD-05 | Status cannot be raised remotely | Remote config/flag claiming `approved_for_intended_use` for a research model → ignored; status comes only from the signed manifest + registry | py, kt | 12 | — |
| AC-MOD-06 | Readiness reflects reality | After an artifact is restored, readiness becomes ready without silently reusing a cached failure (or documents that a restart is required) | py | 4 | L1 |
| AC-MOD-07 | Distributed builds carry no research assets | CI release build: `unzip -l` shows no `assets/models/`; build fails if present | CI | 4, 12 | M7 |

## 4. Research vs clinical status (AC-STAT)

| ID | Requirement | Test and pass condition | Layer | Phase | Finding |
|---|---|---|---|---|---|
| AC-STAT-01 | Research needs a study grant | `research_only` model requested by: anonymous, patient, clinician, org admin, synthetic_test, research operator without a study → all `NOT_APPROVED_FOR_INTENDED_USE`, no value | py | 8 | M5, M6 |
| AC-STAT-02 | No research on real subjects without enrolment | Research operator + study + `person` subject without `research_study` consent → refused | py | 8 | M5 |
| AC-STAT-03 | Flags are kill switches only | Flag on + no permission → refused; permission + flag off → refused | py, kt | 8 | M6 |
| AC-STAT-04 | Research output stays out of clinical views | Research result absent from patient/caregiver/clinician history, reports, referral urgency and LLM fact sheets | py, web | 8, 9 | — |
| AC-STAT-05 | Local toggle grants nothing | Android with toggle on and no valid offline permission token → research models not loaded | kt | 8 | M5 |
| AC-STAT-06 | Defaults stay off | Fresh install (cleared app data on emulator) and fresh server env → research disabled; recorded as an emulator observation | inst, py | 4 | — |

## 5. Warning and provenance persistence (AC-REC)

| ID | Requirement | Test and pass condition | Layer | Phase | Finding |
|---|---|---|---|---|---|
| AC-REC-01 | Save keeps warnings | OOD/research result saved → reloaded envelope SHA-256 identical; `record_warnings` count = envelope warning count | kt | 6 | M3 |
| AC-REC-02 | Sync keeps warnings | Edge record synced to the test server → stored envelope bytes and hash identical; server adds nothing except annotations | e2e | 6 | M3 |
| AC-REC-03 | Server never repairs | Envelope violating an invariant (warning stripped) → `rejected` with code; device keeps it `FAILED` | py, kt | 6 | — |
| AC-REC-04 | App update before sync | Create the record with app build N, migrate the DB to N+1, then sync → envelope hash, `producer.software_version` and warnings unchanged | kt (Room migration test) | 6 | M3 |
| AC-REC-05 | Export and report keep warnings | PDF text, plain-text export and FHIR export of a record with k warnings contain all k codes; validator refuses an export missing one | kt, py | 9 | M3, F3 |
| AC-REC-06 | Legacy records display | Room v2 fixture DB (demo, disabled, experimental rows) migrates to v3: each row readable, `legacy_source` byte-identical, experimental rows carry `LEGACY_WARNINGS_NOT_RECORDED` | kt | 6 | L4 |
| AC-REC-07 | Unknown versions fail safe | Envelope with unknown MAJOR `schema` → "needs newer app", no value shown; unknown warning code → shown generically | kt, web | 6 | — |
| AC-REC-08 | Revoked model after the fact | Revoke a model → old records keep their value, gain `MODEL_REVOKED_AFTER_RESULT` annotation, original bytes unchanged | py | 12 | — |
| AC-REC-09 | Lab vs estimate separation | History/report with an Hb lab measurement and an Hb estimate on the same day → two separate rows; no combined or averaged figure anywhere | py, kt | 9 | — |
| AC-REC-10 | No PII in logs or IDs | Run the full e2e suite with log capture; grep logs for test names, phone patterns, values with units and context fields → zero matches; IDs are UUIDv4 | e2e | 4, 8 | — |

## 6. Offline operation (AC-OFF)

| ID | Requirement | Test and pass condition | Layer | Phase |
|---|---|---|---|---|
| AC-OFF-01 | Full local workflow without network | Emulator in airplane mode: create a subject, capture (synthetic frame source), get an envelope, save, view history, generate PDF → all succeed; no network call attempted (OkHttp/`HttpURLConnection` interceptor counts 0) | inst | 6 |
| AC-OFF-02 | Cloud features say so | Offline: LLM, backend inference, server email show "needs connection"; none shows a spinner forever or fabricated text | inst, web | 6, 10 |
| AC-OFF-03 | Queue survives restarts | Save 3 records offline, kill the app, reboot the emulator, reconnect → each syncs exactly once (server count = 3) | inst + e2e | 6 |
| AC-OFF-04 | Backend failure is safe online | Server returns 500/timeout/malformed JSON → records stay `PENDING`/`FAILED`, nothing deleted, no value changed | kt (MockBackend) | 6 |

## 7. Authorization and cross-patient access (AC-SEC)

| ID | Requirement | Test and pass condition | Layer | Phase |
|---|---|---|---|---|
| AC-SEC-01 | Cross-patient read | Patient A requests B's record by ID → 404, identical body to a missing ID | py | 8 |
| AC-SEC-02 | ID enumeration | 1,000 random `scr-` IDs → all 404; response timing not distinguishable at p95 within 20 % | py | 8 |
| AC-SEC-03 | Revoked and expired grants | Caregiver or clinician after revocation or expiry → 404 on read, 404 on sync of that subject's record | py | 8 |
| AC-SEC-04 | Cross-org clinician | Clinician in org X, grant only to org Y → 404 | py | 8 |
| AC-SEC-05 | Org admin has no individual access | Org admin without a clinician grant → 404 on records; analytics cells < k suppressed | py | 8, 11 |
| AC-SEC-06 | Client role and kind fields ignored | Payload with `role: clinician`, `subject_kind: synthetic_test`, `demo: true` → stored or evaluated as server-derived values; no privilege change | py | 8 |
| AC-SEC-07 | Synthetic accounts cannot screen people | `synthetic_test` user with `source = camera` or a non-allowlisted image hash → 403 `SYNTHETIC_INPUT_REQUIRED` | py | 8 |
| AC-SEC-08 | Token checks | Wrong `aud`, wrong `iss`, expired, bad signature, `email_verified = false` → 401 `IDENTITY_TOKEN_INVALID`; expired access → `TOKEN_EXPIRED`; reused refresh → `SESSION_REVOKED` and family revoked | py | 8 |
| AC-SEC-09 | Rate limits and size limits | Exceed the per-user image bucket → 429 with `Retry-After`; 9 MB body → 413 before full read (existing behaviour kept) | py | 4 |
| AC-SEC-10 | Unauthenticated image endpoints closed | `/api/ml/*` and v2 inference without a token → 401, even with the flag on | py | 4, 8 |
| AC-SEC-11 | Secrets absent from clients | Build the APK and PWA; scan for key patterns (Gemini, private keys, signing keys) → none | CI | 4 |

## 8. LLM boundary (AC-LLM)

| ID | Requirement | Test and pass condition | Layer | Phase |
|---|---|---|---|---|
| AC-LLM-01 | No numbers from nowhere | Mocked LLM outputs containing a number + unit absent from the fact sheet → rejected, deterministic fallback shown, `fallback_reason` recorded | py | 10 |
| AC-LLM-02 | No value for a non-estimate | Fact sheet with `unable_to_estimate` + mocked LLM "your Hb is about 11" → rejected | py | 10 |
| AC-LLM-03 | Diagnosis, treatment, invented ranges | Corpus of unsafe outputs (extends today's `_UNSAFE` tests in `tests/test_gemini.py`) → 100 % rejected; corpus of safe outputs → accepted (false-reject rate reported) | py | 10 |
| AC-LLM-04 | Urgent questions escalate | Neonatal danger-sign questions → fixed escalation copy; no provider call (spy) | py | 10 |
| AC-LLM-05 | LLM cannot write the report body | Report bytes are identical with LLM on/off except the separately labelled explanation section | py, kt | 9, 10 |
| AC-LLM-06 | Minimal context | Captured provider request contains only fact-sheet fields; no IDs, names, images | py | 10 |

## 9. Schema migration and legacy display (AC-MIG)

| ID | Requirement | Test and pass condition | Layer | Phase |
|---|---|---|---|---|
| AC-MIG-01 | Contract 1.x clients keep working | Existing 1.x tests (197 Python, 132 Android, Node suite) still pass while v2 runs alongside | py, kt, web | 6–7 |
| AC-MIG-02 | 1.x → 2.0 mapping | Each legacy case in [prediction_contract.md §10](prediction_contract.md) maps to the stated envelope (golden files) | py, kt | 6 |
| AC-MIG-03 | Old records under a new app | Records from schema 2.0.0 opened by a simulated 2.1.0 reader with extra optional fields → identical display | kt, web | 6 |

## 10. Traceability: critical audit findings → criteria

| Finding | Criteria |
|---|---|
| H1 noise / no modality check | AC-CAP-01, 02, 03 |
| H2 OOD still produces a value | AC-CAP-04, 11 |
| H3 Hb on guide crops | AC-CAP-04, 05 |
| M1 skin-trained classifier on sclera | AC-CAP-02 |
| M2 EXIF orientation | AC-CAP-06, 07 |
| M3 warnings lost on save | AC-REC-01, 02, 04, 05 |
| M4 jaundice artifact unpinned | AC-MOD-02 |
| M5 checkbox research mode | AC-STAT-01, 02, 05 |
| M6 open image endpoints | AC-SEC-09, 10; AC-STAT-03 |
| M7 research assets in local APK | AC-MOD-07 |
| L1 readiness | AC-MOD-01, 06 |
| L4 legacy placeholder | AC-REC-06 |
| F3 LLM text in reports | AC-REC-05, AC-LLM-05 |
