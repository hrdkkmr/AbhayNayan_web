# CI proposal (APPLIED 24 October 2026 after approval Q6)

**Status:** applied with `git apply` to `AbhayNayan_web/.github/workflows/ci.yml` and `AbhayNayan_apk/.github/workflows/android.yml` (uncommitted).

**One deliberate deviation from `android-ci.patch`:** as you preferred, `gradlew` was made executable in Git (`git update-index --chmod=+x AbhayNayan/android/gradlew`, mode 100644 → 100755, staged, blob unchanged). The `chmod +x gradlew` step was therefore removed from the applied workflow, and its header comment was updated. The patch files below are kept unchanged as the reviewed record.

Prepared in Phase 4 (24 October 2026). The patches pass `git apply --check` against the current trees and both resulting YAML files parse.

| File here | Would change | Apply with |
|---|---|---|
| [web-ci.patch](web-ci.patch) | `AbhayNayan_web/.github/workflows/ci.yml` | `git apply docs/ci_proposal/web-ci.patch` (in AbhayNayan_web) |
| [android-ci.patch](android-ci.patch) (= [android.yml](android.yml)) | **new** `AbhayNayan_apk/.github/workflows/android.yml` at the repository root | `git -C ../../AbhayNayan_apk apply <path>/android-ci.patch` |

## Problems solved

| # | Problem (evidence) | Change |
|---|---|---|
| F1 | Web CI fails on every push. The `android` job builds the stale `android/` copy (unescaped `package in.…`, which does not compile), and `gradlew` is stored as mode `100644`, so `./gradlew` cannot even execute on Linux (`git ls-files -s android/gradlew`) | Remove the `android` job from the web repo. Android CI belongs to the Android repo ([ADR-001](../adr/ADR-001-canonical-sources.md)) |
| F2 | Android repo has never run CI: its workflow is at `AbhayNayan/.github/workflows/ci.yml`, and GitHub reads only the root `.github/` (Actions API: 0 runs) | Add a root workflow with `working-directory: AbhayNayan/android` |
| M7 | Research models must never reach a release | Android job runs `:app:assembleRelease :app:bundleRelease`; the build itself fails if an artifact contains research files (verified locally: fails with assets, passes from a clean copy). Web job builds the release ZIP and runs `scripts/check_release_artifacts.py` |
| — | No Android lint in CI | `:app:lintDebug` (0 errors today) |

## Web `ci.yml` diff (summary)

```diff
-  android:
-    name: Android compile, unit tests, and debug APK
-    … setup-java, setup-gradle, ./gradlew … assembleDebug, upload app-debug.apk (14 days)
+  release-artifacts:
+    name: Release ZIP contains no research model artifacts
+    steps: checkout · setup-python 3.13
+      - run: python scripts/package_release.py --output dist/abhaynayan-ci-check.zip
+      - run: python scripts/check_release_artifacts.py dist/abhaynayan-ci-check.zip
```

The `python-api` and `web` jobs are unchanged. The full diff is in `web-ci.patch`.

## Android `android.yml` (new)

checkout → Temurin JDK 17 → `gradle/actions/setup-gradle@v4` → `chmod +x gradlew` → `./gradlew --no-daemon :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease :app:bundleRelease` → upload **test and lint reports only** (7 days).

## Security and maintenance implications

- **Permissions:** `contents: read` only; no secrets are used, no signing keys are needed (release outputs are unsigned and only verified), and nothing is deployed or published.
- **No APK distribution:** unlike the current web job, the proposal does **not** upload APKs. A CI debug APK would contain no research assets (gitignored), but uploading builds is a release-process decision (Phase 12).
- **Third-party actions:** `actions/checkout@v4`, `actions/setup-java@v4`, `actions/setup-python@v5`, `gradle/actions/setup-gradle@v4`, `actions/upload-artifact@v4`, the same set the repos already use. Pinning them to commit SHAs is stronger supply-chain hygiene and is recommended once you approve the workflows (it needs the exact SHAs looked up at that time).
- **Cost/time:** the Android job takes about 10–15 min on a hosted runner (local measurements: unit tests ~4 min, release + bundle ~6 min on this laptop; CI timing not measured). `timeout-minutes: 45`, and concurrency cancels superseded runs.
- **Old nested workflow:** `AbhayNayan_apk/AbhayNayan/.github/workflows/ci.yml` stays inert. Deleting it is a separate cleanup decision.
- **The `gradlew` mode** could instead be fixed in Git (`git update-index --chmod=+x`), which is a repository change. The `chmod` step avoids touching the index.

## Independence

The rest of Phase 4 (orientation, readiness, authentication, rate limiting, configuration validation, release guards) is complete and tested locally **without** these CI changes. Approving them adds automated enforcement (AC-MOD-07 in CI, regression protection on every push).
