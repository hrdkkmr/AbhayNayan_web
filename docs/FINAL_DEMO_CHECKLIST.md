# Final demo and release checklist

**Build identity:** AbhayNayan 0.1.0-final-demo · 8 October 2026  
**Scope:** Runnable FastAPI/PWA prototype, source-only native Android project, and clean release archive. Not a clinical product.

## Before a live presentation

- [x] Automated Python, web-module, JSDOM workflow, syntax, and dependency checks recorded below.
- [x] Started API/PWA from `scripts/run_local.sh`; HTTP smoke returned 200 for `/`, `/api/health`, `/api/demo/cases`, `/api/model/status`, and `/api/pipeline`. Still open the target browser before a live presentation.
- [ ] Use only seeded synthetic profiles and the abstract synthetic image for the displayed fixture result.
- [ ] Point out that image processing is local; it does not generate the numeric estimate.
- [ ] Show the safety boundary, selected DEMO fixture, newborn age-in-hours context, and English/Hindi/Bhojpuri fallback.
- [ ] Show local FHIR JSON/referral print or server PDF, offline outbox, then PHC demo dashboard.
- [ ] Do not use a real patient record, photo, or raw Drive dataset in a public presentation.
- [ ] Make no diagnostic, clinical accuracy, battery, latency, fairness, or production-readiness claims.

## Completed release evidence

- [x] Project plan and architecture boundary recorded.
- [x] FastAPI safety schemas, SQLite demo store, routes, and server-side synthetic-profile guards implemented.
- [x] PWA workflows wired for maternal and newborn synthetic profiles; neonatal demo includes age in hours.
- [x] Local English/Hindi/Bhojpuri fallback counselling.
- [x] Pseudonymous synthetic sync and PHC demo dashboard.
- [x] Local FHIR-style Bundle and referral PDF/print flow.
- [x] Dataset audit and disabled research-only anemia baseline artifact; raw data excluded.
- [x] Dockerfile/Compose configuration and `.env.example` provided.
- [x] Kotlin/Compose/Camera2/Room source, Gradle 8.13 wrapper, and Android CI build workflow included.
- [x] Release ZIP `../AbhayNayan-0.1.0-final.zip` created (74 project files), integrity-checked, and confirmed free of APK claims, SQLite files, real `.env`, build outputs, and `node_modules`; SHA-256 sidecar is adjacent.
- [x] `scripts/verify_all.sh` completed successfully on 8 October 2026.
- [x] Local launch script started Uvicorn; the PWA and core system/demo routes returned HTTP 200.
- [x] JSDOM exercised maternal and newborn synthetic flows, newborn age-in-hours counselling context, safety copy, and local history. This is a simulated DOM test, not a real browser/device test.

## Last verified automated checks

- Python: **60 passed** (`python -m pytest -q`).
- Python compile check: `python -m compileall -q backend tests` passed.
- Python package check: `python -m pip check` reported no broken requirements.
- Web modules: **29 passed** (`npm run test:web`).
- JSDOM workflow: **1 passed** (`npm run test:ui`) — maternal and newborn pathways in a simulated browser DOM.
- Frontend syntax: `npm run check:web` passed.
- Pytest emits one Starlette/httpx deprecation warning; npm reports a deprecated transitive `whatwg-encoding` package.

## Verification not completed

- [ ] Real desktop/mobile browser manual acceptance run and camera permission/orientation test.
- [ ] Android `:app:testDebugUnitTest` and `:app:assembleDebug` completed; no APK is delivered. The wrapper and project configuration work, but the build daemon exited during resource/KSP work in this limited-memory environment. CI workflow is included but has not been executed remotely.
- [ ] Android install, Room persistence, Camera2 lifecycle, TTS voice availability, and accessibility verified on a device/emulator.
- [ ] Docker image build and container health check; Docker is unavailable in this environment.
- [ ] Optional live Gemini call; no key has been used in this build.
- [ ] Clinical validation, prospective study, device/lighting validation, regulatory review, and production security review; none are claimed.

## Non-claims and release blockers for any clinical deployment

1. No approved or clinically validated hemoglobin or bilirubin model, clinical threshold, or patient-use workflow is supplied. Visible numeric values are fixed synthetic fixtures.
2. Camera/import analysis is local quality/feature visualization only; estimates are never computed from image pixels.
3. Dataset license, consent, provenance, and intended reuse remain unverified; do not redistribute raw data.
4. No production authentication, authorization, audit-grade retention, clinical governance, hosting, or regulatory assurance is included.
5. A debug APK—if later produced—is not a store release and is not evidence of clinical readiness.

Any unchecked verification item remains an explicit limitation; do not describe it as complete.
