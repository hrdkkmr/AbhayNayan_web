# ADR-007: Interim server-issued access tokens (HS256, stdlib) before Google sign-in

Status: **Implemented (Phase 4, 24 October 2026)** · To be revisited in Phase 8

## Context
Audit M6: the research image endpoints were unauthenticated. Google sign-in ([ADR-004](ADR-004-identity.md)) needs OAuth client IDs that do not exist yet. No JWT or crypto library is installed, and Phase 4 should not add dependencies.

## Decision
- The backend verifies only **its own** tokens: compact JWS with the header pinned to exactly `{"alg":"HS256","typ":"JWT"}` (no `none`, no `kid`, no other algorithms), signed with `ABHAYNAYAN_SESSION_SIGNING_KEY` (validated at startup). Required claims: `iss`, `aud`, `sub` (`usr-…`), `roles` (known roles only), `iat`, `exp`, `jti`; `nbf` is optional. Lifetime ≤ `ABHAYNAYAN_TOKEN_MAX_TTL_SECONDS`; 60 s skew. Constant-time signature comparison. One error message for every invalid token.
- Tokens are minted only server-side (`scripts/issue_access_token.py`, key from the environment). There is no public token endpoint and no test-only bypass. Tests sign real tokens with a key that exists only inside the pytest process.
- `/api/ml/*` and `POST /api/screenings` in `MODEL` mode require `research_operator`. The operator flag stays a separate kill switch.
- Rate limits are kept in process memory, so production refuses more than one worker.

## Consequences
- No new dependency. The verification code is about 100 lines and covered by 49 security tests (forged, tampered, expired, wrong issuer/audience, algorithm confusion, oversize).
- Symmetric keys mean anyone who can verify can also sign, which is acceptable while only the backend does both. Phase 8 adds the Google ID-token exchange (`POST /api/auth/google`) and refresh tokens. It should then either keep HS256 for server sessions or move to a maintained library (PyJWT/joserfc) together with `google-auth`; that is a dependency decision for that phase.
- The study registry ([security_and_permissions.md §5](../security_and_permissions.md)) is not implemented yet. Holding `research_operator` is the interim gate, and only the key holder can grant it.
