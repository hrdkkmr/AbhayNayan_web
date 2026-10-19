# Android source and build status

**Status as of 9 October 2026:** native source advanced, but the latest Kotlin/Compose changes are **not yet compiled or device-tested**. No APK is delivered. Treat the PWA/API as the runnable demo until Android CI succeeds.

## Native source currently included

`android/` contains a Kotlin/Jetpack Compose prototype with:

- Room entities/DAOs for local synthetic patient profiles and screening records;
- rear Camera2 preview with a best-effort ambient `TextureView` snapshot and brief torch-on snapshot; ambient-only fallback is used when flash is unavailable or fails;
- local in-memory geometric ROI crop and preview of ambient, flash, compensated, and ROI images;
- experimental clipped/normalized flash-minus-ambient visualization;
- RGB means, R/G/B ratios, RGB standard deviation, CIE Lab*, YCrCb, chromaticity, and valid-pixel summary;
- basic local brightness/edge engineering proxy and a manual region-confirmation gate;
- a `ScreeningModel` load/predict/close abstraction with a named fixed-fixture DEMO adapter and a fail-closed missing-clinical-model adapter; fixed maternal/newborn cases are independent from camera pixels/features and expose no confidence value;
- English/Hindi/Bhojpuri deterministic safety copy and optional Android TTS;
- local FHIR-style JSON and referral-text share intents;
- pure-Kotlin pipeline test source for ROI bounds/crops, feature vectors, pixel clipping, and ambient-only/dimension-mismatch fallback.

## Important implementation boundaries

- Camera inputs are **preview snapshots**, not an `ImageReader` still-photo pair. A torch is enabled briefly when supported. Auto exposure remains enabled; no ISO/exposure lock is performed. Camera2 failures fall back to a single ambient frame instead of intentionally crashing the flow.
- There is no MediaPipe model, face/eye/blink/distance/motion detector, anatomy-aware ROI segmentation, or validated image-quality gate. The central ROI is a manual geometric crop; maternal/newborn anatomy is not detected.
- F−A processing is a clipped and percentile-normalized visualization prototype. It is not color-calibrated, clinically calibrated, or proven invariant to ambient illumination.
- The extracted features are engineering/debug data only. They do not feed the result selector. The fixed synthetic fixture is selected separately and can follow a camera preview only for a synthetic demo profile; it is never presented as a camera-derived estimate. A local/non-demo profile cannot save a fixture result.
- No `.tflite` weights/runtime adapter, active Gemini client, Android sync queue, or full native patient-demographic/referral/history/settings flow is included. Those capabilities are not implied by this focused Android shell; the broader prototype flows are primarily in the PWA/backend.
- Frame buffers are held in memory for immediate local review and are not saved with a screening record. The native manifest intentionally omits Internet permission.

## Build tooling and verification

- Gradle 8.13 wrapper scripts/JAR are included (`android/gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar`). A previous `./gradlew --version` and Gradle project-configuration attempt succeeded.
- A GitHub Actions job is included at `.github/workflows/ci.yml`; it installs JDK 17, runs Android unit tests and `assembleDebug`, then uploads the APK. This workflow has not been run in GitHub Actions.
- A previous temporary JDK 17 / Android API 36 build attempt reached resource/KSP tasks, but the Gradle daemon exited under the sandbox's memory ceiling before Kotlin compilation, tests, or APK assembly. The current sandbox exposes JDK 11, not the required JDK 17. The newly added `OpticalPipeline.kt`, Compose integration, and associated test sources have therefore **not** been compiler-verified.
- No Android unit-test result, successful APK, emulator installation, device run, or Camera2/flash lifecycle verification is claimed. No APK is included in the release.

## Build on a provisioned machine

Requirements: JDK 17, Android SDK platform 36, Android build-tools 35 or compatible AGP-selected version, network access for Maven/Google dependencies, and enough RAM for Gradle/Kotlin compilation.

```bash
cd android
./gradlew --no-daemon :app:testDebugUnitTest :app:assembleDebug
```

PowerShell:

```powershell
cd android
.\gradlew.bat --no-daemon :app:testDebugUnitTest :app:assembleDebug
```

Expected debug output: `android/app/build/outputs/apk/debug/app-debug.apk`. Do not call this a compiled artifact until the command succeeds. Then install and test on an Android 8+ device/emulator: camera permission denial/grant, camera lifecycle, torch availability/failure, ambient-only fallback, image quality rejection/retry, Room persistence, TTS language availability, accessibility, and memory cleanup. A debug APK is not a store release or evidence of clinical readiness.

The runnable primary demo remains the FastAPI-served PWA; it is not a replacement claim for the native app.
