# ADR-002: Keep Kotlin + Compose + Camera2; defer CameraX

Status: **Proposed** (24 Oct 2026)

## Context
The app is already Kotlin 2.2 + Jetpack Compose + Room + WorkManager (the preferred stack). Capture uses Camera2 directly to take an ambient/torch frame pair with locked exposure and to validate the pair's metadata (exposure, ISO, timing). CameraX can reach these controls only through `Camera2Interop`/`Camera2CameraControl`, and per-frame metadata access is less direct.

## Decision
- No framework migration. Guided capture (Stage 4) is built on the existing `Camera2PreviewView`, behind a `CaptureProtocol` interface that does not depend on Camera2 types.
- Revisit CameraX only if device testing shows Camera2 compatibility problems that CameraX's device quirks database would fix, and only if the flash-pair validation survives the move.

## Consequences
No rewrite risk. Device coverage remains the main unknown until physical-device testing.
