# Security and permissions

Status: **Design (Phase 3, 24 October 2026). Partly implemented in Phase 4**: server-signed access tokens, the `research_operator` gate on research routes, in-process rate limits, upload limits, startup secret validation ([ADR-007](adr/ADR-007-interim-access-tokens.md), [configuration.md](configuration.md)). Not implemented: Google sign-in, refresh tokens, grants, consent, studies, synthetic-test subjects, offline permission tokens. Implementation: Phase 4 (limits, rate limiting, config validation), Phase 8 (identity, grants, consent), Phase 11 (sharing). Refines [ADR-004](adr/ADR-004-identity.md).

Today there is no authentication apart from the admin usage token. "Research" and "demo" behaviour is unlocked by a profile checkbox (`isSyntheticDemo` / `patient.demo`), which is audit finding M5, and `/api/ml/*` is open whenever its flag is on (M6). This document replaces both.

**Rule zero: a client-side value (checkbox, role field, toggle, profile flag) never grants permission.** The server derives every permission from the verified identity and server-held grants. Android enforces the same rules offline only from a server-signed, expiring permission token (§3.3).

## 1. Authentication vs authorization

| | Authentication | Authorization |
|---|---|---|
| Question | Who is calling? | May this caller do this action on this subject, now? |
| Mechanism | Google ID token verified by the backend, which then issues its own session | Policy function over server-held `grants`, `memberships`, `studies` and `consents`; deny by default |
| Where | `POST /api/auth/google` only | Every protected route, every query (rows filtered by grant), every sync item |

### 1.1 Google ID token verification (backend)

1. The client gets an ID token: Android Credential Manager (`GetSignInWithGoogleOption`), web Google Identity Services.
2. The backend verifies the signature against Google's published JWKS (cached per their `Cache-Control`), `iss` ∈ {`accounts.google.com`, `https://accounts.google.com`}, `aud` ∈ configured client IDs, `exp`/`iat` with ≤ 60 s skew, and `email_verified = true`. The `nonce` is checked where the flow supplies one.
3. `sub` maps to an internal `user_id`. The email is stored only if needed for account recovery and is never used as a key or put in logs.
4. The backend issues an **access token** (short-lived, configurable, proposed 15 min) and a **rotating refresh token** (stored hashed, bound to a random per-install ID, revocable). The Google token is discarded.
5. Web sessions use `HttpOnly; Secure; SameSite=Strict` cookies plus CSRF protection on state-changing routes. Android stores tokens in Keystore-backed encrypted storage, **separate from the Room database key** ([ADR-005](adr/ADR-005-local-encryption.md)).

### 1.2 Token failure behaviour

| Case | Response | Client behaviour |
|---|---|---|
| Missing / malformed token | 401 `UNAUTHENTICATED` | sign-in prompt; local features keep working |
| Expired access token | 401 `TOKEN_EXPIRED` | silent refresh once, then retry |
| Refresh revoked or reused (rotation violation) | 401 `SESSION_REVOKED`; all refresh tokens of that install revoked | sign-in again; queued sync waits; nothing is deleted locally |
| Wrong `aud` / `iss` / bad signature on `POST /api/auth/google` | 401 `IDENTITY_TOKEN_INVALID` | show error; no account created |
| Valid identity, action not permitted on a visible resource | 403 `FORBIDDEN` | explain |
| Resource not visible to this caller (another patient's record, unknown ID) | **404 `NOT_FOUND`** | identical to a truly missing record, to prevent ID enumeration |

## 2. Roles

Roles are bundles of capabilities. Access to a specific subject's data **also** needs a grant (§3). Holding a role alone never exposes records.

| Role | Granted by | Capabilities (least privilege) | Explicitly not allowed | Why |
|---|---|---|---|---|
| `anonymous_local` | nobody; app without sign-in | create local subjects, capture, quality checks, `unable_to_estimate` outcomes, local records and PDF, offline guidance | sync, backend inference, LLM, sharing via server, research models, fixtures on local subjects | Offline usefulness without any server trust |
| `patient` | self (signed in) | read/write own subject's records; manage own grants and consents; export; request deletion | read anyone else's data; run research models | Owner of their own data |
| `caregiver` | a `guardian` relationship (§3.2) | same as patient, for each dependent they hold a grant for | access to the dependent after the grant is revoked; access to other dependents | Newborns cannot hold accounts |
| `clinician` | org membership + subject grant | read granted subjects' records; add annotations and confirmed lab measurements; create referrals | edit or delete envelopes; read non-granted subjects; analytics on individuals; research models | Care needs the minimum view |
| `org_admin` | another org admin or platform operator | manage org membership; view **aggregate** analytics with suppression (Phase 11) | read individual records (needs their own clinician grant); grant themselves access | Admin ≠ clinical access |
| `research_operator` | platform operator, per study | run `research_only` models in a registered study (§5) | patient-facing display of research output; research on non-enrolled people | Research is a separate, accountable context |
| `synthetic_test` | platform operator, for CI and demo accounts | create and use `synthetic_test` subjects; receive fixtures; run tests with allowlisted synthetic images | any `person`/`dependent` subject; camera or gallery input (§6) | Demos without real people |
| `platform_operator` | deployment owner | manage roles, studies, model releases | read clinical records by default | Break-glass access is out of scope until a policy exists |

## 3. Grants, relationships and offline permission

### 3.1 Grant model

`grants(grant_id, subject_id, grantee_user_id | grantee_org_id, kind ∈ {self, guardian, caregiver, clinician, org_care}, scope ∈ {read, read_write, annotate}, granted_by, consent_id, created_at, expires_at, revoked_at)`

- Every record read or write evaluates `exists active grant(subject, caller) ∧ scope covers action`.
- Clinician access comes from either (a) a patient- or guardian-issued grant to that clinician, or (b) an `org_care` grant to the clinician's organization that the patient or guardian consented to. In case (b) access is limited to members of that org with the clinician role. **Being signed in as a clinician grants nothing.**
- Grants expire (`expires_at`, proposed default 90 days for clinician grants, renewable) and can be revoked at any time by the granting patient or guardian, taking effect on the next request.

### 3.2 Newborns and other dependents

- A newborn is a `subject` with `subject_kind = dependent` and no user account.
- Whoever creates it gets a `guardian` grant, recorded as **attested** by that user. An org clinician may mark it **verified**. The verification method is a Phase 8 decision.
- A guardian may add a co-caregiver (`caregiver` grant) and clinician grants. A co-caregiver cannot issue further grants.
- Moving a dependent's records to their own account when they come of age is out of scope, but the model allows it (transfer the `self` grant).
- Children's data needs verifiable parental consent under India's DPDP Act 2023. The exact mechanism awaits legal review (§9). This design records who consented and how; it does not claim compliance.

### 3.3 Offline permission token

For research or synthetic-test use offline, the server issues a **signed, short-lived permission token** (proposed ≤ 24 h). It names the user, role, permitted subject IDs (synthetic) or study ID, and permitted model IDs. Android verifies it with a bundled public key and honours it only until expiry. A local toggle cannot create or extend one. Without a valid token, the app behaves as `anonymous_local` / `patient` and research models are not loaded.

## 4. Consent

`consents(consent_id, subject_id, given_by_user_id, purpose ∈ {local_storage, cloud_sync, clinician_access, org_care, external_ai_explanation, sharing, research_study}, scope, text_version, method, given_at, revoked_at)`

- **Purpose-specific.** Cloud sync does not imply AI explanation, sharing or research.
- **Revocation** stops future processing for that purpose immediately: grants tied to it are revoked, queued sync or share items for it are cancelled locally, and AI calls are refused. The retention and deletion of already-synced data follow a retention policy that is **an open decision** (§10).
- **Images:** no purpose includes image upload by default. Uploading an image would need its own explicit purpose (`image_upload`), which is not defined in this phase.

## 5. Research inference restrictions

`research_only` models run only when **all** of the following hold. The current server flag (`ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS`) and Android toggle remain as additional **kill switches**: a flag can turn research inference off but can never turn it on by itself.

1. The caller holds `research_operator` for a **registered study** `studies(study_id, protocol_ref, ethics_approval_ref, data_licence_ref, permitted_models[], permitted_subject_kinds[], starts_at, ends_at)`.
2. The model is in `permitted_models` and its registry lifecycle allows `research_only` ([prediction_contract.md §12](prediction_contract.md)). This includes the data-licence gate, which **no current model passes**, so in practice no study can list them until licences are confirmed.
3. The subject is either `synthetic_test`, a research-dataset image (input `source = upload` with a dataset tag), or a `person`/`dependent` enrolled in that study with an active `research_study` consent. **No studies are registered, so research inference on real people is impossible by construction.**
4. The result is stored with `model_status = research_only`, appears only in research views, is excluded from patient/caregiver/clinician history and reports, and is never used for referral urgency.

Otherwise the outcome is `unable_to_estimate` / `NOT_APPROVED_FOR_INTENDED_USE`.

## 6. Synthetic-test permission: preventing real-patient use

The `synthetic_test` role replaces the "synthetic demo profile" checkbox:

- **Subjects:** only the server creates `synthetic_test` subjects, at the request of a `synthetic_test` user. The client cannot set `subject_kind` (the field is ignored on input). Their records are stored separately and excluded from analytics.
- **Inputs:** only allowlisted synthetic test images, identified by SHA-256 in a server-side list (for example the abstract colour chart, `OpticalPipeline.createAbstractDemoPair`, and the `ml_golden` fixtures). Camera and gallery sources are refused with 403 `SYNTHETIC_INPUT_REQUIRED`. A synthetic account therefore cannot be used to screen a real person.
- **Outputs:** `status = synthetic_fixture` only, with warning `SYNTHETIC_FIXTURE_NOT_A_MEASUREMENT`.
- Fixtures are never attached to `person`/`dependent` subjects. The server already enforces this for demo profiles (`DEMO_FIXTURE_REQUIRES_DEMO_PROFILE`); the rule moves from the profile flag to `subject_kind`.

**Open question Q1 ([implementation_plan.md](implementation_plan.md)):** should anonymous users keep an offline tutorial that uses bundled synthetic images only, with the camera disabled and nothing saved? Today's app lets any local profile be marked synthetic. Removing that is a visible behaviour change.

## 7. Image and inference endpoint protections

Applies to every endpoint that accepts an image or document.

| Control | Design | Existing |
|---|---|---|
| Authentication | required (access token) | none (M6) |
| Authorization | §5 for research models; approved models need a subject grant with `read_write` | none |
| Body size | ≤ 8 MB, rejected from `Content-Length` before reading and while streaming | yes (`_read_bounded`) |
| Pixel limits | ≥ 32 px side, ≤ 40 MP, from the header before decoding | yes (`imageio`) |
| Type | content-type whitelist + magic-byte match | yes |
| Rate limit | token bucket per user and per IP, with separate buckets for image routes. Proposed starting values: 10 requests/min and 100/day per user, 2 concurrent; 429 `RATE_LIMITED` + `Retry-After`. **To be tuned from measured load, not assumed** | none |
| Timeouts | per-request inference deadline, then `status = error` / `TIMEOUT` | none |
| Storage | images processed in memory, never written, logged or forwarded | yes |
| Audit log | `{event, user_ref, subject_ref, model_id, status, reason_code, trace_id, ts}`, with no values, warning params, images or context | partial |
| Abuse | repeated `MODALITY_*` / `QUALITY_FAILED` bursts count toward the rate limit; accounts can be suspended | none |

## 8. Secrets, configuration and data minimisation

- Server-only secrets: Gemini key, session signing key, refresh-token pepper, database URL, email-provider key, model-release signing key (kept offline; only the public key ships in the app). They come from environment variables or a secret manager and are never in Git, the APK or the PWA bundle. `.env` is already gitignored; startup validation should refuse to boot in production mode with a missing or weak secret (Phase 4).
- Deployment configuration still needed. **None of these is invented here; all are open (§10):** Google OAuth web client ID, Android client ID(s) with the release signing SHA-256 fingerprint, allowed audiences, production domain (CORS, cookies, App Links, OAuth origins), database host, email provider, model-release public key.
- Minimisation: pseudonymous subject IDs; coded context only; no images uploaded by default; LLM requests carry only the fields in the report fact sheet the user consented to ([architecture.md §4.11](architecture.md)); logs and notifications carry no clinical content ([record_contract.md §7](record_contract.md)).

## 8a. Local database protection (Android, Phase 6)

Implemented as in [ADR-005](adr/ADR-005-local-encryption.md). Emulator-verified only.

| Topic | Rule |
|---|---|
| Encryption | SQLCipher 4.12.0 under Room; one random 256-bit passphrase per installation |
| Key protection | The passphrase is wrapped with an Android Keystore AES-256-GCM key (non-exportable; StrongBox if available). Only the wrapped blob is stored, in `noBackupFilesDir`, never in preferences. It is never logged, hard-coded or derived from an identifier, and there is no fixed fallback key |
| Key retrieval | Unwrapped once per process, off the main thread, and kept in memory for the process lifetime. It is not bound to user authentication (background sync needs it), so it protects data at rest, not an unlocked phone |
| Invalidation | Factory reset or clearing app data removes the Keystore key. Backups are disabled, so a copied database fails with "records are locked" (`KEY_MISSING`) on another phone |
| Failure behaviour | Missing, unusable or rejected keys, a plaintext file in the encrypted file's place, a failed or conflicting migration, and an open failure each show an actionable message with no secrets or stack traces. Nothing is deleted, nothing silently resets, and there is no plaintext fallback. Setting locked records aside is an explicit, confirmed action that moves the encrypted files |
| Logs | `SafeLog` logs only the exception type for storage failures (no SQL, no paths with IDs, no record content); release builds log nothing from the app layer |
| Integrity | Content hashes and triggers detect and block changes through the app ([record_contract.md §8](record_contract.md)). They are **not** signatures |
| Not protected | A rooted or compromised OS; code running as the app; physical recovery of the deleted plaintext file from flash after the one-time move |

The PWA's IndexedDB is still unencrypted (unchanged).

## 9. Compliance position

Not assessed. Before any real-patient use, review the Digital Personal Data Protection Act 2023 and Rules 2025 (consent, children's data, data-principal rights, breach notification) and the CDSCO Medical Device Rules 2017 (whether this software is a medical device and its risk class). Nothing in this design claims compliance.

## 10. Open decisions (owner approval needed)

Google OAuth client IDs; production domain; database host and deployment; session and grant TTLs; retention and deletion periods after revocation; guardian verification method; offline tutorial (Q1); email/WhatsApp providers; dataset licences (gates research use, §5.2).

## 11. Security tests required

Listed with IDs in [phase3_acceptance_criteria.md](phase3_acceptance_criteria.md) (AC-SEC-*). They cover cross-patient reads by ID guessing, revoked or expired grants, cross-org clinician access, org-admin individual reads, role fields in the payload being ignored, a client-set `subject_kind`, synthetic accounts sending camera images, research without a study, tampered or expired tokens, refresh-token reuse, rate limiting, and sync items for ungranted subjects.
