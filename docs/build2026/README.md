# Build 2026 additions (24–25 October 2026)

This phase improves how AbhayNayan is presented. It does not change clinical capability:
- research switches stay off;
- no model was trained, activated, replaced or calibrated;
- no camera or gallery image produces a clinical number;
- the `estimated` / `unable_to_estimate` / `error` / `synthetic_fixture` outcome contract is unchanged.

Neither Agent37 nor Nodus validates or runs any clinical model, and neither receives images, records or health information.

| Document | Contents |
|---|---|
| [assistant.md](assistant.md) | Help assistant and Agent37 integration: design, safety rules, configuration, verification checklist, **status** |
| [nodus.md](nodus.md) | Knowledge-base and assistant evaluation workload on Nodus compute: what runs, how to reproduce, **status** |
| [terms.md](terms.md) | Terms & Conditions: content source, versioning, acceptance behaviour |
| [evidence.md](evidence.md) | Evidence manifest and the tests executed |

## What was added

| Area | Web (AbhayNayan_web) | Android (AbhayNayan_apk) |
|---|---|---|
| Visual design | Public-service style: plain navy header, white navigation, flat cards, 15–16 px text, higher-contrast greys, amber focus ring, structured footer. Large repeated warning banners became one-line notes linking to the terms. Result screens keep their provenance banner and safety box | Same palette in `Palette` (Theme.kt). Home ends with one quiet line instead of a warning card. Results unchanged |
| Home | Welcome panel with the main actions, a four-step "how it works" strip, status cards, workflows, recent records and quick links | Terms & Conditions and Get the app buttons |
| Terms & Conditions | Settings card, a full page and a review dialog before the first screening ([terms.md](terms.md)) | Settings card, a full screen and a review dialog before the first screening |
| Get the app (QR) | Footer link, Settings card and page. A QR generated in the browser opens the web app | Settings and Home lead to a screen with a QR generated on the phone (ZXing), plus copy, share and open |
| Help assistant | Page that calls `POST /api/assistant/ask` | Not added (web only) |
| Backend | `app/assistant/` (knowledge base, guards, Agent37 adapter, service). API contract **1.4.0** (additive) | — |
| Evaluation | `scripts/assistant_eval/` (Nodus workload, bundle, job wrapper) | — |
| Tester APK | — | `qa` build type: release behaviour, signed with the debug key, separate ID `in.abhaynayan.app.qa`, same research-artifact check as release |

## Pre-existing (not changed in this phase)

The following are preserved and their tests still pass:
- capture limits and image compatibility checks;
- the prediction envelope and safe-outcome handling;
- SQLCipher encryption with the Keystore-wrapped key;
- record hashes, warning index and migrations (Phase 6);
- the demo sync and its integrity gate;
- Gemini counselling.

Outcome-record sync is still **not** implemented.

## QR destination

| Item | Value |
|---|---|
| Destination | `https://abhaynayan-web.onrender.com/`, labelled **Open the web app** |
| Why | There is no public Android release: no GitHub releases on `shubhamcore/AbhayNayan_apk`, and the Play Store page for `in.abhaynayan.app` returns 404 (checked 24 Oct 2026) |
| Verified how | HTTP 200, the AbhayNayan page title, and `/api/health` answered (the deployed build is older, contract 1.1.0) |
| Where it is set | Web: `web-dashboard/js/distribution.js`. Android: Gradle properties `abhaynayanAppShareUrl`, `abhaynayanAppShareKind` (defaults are the web app) |
| Rules | https only, no credentials, query or fragment, no local or IP hosts, never an APK/AAB file. An invalid value shows "The app link is not available yet" and **no QR** |
| Generation | Web: vendored `qrcode-generator` 2.0.4 (MIT, integrity-checked, `js/vendor/README.md`). Android: ZXing core 3.5.3. Both run locally, so no QR service sees the URL |
| Decoding tests | Web: `tests/test_qr_destination.py` decodes the browser module's matrix with OpenCV. Android: `TermsAndDistributionTest.qrCodeDecodesToTheExactUrl` decodes with ZXing's reader |

**To switch to a real installation page later:**
1. Publish an authorized page, never a debug or research APK.
2. Web: set `kind: 'android_install_page'` and `url` in `distribution.js`.
3. Android: build with `-PabhaynayanAppShareKind=android_install_page -PabhaynayanAppShareUrl=https://…`.

The label then changes to "Install the Android app".

## Architecture

```
Android app ──(unchanged: capture, refusal, encrypted records, integrity, demo sync)
Web app (PWA) ─ new UI, terms gate, QR page ──► FastAPI (contract 1.4.0)
                 help assistant page ─────────►  POST /api/assistant/ask
                                                   │ guard → retrieve (curated KB) → optional Agent37 wording → validator
                                                   └──► Agent37 instance (server-side key; only approved passages + guarded question)
scripts/assistant_eval (stdlib only) ── bundle ──► Nodus compute job ──► report.json (non-clinical evaluation)
```
