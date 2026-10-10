# Native Android prototype source

This is a Kotlin/Compose Android shell for the AbhayNayan demo. It uses Room, Camera2 preview, a manual target guide, a local brightness/edge quality proxy, fixed synthetic case fixtures, and Android TextToSpeech. It has no network permission, no image upload, no active clinical model, and no patient-image persistence.

## Build environment

- JDK 17
- Android SDK platform 36 and compatible build tools
- Gradle 8.13 (wrapper included)
- Kotlin 2.2.20, Compose compiler plugin, and KSP as configured in `app/build.gradle.kts`

Build/test command:

```bash
./gradlew --no-daemon :app:testDebugUnitTest :app:assembleDebug
```

> The canonical Android source is now the separate `shubhamcore/AbhayNayan_apk` repository; this folder is a stale snapshot (see `../docs/ANDROID_INTEGRATION.md`).

The wrapper has been bootstrapped and `./gradlew --version` succeeds. In this sandbox, a temporary JDK 17/API 36 toolchain was provisioned and Gradle project configuration worked, but the daemon exited during resource/KSP work before compilation, Android unit tests, or APK assembly completed. No APK is currently delivered. A hosted Android CI job is configured in `../.github/workflows/ci.yml` but has not yet been executed. Read `../docs/ANDROID_INTEGRATION.md` for exact evidence and the device-verification checklist.

## Native demo flow

1. Choose the synthetic demo profile or create a local profile with consent.
2. Select maternal anemia or neonatal jaundice.
3. Grant optional Camera permission for a local Camera2 preview, or choose the abstract synthetic image.
4. Confirm the manual ROI and local quality gate.
5. Run a named fixture only when both profile and capture are synthetic. A real Camera2 frame is for local quality preview only; it cannot be linked to a synthetic estimate.
6. Review the safety warning, use local English/Hindi/Bhojpuri counselling/TTS, and share a local FHIR-style JSON/referral text.

The native source is a focused shell; it does not have parity with every PWA dashboard, sync, or Gemini workflow. It has no clinically validated inference model. See `../docs/SAFETY.md`.
