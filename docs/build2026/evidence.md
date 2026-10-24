# Evidence manifest and test results (24–25 October 2026)

Raw platform output belongs in `evidence/local/` (ignored by Git). Review and redact it before sharing. Nothing here was published.

## Platform evidence

| Platform | Evidence that exists | Evidence still needed |
|---|---|---|
| Agent37 | None from the platform. Only mocked-API tests (`tests/test_assistant.py`) | Instance ID, dashboard screenshot, and the `create` / `health` / `smoke` JSON from `scripts/agent37/agent37_instance.py` ([assistant.md](assistant.md) checklist) |
| Nodus | None from the platform. A local run of the same workload passed: label `local`, 54/54 question cases and 20/20 provider-output cases, knowledge base `2026-10-24.1` | Job name and ID, `nodus describe`, `nodus logs`, the `report.json` downloaded with `nodus cp` and verified by `nodus_job.py` ([nodus.md](nodus.md)) |

Neither integration is claimed to be complete. Both were blocked by the lack of an account, key or credits in this environment.

## Other evidence

| Item | Evidence |
|---|---|
| QR destination | `https://abhaynayan-web.onrender.com/` returned HTTP 200 with the AbhayNayan title. `/api/health` answered (deployed contract 1.1.0, an older build). GitHub releases API: none. The Play Store page for `in.abhaynayan.app`: 404 |
| QR decodes | `tests/test_qr_destination.py` (OpenCV decode of the browser module's matrix) and Android `TermsAndDistributionTest.qrCodeDecodesToTheExactUrl` (ZXing decode) |
| QR library | `qrcode-generator` 2.0.4 tarball integrity matched the npm registry. The vendored file's SHA-256 is pinned in a test |
| UI | Local server and Chrome, 24–25 Oct 2026: <br>• desktop 1366 px and 375 px / 320 px frames; <br>• every page has no horizontal overflow, after fixing two found by this check (long terms URLs; model-page badges at 320 px); <br>• the terms dialog appeared before the first screening; <br>• the assistant answered in knowledge-base mode and refused "What is my hemoglobin?" |

Screenshots were viewed during the check but not saved as files.

## Tests executed (final run)

| Suite | Result |
|---|---|
| Python `.venv` (`PYTHONPATH=backend python -m pytest -q`) | 452 passed, 1 skipped (`jsonschema` not installed in `.venv`, as before) |
| Python `.venv-ml` | 453 passed |
| Node `npm test` | 32 passed (unit), 16 passed (UI: browser smoke, offline sync, Build 2026), `check:web` OK |
| Android `:app:testDebugUnitTest` | 203 run, 0 failed, 1 skipped (`liveBackendAcceptsRecordAndProducesReferralPdf` needs a live backend, as before) |
| Android `:app:lintDebug` | 0 errors, 22 warnings (dependency-version and style notices) |
| Android `:app:assembleDebug`, `:app:assembleDebugAndroidTest` | Succeeded |
| Android `:app:assembleQa` from a clean checkout | Succeeded; see the tester APK folder (outside Git) |
| Assistant evaluation workload, local | pass (54/54, 20/20, 0 knowledge-base problems) |
| Model pins (`models/MODEL_REGISTRY.json`) | 5/5 SHA-256 match |

**Not run in this phase:**
- instrumented emulator tests (storage code is unchanged since Phase 6, when they passed 13/13);
- physical-device tests;
- JDK 17 builds.

## Tests whose expectations changed

| Test | Before | Now | Why |
|---|---|---|---|
| `tests/browser-smoke.test.mjs`, `tests/offline-sync.test.mjs` | waited for `.hero-panel` | wait for `.welcome-panel`; accept the terms dialog before the first screening; serve the terms file | Home was redesigned and the terms gate is new. Every earlier assertion is unchanged |
| `tests/test_record_integrity.py` | contract `1.3.0` | `1.4.0` | The contract changed (additive assistant endpoints) |
| `OutcomeSyncTest` comment, `OutcomeSync` message | "1.3.0" | "1.4.0" | Same; outcome sync is still unavailable |
