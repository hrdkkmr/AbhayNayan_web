# AbhayNayan implementation plan

Started 24 October 2026. This is the working checklist for evolving the prototype into an offline-first screening platform. Tick an item only when the evidence in its row exists. Architecture: [architecture.md](architecture.md). Decisions: [adr/](adr/).

Status words used below have fixed meanings: **Implemented** (code exists and its tests pass), **Trained** (an artifact was fitted on labelled data), **Evaluated** (scored once on a documented held-out set), **Integrated** (reachable from the app or API), **Clinically validated** (prospective clinical study for the intended use). No component is clinically validated.

## Phase 1 baseline (24 October 2026)

### Repositories

| Local path | Remote | Branch / HEAD | Sync state | Local changes |
|---|---|---|---|---|
| `Programming/AbhayNayan/AbhayNayan_web` | `hrdkkmr/AbhayNayan_web` | `master` @ `f52fde7` | equal to `origin/master` after `git fetch` (remote also has branch `kushagra-p1`, not merged) | none tracked; `.env` present and gitignored |
| `Programming/AbhayNayan_apk` (project in `AbhayNayan/`) | `shubhamcore/AbhayNayan_apk` | `main` @ `06828c5` | equal to `origin/main` after `git fetch` | untracked `1.jpeg`–`5.jpeg` at the repo root (540×1189 screenshots), left untouched |

`Programming/AbhayNayan/` itself is not a Git repository. It holds the web repo plus the raw datasets (`archive/`, CP-AnemiC, NJN, neonatal forehead/sternum, `datasets_extracted/`, `Anemia_Dataset.csv`), which stay outside Git. No other project in `Programming/` was read or modified.

### Duplicate code across the two repositories

| Copy | Status | Evidence |
|---|---|---|
| `AbhayNayan_web/android/` | Stale snapshot; does not compile | Unescaped `package in.abhaynayan.app…` (`in` is a Kotlin keyword); 45 file differences from the canonical app |
| `AbhayNayan_apk/AbhayNayan/backend`, `web-dashboard`, `tests` | Stale snapshot of the web repo | No `ml/` package or `model_adapters.py`; every shared file differs |

Canonical: **backend and PWA → `AbhayNayan_web`; Android → `AbhayNayan_apk/AbhayNayan/android`.** See [ADR-001](adr/ADR-001-canonical-sources.md).

### Test and build baseline (run on this machine, 24 Oct 2026)

| Suite | Command | Result |
|---|---|---|
| Python (API, contract, core, Gemini mocks, ML) | `PYTHONPATH=backend .venv/Scripts/python -m pytest -q` | **197 passed** (same in `.venv-ml`) |
| Web modules, JSDOM workflows, syntax | `npm test` | **all passed** (module tests + 4 JSDOM workflow tests + `node --check`) |
| Android unit tests | `./gradlew :app:testDebugUnitTest --rerun-tasks` (JDK 22, SDK at `E:\Android\Sdk`) | **132 tests, 0 failures, 1 skipped** (live-backend test) |
| Android debug APK | `:app:assembleDebug` | builds (`app-debug.apk`, 12.6 MB) |
| Android lint | `:app:lintDebug` | 0 errors, 16 warnings (10 `GradleDependency`, 1 each `LockedOrientationActivity`, `NewerVersionAvailable`, `DiscouragedApi`, `ObsoleteSdkInt`, `UseKtx`) |
| Device | `adb devices` | no device attached. An AVD `abhay_api36` (API 36 google_apis x86_64) exists but was not started in this phase |

These tests use synthetic fixtures and mocks, except the ML tests that load trained research artifacts when present. No test exercises a live Gemini call or a physical device.

### Current failures found

| # | Failure | Evidence | Fix (planned) |
|---|---|---|---|
| F1 | **Web-repo CI has failed on every recent push.** Python and web jobs pass; the Android job fails at "Assemble and run unit tests" | GitHub Actions runs for `f52fde7`, `8c089df`, `1987a5e` (public API, 24 Oct) | The job builds the stale `android/` copy. Remove the job (and later the folder) from the web repo; Android CI belongs in the Android repo. P0 |
| F2 | **Android repo has no working CI.** Its workflow lives at `AbhayNayan/.github/workflows/ci.yml`, but GitHub only reads `.github/` at the repository root | Actions API reports 0 runs for `shubhamcore/AbhayNayan_apk` | Move a workflow to the repo root, with `working-directory: AbhayNayan/android`. P0 |
| F3 | Reports copy free-text LLM wording verbatim | `ReportDocument.from` puts `CounselText.summary/riskExplanation/script` into the PDF whenever the source is `SERVER_GEMINI` | Stage 8: the report body becomes deterministic only; LLM explanations are labelled and kept separate. P1 |
| F4 | **Remote branch `kushagra-p1` breaks the clinical ML rules. Do not merge it.** It shares no history with `master` (no merge base) | See the next table | Keep it unmerged. Any idea worth keeping is re-implemented on `master` through the existing fail-closed adapters |

### Findings on `origin/kushagra-p1` (4 commits, 19 Oct 2026, not on `master`)

| Problem | Where |
|---|---|
| On any inference exception it silently returns a fixed anemia probability of 0.35 and Hb of 12.0 g/dL | `backend/abhaynayan_screening_engine.py` ≈ line 354 |
| It clamps Hb to 5.5–17.5 g/dL instead of discarding implausible output | same file, `np.clip(..., 5.5, 17.5)` |
| It outputs cataract, conjunctivitis and scleral-icterus "proxies" with invented reference ranges (for example "18.0 – 36.0 EI"). No model, labels or evaluation exist for any of these | same file, lines ≈ 405–495; `reports/ABN-20261019-9AFF60.json` |
| The report text makes claims and recommends treatment: "Capture meets clinical optical quality standards"; "initiate iron/folate protocol" | committed sample report |
| `models/model_card.json` claims sensitivity 1.0 and accuracy 0.986 from "CV" over all 217 rows, with no held-out split. **`scripts/train_eyes_defy_anemia.py` is an empty file**, so the weights cannot be reproduced | `models/` |
| It defaults patient age to 34 when unknown and falls back to unfiltered pixels when fewer than 50 are valid | `extract_eyes_defy_f1_features` |
| It writes reports with patient names (synthetic in the sample) to a tracked `reports/` folder | `reports/` |

This branch is the most likely origin of the "irrelevant AI-generated report content" seen in demos. `master` contains none of this code.

## Phase 2 audit result (24 October 2026)

Full evidence: [model_audit.md](model_audit.md). No source code changed; audit scripts were added under `scripts/audit/`.

| Task | Implemented | Trained | Held-out evaluated | Integrated | Clinically validated |
|---|---|---|---|---|---|
| Hb, training input (segmented crop) | yes | yes | yes, re-run with identical metrics | behind flags | no |
| Hb, app input (manual guide crop) | yes | — | **probe: R² −0.99 backend / −6.82 edge** | behind flags | no |
| Bilirubin | interface only | **blocked: no labels** | no | disabled | no |
| NJN dataset class | yes | yes | yes (leakage possible) | behind flags | no |

New findings, mapped to the phase that fixes them:

| ID | Finding | Phase |
|---|---|---|
| H1 | No input-domain/anatomy check (pink noise → Hb 13.4 g/dL) | 5 / 7 |
| H2 | OOD inputs still produce a displayed value | 7 |
| H3 | Android Hb research model gets a whole-eye crop, not a segmented conjunctiva | 5 (keep toggle off meanwhile) |
| M1 | Jaundice-class score computed on a sclera photo; trained on newborn skin photos | 5 |
| M2 | EXIF orientation ignored on upload; CNN score shifts up to 0.50 | 4 |
| M3 | OOD warning not saved with the record or report | 6 |
| M4 | Edge jaundice-class artifact has no checksum pin | 7 |
| M5 | Research mode depends on a self-declared "synthetic" profile flag | 8 |
| M6 | `/api/ml/*` unauthenticated, no rate limit | 4 / 8 |
| M7 | Locally built debug APK embeds research assets: do not distribute | 12 (release process) |
| L1–L5 | readiness in `/api/health`, line-ending cache key, stale PWA text, legacy placeholder column, parity test skipped in CI | 4 / 6 / 14 |

**Gate: clinical training remains blocked** (no bilirubin labels; no licence-confirmed, maternal or app-captured Hb data). Research flags stay off by default.

## Phase 3 architecture and contracts (24 October 2026): design complete, nothing implemented

No source code, model artifact, dataset, dependency, screenshot or environment file was changed. Research switches remain off (`ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA=0` in `.env`; `ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS` unset; Android default `false`).

### Documents

| Document | Content |
|---|---|
| [architecture.md](architecture.md) §4–7 (Phase 1 §1–3 kept) | 14 components with responsibilities, I/O, trust, failure, dependencies and phase; online vs offline table; 5 Mermaid diagrams; lifecycle summary |
| [prediction_contract.md](prediction_contract.md) | Envelope `abhaynayan.prediction/2.0.0`: statuses, 26 reason codes, quality vs compatibility, persistent warnings, versioning, model lifecycle, 5 JSON examples, JSON Schema |
| [capture_protocols.md](capture_protocols.md) | `anemia-palpebral` and `newborn-skin` protocols, orientation, burst selection, retry limits, calibration method |
| [record_contract.md](record_contract.md) | Record `abhaynayan.record/2.0.0`: immutable envelopes, append-only annotations, lab measurements, lifecycle, sync/export/migration rules |
| [security_and_permissions.md](security_and_permissions.md) | Authn vs authz, 8 roles, grants, dependents, consent, research and synthetic-test permissions, endpoint protections |
| [phase3_acceptance_criteria.md](phase3_acceptance_criteria.md) | 64 testable criteria (AC-CAP, PRED, MOD, STAT, REC, OFF, SEC, LLM, MIG) with finding traceability |

### Decisions and rationale

| # | Decision | Rationale |
|---|---|---|
| D1 | New envelope as contract **2.0** next to 1.x, not a 1.x change | 1.x `estimate` is a required float with `extra='forbid'`; it cannot carry `unable_to_estimate` |
| D2 | Fourth status `synthetic_fixture` | A fixture is not an estimate; the project already separates `DEMO_SYNTHETIC` |
| D3 | OOD is **blocking** (`INPUT_OUT_OF_DISTRIBUTION`), not a warning | Audit §5.1: OOD on 54/54 app crops with R² −0.99 / −6.82 |
| D4 | Guide-rectangle crops are never compatible with existing Hb models | Same evidence; a segmentation step must be built and validated first |
| D5 | Sclera capture retired as a jaundice inference input; newborn protocol targets skin | NJN/forehead-sternum data are skin; no sclera data or model exists |
| D6 | Quality and compatibility are separate result blocks | 54/54 incompatible crops passed quality |
| D7 | Envelopes immutable and stored as bytes + SHA-256; warnings append-only; server annotations separate | Prevents warning loss (M3) through sync, migration and app updates |
| D8 | Server returns 200 for `unable_to_estimate` and embeds the envelope in 5xx `error` bodies | Outcomes must be saved, not retried as transport errors |
| D9 | Research permission = registered study + role + consent; flags are kill switches only | Replaces the checkbox (M5) without a public bypass |
| D10 | `synthetic_test` accepts only allowlisted synthetic images, never camera/gallery | Prevents screening real people through a demo account |
| D11 | 404 (not 403) for records outside the caller's grants | Prevents ID enumeration |
| D12 | Bilirubin estimation impossible in schema 2.0 (schema clause) | Enabling it must be a reviewed MAJOR change, not configuration |
| D13 | Model release status can only come from a signed manifest | A remote flag must never promote a model |

### Questions that need your approval

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | Keep an anonymous offline tutorial (bundled synthetic images, camera off, nothing saved)? This changes today's "mark any profile synthetic" behaviour | Tutorial kept; profile checkbox removed |
| Q2 | Accept contract 2.0 alongside 1.x (D1), with 1.x retired after both clients migrate? | Yes |
| Q3 | Accept OOD-blocking (D3) and guide-crop incompatibility (D4)? The visible effect: the research Hb toggle produces no value for any camera capture | Yes |
| Q4 | Retire the sclera capture for jaundice inference (D5) and move the newborn flow to forehead/sternum skin? | Yes, after clinician wording review |
| Q5 | Proposed defaults (access token 15 min, clinician grant 90 days, image rate limit 10/min and 100/day per user, offline permission token ≤ 24 h)? | Configurable; tuned in Phase 4/8 |

### Still open (not resolved here)

CI fixes F1/F2 (awaiting approval) · `kushagra-p1` branch decision · OAuth client IDs and release signing fingerprint · production domain · database host and deployment · dataset licences and redistribution rights · email/WhatsApp providers · retention periods · guardian verification method.

### Dependencies blocking later phases

| Phase | Blocked by |
|---|---|
| 4 | CI approval (F1/F2) for the CI parts only; everything else can start |
| 5 | Clinician review of capture wording; Q3/Q4 |
| 6 | Q2; ADR-005 acceptance (SQLCipher) |
| 7 | A validated segmentation step for any Hb estimate (data-licence blocked); otherwise only the refusal paths can be built |
| 8 | OAuth client IDs, domain, database host (ADR-003/004) |
| 9–10 | Lab-OCR/LLM provider choice; consent texts |
| 11 | Domain (App Links), email/WhatsApp providers |
| 12 | Release and model-signing keys |
| Any clinical estimate | Dataset licences, bilirubin labels, maternal and app-captured Hb data, independent validation |

### Audit finding → phase → acceptance test

| Finding | Phase | Acceptance criteria |
|---|---|---|
| H1 noise and modality | 5, 7 | AC-CAP-01, 02, 03 |
| H2 OOD still shows a value | 7 | AC-CAP-04, 11 |
| H3 Hb on guide crops | 5, 7 | AC-CAP-04, 05 |
| M1 skin model on sclera | 5 | AC-CAP-02 |
| M2 EXIF orientation | 4 | AC-CAP-06, 07 |
| M3 warnings lost | 6, 9 | AC-REC-01, 02, 04, 05 |
| M4 unpinned jaundice artifact | 7 | AC-MOD-02 |
| M5 checkbox research mode | 8 | AC-STAT-01, 02, 05 |
| M6 open image endpoints | 4, 8 | AC-SEC-09, 10; AC-STAT-03 |
| M7 research assets in local APK | 4, 12 | AC-MOD-07 |
| L1 readiness | 4 | AC-MOD-01, 06 |
| F3 LLM text in reports | 9, 10 | AC-REC-05, AC-LLM-05 |

## Phase 4 engineering foundation and security hardening (24 October 2026): implemented and tested locally; CI not applied

Nothing committed or pushed. No dataset, model weight, `.env`/`.env.example`, screenshot or active CI workflow was modified. Research switches remain off in configuration (`.env`: anemia `=0`, image flag unset; Android default `false`).

### Files changed

| Repo | Modified | New |
|---|---|---|
| web | `backend/app/main.py` (auth, rate limits, readiness, orientation, configured size limit), `backend/app/ml/imageio.py` (EXIF orientation), `backend/app/ml/registry.py` (fingerprint re-verification, `diagnose`), `backend/app/models/schemas.py` (contract 1.2.0), `backend/app/services/store.py` (`ping`), `scripts/package_release.py` (final archive gate, `assets/models` exclusion), `tests/conftest.py`, `tests/test_ml.py`, `tests/test_contract.py` (authenticated fixtures), `README.md`, `docs/API_CONTRACT.md`, `docs/ml_integration.md`, `docs/security_and_permissions.md` and `docs/capture_protocols.md` (status lines) | `backend/app/core/{config,auth,ratelimit}.py`, `scripts/issue_access_token.py`, `scripts/check_release_artifacts.py`, `tests/test_{orientation,security,config,readiness,release_artifacts}.py`, `docs/configuration.md`, `docs/adr/ADR-007-interim-access-tokens.md`, `docs/ci_proposal/` |
| android | `app/build.gradle.kts` (`RESEARCH_MODELS_ALLOWED`, release artifact verification), `core/EdgeModels.kt` (`EdgeModelPolicy`, SHA-256 pins incl. jaundice class), `core/ImageAnalysis.kt` (`applyExifOrientation`), `ui/AppViewModel.kt` (gallery EXIF, policy), `EdgeModelsTest.kt`, `docs/edge_ai.md` | `ExifOrientationTest.kt` |

### Decisions

| # | Decision | Rationale |
|---|---|---|
| P4-1 | Parse the EXIF orientation tag in our own code and apply it once after `cv2.imdecode(IMREAD_UNCHANGED)` (which ignores EXIF); same for the training reader | Explicit and testable; avoids double rotation; keeps alpha. Pillow is only a transitive dependency of reportlab |
| P4-2 | Unreadable orientation: CNN task → `422 ORIENTATION_UNKNOWN`; cf-v1 Hb → result with warning `ORIENTATION_UNKNOWN`; training reader → error | Contract AC-CAP-07; colour features are nearly rotation-invariant, the CNN is not |
| P4-3 | Interim HS256 server tokens, no new dependency, no bypass ([ADR-007](adr/ADR-007-interim-access-tokens.md)) | OAuth IDs do not exist; identity must still be verified |
| P4-4 | Research routes **and** MODEL-mode screenings require `research_operator`; flags remain kill switches | M5/M6; MODEL mode reaches research adapters too |
| P4-5 | Contract **1.2.0**, not 2.0.0, despite tightening research routes | Android accepts only `1.x` (`Contract.fromVersion`); no client uses the tightened routes. Documented as an exception in `API_CONTRACT.md` |
| P4-6 | In-process rate limiter; production refuses more than one worker | Matches today's single-worker Docker image; a shared store is needed before scaling out |
| P4-7 | Unknown `ABHAYNAYAN_ENV` refuses to start anywhere; weak keys are never used in any environment | Fail closed; development stays usable without secrets |
| P4-8 | Research flags are errors in `production` | Artifacts derive from unlicensed datasets (M7) |
| P4-9 | Android: compiled-in SHA-256 pins for every edge artifact; release builds load none; release APK/AAB containing research files fails the build and is deleted | M4, M7: "file present" must never be enough |
| P4-10 | Android gallery uses the framework `android.media.ExifInterface` (lint suggests AndroidX) | No new dependency in Phase 4; see Q7 |

### Conflict with existing tests (resolved without weakening)

Four `test_contract.py` tests and the `test_ml.py` route tests called research routes anonymously. Under the Phase 3 contracts that must now fail with 401. Resolution: their fixtures authenticate with a real server-signed `research_operator` token (key exists only in the pytest process), so every original assertion still runs **behind** authentication. `test_security.py` covers the anonymous, forbidden, expired and rate-limited cases. One assertion's hard-coded `'1.1.0'` now reads `API_CONTRACT_VERSION`.

### Tests and results

| Suite | Before Phase 4 | After |
|---|---|---|
| Python (`.venv`, `.venv-ml`) `PYTHONPATH=backend python -m pytest -q` | 197 passed | **373 passed** (both venvs; 8 trained-artifact tests pass in `.venv-ml`, including golden outputs after the orientation change) |
| Node `npm test` | 32 + 4 passed | 32 + 4 passed |
| Android `:app:testDebugUnitTest` | 132 run, 0 failed, 1 skipped | **140 run, 0 failed, 1 skipped** (skip = live-backend test; `trainedAssetsReproducePythonGoldenOutputs` passes against the compiled-in pins) |
| Android `:app:lintDebug`, `:app:assembleDebug` | 0 errors, 15 warnings (Phase 1 recorded 16: that `grep -c '<issue'` also matched the `<issues>` root element) | 0 errors, 17 warnings (+2 `ExifInterface` suggestions, P4-10) |

Additional evidence (one-off runs, not automated):

- **Training-reader parity:** the new `read_path` on all 617 Hb and 755 NJN training images gives 0 changed feature vectors (max abs diff 7e-15); no training image carries a rotating EXIF tag. No retraining needed; audit metrics unaffected.
- **Live server** (uvicorn, temporary DB, flag set only in that shell): `/api/ready` 200 `ready` with clinical inference disabled and 4/4 models verified; Hb route → `UNAUTHENTICATED` / `TOKEN_INVALID` / `FORBIDDEN` (patient token) / research result (operator token); token absent from the server log; `ABHAYNAYAN_ENV=production` with weak config → `Application startup failed` naming variables only.
- **Secret scan** of `web-dashboard/` and the debug APK for key patterns and the `.env` secret values: 0 hits.

### Release artifacts: verified separately from configuration

| Check | Result |
|---|---|
| Build configuration | `RESEARCH_MODELS_ALLOWED=false` in the generated release `BuildConfig`; verification tasks wired to `assembleRelease` / `bundleRelease` |
| Release APK built **with** local research assets present | **Build failed** at `verifyReleaseApkHasNoResearchModels`, listing the 3 asset files; the rejected APK was deleted |
| Release APK + AAB built from a copy **without** the gitignored assets (as a clean CI checkout) | Build succeeded; both archives verified by the Gradle task **and** independently by `scripts/check_release_artifacts.py` / `unzip -l`: no research files (APK 8.4 MB, AAB 8.0 MB, unsigned, deleted after the check, never distributed) |
| Local debug APK (`app/build/outputs/apk/debug/app-debug.apk`) | **Contains** the 3 research assets, as expected for a debug build on this machine. **Do not distribute it** |
| Backend release ZIP (`package_release.py --output <scratch>`) | Built; checker: no research files; `models/` holds only `MODEL_REGISTRY.json` and `anemia_color_baseline.json`. Deleted after the check |
| Dockerfile | Copies only `models/anemia_color_baseline.json` (locked by `test_release_artifacts.py`) |

### Phase 4 acceptance criteria

| Criterion | Status | Evidence / gap |
|---|---|---|
| AC-CAP-06 orientation consistency | **Satisfied (backend, training reader, Android transform)**; Android `ExifInterface` read path untested | PNG: identical pixels, features and CNN tensors for all 8 tags; JPEG matches OpenCV's own EXIF decode exactly; Kotlin matches the EXIF definition. The framework EXIF read needs instrumentation/device tests |
| AC-CAP-07 unknown orientation | **Satisfied** (backend) | `test_unknown_orientation_blocks_cnn_but_warns_for_colour_model` |
| AC-MOD-01 missing model | **Satisfied** | readiness `artifacts: missing`; 503 `MODEL_UNAVAILABLE`; Android `noAssetsMeansDisabledAndNoValue` |
| AC-MOD-02 checksum mismatch (Hb and jaundice) | **Satisfied** | backend readiness + route; Android `tamperedJaundiceArtifactIsRefused`, `compiledPinsReject…` |
| AC-MOD-06 readiness reflects restore | **Satisfied** | `test_restored_artifact_is_reverified_without_restart` |
| AC-MOD-07 no research assets in distributed builds | **Partially**: enforced by the build and verified on real artifacts locally; **CI enforcement awaits approval** | see table above |
| AC-SEC-08 token checks | **Partially**: server tokens (signature, alg, iss, aud, exp, iat, nbf, TTL, roles) satisfied; Google ID-token checks and refresh-token reuse **blocked** (Phase 8, OAuth IDs) | `test_security.py` |
| AC-SEC-09 rate and size limits | **Satisfied** (single process) | per-user minute/day, concurrency, per-IP auth failures, 413 before read, thread-exact limiter |
| AC-SEC-10 unauthenticated image endpoints closed | **Satisfied** for `/api/ml/*` and MODEL mode (v2 inference does not exist yet) | 401 even with the flag on, before the body is read |
| AC-SEC-11 secrets absent from clients | **Partially**: startup validation and a one-off scan done; automated CI scan not implemented | |
| AC-STAT-03 flags are kill switches only | **Satisfied (backend)**; Android toggle still enables research models in **debug** builds without a token (AC-STAT-05, Phase 8) | |
| AC-STAT-06 defaults stay off | **Partially**: server default and readiness tested; fresh-install emulator check not run | |
| AC-REC-10 no PII/tokens in logs | **Partially**: tokens, keys and config values verified absent from logs; full e2e log scan in Phase 8 | |

Other AC rows remain in their planned phases ([phase3_acceptance_criteria.md](phase3_acceptance_criteria.md)). Cross-patient access (AC-SEC-01…05) cannot be tested yet: the server holds only synthetic demo records with no per-user ownership (blocked on Phase 8).

### CI proposal (not applied)

Prepared in [ci_proposal/](ci_proposal/README.md): drop the failing `android` job from web CI, add a release-ZIP research-artifact job, and add a root `android.yml` to the Android repo (tests, lint, debug, release and bundle checks; `chmod +x gradlew`, because the file is stored as mode 100644). Both patches pass `git apply --check`. **Awaiting your approval.** The rest of Phase 4 does not depend on it.

### Remaining blockers and questions

| # | Item |
|---|---|
| Q6 | Approve the CI patches (and optionally fix `gradlew`'s Git mode instead of `chmod` in CI) |
| Q7 | Add `androidx.exifinterface` (broader format support on older Android; removes 2 lint warnings)? |
| Q8 | Apply the proposed `.env.example` additions in [configuration.md §3](configuration.md)? |
| — | Still open from earlier phases: Q1–Q5, `kushagra-p1`, OAuth IDs, domain, database host, dataset licences |
| — | Rate limiting must move to a shared store before running more than one worker |

## Phase 4 approved follow-ups Q6, Q7, Q8 (24 October 2026): applied, uncommitted

### Files changed

| Repo | Change |
|---|---|
| web | `.github/workflows/ci.yml`: `web-ci.patch` applied (removed the failing `android` job; added `release-artifacts`) |
| web | `.env.example`: placeholders and production-required markers for `ABHAYNAYAN_ENV`, `ABHAYNAYAN_SESSION_SIGNING_KEY`, token TTL, rate limits, upload limit, `ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS=0`, the origin and single-worker notes. `.env` untouched |
| web | `tests/test_config.py`: 4 tests proving `.env.example` covers every validated variable, starts in development with research closed, is rejected in production, and holds no secret values |
| web | `docs/ci_proposal/README.md` (status), this section |
| android | **new** `.github/workflows/android.yml` (from `android-ci.patch`, minus the `chmod` step) |
| android | `AbhayNayan/android/gradlew`: Git mode **100644 → 100755** (staged with `git update-index --chmod=+x`; content unchanged) |
| android | `app/build.gradle.kts`: `implementation("androidx.exifinterface:exifinterface:1.4.1")` (direct coordinates; the project has no version catalog) |
| android | new `vision/ExifOrientationReader.kt`; `ui/AppViewModel.kt` uses it instead of `android.media.ExifInterface` |
| android | new `ExifOrientationReaderTest.kt` + `src/test/resources/exif_orientation/` (12 synthetic Pillow-generated fixtures) |

Dependency impact: the only new artifact is `exifinterface` 1.4.1. Its transitives (`annotation` → resolves to the existing 1.9.1; `jspecify` 1.0.0) were already on the classpath, so nothing was upgraded. Lint now reports 1.4.2 as available; it was kept at 1.4.1, the version known before this session.

### CI safeguards verified (static review)

Both workflows trigger on every push, every pull request and manual dispatch, with `permissions: contents: read`. No step has `continue-on-error`. No `secrets.*` are referenced. The Android job uploads only `build/reports/` and `build/test-results/` (7 days). No APK/AAB is uploaded or published, and release outputs are unsigned and only verified. The backend release-ZIP research check is retained.

### Tests and dry runs

| Check | Result |
|---|---|
| Python, working tree (`.venv`, `.venv-ml`) | **377 passed** (373 + 4 new) |
| Node, working tree | 32 + 4 passed |
| Android, working tree `:app:testDebugUnitTest :app:lintDebug :app:assembleDebug` | **145 run, 0 failed, 1 skipped** (+5 reader tests); lint 0 errors, 16 warnings (the 2 `ExifInterface` warnings are gone; +1 `GradleDependency` for exifinterface 1.4.2) |
| **Android CI dry run**: exact workflow command on a snapshot of tracked + new non-ignored files (no research assets, no `local.properties`, `ANDROID_HOME` set) | exit 0; 145 run, 0 failed, 2 skipped (trained-asset parity and live backend, as expected without gitignored assets); release APK and AAB verified by Gradle and `check_release_artifacts.py`; uploaded report dirs contain no model files |
| Failing-test probe in the snapshot | deliberate failure → Gradle exit 1, so the CI job would fail |
| **Web CI dry run**: same snapshot approach, fresh venv with `requirements.txt` only | `python-api`: compileall ok, `pip check` clean, **368 passed, 9 skipped** (trained-artifact tests skip without models); `web`: 32 + 4 passed, `check:web` ok; `release-artifacts`: ZIP 165 files / 2.3 MB, checker ok |
| Release guard, working tree with local assets | `assembleRelease` fails and deletes the APK |

**Could not be run here:**

- GitHub-hosted runs. Nothing was pushed, so the workflows have not executed on GitHub.
- JDK 17. Only JDK 22 is installed; CI uses Temurin 17 and the project targets Java 17.
- Actual Linux checkout of the 100755 `gradlew`. The mode is verified in the index only; Windows has `core.fileMode=false`.

### Found during the dry run (not fixed; outside the approved scope)

`scripts/package_release.py` excludes virtualenvs only by directory name (`.venv`, `venv`, …). A virtualenv with another name inside the repository is packaged (the dry run's `.ci-venv` added 3,009 files / 206 MB before it was moved out). This does not affect CI, where setup-python installs outside the checkout. Proposed fix for a later phase: exclude any directory containing `pyvenv.cfg`.

## Phase 5 guided capture, quality control and safe outcomes (24 October 2026): implemented, uncommitted

No clinical inference enabled, no model weights, datasets, `.env` or screenshots changed, and no commit. The staged `gradlew` mode change (100644 → 100755) is preserved unchanged.

### What changed in behaviour

- **No app capture reaches a model.**
  - Android camera frames are guide-rectangle crops → `TARGET_REGION_INCOMPATIBLE`.
  - Masked gallery imports are unverified → `MODALITY_UNVERIFIED`.
  - The newborn workflow is always `NO_VALIDATED_MODEL_FOR_TASK`.
  - The NJN research scorer is no longer run on app captures (audit H3, M1).
- **The backend research routes fail closed too.** Opaque Hb uploads → `TARGET_REGION_INCOMPATIBLE`; masked NJN uploads → `MODALITY_UNSUPPORTED`; out-of-distribution inputs → `INPUT_OUT_OF_DISTRIBUTION` (previously a warning); otherwise `MODALITY_UNVERIFIED`, because masked pink noise passed every other gate in 20/20 trials.
- **Every analysed Android capture has a contract 2.0 envelope** (`estimated` / `unable_to_estimate` / `synthetic_fixture`), validated by `PredictionInvariants` before it can be stored, kept in Room v3 `predictionJson`, and shown on the result screen, the record screen and the PDF/text report with all warnings. Legacy records say "Not recorded".
- **Protocols:** separate `anemia-palpebral` / `newborn-skin` guides and versioned (uncalibrated) quality rules. The newborn flow is labelled a research/design prototype, photographs forehead or upper-chest skin chosen in advance, and **never switches on the phone light**.
- **Bounded retries:** 3 rejected captures, then "record without a photo result" (`CAPTURE_RETRY_LIMIT`) or "exit". Camera and permission problems are shown separately and not counted.
- **Stale values:** every new capture or analysis clears the previous outcome; a failed analysis never keeps an earlier value (`WorkflowTransitions`).
- **Multi-frame capture: deferred** (not testable on the emulator camera).

### Files

| Repo | Modified | New |
|---|---|---|
| android | `core/{CameraModel,EdgeModels,ImageAnalysis,ModelContract,Workflow}.kt`, `data/LocalData.kt` (Room v3), `interop/ReportDocument.kt`, `ui/{AppViewModel,CameraPanel,RecordScreens,Strings,WorkflowScreens}.kt`, `vision/Camera2PreviewView.kt`, `scripts/verify_room_migration.py` (2→3 check), tests `EdgeModelsTest`, `WorkflowEngineTest`, `ReportDocumentTest` | `core/Prediction.kt`, `core/CaptureProtocol.kt`, `ui/WorkflowTransitions.kt`, `app/schemas/.../3.json`, tests `CaptureOutcomeTest`, `PredictionContractTest`, `WorkflowTransitionsTest`, resources `prediction_contract/` (5 examples) |
| web | `backend/app/main.py`, `backend/app/models/schemas.py` (contract 1.3.0), `tests/{conftest,test_ml,test_orientation,test_security}.py`, `docs/{API_CONTRACT,prediction_contract,capture_protocols,record_contract,phase3_acceptance_criteria}.md` | `backend/app/core/prediction.py`, `tests/test_capture_outcomes.py` |

### Tests whose expectations changed (strengthened, not weakened)

| Test | Before | Now |
|---|---|---|
| Android `maternalWorkflowNeverCallsTheBilirubinModel`, `experimentalEdgeModelProducesLabelledLocalEstimate…`, `implausibleOrFailing…`, `inferenceExceptions…` | the model ran on a synthetic chart / masked import | refused without a verifier; the model path is exercised only with an injected test verifier (production has none) |
| Android `neonatalWorkflowUsesBilirubinModel…` | the bilirubin model was called | `neonatalWorkflowNeverCallsAnyModel` |
| Backend `test_out_of_distribution_warning` | value plus warning | `test_out_of_distribution_input_is_refused` |
| Backend `test_real_jaundice_route_end_to_end` | golden score through the route | golden image is OOD on 8 features → refused; score reproduction still checked directly |
| Backend NJN, quality, orientation route tests | masked/opaque inputs as before | inputs changed to the form each route accepts |

### Results (exact commands)

| Check | Result |
|---|---|
| `PYTHONPATH=backend .venv/Scripts/python -m pytest -q` | **404 passed, 1 skipped** (JSON-Schema cross-check needs `jsonschema`) |
| same with `.venv-ml` | **405 passed** (includes trained-artifact and JSON-Schema checks) |
| `npm test` | see the final verification below |
| `./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug` | **173 run, 0 failed, 1 skipped**; lint 0 errors, 16 warnings (unchanged) |
| `python scripts/verify_room_migration.py` | 1→2 PASS, 2→3 PASS |
| Route probe on the 54 held-out patients (private data, aggregates only) | app-style crops 54/54 `TARGET_REGION_INCOMPATIBLE`; segmented crops 44 `MODALITY_UNVERIFIED` + 10 `TARGET_REGION_INCOMPATIBLE` (opaque-background crops); with a test verifier, 44 estimates, MAE 1.31 (matches the Phase 2 served-path figure) |
| **Emulator** (`abhay_api36`; not a physical device) | upgrade install over a v2 database → `user_version 3`, 4 legacy rows intact; newborn flow: prototype notice, site choice, camera capture with "Phone light not used", glare rejection, counter 1→3, limit card, saved `CAPTURE_RETRY_LIMIT` record with `predictionJson`, record screen outcome details; legacy record shows "Not recorded"; no app crash in logcat |

**Not verified:** physical-device camera behaviour and colour; real eyelid or newborn captures; JDK 17 builds; the PWA (unchanged: it never sends images to models and shows only fixtures).

### Open items and decisions needed

| # | Item |
|---|---|
| Q9 | ~~AC-PRED-05 conflict: should a failed *inference* (model error) be saved as an `error` record, or stay unsaved as now?~~ Decided and implemented in Phase 6 |
| Q10 | Clinician review of the anemia and newborn capture wording; native-speaker review of the new Hindi/Bhojpuri subtitle |
| — | Threshold calibration needs labelled app captures (capture_protocols.md §4) |
| — | Body-site verification / segmentation needs a licensed, validated component (blocked on data licences) |
| — | Still open: Q1–Q5, `kushagra-p1`, OAuth IDs, domain, database host, dataset licences |

## Phase 6 offline-first foundation, encrypted storage and record integrity (24 October 2026): implemented, uncommitted

No clinical inference was enabled; research switches stay off (`.env` `ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA=0`, image flag absent, Android `experimentalModels` default false, release `RESEARCH_MODELS_ALLOWED=false`). No model weights, datasets, `.env` or screenshots were changed, and there was no commit. The staged `gradlew` mode change (100644 → 100755) is preserved.

### Decisions

| # | Decision |
|---|---|
| ADR-005 | **Accepted.** SQLCipher `sqlcipher-android` 4.12.0 under Room 2.7.2. The passphrase is wrapped by an Android Keystore AES-GCM key, and the plaintext database is moved after a verified copy. Evidence, lifecycle and limits are in [ADR-005](adr/ADR-005-local-encryption.md) |
| Q9 | **Decided.** An analysis that started and then failed is saved atomically as a no-value record: `error` for system errors, `unable_to_estimate` for discarded output or an unverifiable model. Nothing is saved for a failure before analysis (rejected capture, camera or permission problem, cancellation). A failed save is reported as "nothing was recorded" ([prediction_contract.md §4](prediction_contract.md)) |
| Record integrity | Implemented on the existing `screenings` table (Room v4), not as a parallel record model: `abhaynayan.record-hash/1`, a `record_warnings` index and immutability triggers ([record_contract.md §8](record_contract.md)) |
| Sync | **No compatible endpoint exists** (contract 1.3.0). Envelope sync is disabled. Its contract is specified as proposed ([API_CONTRACT.md §7](API_CONTRACT.md)) and its payload builder and server-side verifier are tested. The 1.x demo sync continues, now with an integrity gate |

### Files

| Repo | Modified | New |
|---|---|---|
| android | `app/build.gradle.kts` (SQLCipher 4.12.0; androidTest runner/ext-junit/room-testing; schemas as androidTest assets), `AbhayApp.kt`, `MainActivity.kt` (storage gate), `data/{LocalData,ScreeningRepository}.kt` (v4, sealed atomic saves, verified reads), `core/{Prediction,Workflow}.kt` (Q9), `sync/{SyncEngine,SyncWorker}.kt`, `ui/{AppViewModel,RecordScreens,WorkflowScreens,WorkflowTransitions}.kt`, `scripts/verify_room_migration.py` (3→4), tests `WorkflowEngineTest`, `WorkflowTransitionsTest`, `SyncEngineTest`, `android/README.md`, `docs/SAFETY.md` | `data/{RecordIntegrity,RecordMigrations,SecureStorage,SecureDatabase}.kt`, `sync/OutcomeSync.kt`, `ui/StorageScreens.kt`, `schemas/.../4.json`, tests `data/RecordIntegrityTest`, `data/SecureStorageTest`, `sync/OutcomeSyncTest`, `androidTest/.../SecureDatabaseInstrumentedTest`, resource `record_integrity/vectors.json` |
| web | `docs/{API_CONTRACT,architecture,prediction_contract,record_contract,security_and_permissions,phase3_acceptance_criteria,implementation_plan}.md`, `docs/adr/ADR-005-local-encryption.md` | `backend/app/core/record_integrity.py`, `tests/test_record_integrity.py`, `tests/fixtures/record_integrity_vectors.json` |

`WorkflowTransitions.kt` and `WorkflowTransitionsTest.kt` were new in Phase 5 (untracked) and were extended here. No backend route, schema or API contract version changed.

### Tests whose expectations changed

| Test | Before | Now |
|---|---|---|
| `SyncEngineTest.FakeStore` | stored records as given | seals each record and its warning index on insert, as the v4 database does, and implements the new `SyncStore.integrity`. All earlier assertions are unchanged |
| `WorkflowEngineTest.inferenceExceptionsAndInvalidOutputsNeverBecomeResults` | unchanged | still passes. The new `failedAnalysisCarriesAValidNoValueRecord` also requires the model **not** to be called when its checksum is missing (the check moved before inference) |

### Results (exact commands)

| Check | Result |
|---|---|
| `PYTHONPATH=backend .venv/Scripts/python -m pytest -q` | **418 passed, 1 skipped** (the JSON-Schema cross-check needs `jsonschema`, which is absent from `.venv`) |
| same with `.venv-ml` | **419 passed** |
| `npm test` | 32 + 4 passed; `check:web` ok |
| `./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleDebugAndroidTest` | **198 run, 0 failed, 1 skipped** (`liveBackendAcceptsRecordAndProducesReferralPdf`, which needs a live backend, as before). Lint: **0 errors**, 20 warnings: the earlier 16, plus `NewerVersionAvailable`/`GradleDependency` for the new libraries |
| `python scripts/verify_room_migration.py` | 1→2 PASS, 2→3 PASS, 3→4 (schema) PASS |
| Instrumented `SecureDatabaseInstrumentedTest` via `adb shell am instrument` on `abhay_api36` (API 36 emulator) | **13/13 passed**, run twice. Run manually rather than with `connectedDebugAndroidTest`, so the app's data was not uninstalled |
| Doc validator (JSON blocks, prediction examples, Mermaid) | ALL CHECKS PASSED |
| **Emulator upgrade** of the installed Phase 5 app (plaintext v3 with WAL, 5 records) | The first attempt failed safely: `ATTACH` could not create the target file. The app showed "Records not yet moved" and kept the source, and the bug was fixed. The second attempt migrated all 5 records: plaintext files removed, encrypted file without the SQLite header, legacy labels and stored values shown. A new demo record shows "unchanged since it was saved". 6 records after a forced stop and restart |

**Not verified:**
- physical-device behaviour (Keystore/StrongBox hardware, performance, OEM storage);
- JDK 17 builds;
- airplane-mode network counting (AC-OFF-01);
- the Q9 path in the UI: no production input reaches a model, so it is covered by unit tests only;
- live e2e sync after restart.

### Remaining blockers and open items

| Item | Status |
|---|---|
| Envelope sync (AC-REC-02) | Blocked on the v2 endpoint, which needs auth/grants (Phase 8; OAuth client IDs open) and server storage (ADR-003) |
| Record 2.0 restructuring (`legacy_source`, annotations, outbox tables) | Design only |
| Physical-device test of encryption and migration | Needs a phone |
| Q10 | Clinician review of the capture wording and native-speaker review of the Hindi/Bhojpuri subtitle: still external, not done |
| Emulator housekeeping | 9 empty `it-*.lck` files from the first instrumented run remain in the app's `databases/` (a safety check blocked their removal; the test now cleans up its own) |
| Still open | Q1–Q5, `kushagra-p1`, OAuth IDs, domain, database host, dataset licences, threshold calibration, body-site verifier |

## What already exists (do not rebuild)

- **Contract 1.0.0** shared by PWA and Android: error envelope, explicit `provenance`, idempotent creates, per-record sync results (`accepted/duplicate/conflict/rejected`).
- **Fail-closed model boundary** on all three clients: `DISABLED_NO_VALID_MODEL`, no fixture fallback, output validation that discards rather than clamps.
- **Research ML** (22 Oct 2026). Every model below is **Implemented, Trained, Evaluated, Integrated behind an off-by-default flag**, and none is validated:
  - `hb-ridge-cf` (edge) and `hb-hgb-cf` (backend). Eyes-defy test MAE ≈ 1.3 g/dL. Worse than the mean on unseen CP-AnemiC hospitals.
  - `njn-logreg-cf` (edge) and `njn-mnv3-logreg` (backend). This is a dataset-class score, not bilirubin.
- **MobileNetV3-Small was already evaluated.** It did not beat colour features for Hb (grouped CV R² 0.42 vs 0.50). It was best for the NJN class (AUROC 0.920 held out, leakage not ruled out). See [ml_evaluation.md](ml_evaluation.md).
- **Bilirubin is blocked**: no bilirubin labels exist in any local dataset ([dataset_requirements.md](dataset_requirements.md)).
- **Android**: Kotlin + Compose, Camera2 ambient/torch pair with exposure lock, quality gate, Room v2 with sync columns, WorkManager sync, on-device PDF report, pure-Kotlin JSON model runtime with SHA-256 pinning.

## Checklist by stage

Priority: P0 = blocks safe progress, P1 = next increment, P2 = later. "Blocked" lists the missing input.

### Stage 1 — audit and synchronization
- [x] Inspect both repos, remotes, branches, HEADs, uncommitted work; fetch upstream (no merge needed)
- [x] Inventory components; identify canonical sources and stale copies
- [x] Run all tests/builds and record the baseline (above)
- [x] Write this plan, [architecture.md](architecture.md) and the ADRs
- [ ] Decide what happens to unmerged remote branch `kushagra-p1` (needs owner input)

### Stage 2 — architecture decisions and CI repair
- [ ] P0 F1: drop the Android job from web-repo CI ([ADR-001](adr/ADR-001-canonical-sources.md))
- [ ] P0 F2: root-level CI in the Android repo: unit tests, lint, debug APK
- [ ] P1 Remove the stale `android/` copy from the web repo and the stale backend/PWA copy from the Android repo, once both owners agree
- [ ] P1 Accept or amend ADR-002…ADR-006

### Stage 3 — ML pipelines
- [x] Separate Hb and NJN-class pipelines: validation, quality gate, cf-v1 preprocessing, inference, output validation, provenance, fail-closed state (Implemented, Python ↔ Kotlin parity to 1e-6)
- [x] MobileNetV3-Small compared with colour-feature models (done 22 Oct; see above)
- [x] Phase 2 model/pipeline audit with live smoke tests and input-domain probe ([model_audit.md](model_audit.md))
- [ ] P0 H1/H2: refuse inference on inputs that fail target-region validation or are out of distribution → `UNABLE_TO_ESTIMATE` (server and Android)
- [x] P1 M2: EXIF-orientation handling in `imageio.decode` and `read_path`, with a regression test (Phase 4; Android gallery too)
- [ ] P1 M3: persist model warnings (OOD, research-only) with the record and print them in reports
- [x] P1 M4: SHA-256 pin for the edge jaundice-class artifact (Phase 4: compiled-in pins for all edge artifacts; a separate metadata file is still to do)
- [ ] P1 Common `ScreeningModule` descriptor (Stage 14) wrapping both pipelines
- [ ] P2 Anatomical localization (eye/conjunctiva; newborn skin region). The current ROI is manual. Needs a licensed landmark model and labelled ROI data
- [ ] **Blocked:** bilirubin regression. Needs paired TSB/TcB labels ([dataset_requirements.md §3](dataset_requirements.md))
- [ ] **Blocked:** any maternal-population evaluation. Needs pregnant-cohort Hb images captured with the app
- [ ] **Blocked:** publishing any trained artifact. Needs licence/consent confirmation ([DATA_PROVENANCE.md §6](DATA_PROVENANCE.md))
- [ ] P2 Device latency/memory measurement of the edge models on named phones

### Stage 4 — guided capture
- [x] Quality gate (brightness, glare, blur, target, motion) separate from estimation; manual ROI guide; flash pair validation
- [ ] P1 Per-protocol capture config (`CaptureProtocol`: anemia palpebral conjunctiva vs neonatal forehead/sternum), with thresholds, instructions and retry limits
- [ ] P1 Multi-frame burst: reject failing frames, select the best by a documented score, cap retries, return explicit `UNABLE_TO_ESTIMATE`
- [ ] P1 Live guidance text ("hold still", "move closer", "reduce glare") driven by the measured criteria
- [ ] P2 Evaluate CameraX migration ([ADR-002](adr/ADR-002-android-stack.md)): only if it keeps exposure-locked flash pairs
- [ ] Neonatal copy: safe positioning only, danger signs → immediate care, never "wait for the app"

### Stage 5 — offline-first
- [x] Local capture, quality checks, local inference (research build), Room history, sync queue with stable IDs and per-record results
- [x] P1 Room encryption with a Keystore-wrapped key ([ADR-005](adr/ADR-005-local-encryption.md)) and migration tests from v1/v2/v3 (Phase 6; emulator-verified only)
- [x] P1 Record integrity: content hashes, warning index, legacy classification, verification on load/export/sync (Phase 6)
- [ ] P1 Envelope sync (`/api/v2/sync`, proposed in API_CONTRACT.md §7): blocked on auth and server storage
- [ ] P1 Sharing outbox table (Stage 9) next to the sync outbox
- [ ] P1 Offline/online status chips on every cloud-only action
- [ ] Explicit, per-record opt-in before any photo upload (none exists today; keep it that way by default)

### Stage 6 — identity and records
- [ ] P1 Backend: verify Google ID tokens server-side; issue short-lived app session tokens ([ADR-004](adr/ADR-004-identity.md))
- [ ] P1 Data model: `users`, `subjects`, `relationships` (patient/caregiver/clinician grants with scope and expiry), `organizations`, `audit_log`
- [ ] P1 Authorization checks on every record route plus negative tests (unauthorized patient access → 404/403)
- [ ] P1 Android: Credential Manager "Sign in with Google"; tokens in encrypted storage, separate from the Room key
- [ ] P2 Revocation, device loss, export, deletion, retention policy
- **Blocked on you:** Google Cloud OAuth client IDs (Web and Android, with the release SHA-256 signing fingerprint)

### Stage 7 — laboratory report ingestion
- [ ] P2 Strict schema `LabResult{test_code, value, unit, ref_low, ref_high, collected_at, source_doc_id, page, bbox, ocr_confidence, confirmed_by_user}`
- [ ] P2 First scope: CBC hemoglobin and serum total/direct bilirubin only. Reject other tests explicitly
- [ ] P2 OCR or multimodal extraction on the server; unit whitelist (g/dL, g/L, mg/dL, µmol/L) with exact conversions; anything ambiguous → user confirmation
- [ ] Measured lab values are stored separately from image estimates and never averaged with them

### Stage 8 — reports and chatbot
- [ ] P1 F3: deterministic report body from verified fields only. Include previous results (same subject, same biomarker, labelled by provenance), missing data and limitations
- [ ] P1 LLM explanation in a separate, labelled section; response schema checked against the report facts (numbers, units and dates must appear in the input); reject on mismatch
- [ ] P2 Chatbot endpoint with the same grounding validator and a refusal path for diagnosis/treatment/urgent neonatal questions → escalation copy
- [ ] Offline: reviewed static help text and local reports only

### Stage 9 — sharing
- [ ] P2 Share flow: validated report → recipient + channel → confirmation → queue
- [ ] P2 Android: system share sheet / `mailto:` / WhatsApp intent. State = `HANDED_OFF` (never "delivered")
- [ ] P2 Server email (provider TBD) only with delivery webhooks, which are what allow `SENT/DELIVERED`
- [ ] Notifications and logs never contain values or names

### Stage 10 — portal and analytics
- [ ] P2 Role-based portal views on the existing PWA (patient, clinician, organization)
- [ ] P2 Aggregate analytics: district-level region, k ≥ 10 cohort suppression, no precise location collected
- [ ] P2 Android App Links: `assetlinks.json` served by the backend; browser fallback always works
- **Blocked on you:** production domain name and the release signing certificate fingerprint

### Stage 11 — CI/CD and model versioning
- [ ] P0 CI fixes (Stage 2)
- [ ] P1 Release workflow: signed release APK (key held in GitHub secrets, never in Git), checksums
- [x] SHA-256 pinned model registry; model version recorded per result; incompatible metadata refused
- [ ] P2 Signed model bundles (Ed25519 manifest signature, public key in the app), staged rollout, keep last known-good for rollback; a remote flag can never raise a model's validation status

### Stage 12 — security and privacy
- [ ] P1 Rate limiting and upload size/type limits on all image/document routes
- [ ] P1 Dependency audit (`pip-audit`, `npm audit`, Gradle dependency updates) and secret scanning in CI
- [ ] P1 Audit log without clinical content
- [ ] P2 DPDP Act 2023 / DPDP Rules 2025 review, including verifiable parental consent for children's data. Check CDSCO Medical Device Rules 2017 for software-as-a-medical-device. Do not claim compliance before an actual legal review

### Stage 13 — testing
- Every stage adds its own tests and reruns all three suites
- [ ] P1 Run the instrumentation/smoke path on the `abhay_api36` emulator and record it as **emulator-only**
- [ ] Physical device test (needs a phone over USB; not available today)

### Stage 14 — modular screening interface
- [ ] P1 `ScreeningModule` descriptor (backend + Kotlin) declaring input, target, preprocessing, model version, output schema, intended use, quality rules, evaluation evidence and reporting constraints; Hb and NJN-class as the first two modules

## Inputs needed from the project owner

1. Google OAuth client IDs (web + Android) and the release signing SHA-256 fingerprint
2. Production domain (App Links, CORS, OAuth redirect) and whether Render stays the host
3. PostgreSQL hosting choice (managed Render Postgres, Supabase, Neon …)
4. Email provider for server-side sharing, if wanted (otherwise system share only)
5. Whether WhatsApp Business API is in scope (needs a Meta business account) or only share intents
6. Agreement from both repo owners to delete the stale duplicate folders, and a decision on `kushagra-p1`
7. Any bilirubin-labelled or maternal datasets with confirmed licences
