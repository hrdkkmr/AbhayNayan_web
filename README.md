# AbhayNayan

**Edge-AI Optical Biomarker Screening & Multimodal Clinical Protocol Copilot**  
**Tagline:** “Turn an entry-level Android phone into a frontline screening assistant.”

> **Safety boundary:** This is a hackathon prototype, not a medical device, approved EHR, or diagnostic tool. Every numeric screening value in the running app is a fixed **synthetic demonstration fixture**. It is not computed from the live camera, imported image, optical features, or a validated clinical model. Do not use it to diagnose, triage, delay care, or change treatment. Confirm with appropriate clinical testing and qualified clinicians under local protocol.

## What is implemented

- Responsive, installable, offline-capable web dashboard served by FastAPI.
- Maternal-anemia and neonatal-jaundice guided workflows, distinct synthetic maternal/newborn profiles (including newborn age in hours), local-only patient profiles, worker settings, camera/file quality gate, manual ROI guide, and browser-only optical feature visualization.
- Deterministic synthetic fixture cases with prominent `DEMO` labels. A real/local patient profile cannot receive a synthetic estimate.
- IndexedDB persistence with localStorage fallback, offline outbox, retry-safe demo sync, local FHIR R4-style JSON, counselling in English/Hindi/Bhojpuri, server-side optional Gemini integration with deterministic fallback, referral PDF/print view, and PHC demo dashboard.
- FastAPI + SQLite endpoints with server-side demo-profile guards, OpenCV utilities, PDF generation, safety-oriented schemas, and research/data audit.
- Automated suite (8 October 2026): **60 Python tests + 29 Node.js module tests + 1 JSDOM maternal/newborn workflow smoke** passed; Python compileall, `pip check`, and web syntax checks passed.

## Important implementation limits

- No approved or clinically validated anemia or bilirubin model is bundled. TFLite interfaces are placeholders and are not activated.
- Browser camera frames and imported images are analyzed locally and are not sent to FastAPI or Gemini. The current image feature vector is for pipeline visualization only.
- There is no face/eye landmark model; ROI alignment is a manual guide. Flash/ambient correction is only an experimental visualization.
- A small, internal grouped-CV Ridge baseline exists as disabled research material. It is not used by the app. See [dataset audit](docs/dataset-audit.md).
- Android Kotlin/Compose source, a Gradle 8.13 wrapper, and CI build workflow are included, but no verified APK is delivered. A temporary JDK 17/API 36 build attempt reached Android resource/KSP tasks before the Gradle daemon exited under this sandbox's memory ceiling. See [Android status](docs/ANDROID_STATUS.md); do not represent the PWA as a native APK.
- Docker configuration is provided but has not been built in the current environment because Docker is not installed there.

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

This creates/uses `.venv`, installs the Python requirements if missing, runs Python compile checks, `pip check`, all Python tests, runs `npm ci`, then executes 29 web-module tests, the JSDOM workflow smoke, and browser-module syntax checks. For manual runs, use `python -m pytest -q`, then `npm ci && npm test`. The PWA itself has no bundler/runtime dependency; JSDOM is only a development/test dependency. Python tests use a temporary SQLite database and do not require a Gemini key.

### Run with Docker Compose

Docker is not installed in the inspected build environment, so this path is provided but not verified here.

```bash
cp .env.example .env
# Optionally set GEMINI_API_KEY in the server-only .env file. It is not required.
docker compose up --build
```

The service listens on port 8000 by default and persists SQLite data in a named volume. The Docker image runs as a non-root user. **Never commit a real `.env` file.** If a key has previously been exposed, rotate it with the provider; do not paste the replacement into the frontend, repository, or chat.

## Optional Gemini counselling

The API reads `GEMINI_API_KEY` and `GEMINI_MODEL` only on the server. The client never reads or stores the key. Without a key, without network access, or after a model/API error, the app returns deterministic English/Hindi/Bhojpuri fallback copy. The request contains only screening type, the synthetic estimate/category, quality/confidence placeholders, language, and optional gestational/newborn-age fields; it does not include patient name, phone, or image.

Default model ID: `gemini-3.8-flash` (override with `GEMINI_MODEL`). Check provider availability, billing, data-processing terms, regional availability, and current model lifecycle before enabling. This integration is optional and has not been exercised against a live key in this build. Google model reference: <https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash>.

## Demo walkthrough

1. Open **New screening** and keep the preloaded synthetic demo profile.
2. Choose maternal anemia or neonatal jaundice.
3. On the capture step choose **Use abstract synthetic image** (or use a local camera/file only to demonstrate quality/feature processing).
4. Review the local quality gate and optical feature visualization. These do not drive the estimate.
5. Select a named synthetic case and run it. The result explains its mode, fixed fixture provenance, safety note, and next step.
6. Switch English/Hindi/Bhojpuri counselling; optionally create a referral, download/print the PDF, and export the local FHIR-style JSON.
7. Turn on **Simulate offline**, create a new demo record, inspect the queue, switch offline simulation off, and sync. Then review the PHC dashboard and model/data audit.

A detailed timed script and do/don't narration are in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Architecture

```text
Browser / installable PWA
  ├─ local patient profile + IndexedDB outbox
  ├─ camera/file pixels → local quality/feature utility only
  ├─ selected deterministic synthetic fixture → result UI
  ├─ local FHIR JSON + print/PDF workflow
  └─ optional pseudonymous synthetic sync / counselling
             │ same-origin REST
FastAPI + SQLite demo API
  ├─ strict schemas + idempotent sync
  ├─ deterministic fixture service (no pixel inference)
  ├─ optional server-side Gemini + local fallback
  └─ FHIR-style bundle + referral PDF + dashboard
```

The planned Android shell is tracked separately and is not yet build-verified. This diagram describes the current web/API prototype, not deployed clinical infrastructure.

## Create a clean release ZIP

```bash
python3 scripts/package_release.py
```

The script writes `../AbhayNayan-0.1.0-final.zip` and a `.sha256` sidecar, validates ZIP integrity, and excludes real `.env` files, generated SQLite databases/local records, virtual environments, `node_modules`, Android build outputs, and caches. If a debug APK has separately been built and verified, add it with `--include-android-apk`; the option fails closed if the APK is missing.

## Data and research artifact

The shared anemia CSV had 104 rows/104 subject groups and a direct `Name` field. The field was used transiently only to create subject-grouped folds and is excluded from the derived artifact. The exploratory five-fold GroupKFold baseline reported MAE **1.5041 g/dL**, RMSE **1.9392 g/dL**, and R² **0.3987** on precomputed color percentages. This is internal exploratory analysis—not external validation, camera performance, fairness evidence, or clinical accuracy. The neonatal archive contained 478 images but no bilirubin label table. No raw shared images or CSV are shipped. Dataset permissions, license, provenance, consent, and intended reuse remain unverified.

## Project files

- `web-dashboard/` — PWA shell, local UI/modules, service worker, and manifest.
- `backend/app/` — FastAPI schemas, OpenCV utilities, demo inference, SQLite services, FHIR, Gemini adapter, referral PDF.
- `models/anemia_color_baseline.json` — disabled research-only aggregate/coefficient artifact; not used for screening.
- `scripts/train_anemia_baseline.py` — sanitized reproduction script; raw source CSV is not included.
- `docs/` — API, safety, demo, audit, Android status, release notes, final checklist.
- `scripts/` — one-step launchers, complete verification runner, and clean ZIP packager.
- `.github/workflows/ci.yml` — Python/web checks and an Android build/test artifact job.
- `android/` — Kotlin/Compose source and Gradle wrapper; no verified APK is currently delivered.

## Safety and data handling

Read [docs/SAFETY.md](docs/SAFETY.md) before demonstration or modification. The app is not a substitute for CBC, serum bilirubin, established screening protocols, or clinical judgment. Do not upload identifiable patient information, images, or raw shared datasets to public demos. Use synthetic profiles for the walkthrough.
