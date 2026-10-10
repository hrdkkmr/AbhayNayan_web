# AbhayNayan release notes

## 0.2.0 · API contract 1.0.0 · 10 October 2026

Prototype update, not a clinical product. Highlights:

- **Contract 1.0.0** shared with Android: error envelope with stable codes, `X-AbhayNayan-Contract-Version` header, explicit `provenance`, nullable `confidence`/`quality_score` (fixtures now send `null` instead of invented placeholders), `context.infant_age_hours`, `id_origin`, and server IDs prefixed `srv-`. See [API_CONTRACT.md](API_CONTRACT.md) for the change list.
- **Sync:** each record is validated on its own. Results are `accepted`/`duplicate`/`conflict`/`rejected`; a reused ID with different content is a conflict (first write wins). The PWA keeps failed items queued with attempt counts and flags rejected/conflicting records.
- **Model adapters:** separate maternal and neonatal adapters with model cards, both `DISABLED_NO_VALID_MODEL` and fail-closed. The anemia research baseline can be enabled for research-dataset features only. See [ML_MODEL_CARD.md](ML_MODEL_CARD.md).
- **Gemini:** no hard-coded model; `models.get` verification; classified fallbacks; safety fields always deterministic; provider-reported token telemetry; idempotent `request_id`; demo-only cache; admin usage report. See [TOKEN_USAGE.md](TOKEN_USAGE.md).
- **FHIR/referral:** HTEST security tag on synthetic data, text-only codes, provenance and timestamps on PDF and print, Devanagari PDF fonts when available.
- **UI:** provenance banner and badges, required newborn age in hours, sync-problem dashboard card and list, model audit page with notebook findings, admin usage page, readable typography (no text below 11 px).
- **Data:** dataset manifest, aggregate-only audit scripts, `.gitignore` for raw data and weights. Nothing from the Drive folder is committed. See [DATA_PROVENANCE.md](DATA_PROVENANCE.md).
- **Tests:** 119 Python, 32 Node module and 4 JSDOM workflow tests pass via `scripts/verify_all.sh`. Not verified: a live Gemini call, Docker, devices, and the Android build.

---


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

The latest regression passed **60 Python tests, 29 web-module tests, and 1 JSDOM maternal/newborn workflow smoke**; Python compileall, `pip check`, and web syntax checks also passed. The Android Gradle wrapper is included and `--version`/project configuration work, but the Android compile/unit-test/APK build did not complete in the low-memory sandbox. See `docs/ANDROID_INTEGRATION.md`; do not infer an APK from the source or wrapper.

## Release archive hygiene

`python3 scripts/package_release.py` creates `../AbhayNayan-0.1.0-final.zip` and a SHA-256 sidecar. The archive excludes `.env` secrets, generated SQLite databases/local records, virtual environments, `node_modules`, Android/Gradle build caches, and other generated output. It includes `.env.example`, the Gradle wrapper, source, docs, and tests. A locally built APK is only added if the packager is invoked with `--include-android-apk`.

## Limitations that remain

- No approved or clinically validated hemoglobin/bilirubin model is supplied; fixture values are synthetic and for demonstration only.
- No real-patient or clinical use, diagnosis, triage, treatment change, or delay of care is supported.
- The dataset baseline is disabled research material; reuse permissions are unverified.
- Docker, live Gemini, real-device camera behavior, and production security require independent environment-specific verification.
- A compiled debug APK, if delivered, is not a signed store release or evidence of clinical readiness.
