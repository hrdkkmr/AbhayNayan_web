# ADR-004: Google sign-in verified by the backend; server-issued sessions; grant-based authorization

Status: **Proposed** (24 Oct 2026) · Blocked on OAuth client IDs

## Decision
- Android: Credential Manager with `GetSignInWithGoogleOption`, returning a Google ID token. Web: Google Identity Services button.
- Backend: verify the ID token with `google-auth` (signature, `aud` = our client IDs, `iss`, `exp`, `email_verified`) and map `sub` to a `users` row. Issue our own short-lived access token and a rotating refresh token. Google tokens are never stored.
- Roles do not come from the client. Access to a subject's records requires a row in `grants(subject_id, grantee_user_id, role ∈ {self, caregiver, clinician}, scope, expires_at, revoked_at)`. Clinician grants are created by the patient/caregiver or by an org admin within their organization. Every record route checks a grant; there is no "all patients" query outside org-admin analytics, which is aggregate only.
- Device tokens live in encrypted storage, separate from the Room database key (ADR-005).

## Consequences
Every existing record route gains an authorization dependency and negative tests. Offline use keeps working with the last valid local session, and sync waits until the token can be refreshed.
