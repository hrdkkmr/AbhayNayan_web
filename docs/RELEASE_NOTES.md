# AbhayNayan release notes

**Package:** 0.1.0-final-demo · **Date:** 8 October 2026

This is a final hackathon **prototype release**, not a clinical product. It contains a runnable FastAPI-served PWA, demo API, tests, setup/verification scripts, native Android project source, and Docker configuration.

## User-visible workflows

- Maternal-anemia and neonatal-jaundice demo journeys.
- Distinct local synthetic maternal and newborn profiles; newborn counselling context uses age in hours.
- Local camera/file quality and color-feature visualization; manual target guide; no image upload endpoint.
- Fixed deterministic examples selected by the operator; no biomarker estimate is inferred from pixels or from patient data.
- Offline local profile/history storage, queued synthetic demo sync, English/Hindi/Bhojpuri deterministic counselling, optional server-only Gemini adapter, local FHIR-style JSON, referral PDF/print, and PHC prototype dashboard.
- Added server-side guards: fixed fixture creation, FHIR export, sync, and referral generation reject local/non-demo patient profiles where applicable.

## Verification

The latest regression passed **60 Python tests, 29 web-module tests, and 1 JSDOM maternal/newborn workflow smoke**; Python compileall, `pip check`, and web syntax checks also passed. The Android Gradle wrapper is included and `--version`/project configuration work, but the Android compile/unit-test/APK build did not complete in the low-memory sandbox. See `docs/ANDROID_STATUS.md`; do not infer an APK from the source or wrapper.

## Release archive hygiene

`python3 scripts/package_release.py` creates `../AbhayNayan-0.1.0-final.zip` and a SHA-256 sidecar. The archive excludes `.env` secrets, generated SQLite databases/local records, virtual environments, `node_modules`, Android/Gradle build caches, and other generated output. It includes `.env.example`, the Gradle wrapper, source, docs, and tests. A locally built APK is only added if the packager is invoked with `--include-android-apk`.

## Limitations that remain

- No approved or clinically validated hemoglobin/bilirubin model is supplied; fixture values are synthetic and for demonstration only.
- No real-patient or clinical use, diagnosis, triage, treatment change, or delay of care is supported.
- The dataset baseline is disabled research material; reuse permissions are unverified.
- Docker, live Gemini, real-device camera behavior, and production security require independent environment-specific verification.
- A compiled debug APK, if delivered, is not a signed store release or evidence of clinical readiness.
