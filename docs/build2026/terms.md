# Terms & Conditions

## Source and versioning

- **Canonical file:** `web-dashboard/assets/terms/terms.json`. Android ships a byte-identical copy at `app/src/main/assets/terms/terms.json`. Both test suites pin its SHA-256 (`d79ea4c9…` with LF line endings), so the copies cannot drift silently.
- **Version fields:**
  - `version` changes with every edit.
  - `acceptance_version` changes **only for a material change**.
  - `last_updated` is a date.
- **Current version:** `version` 1.0, `acceptance_version` 1.0, last updated 2026-10-24.
- **Language:** English only. No Hindi or Bhojpuri translation was added, because none has been reviewed.
- **Review status:** the file states that it has not been reviewed by a lawyer or a clinician.

To change the terms:
1. Edit the JSON and bump `version`. Also bump `acceptance_version` if the change is material.
2. Copy the file to Android.
3. Update the pinned SHA-256 in `tests/build2026-ui.test.mjs` (via the shared file), `TermsAndDistributionTest.kt` and this page.

The web service worker fetches the terms network-first, so a new version is seen as soon as the device is online.

## Behaviour (web and Android)

| Situation | Result |
|---|---|
| Browsing Home, Records, Settings, Help, the terms, Get the app | Never blocked |
| Starting a screening with no stored acceptance | A review dialog shows the version, the date and four summary points, with **Read the full terms**, **Not now** and **I have read and accept** |
| "Not now" | Nothing starts and nothing is stored |
| "I have read and accept" (dialog or full page) | Stores `{version, acceptance_version, accepted_at}` on this device only (web: IndexedDB or localStorage settings; Android: SharedPreferences). No name or identifier. The pending workflow then starts |
| A new `version` with the same `acceptance_version` | No new prompt (wording-only change) |
| A new `acceptance_version` | "The terms have changed" dialog before the next screening |
| Terms file missing or malformed | No screening starts; the dialog says the terms could not be loaded and offers nothing to accept |
| "Clear all local app data" (web) | Also clears the acceptance (it is a setting), so the terms are asked again |
| "Delete all local data" (Android) | Deletes records and profiles only. Settings, including the acceptance, are kept; clearing app data in Android settings removes it |

Accepting is explicitly **not** consent to research, image upload or sharing personal data. The point-of-use safety messages stay where they are:
- the result provenance banner and safety box;
- `unable to estimate` explanations;
- the research indication next to workflows;
- the consent checkbox for local profiles.

Tests: `tests/build2026-ui.test.mjs` (gate, "Not now", stored fields, material change, load failure, Settings and page status) and Android `TermsAndDistributionTest`.
