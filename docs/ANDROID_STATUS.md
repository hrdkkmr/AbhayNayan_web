# Android source and build status

## Native source included

`android/` contains a Kotlin/Jetpack Compose shell with:

- Room entities/DAOs for local synthetic patient profiles and screening records;
- optional Camera2 preview and a local in-memory preview snapshot;
- a manual target guide and simple brightness/edge quality proxy;
- fixed synthetic maternal-anemia and neonatal-jaundice fixtures;
- a disabled-model interface that refuses to infer an estimate from optical features;
- English/Hindi/Bhojpuri deterministic safety copy and optional Android TTS;
- local FHIR-style JSON and referral text share intents.

The native result path requires both a synthetic profile and an abstract synthetic capture. Camera2 preview frames are not saved, exported, or used as the source of a numeric result. The manifest intentionally has no Internet permission.

## Build tooling and verification

- Gradle 8.13 wrapper scripts/JAR are included (`android/gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar`). `./gradlew --version` completed successfully.
- A GitHub Actions job is included at `.github/workflows/ci.yml`; it installs JDK 17 on a hosted runner, runs Android unit tests and `assembleDebug`, then uploads the APK artifact. This workflow has not been run in GitHub Actions.
- A temporary JDK 17 and Android API 36 toolchain were provisioned in the sandbox. Gradle project configuration and task listing succeeded. Attempts at `:app:testDebugUnitTest :app:assembleDebug` reached Android resource processing/KSP, but the Gradle daemon exited before Kotlin compilation/tests completed. The limited-memory sandbox could not complete the build. No successful APK artifact is present in the release.
- No emulator/device run, installation, Camera2 verification, or Android unit-test result is claimed. SDK tooling also emitted an Android SDK XML-version compatibility warning.

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

Expected debug output: `android/app/build/outputs/apk/debug/app-debug.apk`. Only call this a compiled artifact after the command succeeds. Before distribution, verify install and camera-less synthetic mode on an Android 8+ device/emulator, camera permission/lifecycle behavior, Room, TTS, accessibility, and signing requirements. A debug APK is not a store release or evidence of clinical readiness.

The runnable primary demo remains the FastAPI-served PWA; it is not a replacement claim for the native app.
