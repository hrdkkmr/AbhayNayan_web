# ML audit: baseline state before the 22 October 2026 ML work

This records what existed **before** any change in this round, so later claims can be checked against it. Patient-level data is not reproduced here; all counts are aggregates.

## 1. Repositories and workspace (22 Oct 2026)

| Repository | Local path | Branch | Start SHA | Remote state at start | Action |
|---|---|---|---|---|---|
| `hrdkkmr/AbhayNayan_web` | `Programming/AbhayNayan/AbhayNayan_web` | `master` | `2c17e8b` | behind `origin/master` by 2 (`993c22a` adds a one-line file `shubham`, `1987a5e` adds one README line); clean tree | fast-forward only (`git merge --ff-only`) → `1987a5e` |
| `shubhamcore/AbhayNayan_apk` | `Programming/AbhayNayan_apk` (project in `AbhayNayan/` subfolder) | `android-0.2.0-workflows-sync-camera` | `cbfb00b` | up to date; `origin/main` (`8f65b73`) is older | none; untracked `1.jpeg`–`5.jpeg` at the repo root were left untouched |

The folders are spelled `AbhayNayan/AbhayNayan_web` and `AbhayNayan_apk` on disk (Windows paths are case-insensitive, so they match the requested layout). The web repo also contains `android/`, a stale snapshot of the app (already documented as such); the canonical Android source is the `AbhayNayan_apk` repository. No destructive Git command was used, and nothing was committed or pushed.

## 2. Backend (FastAPI), as found

| Area | Finding |
|---|---|
| Predictions | No image model. `POST /api/screenings` returns fixed `DEMO_SYNTHETIC` fixtures (`core/inference.py`) or, only with `ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA=1`, a 3-coefficient Ridge on dataset-supplied colour percentages (`models/anemia_color_baseline.json`). Camera-pipeline features are rejected by that adapter. |
| Bilirubin | `NeonatalJaundiceAdapter` always raises `MODEL_DISABLED` (503). Correct: there are no bilirubin labels. |
| Image upload | None. `GET /api/vision/capabilities` reports `image_upload_api: false`. |
| Fabrication safeguards | Good. Fixtures are labelled `DEMO_SYNTHETIC`; a schema validator forces `synthetic == (provenance == DEMO_SYNTHETIC) == (model_mode == DEMO)`; disabled models fail with 503 and no value. |
| Feature mismatch | `core/vision.py` computes RGB/HSV/Lab means on a manual crop. These do not reproduce the CSV's `%Red/%Green/%Blue Pixel` columns (undocumented ROI/device), so the Ridge baseline cannot be applied to camera images. Confirmed: the adapter refuses `camera_pipeline` features. |
| Dependencies | Python 3.13; FastAPI 0.142.4, numpy 2.3.5, OpenCV-headless 4.11, no ML runtime. `python-multipart` is not installed (relevant for upload design). |
| Deployment | Dockerfile copies only `models/anemia_color_baseline.json`. The Android build defaults to `https://abhaynayan-web.onrender.com`; the hosting plan's memory limit is not known to this audit. |
| Tests at baseline | `pytest`: **127 passed** (README said 119). `npm test`: 32 module + 4 JSDOM workflow tests and syntax checks, all passed. |

## 3. Android (AbhayNayan_apk), as found

| Area | Finding |
|---|---|
| Build | AGP 8.13.2, Kotlin 2.2.20, Gradle 8.13, compileSdk/targetSdk 36, **minSdk 26**. Builds locally with JDK 22 and the SDK at `E:\Android\Sdk` (platform 36, build-tools 35/36). No emulator or system image is installed and `adb devices` lists no device, so instrumentation/device tests cannot run here. |
| Unit tests at baseline | `:app:testDebugUnitTest`: **112 tests, 0 failures, 1 skipped** (a live-backend test). |
| Camera | Camera2 YUV→RGB ambient/flash pair, exposure lock, motion-compensated flash differential, manual ROI guide, quality gate (`ImageQualityChecker`). Gallery import via `BitmapFactory` (ARGB_8888, downscaled to ≤ 640 px). |
| Model contract | Strong fail-closed design: `ModelArtifactMetadata` card parsing, `ModelModeResolver`, typed `HemoglobinModel` / `BilirubinModel` slots, `ModelOutputValidator` (discard, never clamp). But `RUNTIME_AVAILABLE = false`, the card parser only accepted tensor models, and there was **no experimental opt-in setting**, so no model could ever run. |
| Latent defect found | `WorkflowEngine.analyze` would have given a model `optical.roi`, which is cropped from the *normalised flash-minus-ambient preview* when the flash pair is accepted, not the raw colours. Fixed in this round (`WorkflowEngine.modelInput`). |
| Offline | All capture, quality checks and records are local (Room). The backend is used only for sync/counselling of synthetic demo records; photos are never uploaded. |

## 4. Datasets found locally (the user added them to `Programming/AbhayNayan/`)

| File | What it actually contains | Usable labels |
|---|---|---|
| `Anemia_Dataset.csv` | 104 rows: name, sex, precomputed %R/%G/%B, Hb, Anaemic | Hb g/dL, but no images and an undocumented feature pipeline |
| `archive/` (Eyes-defy-anemia) | 218 patients (India 95, Italy 123): full-eye JPEG + expert-segmented palpebral/forniceal PNGs; `India.xlsx`, `Italy.xlsx` with **laboratory Hgb**; docx describes a Samsung S6 + magnifier + fixed LED capture device | Hb g/dL per patient |
| `CP-AnemiC …/CP-AnemiC dataset.rar` (**not opened in the previous audit**) | 710 pre-segmented palpebral-conjunctiva PNGs (RGBA mask) of children 6–60 months from 10 hospitals in 4 Ghanaian regions; sheet `Anemia_Data_Collection_Sheet.xlsx` with `HB_LEVEL`, severity, age, sex, hospital | Hb g/dL per image |
| `Neonatal Jaundice Assessment …` | 478 JPEGs (239 forehead, 239 sternum), 640×480 | **none** |
| `NJN.rar` (**not opened before**) | `jaundice.zip` (200), `normal.zip` (560) newborn photos 1000×1000; `train.csv` of 761 rows of colour features + class, not linkable to files; a KNN/RF/XGBoost script | Binary folder class only; **no bilirubin values** |

## 5. Data-integrity defects discovered

1. **CP-AnemiC duplicated images with conflicting labels.** 91 groups of byte-identical images (303 rows) are assigned to different children: 86 of the groups span different hospitals, 82 different ages, 59 different sexes, and Hb within a group differs by up to 7.1 g/dL. The image-to-label link is broken for these rows, so all 303 rows are excluded. A further 7 rows that are perceptual near-copies (dHash ≤ 4/256 bits) are excluded because their owner cannot be determined. **400 of 710 rows remain.**
2. **Eyes-defy-anemia "unreadable" images are readable.** 187 PNGs fail in Pillow because an embedded iCCP colour-profile chunk has a bad CRC; libpng/OpenCV decode all of them. The earlier notebook's "110 unreadable images" was a reader problem, not missing data.
3. **Eyes-defy-anemia sheet issues:** 15 Italian Hb values use a decimal comma; one row is marked `ELIMINATO` and has no Hb (excluded).
4. **NJN:** 5 exact duplicates (same class; one copy kept). No patient identifiers exist, so same-infant images may fall on both sides of a split.
5. **Neonatal forehead/sternum set:** still no label table; nothing can be trained.

## 6. Baseline model evidence, before this round

| Candidate | Evidence | Status |
|---|---|---|
| Ridge on CSV %RGB | MAE 1.50 g/dL, R² 0.40 (internal CV, 104 rows) | research-only, disabled; inputs not reproducible |
| Notebook MobileNetV3 (Eyes-defy) | test R² −0.197; artifact never exported | not available |
| Bilirubin | no labels | disabled |

What changed afterwards is in [ml_architecture.md](ml_architecture.md), [ml_evaluation.md](ml_evaluation.md) and [ml_integration.md](ml_integration.md).
