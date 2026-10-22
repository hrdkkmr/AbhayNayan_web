# AbhayNayan

**Edge-AI Optical Biomarker Screening & Multimodal Clinical Protocol Copilot**
**Tagline:** “Turn an entry-level Android phone into a frontline screening assistant.”

> **Safety boundary:** This is a prototype, not a medical device, approved EHR, or diagnostic tool. By default every numeric screening value is a fixed **synthetic demonstration fixture** (`provenance: DEMO_SYNTHETIC`). It is not computed from the camera, an imported image, optical features, or a validated model. No validated hemoglobin or bilirubin model exists. Do not use any value to diagnose, triage, delay care, or change treatment. Confirm with appropriate clinical testing and qualified clinicians under local protocol.

## What is implemented

- **Web app (PWA):** responsive, installable, offline-capable, served by FastAPI. Home dashboard with maternal and neonatal entry points and persisted counts (completed, pending sync, sync problems, profiles). Every value carries a provenance badge.
- **Workflows:**
  - Maternal anemia (optional gestational week) and neonatal jaundice (**age in hours required**).
  - Camera/file capture with a local quality gate that is shown separately from any estimate.
  - Manual ROI guide and browser-only optical feature visualization.
  - Synthetic fixtures are offered only for synthetic profiles with the abstract synthetic image.
- **Results:**
  - The page shows provenance, model version and timestamp.
  - Confidence reads "Not available": no calibrated uncertainty exists, so none is invented.
  - Limitations and safety notes appear on every result.
- **API contract `1.0.0`** shared with the Android app ([docs/API_CONTRACT.md](docs/API_CONTRACT.md)):
  - one error envelope with stable codes and a contract header;
  - explicit `provenance` (`DEMO_SYNTHETIC` / `EXPERIMENTAL_RESEARCH_ONLY` / `VALIDATED_FOR_INTENDED_USE`);
  - client/server ID distinction and idempotent creates with conflict detection.
- **Model adapters:** separate maternal-anemia and neonatal-jaundice adapters with model cards. Both report `DISABLED_NO_VALID_MODEL`, fail closed with `503 MODEL_DISABLED`, and never fall back to a fixture. An operator can enable the anemia research baseline for research-dataset features only ([docs/ML_MODEL_CARD.md](docs/ML_MODEL_CARD.md)).
- **Offline outbox:** IndexedDB with localStorage fallback. Records survive restarts, failed requests delete nothing, and retries reuse the client ID. `/api/sync` returns one result per record (`accepted`/`duplicate`/`conflict`/`rejected`), and the sync page lists records that need attention.
- **Counselling:** reviewed deterministic English/Hindi/Bhojpuri copy, with optional server-side Gemini rewording of explanatory text only. Urgency, the referral flag, next step and safety note always come from deterministic code.
- **Gemini handling:**
  - model verification and classified failures (missing key or model, rate limit vs quota, timeout, malformed, truncated, wrong language, unsafe);
  - provider-reported token telemetry and a token-protected admin usage report ([docs/TOKEN_USAGE.md](docs/TOKEN_USAGE.md));
  - idempotent retries and a demo-only response cache.
- **Referrals:** structured brief (reason, provenance, model version, result and brief timestamps, counselling source, newborn age), server PDF with Devanagari font fallback, and a local print view.
- **FHIR R4-style bundle:** synthetic data marked `meta.security HTEST`, text-only codes, no fabricated components. Not ABDM-conformant.
- **Data hygiene:** dataset manifest ([docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md), [data/DATASET_MANIFEST.json](data/DATASET_MANIFEST.json)), aggregate-only audit scripts, and `.gitignore` rules for raw data and model weights. No dataset file is committed.
- **Research image models (22 October 2026, off by default):** colour-feature hemoglobin models trained on Eyes-defy-anemia and a newborn jaundice/normal *dataset-class* classifier trained on NJN. They are served by `POST /api/ml/hemoglobin` and `POST /api/ml/neonatal-jaundice-class` only when `ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS=1`, and run on-device in the Android app behind a developer toggle. Results are labelled `EXPERIMENTAL_RESEARCH_ONLY`. On the held-out test, Hb MAE is ≈ 1.3 g/dL on the same capture device, but the models are **worse than the mean on children from other hospitals**. Bilirubin stays disabled. See [ml_evaluation.md](docs/ml_evaluation.md) and [ml_integration.md](docs/ml_integration.md); the trained artifacts are not in Git.
- **Tests (22 October 2026):** **193 Python tests** (66 for the ML pipeline), **32 Node module tests** and **4 JSDOM workflow tests** pass, along with compileall, `pip check` and web syntax checks.

## Important implementation limits

- **No validated model.** The October 22 research models are trained and evaluated on small public datasets only (see above). The 10 October findings for the earlier candidates still apply:
  - The Ridge colour baseline reproduces MAE 1.5041 g/dL, R² 0.3987 on 104 rows, versus MAE 1.95 for predicting the mean. Its inputs are not reproducible from the camera pipeline.
  - The notebook's MobileNetV3 scored R² −0.197 and its model file was never exported.
  - No bilirubin labels exist, so no jaundice model can be trained.
- Browser camera frames and imported images stay in the browser; the PWA never uploads them. The research image endpoints are disabled unless an operator sets the flag, and even then they process images in memory only.
- There is no face or eye landmark model; ROI alignment is a manual guide. Flash/ambient correction is an experimental visualization only.
- **No authentication** apart from the admin usage report. The SQLite store and browser storage are not encrypted. There is no EHR or ABDM integration. Use synthetic profiles only.
- **Android:** canonical source is the separate [`AbhayNayan_apk`](https://github.com/shubhamcore/AbhayNayan_apk) repository; the `android/` folder here is a stale snapshot that does not compile as-is. See [docs/ANDROID_INTEGRATION.md](docs/ANDROID_INTEGRATION.md).
- **Not verified:** a live Gemini call, a Docker build, and device or browser-farm testing. No latency, memory or device-compatibility figures have been measured.

## Run locally

Requirements: Python 3.13 recommended (3.11+ may work), pip, and Node 20+ for the web-module test suite. The one-step launcher creates `.venv`, installs backend dependencies if needed, and starts the API/PWA:

```bash
./scripts/run_local.sh
```

On Windows PowerShell, run `./scripts/run_local.ps1`. Then open <http://localhost:8000>. Set `PORT`/`HOST` (or `ABHAYNAYAN_PORT` in Docker) to change the listener.

Manual setup is also available:

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
PYTHONPATH=backend python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>. FastAPI's interactive API explorer is at <http://localhost:8000/docs>; the static audit documents are under `/docs/`.

The SQLite demo database is created on first server startup at `backend/data/abhaynayan.sqlite3`. Override it with `ABHAYNAYAN_DB_PATH` if you want a different location. The release ZIP excludes generated databases/local records for a clean start; this is not a production clinical database.

### Run tests and syntax checks

From the project root:

```bash
./scripts/verify_all.sh
```

This creates/uses `.venv`, installs the Python requirements if missing, runs Python compile checks, `pip check`, all Python tests (API, contract, core, mocked Gemini), runs `npm ci`, then executes the web-module tests, the JSDOM workflow, offline-sync and page-render tests, and browser-module syntax checks. On Windows, run it from Git Bash with `PYTHON_BIN=.venv/Scripts/python bash scripts/verify_all.sh`. For manual runs, use `python -m pytest -q`, then `npm ci && npm test`. The PWA itself has no bundler/runtime dependency; JSDOM is only a development/test dependency. Python tests use a temporary SQLite database and do not require a Gemini key.

### Run with Docker Compose

Docker is not installed in the inspected build environment, so this path is provided but not verified here.

```bash
cp .env.example .env
# Optional: set GEMINI_API_KEY and GEMINI_MODEL (both needed for Gemini) and ABHAYNAYAN_ADMIN_TOKEN in the server-only .env file.
docker compose up --build
```

The service listens on port 8000 by default and persists SQLite data in a named volume. The Docker image runs as a non-root user. **Never commit a real `.env` file.** If a key has previously been exposed, rotate it with the provider; do not paste the replacement into the frontend, repository, or chat.

## Optional Gemini counselling

The API reads `GEMINI_API_KEY` and `GEMINI_MODEL` only on the server; the client never sees the key. **No model ID is hard-coded.** Gemini stays off until an operator sets both values. The server checks the model with `models.get` before use. On 10 October 2026 Google's [model list](https://ai.google.dev/gemini-api/docs/models) showed `gemini-3.8-flash` as stable. This integration has **not** been exercised against a live key; all provider behaviour is tested with mocked responses.

The request contains only screening type, value, unit, demo tag, provenance, language, and optional gestational week or newborn age in hours. It never includes a patient name, ID, phone number or image. Token usage reported by the provider is recorded without prompts or outputs and summarised at `GET /api/admin/usage`, which requires `ABHAYNAYAN_ADMIN_TOKEN`. See [docs/TOKEN_USAGE.md](docs/TOKEN_USAGE.md) for configuration, failure codes and privacy controls.

## Demo walkthrough

1. Open **New screening** and keep the preloaded synthetic demo profile.
2. Choose maternal anemia or neonatal jaundice. For jaundice, confirm the newborn age in hours (required).
3. On the capture step choose **Use abstract synthetic image** (or use a local camera/file only to demonstrate quality/feature processing).
4. Review the local quality gate and optical feature visualization. These do not drive the estimate.
5. Select a named synthetic case and run it. The result explains its mode, fixed fixture provenance, safety note, and next step.
6. Switch English/Hindi/Bhojpuri counselling; optionally create a referral, download/print the PDF, and export the local FHIR-style JSON.
7. Turn on **Simulate offline**, create a new demo record, inspect the queue, switch offline simulation off, and sync. Then review the PHC dashboard and model/data audit.

A detailed timed script and do/don't narration are in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Architecture

```text
Browser / installable PWA                    Android app (separate repo, local-only today)
  ├─ local profiles + IndexedDB outbox         └─ Room + Camera2 + demo fixtures
  ├─ camera/file pixels → local quality/features only (never uploaded)
  ├─ DEMO fixture → result with provenance badge
  └─ pseudonymous sync / counselling / referral ──────┐ same-origin REST, contract 1.0.0
FastAPI + SQLite                                      ▼
  ├─ Pydantic contract + error envelope + idempotent create/sync with conflict detection
  ├─ model adapters: anemia (disabled; research opt-in) · jaundice (disabled, no labels)
  ├─ deterministic counselling + optional Gemini wording → llm_usage telemetry
  └─ FHIR-style bundle (HTEST-tagged) · referral PDF · dashboard · admin usage report
```

This describes a prototype, not deployed clinical infrastructure.

## Create a clean release ZIP

```bash
python3 scripts/package_release.py
```

The script writes `../AbhayNayan-0.1.0-final.zip` and a `.sha256` sidecar, validates ZIP integrity, and excludes real `.env` files, generated SQLite databases/local records, virtual environments, `node_modules`, Android build outputs, and caches. If a debug APK has separately been built and verified, add it with `--include-android-apk`; the option fails closed if the APK is missing.

## Data and research artifact

The shared Drive folder holds five files: an anemia CSV with a direct `Name` field, the Eyes-defy-anemia image archive, the CP-AnemiC RAR, a neonatal ZIP of 478 unlabelled images, and an uninspected RAR. **None has verified licence, consent or redistribution rights, and none is committed.** Sizes, counts, labels, identifiers and the access process are in [docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md). The only research artifact in Git is `models/anemia_color_baseline.json` (coefficients and aggregate metrics); its evaluation is in [docs/ML_MODEL_CARD.md](docs/ML_MODEL_CARD.md).

## Project files

- `web-dashboard/`: PWA shell, modules, service worker and manifest.
- `backend/app/`:
  - `models/schemas.py`: contract models;
  - `core/model_adapters.py`: inference adapters;
  - `core/inference.py`: demo fixtures;
  - `services/`: Gemini and telemetry, SQLite store, FHIR, referral PDF, language copy.
- `models/anemia_color_baseline.json`: research-only coefficients; runtime adapter disabled by default.
- `scripts/`:
  - `train_anemia_baseline.py`, `audit_anemia_csv.py`, `inspect_dataset_archives.py`: aggregate-only research tooling;
  - `ml/`: dataset preparation, training/evaluation (`train_hb.py`, `train_njn.py`), golden vectors, Android asset export, serving verification;
  - launchers, `verify_all.sh` and the release packager.
- `data/`: dataset manifest only; raw data is ignored.
- `docs/`: [ML audit](docs/ml_audit.md), [ML architecture](docs/ml_architecture.md), [dataset requirements](docs/dataset_requirements.md), [ML evaluation](docs/ml_evaluation.md), [ML integration](docs/ml_integration.md), [model cards](docs/model_cards/), [API contract](docs/API_CONTRACT.md), [Android integration](docs/ANDROID_INTEGRATION.md), [model card](docs/ML_MODEL_CARD.md), [data provenance](docs/DATA_PROVENANCE.md), [token usage](docs/TOKEN_USAGE.md), [safety](docs/SAFETY.md), demo script, release notes, checklist.
- `tests/`: Python (API, contract, core, Gemini) and Node (modules, JSDOM workflows, offline sync).
- `android/`: stale snapshot of the Android source; canonical source is `AbhayNayan_apk`.
- lab/

## Safety and data handling

Read [docs/SAFETY.md](docs/SAFETY.md) before demonstration or modification. The app is not a substitute for CBC, serum bilirubin, established screening protocols, or clinical judgment. Do not upload identifiable patient information, images, or raw shared datasets to public demos. Use synthetic profiles for the walkthrough.
