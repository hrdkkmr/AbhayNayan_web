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

The wrapper has been bootstrapped and `./gradlew --version` succeeds. In this sandbox, a temporary JDK 17/API 36 toolchain was provisioned and Gradle project configuration worked, but the daemon exited during resource/KSP work before compilation, Android unit tests, or APK assembly completed. No APK is currently delivered. A hosted Android CI job is configured in `../.github/workflows/ci.yml` but has not yet been executed. Read `../docs/ANDROID_STATUS.md` for exact evidence and the device-verification checklist.

## Native demo flow

1. Choose the synthetic demo profile or create a consented local-only profile.
2. Select maternal anemia or neonatal jaundice.
3. Grant optional Camera permission. Camera2 captures an ambient `TextureView` preview snapshot and, when the device supports it, a short torch-on preview snapshot; if flash fails, it falls back to ambient-only. This is not a still-photo pair and does not lock exposure or ISO.
4. Review the basic brightness/edge engineering check, manually confirm the geometric guide, and inspect the local ROI, F−A visualization, RGB/Lab*/YCrCb features, and measured image-processing time. There is no face/eye landmark detector or anatomical ROI model.
5. A fixed demo case may follow the camera flow only for a synthetic demo profile. The case value is selected independently of the camera image/features and is labelled `FIXED DEMO VALUE · NOT FROM IMAGE`. Local/non-demo profiles cannot save a fixture result.
6. Review the safety notice; use English/Hindi/Bhojpuri deterministic counselling/TTS and share local FHIR-style JSON/referral text. Temporary image buffers are held in memory for the local preview and are not stored with the screening.

The native source is a focused shell; it does not have parity with every PWA dashboard, sync, Gemini workflow, or required registration field. The TFLite interface is not active and there is no clinically validated inference model. The new Android pipeline/unit-test sources have not been compiled or run here; no APK/device verification is claimed. See `../docs/ANDROID_STATUS.md` and `../docs/SAFETY.md`.
