# AbhayNayan release notes

**Package:** 0.1.0-final-demo · **Updated:** 9 October 2026

This is a hackathon **prototype source release**, not a clinical product. It contains the runnable FastAPI-served PWA, demo API, tests, documentation, native Android source, and Docker configuration. No APK is included.

## Latest native-source iteration

- Added a testable pure-Kotlin image pipeline for manual geometric ROI crop, clipped/percentile-normalized positive flash-minus-ambient visualization, RGB means/ratios/standard deviations, CIE Lab*, YCrCb, chromaticity, and valid-pixel reporting.
- Added abstract offline color-chart pixels for exercising the local pipeline without a camera or anatomical image.
- Added a `ScreeningModel` load/predict/close boundary, explicit fixed-fixture DEMO adapter (no confidence estimate), and fail-closed missing-clinical-model path. No TFLite runtime/weights or clinical tensor contract is bundled.
- Extended the Camera2 preview utility to attempt an ambient preview snapshot plus a brief torch-on preview snapshot. It falls back to ambient-only if flash/capture fails; auto exposure stays enabled and no ISO/exposure lock is claimed.
- Added on-device debug previews for ambient, flash, compensated, and ROI images, along with the locally measured image-processing time. This timing is not model-inference time.
- Allowed a fixed fixture to follow a Camera2 capture only for a synthetic demo profile. The fixture remains independent from captured pixels/features, is labelled `FIXED DEMO VALUE · NOT FROM IMAGE`, and is not available for a local/non-demo profile.
- Added Android unit-test source for ROI bounds/crops, feature extraction, clipping, and differential fallback. These tests have not been executed because this sandbox currently exposes JDK 11 and the previous JDK17/API36 build attempt exited under its memory limit.

## Existing user-visible prototype workflows

- Maternal-anemia and neonatal-jaundice PWA demo journeys with distinct local synthetic maternal/newborn profiles; newborn context includes age in hours.
- Local browser camera/file quality and color-feature visualization; manual guide; no image upload.
- Fixed deterministic PWA fixtures selected only through the explicit synthetic-demo path; no estimate is inferred from pixels or patient data.
- Offline local profile/history storage, queued synthetic demo sync, English/Hindi/Bhojpuri deterministic counselling, optional server-only Gemini adapter, local FHIR-style JSON, referral PDF/print, and PHC prototype dashboard.
- FastAPI safety schemas, server-side demo-profile guards, SQLite demo store, OpenCV utilities, and local fallback copy.

## Verification

The latest verified web/backend checks passed: **60 Python tests, 29 Node.js web-module tests, and 1 JSDOM maternal/newborn workflow smoke**; Python `compileall`, `pip check`, and web syntax checks also passed. These tests do not compile or test Android. The Android CI workflow is included but has not been run; the latest native Camera2/Compose/pipeline additions are uncompiled and unverified. Docker, live Gemini, real-device camera behavior, and clinical validation are also not verified.

## Release archive hygiene

`python3 scripts/package_release.py` creates `../AbhayNayan-0.1.0-final.zip` and a SHA-256 sidecar. The archive excludes `.env` secrets, generated SQLite databases/local records, virtual environments, `node_modules`, Android/Gradle build caches, and other generated output. It includes `.env.example`, the Gradle wrapper, Android source and tests, documentation, and web/backend source. A locally built APK is only included if the packager is explicitly invoked with `--include-android-apk` and the expected APK exists.

## Limitations

- No approved or clinically validated hemoglobin/bilirubin model is supplied; displayed fixture values are synthetic and independent of image features.
- No MediaPipe landmarks, face/eye/blink/distance/motion checks, or anatomy-aware segmentation are present in Android; the ROI is a manually positioned geometric crop.
- Experimental F−A visualization is not color-calibrated or proven illumination-invariant.
- No active Android TFLite adapter/weights, native Gemini/API/sync workflow, or production Android parity is included.
- The Android project has not been compiled after the latest additions, installed, or device-tested; no APK is delivered.
- The research baseline is disabled research material; data reuse permissions are unverified.
- Docker, live Gemini, production security, clinical performance, regulatory readiness, and real-patient use are not claimed.
