# AbhayNayan — Project Plan & Implementation Status

**Product:** ABHAYNAYAN — Edge-AI Optical Biomarker Screening & Multimodal Clinical Protocol Copilot  
**Tagline:** “Turn an entry-level Android phone into a frontline screening assistant.”  
**Plan date:** 8 October 2026  
**Update 10 October 2026:** API contract 1.0.0, model adapters, Gemini telemetry and sync conflict handling implemented; see `docs/RELEASE_NOTES.md` (0.2.0). Sections below describe the 8 October baseline.  
**Status:** Final hackathon prototype release prepared: runnable web/API workflow, clean ZIP packager, native Android source plus Gradle wrapper/CI. Android APK, Docker image, live Gemini, and clinical model remain unverified/unavailable. This project is separate from `/home/user/spotstory`, which must remain untouched.

## 1. Product boundary and current truth

Build a demonstrable, offline-first prototype for frontline workflows covering maternal anemia and neonatal jaundice. Current estimates are **deterministic synthetic fixtures selected by the user**. They are not inferred from camera pixels, optical features, patient data, or an approved clinical model. Every result must retain a prominent safety notice and confirmation direction.

Current capability split:

| Capability | State | Important qualification |
|---|---|---|
| Responsive PWA workflow | Implemented in source | API-served same-origin; JSDOM tests maternal and newborn workflows; no real-device/browser farm test |
| Patient/worker records | Implemented locally | Separate synthetic maternal/newborn profiles; newborn demo includes age in hours; profile details remain in IndexedDB/localStorage |
| Browser capture/file import | Implemented in source | Pixel processing stays in browser memory; backend image upload is disabled |
| Quality/optical utilities | Implemented and unit-tested | Brightness/edge proxy, manual ROI, uncalibrated RGB/HSV/Lab/YCrCb; not clinical measurements |
| Synthetic inference | Implemented and unit-tested | Fixed fixtures only; real/local profile and real image cannot be paired to run a fixture |
| FastAPI + SQLite API | Implemented and unit-tested | Demo-only service, no authentication or production governance |
| Gemini counselling | Implemented behind server environment configuration | Fallback tested; live key/model call not exercised |
| FHIR-style bundle/referral PDF | Implemented and unit-tested | Preliminary synthetic demonstration mapping; local print fallback |
| Offline sync | Implemented in web source and API-tested | Pseudonymous synthetic records only; retry-safe demo SQLite store |
| Native Kotlin/Compose/Room/Camera2 | Source, Gradle 8.13 wrapper, and CI workflow delivered | Wrapper/project configuration verified; build reached resources/KSP then daemon exited in low-memory sandbox; no APK/device test |
| Docker | Dockerfile/Compose provided | Docker absent in build environment; image not built |
| Automated tests | Python + Node suites implemented | Latest successful run: 60 Python, 29 Node, 1 JSDOM maternal/newborn workflow smoke; Android tests not executed |

## 2. Architecture

```text
Native Android source (Kotlin / Compose / Camera2 / Room / local TTS)
  └─ synthetic-only result path; source delivered, APK not build-verified

Web PWA (current broad workflow)
  ├─ IndexedDB/localStorage patient profiles and sync outbox
  ├─ browser camera / local image → local quality + optical preview only
  ├─ manual ROI guide (no landmark model bundled)
  ├─ fixed synthetic case fixtures (no pixel-to-biomarker mapping)
  ├─ local FHIR-style JSON, referral print/PDF, three-language counselling
  └─ optional sync/counselling requests with no image or profile name
                  │ same-origin REST
FastAPI + SQLite demo backend
  ├─ strict Pydantic request models
  ├─ deterministic synthetic inference fixtures
  ├─ idempotent pseudonymous synthetic sync
  ├─ optional server-side Gemini with deterministic fallback
  ├─ FHIR R4-style demonstration bundle + ReportLab PDF
  └─ local PHC-style dashboard
```

## 3. Environment and dependencies

- Python 3.13 tested; Python dependency pins are in `requirements.txt`.
- Node 20 tested using built-in test runner; the browser uses vanilla HTML/CSS/JS without CDN/package runtime dependencies.
- Android source declares API 26 minimum / API 36 compile target, JDK 17, Gradle 8.13, AGP 8.13.2, Kotlin 2.2.20, Room and KSP. Wrapper version/configuration succeeded. A temporary JDK17/API36 toolchain build reached resource/KSP tasks then Gradle daemon exited before compilation/tests/APK; no Android device/emulator was available.
- Docker executable is unavailable in the host; `Dockerfile`/`compose.yaml` have not been built or run.
- Optional Gemini model/key are server-only environment variables. Without a configured key/network, the local fallback is the expected behavior.

## 4. Dataset review / research-only result

- `Anemia_Dataset.csv` contained 104 valid rows / 104 unique subject groups and a direct `Name` field. Names were used transiently only to group validation folds, excluded from features and the saved artifact.
- Standardized Ridge regression on three precomputed RGB percentage features with five-fold `GroupKFold` by group produced **MAE 1.5041 g/dL, RMSE 1.9392 g/dL, R² 0.3987**. This is a small internal exploratory split only—not external validation, image-based performance, prospective validation, fairness evidence, or fit for patient decisions. The derived coefficients are disabled research material and never feed the app.
- The neonatal ZIP contains 478 JPEGs (239 `Forehead/`, 239 `Sternum/`) but no bilirubin label table was found. No jaundice model was trained/reported.
- The CP-AnemiC ZIP has an uninspected nested RAR. Large `archive.zip` and `NJN.rar` were not downloaded. The supplied Colab was inspected statically but not run; it contains Kaggle-path-oriented repeated drafts.
- Dataset license, provenance, consent, intended reuse, and clinical validity remain unverified. Raw CSV/images are not in the repository or package.
- See `docs/DATA_PROVENANCE.md` and `docs/ML_MODEL_CARD.md` for methods, exact metric context, and reproduction command.

## 5. Milestones

1. Repository plan, responsive shell, FastAPI+SQLite API, API health/dashboard — **implemented; tests pass**.
2. Patient/worker records and local persistence — **implemented in PWA**; data remains local; Android source uses Room but is unverified.
3. Browser camera and local image workflow — **implemented in PWA source**; no image upload. Camera permission requires a supported secure browser context.
4. Quality gate/manual ROI — **implemented/tested**; no MediaPipe/landmark model, and a user confirms the region.
5. Optical features + ambient/flash concept — **implemented/tested**; exploratory only; no calibration or clinically validated correction.
6. Inference abstraction/TFLite interface/synthetic cases — **implemented/tested**; TFLite interface refuses unverified feature-to-output mapping.
7. Result engine and safety copy — **implemented in PWA/native source**; synthetic-only association safeguards.
8. Gemini copilot with no-key/local fallback — **implemented/tested with mocked/no-key paths**; live provider call not verified.
9. FHIR bundle + referral PDF — **implemented/tested**; demonstration FHIR style, not certified exchange.
10. Offline persistence/queue/retry-safe sync — **implemented in PWA/API and tested**; demo database only.
11. PHC dashboard — **implemented in PWA/API**; shows synthetic/pseudonymous records only.
12. Tests/docs/release/native source — **Python/Node/JSDOM suites pass; docs, launch/verify scripts, CI, Gradle wrapper, and clean ZIP packager included**; Docker not run; native Android compile/APK still unverified.

## 6. Safety, privacy, and operational controls

- No estimated value may be presented as a diagnosis or clinically validated result.
- Do not imply replacement of CBC, serum bilirubin testing, established local protocols, or clinicians.
- No fake latency, battery, memory, image-model, diagnostic, or fairness performance claims.
- Gemini key remains server-side; never hard-code, expose, or log secrets. Do not ask for a replacement key in chat.
- Use synthetic profiles in public demos; do not upload real camera images, identifiers, or raw Drive data.
- Actual camera/import frames support local quality/feature demonstrations only; a fixture is enabled only with an abstract synthetic image and a synthetic profile.
- Docker/SQLite prototype is not a secure production clinical service. No authentication, audit-grade retention, access control, clinical governance, or regulatory review is supplied.

## 7. Acceptance evidence and remaining work

- Source contains complete PWA journeys for maternal and neonatal fixture demos, local records, offline queue/sync, PHC view, counselling, FHIR and referral.
- Verified on 8 October 2026: `python -m compileall -q backend tests`, `python -m pip check`, and `npm run check:web` passed; Python tests → 60 passed; web modules → 29 passed; JSDOM maternal/newborn workflow smoke → 1 passed. Pytest emits one Starlette/httpx deprecation warning; npm reports a deprecated transitive `whatwg-encoding` package.
- README, API, dataset audit, safety, demo script, Android status, release notes, and final checklist are present.
- `/home/user/AbhayNayan-0.1.0-final.zip` contains 74 project files and passed ZIP integrity/archive-hygiene checks; a SHA-256 sidecar is next to the archive. Generated SQLite, environment secrets, dependency/build caches, and APKs are excluded.
- Native APK remains unavailable until a provisioned JDK17/Android SDK/Gradle runner compiles, tests, installs, and verifies it. Do not deliver or claim an APK before then.
- Docker configuration and live Gemini integration remain operator-verification steps.
- No supplied spec/PPT file was present in the inspected project workspace; this plan follows the detailed written prompt until the user provides that source document.
