# Model and prediction-pipeline audit (Phase 2)

Audit date: 24 October 2026. Code audited: `AbhayNayan_web` `master` @ `f52fde7` and `AbhayNayan_apk` `main` @ `06828c5`. No source file was changed during this phase. Datasets were read in place and nothing was modified or uploaded; all outputs below are aggregates. Earlier audits ([ml_audit.md](ml_audit.md), [ml_evaluation.md](ml_evaluation.md), [dataset_requirements.md](dataset_requirements.md)) were re-checked against code and re-run results rather than copied.

Reproduce the new measurements with the scripts in `scripts/audit/` (commands in §8).

## 1. Status by task

Each status needs its own evidence. "Yes" means the evidence in the next column exists and was checked in this audit.

### Anemia: hemoglobin (g/dL)

| Status | Answer | Evidence |
|---|---|---|
| Implemented in code | **Yes** | Backend: `backend/app/ml/{imageio,quality,features,registry}.py`, `main.py::_run_image_model`. Android: `core/ColourFeatures.kt`, `core/EdgeModels.kt`, `core/Workflow.kt::analyze` |
| Actually trained | **Yes**, on Eyes-defy-anemia (163 patients) | `models/hb_hgb_cf_v1.json`, `models/hb_ridge_cf_v1.json`; SHA-256 match `MODEL_REGISTRY.json` (re-verified); `scripts/ml/train_hb.py` |
| Evaluated on legitimate held-out data | **Yes, for the training input format only.** Patient-level held-out set of 54, selection recorded first (`ml/runs/hb-v1/selection.json` 12:38 UTC, before `final_results.json` 13:12 UTC). **Re-run today: identical metrics** (backend MAE 1.26, R² 0.47; edge MAE 1.30, R² 0.51). External site check: worse than the mean (R² −0.25 / −0.64) | §5.1 |
| Evaluated in the app's input format | **No, and the probe is strongly negative**: with the app's manual-guide crop instead of the expert segmentation, edge R² −6.82, backend R² −0.99 | §5.1 |
| Integrated | **Yes, behind off-by-default flags.** Server: `ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS=1`. Android: Settings toggle (`BackendConfig.kt:73`, default `false`), plus synthetic/research profiles only | §3, §4 |
| Clinically validated | **No** | No prospective study; no data from the intended maternal population |

Also present: `models/anemia_color_baseline.json` (Ridge over 3 CSV colour percentages). It is trained, has cross-validation only, and is integrated behind `ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA`. It accepts only `research_dataset_precomputed` features, so it can never score a photo (`model_adapters.py`).

### Neonatal jaundice

| Status | Bilirubin (mg/dL) | NJN "jaundice" dataset class (not bilirubin) |
|---|---|---|
| Implemented | Interface only: `BilirubinModel` / `NeonatalJaundiceAdapter`, always `DISABLED_NO_VALID_MODEL` | Yes: `njn-mnv3-logreg` (ONNX, server) and `njn-logreg-cf` (Kotlin, edge) |
| Trained | **No.** No dataset has bilirubin values | Yes, on NJN folder labels (566 images) |
| Evaluated (held out) | No | Yes: 189 group-stratified images, AUROC 0.920 / 0.793. **Same-infant leakage cannot be ruled out** (no patient IDs) |
| Integrated | No (503 `MODEL_DISABLED`; never filled by the class score, which is tested) | Behind the same flags. Android shows the score on a separate card and never saves or syncs it |
| Clinically validated | No | No. The labelling rule is undocumented |
| **Training status** | **BLOCKED: no bilirubin labels** | Not a clinical target; no further training planned |

## 2. End-to-end flows as they exist

### 2.1 Android (canonical app)

```text
Camera2 YUV_420_888 ~640×480 (CameraModel.kt:45 chooseStreamSize)
  → ImageTransforms.yuv420ToArgb, full-range BT.601 (ImageAnalysis.kt:431)    [or gallery: BitmapFactory, ≤640 px]
  → WorkflowEngine.assess: ImageQualityChecker on manual guide NormalizedRect(.14,.34,.86,.66) (OpticalPipeline.kt:32)
       + optional ambient/flash differential (visualisation only)
  → user confirms region (regionConfirmed)
  → WorkflowEngine.analyze (Workflow.kt):
       quality fail → Blocked;  region not confirmed → Blocked
       synthetic profile + demo case → DemoInference fixture (DEMO_SYNTHETIC)
       model status not producing → record with estimate=null, DISABLED_NO_VALID_MODEL
       EXPERIMENTAL on a non-synthetic profile → record with estimate=null
       else modelInput (ambient crop, never the flash preview) → ColourFeatures cf-v1
            → LinearColourHemoglobinModel → ModelOutputValidator (2–25 g/dL; discard, never clamp)
            → exception → InferenceFailed, no value
  → newborn only: JaundiceClassScorer on the same guide crop (AppViewModel.kt:275), separate card, not saved
  → saveResult → Room (unencrypted) → SyncEngine: non-demo records → LOCAL_ONLY; demo → /api/sync
  → ReportDocument → PdfReportWriter (on device)
```

**Does the Android app call the backend for inference? No.** No code path calls `/api/ml/*` (`grep` of `net/`, `ui/`, `services/`). Network calls are `/api/sync`, `/api/counselling`, `/api/referrals` and the contract check, for demo records only.

### 2.2 Backend

```text
POST /api/ml/{hemoglobin,neonatal-jaundice-class}  (raw PNG/JPEG body)
  → REGISTRY.served(): flag off → 503 MODEL_DISABLED (before reading the body)
  → _read_bounded (8 MB) → imageio.decode: content-type whitelist, magic-byte sniff, header dimensions, ≥32 px, ≤40 MP
  → quality.assess (valid pixels, glare ≤25 %, brightness, Laplacian sharpness) → 422 IMAGE_QUALITY_REJECTED
  → features.extract cf-v1 → model.predict (trees / linear / ONNX cnn-v1)
  → non-finite → 500; Hb outside 2–25 → 422 OUTPUT_OUT_OF_RANGE; score outside [0,1] → 500
  → JSON with provenance EXPERIMENTAL_RESEARCH_ONLY, model_version, warnings, OOD feature list; not persisted
POST /api/screenings  DEMO → fixed fixtures (core/inference.py), demo profile only
                      MODEL → adapters: anemia CSV baseline (research features only) | bilirubin always 503
POST /api/sync        accepts DEMO_SYNTHETIC records on demo profiles only (main.py::_sync_one)
```

### 2.3 PWA

Camera/file pixels → local quality and colour-feature visualisation only (`web-dashboard/js/vision.js`). Estimates come only from named fixtures (`inference.js`) on synthetic profiles. The PWA never calls `/api/ml/*` (`app.js:410` states this). Records → IndexedDB outbox → `/api/sync`.

## 3. Inventory: artifacts, loaders, guards, fixtures, placeholders

| Item | Location | Kind | Notes |
|---|---|---|---|
| `hb_hgb_cf_v1.json` (218,757 B) | `models/` (gitignored) | trained, backend | SHA-256 OK |
| `hb_ridge_cf_v1.json` (5,940 B) | `models/`; Android `assets/models/hemoglobin/model.json` | trained, edge | byte-identical copies |
| `njn_logreg_cf_v1.json` (5,397 B) | `models/`; Android `assets/models/jaundice_class/model.json` | trained, edge | byte-identical copies |
| `njn_mnv3_logreg_v1.{json,onnx}` (3.7 MB) | `models/` | trained, backend | SHA-256 OK |
| `anemia_color_baseline.json` | `models/` (tracked) | trained (CSV), backend | research features only |
| Registry + loader | `backend/app/ml/registry.py` | SHA-256, schema, research-only gate; caches failures per process | |
| Edge loader | `core/EdgeModels.kt::EdgeModelLoader` | Hb: metadata + SHA-256; **jaundice class: parsed with no checksum** (`expectedSha256` not passed) | finding M4 |
| Disabled guards | `model_adapters.py`, `registry.served`, `ModelModeResolver`, `UnavailableBilirubinModel`, `Workflow.statusFor` | fail closed | verified by tests and smoke runs |
| Demo fixtures | `backend/app/core/inference.py` (5 cases), Android `core/DemoInference.kt`, PWA `js/inference.js` | `DEMO_SYNTHETIC`, fixed values | demo profiles only, on all three clients |
| Placeholder | `ScreeningEntity.confidencePlaceholder` (fixture 0.76–0.82; 0.0 for real) | stored, not sent as `confidence` | legacy column; remove in a Room migration |
| Hardcoded predictions | **None on `master`** besides the labelled fixtures | | the `kushagra-p1` branch has a hardcoded fallback (0.35 / 12.0 g/dL); not merged ([implementation_plan.md](implementation_plan.md) F4) |
| Notebook MobileNetV3 / RF | not present | listed in `CANDIDATE_MODELS` as never loadable | |

## 4. Fail-safe behaviour, verified on a live server

`uvicorn` with a temporary SQLite DB, Gemini unset. Script: `scripts/audit/smoke_api.py`.

| Request | Flag off | Flag on |
|---|---|---|
| `/api/ml/*` any body | 503 `MODEL_DISABLED` | see below |
| `text/plain` / PNG declared with JPEG bytes | — | 415 `UNSUPPORTED_MEDIA_TYPE` |
| empty / 9 MB / 16×16 / truncated PNG | — | 422 `EMPTY_IMAGE` / 413 `IMAGE_TOO_LARGE` / 422 `IMAGE_TOO_SMALL` / 422 `CORRUPT_IMAGE` |
| all-white / flat grey | — | 422 `IMAGE_QUALITY_REJECTED` with issue list |
| **random pink noise (not an eye)** | — | **200, Hb 13.4 g/dL**, only warning `RESEARCH_ONLY_NOT_VALIDATED` (no OOD warning) |
| same noise → NJN class | — | 200, score 0.0027, warning `INPUT_OUTSIDE_TRAINING_DISTRIBUTION` |
| `/api/screenings` MODEL (anemia, jaundice) | 503 `MODEL_DISABLED` | 503 (separate flag) |
| `/api/screenings` DEMO on a real profile | 422 `DEMO_FIXTURE_REQUIRES_DEMO_PROFILE` | same |
| malformed JSON | 422 `VALIDATION_ERROR` | same |

The error envelope is consistent and no request produced a value after a failure. The gap is the absence of any input-domain check (finding H1).

**Android emulator** (`abhay_api36`, API 36 x86_64, headless; emulator only, no physical device): the debug APK installed and launched (`am start` status ok, 4.2 s cold start) with no crash in logcat. The home screen showed "Maternal anemia · Experimental · research only" and "Newborn jaundice · Estimate disabled". That AVD kept app data from earlier testing with `experimental_models=true` in `shared_prefs`, so this is **not** a fresh-install observation. The default-off behaviour is established by code (`BackendConfig.kt:73`) and `EdgeModelsTest`, not by this run. App data was not wiped.

## 5. Training-time vs inference-time mismatches

### 5.1 Measured: segmented crop vs the app's manual guide crop (Hb)

`scripts/audit/probe_input_domain.py`, on the 54 held-out Eyes-defy test patients. Variant B uses the same patient's full-eye JPEG, EXIF-transposed upright, cropped with the Android guide rectangle. It is a proxy for an app capture: a research macro photo, not a phone frame.

| Input | Gate passes | Backend `hb-hgb-cf` | Edge `hb-ridge-cf` | OOD-flagged |
|---|---|---|---|---|
| A. Expert-segmented palpebral PNG (training format) | 44/54 | MAE 1.26, bias +0.23, R² 0.47 | MAE 1.30, bias +0.12, R² 0.51 | 2/54 |
| B. Manual guide crop of the whole eye (app format) | **54/54** | MAE 2.91, bias −2.45, **R² −0.99** | MAE 6.12, bias −6.12, **R² −6.82** | 54/54 |

Row A reproduces the documented results exactly. Row B shows that the app's actual input is far outside the training domain. Every such image **passes the quality gate**, the OOD check fires on all of them, and the value is still returned or displayed.

### 5.2 Other mismatches

| # | Mismatch | Training | Inference | Effect / evidence |
|---|---|---|---|---|
| 1 | **Anatomy / segmentation** (Hb) | expert-segmented palpebral conjunctiva, background masked | Android: rectangle of a whole-eye frame; server: whatever is uploaded | §5.1; pink noise scored 13.4 g/dL |
| 2 | **Anatomy** (jaundice class) | NJN: whole 1000×1000 newborn photos (skin); the code itself notes "images are skin, not sclera" (`ModelContract.kt:226`) | Android newborn flow asks for a **sclera** photo (`Strings.kt:24`, `WorkflowScreens.kt:238`), and the scorer receives the guide crop of it (`AppViewModel.kt:275-281`) | score is computed on a different body site and framing from training |
| 3 | **EXIF orientation** | NJN JPEGs carry no orientation tag | `imageio.decode` (cv2) ignores EXIF; phone JPEGs often carry orientation 6 | Live probe, 20 NJN images re-encoded sideways + tag 6: CNN score changes by mean 0.18, max 0.50; class flipped 1/20. Colour features are almost rotation-invariant |
| 4 | Capture device / ISP | Samsung S6 + macro attachment + fixed LED (Eyes-defy); unknown (NJN) | any phone, ~640×480 YUV, auto white balance, no colour reference | not quantifiable without app-captured labelled data |
| 5 | Colour space | Eyes-defy PNGs embed ICC profiles (456/644); decoders ignore them on both sides (consistent) | Camera2 YUV assumed full-range BT.601 "on typical devices" (`ImageAnalysis.kt:431`) | untested per device |
| 6 | Resolution | segmented crops ~800×1067 source; CP-AnemiC 79–513 px | camera ~640×480 whole frame, guide crop ≈ 460×154; gallery ≤640 px bilinear | features subsample to ≤256 px; documented in `edge_ai.md` |
| 7 | Population | adults (Eyes-defy), children 6–60 mo (CP-AnemiC) | pregnant women (app's maternal flow) | no data at all |

Preprocessing *code* is consistent: the backend trains and serves through the same `read_path`/`decode` and `features.py`; Kotlin matches Python to 1e-6 on golden vectors (`ColourFeaturesTest`, `EdgeModelsTest.trainedAssetsReproducePythonGoldenOutputs`, both run in this audit); CNN training and serving share `cnn_preprocess.to_tensor` (NCHW float32 1×3×224×224, letterbox, ImageNet mean/std). The mismatches are in **what images reach the pipeline**, not in the arithmetic.

## 6. Datasets (read-only, aggregates)

No dataset folder contains a licence or README file (file-type inventory of every folder). Labels and identifiers:

| Dataset | Files | Label (unit, range) | Identifiers / quasi-identifiers | Image properties | Suitable for |
|---|---|---|---|---|---|
| Eyes-defy-anemia (`archive/`) | 218 JPG, 644 PNG, 2 XLSX, 1 DOCX | `Hgb` g/dL; India 95 rows 7.6–17.1; Italy 122 numeric of 123, 7.0–17.4 (decimal commas) | age, gender; eye images are biometric. Italy sheet has 4 unnamed columns, one holding a repeated undocumented marker in 30 rows (not used) | full-eye JPG 3984×2988 with EXIF orientation 6 (217/218); PNG RGBA 800×1067, ICC profile in 456, Pillow fails on 187 (bad iCCP CRC; OpenCV reads all) | Hb regression **from segmented crops on the same device**; citation requested in the DOCX, no licence |
| CP-AnemiC (`datasets_extracted/cp_anemic`) | 710 PNG + sheet | `HB_LEVEL` g/dL 3.1–15.0 | hospital, city, district, region, age (months), gender | RGBA crops, 452 distinct sizes | external check only; 303 rows with conflicting duplicate labels excluded (prior audit) |
| NJN (`datasets_extracted/njn`) | 760 JPG, `train.csv` (761 rows: ID, RGB, YCbCr means, class), script | folder class only; **no bilirubin** | none, so no patient grouping is possible | RGB 1000×1000, no EXIF, no ICC | dataset-class research only |
| Neonatal forehead/sternum | 478 JPG | **none** | none | RGB 640×480 | nothing until the label table is obtained |
| `Anemia_Dataset.csv` | 104 rows | Hb 2.8–16.3 | **`Name` column (direct identifier)**, sex | no images | nothing photo-based |

**Licensing / legal usability: not established for any dataset.** This keeps every trained artifact research-only and unpublishable ([DATA_PROVENANCE.md §6](DATA_PROVENANCE.md)).

Minor reproducibility issue: the training feature cache key hashes `features.py` bytes (`scripts/ml/common.py:36`). With `core.autocrlf=true` the checked-out file hashes `f8c85384df20`, while the training cache is `7ec0295dac55`. The difference is line endings only (CRLF-stripped hash = `7ec0295dac55`). The contract is unchanged; a re-run on Windows just recomputes the cache.

## 7. Findings

Severity: H = could show a misleading value; M = safety/integrity gap with limited exposure; L = hygiene.

| ID | Sev | Finding | Evidence | Where to fix |
|---|---|---|---|---|
| H1 | H | **No input-domain or anatomy check.** Any image that passes the generic quality gate gets an Hb estimate (pink noise → 13.4 g/dL, no OOD warning) | §4, `quality.py` | Phase 5/7: target-region validation before inference; return `UNABLE_TO_ESTIMATE` otherwise |
| H2 | H | **Out-of-distribution inputs still produce a displayed value.** The app's own crop format is OOD on 54/54 test patients with R² −0.99 / −6.82, but Android and the server return the number with a note | §5.1, `Workflow.kt` (`shown` status), `main.py` warnings | Phase 7: OOD → no value, explicit reason |
| H3 | H | Android research Hb runs on a whole-eye guide crop, not the segmented conjunctiva it was trained on | §5.1, `Workflow.kt::modelInput` | Keep the research toggle off; the input format needs a segmentation step plus app-captured labelled data |
| M1 | M | Jaundice-class model is applied to a **sclera** capture but was trained on whole-newborn skin photos | §5.2 #2 | Phase 5: separate neonatal capture protocol; disable scorer on sclera input |
| M2 | M | EXIF orientation is ignored on upload; the CNN score shifts by up to 0.50 | §5.2 #3 | Phase 4: apply EXIF transpose in `imageio.decode` (and the training reader) with a test |
| M3 | M | OOD warning is not persisted: saved records/PDFs show the experimental value without it (`ScreeningEntity` has no field; `ReferralSummary` limitations omit it) | `Workflow.kt`, `ReferralSummary.kt:73-77` | Phase 6: store warnings with the record |
| M4 | M | Edge jaundice-class artifact loads without a checksum or metadata file | `EdgeModels.kt` `parse(it, TYPE_CLASSIFIER)` with no SHA | Phase 7: metadata + SHA pin, as for Hb |
| M5 | M | Research-profile rule relies on a user-set "synthetic demo" checkbox; a real person photographed under such a profile gets research output | `Workflow.kt::statusFor`, `main.py` same rule | Phase 8: research mode tied to an authorized research role, not a profile flag |
| M6 | M | `/api/ml/*` has no authentication, rate limit or research-profile check when the flag is on | `main.py` routes | Phase 4 (rate/size limits) and Phase 8 (auth) |
| M7 | M | **The locally built debug APK embeds the research model assets** (`unzip -l`: `assets/models/hemoglobin/*`, `jaundice_class/model.json`), which derive from unlicensed data | APK listing | Do not distribute local builds; CI builds exclude them (assets are gitignored) |
| L1 | L | `/api/health` reports Gemini only; model readiness is only in `/api/ml/models`, and registry load failures are cached until restart | `main.py:128`, `registry.get` | Phase 4 readiness endpoint |
| L2 | L | Feature-cache key depends on line endings | §6 | hash with normalised newlines |
| L3 | L | PWA architecture page says "no APK build evidence" (stale) | `app.js:390` | docs pass |
| L4 | L | `confidencePlaceholder` legacy column | `LocalData.kt:58` | Room migration |
| L5 | L | `EdgeModelsTest.trainedAssetsReproducePythonGoldenOutputs` is skipped in CI and clean checkouts (assets absent), so parity is only checked on machines holding the artifacts | `assumeTrue` | document; optional private CI job |

## 8. Commands run (24 Oct 2026, Windows 11, Python 3.13.7, JDK 22)

```bash
# web repo
PYTHONPATH=backend .venv-ml/Scripts/python -m pytest -q            # 197 passed (66 in tests/test_ml.py)
npm test                                                           # all passed (Phase 1, unchanged code)
python - (registry SHA-256 check)                                  # 5/5 files OK
ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS={0,1} uvicorn … ; python -I scripts/audit/smoke_api.py http://127.0.0.1:PORT [NJN jaundice dir]
python -I scripts/audit/probe_input_domain.py <AbhayNayan_web>    # §5.1
python -I scripts/audit/dataset_properties.py <Programming/AbhayNayan> <AbhayNayan_web>   # §6
# android
./gradlew :app:testDebugUnitTest --rerun-tasks                     # 132 tests, 0 failures, 1 skipped (live backend)
emulator -avd abhay_api36 -no-window ; adb install -r app-debug.apk ; am start ; uiautomator dump
```

Environment limits: no physical device; emulator camera not exercised; no live Gemini key used; Docker not available; device latency/memory not measured.

## 9. Gate decision

Clinical training **remains blocked**:

- Bilirubin: no labels at all.
- Hemoglobin for the app's use: no licence-confirmed data, no maternal data, and no labelled images captured through the app's own pipeline. The existing evaluation protocol is sound for its research question (verified), but §5.1 shows that its results do not transfer to the app's input.

Nothing in this audit justifies enabling any prediction by default. The research toggle and server flag should stay off. Engineering work (Phases 3–7) can proceed: anatomy/OOD gating, EXIF handling, persisted warnings, artifact pinning, readiness checks.
