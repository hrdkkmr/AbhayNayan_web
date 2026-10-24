# ADR-001: Canonical sources and CI ownership

Status: **Proposed** (24 Oct 2026) · Needs agreement from both repository owners

## Context
Each repository contains a stale copy of the other's code. `AbhayNayan_web/android/` does not compile (unescaped `in` package). Building it makes web CI fail on every push. `AbhayNayan_apk/AbhayNayan/{backend,web-dashboard,tests}` lags behind the web repo. The Android repo's workflow sits under `AbhayNayan/.github/`, which GitHub does not read, so that repo has never run CI.

## Decision
- Backend and PWA: `hrdkkmr/AbhayNayan_web` only. Android: `shubhamcore/AbhayNayan_apk`, path `AbhayNayan/android`, only.
- Web CI drops its Android job now. Android CI moves to `AbhayNayan_apk/.github/workflows/android.yml` with `working-directory: AbhayNayan/android`.
- The stale copies are deleted in a separate commit once both owners agree. Shared contracts (`API_CONTRACT.md`, golden vectors) are copied by script (`scripts/ml/export_*`), not by hand.

## Consequences
CI becomes meaningful in both repos. Cross-repo changes need two coordinated PRs; the contract version header catches drift.
