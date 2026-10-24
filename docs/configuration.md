# Server configuration

Implemented in Phase 4 (24 October 2026): `backend/app/core/config.py`, tested by `tests/test_config.py` and `tests/test_readiness.py`. Problems are reported as `VARIABLE=CODE` only. **Values are never printed, logged or returned.**

## 1. Environments and startup behaviour

`ABHAYNAYAN_ENV` selects the behaviour. The default is `development`, so local and offline workflows need no secret.

| `ABHAYNAYAN_ENV` | Error-level problem | Warning-level problem |
|---|---|---|
| `development` (default), `test` | logged as `configuration error VAR=CODE`; shown in `GET /api/ready`; the app starts | logged; shown in readiness |
| `production` | **the app refuses to start** (`ConfigurationError: Invalid configuration for environment 'production': VAR=CODE, …`) | logged; shown in readiness |
| anything else (`staging`, `prod`, typo) | **refuses to start in every case** (`UNKNOWN_ENVIRONMENT`): a typo must not silently mean "development" | — |

Whatever the environment, a weak or placeholder signing key is **never used**: protected endpoints then return `503 AUTH_NOT_CONFIGURED`.

## 2. Variables

| Variable | Required | Default | Validation (problem codes) |
|---|---|---|---|
| `ABHAYNAYAN_ENV` | no | `development` | `UNKNOWN_ENVIRONMENT` |
| `ABHAYNAYAN_SESSION_SIGNING_KEY` | **production** | none (auth disabled) | `MISSING`; `TOO_SHORT` (< 32 characters); `PLACEHOLDER` (contains change, replace, placeholder, example, your, secret, password, dummy, sample, todo, xxxx, test, default, insecure, demo); `LOW_ENTROPY` (< 12 distinct characters). Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ABHAYNAYAN_ALLOW_ORIGINS` | **production** | `http://localhost:8000,http://127.0.0.1:8000` | production: `MISSING`, `WILDCARD_ORIGIN`, `INSECURE_ORIGIN` (not `https://`) |
| `ABHAYNAYAN_ADMIN_TOKEN` | no | unset (usage report disabled) | production: same rules as the signing key. Development keeps the old ≥ 16-character rule of `/api/admin/usage` |
| `ABHAYNAYAN_TOKEN_MAX_TTL_SECONDS` | no | `3600` | 60–43200; `MALFORMED`, `OUT_OF_RANGE` |
| `ABHAYNAYAN_IMAGE_RATE_PER_MINUTE` | no | `10` | 1–600 per research operator |
| `ABHAYNAYAN_IMAGE_RATE_PER_DAY` | no | `100` | 1–100000 per research operator |
| `ABHAYNAYAN_IMAGE_MAX_CONCURRENT` | no | `2` | 1–32 in-flight requests per research operator |
| `ABHAYNAYAN_AUTH_FAILURES_PER_MINUTE_PER_IP` | no | `20` | 1–1000 failed authentications per client IP before 429 |
| `ABHAYNAYAN_MAX_IMAGE_BYTES` | no | `8388608` (8 MB) | 64 KiB – 8 MB; **cannot be raised** above the 8 MB hard limit |
| `ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS`, `ABHAYNAYAN_ENABLE_EXPERIMENTAL_ANEMIA` | no | off | production: `NOT_ALLOWED_IN_PRODUCTION` (research artifacts derive from datasets with unverified licences). In development they remain kill switches only: research routes also need a `research_operator` token |
| `WEB_CONCURRENCY`, `ABHAYNAYAN_WORKERS` | no | 1 | production: > 1 ⇒ `RATE_LIMITER_REQUIRES_SINGLE_PROCESS` (limits live in process memory) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | no | unset | only one set ⇒ `INCOMPLETE` (warning; readiness `gemini: misconfigured`, status `degraded`) |
| `ABHAYNAYAN_DB_PATH`, `ABHAYNAYAN_PORT`, PDF font paths, `GEMINI_TIMEOUT_SECONDS`, `GEMINI_MAX_OUTPUT_TOKENS` | no | unchanged | unchanged |
| `ABHAYNAYAN_ASSISTANT_ENABLED` | no | `1` | `0`, `false`, `no` or `off` disables the help assistant (`503 ASSISTANT_DISABLED`) |
| `ABHAYNAYAN_ASSISTANT_PROVIDER` | no | `knowledge_base` | `agent37` uses Agent37 when the two `AGENT37_*` values below are valid; otherwise the approved text is answered with `fallback_reason: PROVIDER_NOT_CONFIGURED` |
| `AGENT37_API_KEY`, `AGENT37_INSTANCE_URL` | no | unset | Server only. Problem codes in `GET /api/ready` → `integrations.assistant.agent37`: `NOT_CONFIGURED`, `INCOMPLETE`, `MALFORMED_KEY` (not `sk_…`), `MALFORMED_INSTANCE_URL` (not `https://<10 chars>.agent37.app`) |
| `AGENT37_TIMEOUT_SECONDS` | no | `30` | clamped to 5–120 |
| `ABHAYNAYAN_ASSISTANT_RATE_PER_MINUTE`, `ABHAYNAYAN_ASSISTANT_GLOBAL_RATE_PER_MINUTE` | no | `6`, `60` | per client IP and for all clients; invalid values fall back to the default |

The limit defaults are **engineering starting points**. They are not operationally validated and should be tuned from measured load.

**Not yet configurable, because they don't exist yet (Phase 8, open decisions):** Google OAuth client IDs, allowed audiences, the release signing SHA-256 fingerprint, production domain, database URL, email provider. None is invented here.

## 3. Safe example (placeholders only)

`.env.example` was not edited in Phase 4, because environment files are out of scope without approval. These are the proposed additions for review. Every value is a placeholder that the validator **rejects** until it is replaced:

```text
# --- Phase 4: environment and authentication ---
ABHAYNAYAN_ENV=development
# Required in production. 32+ random characters; never commit a real value.
ABHAYNAYAN_SESSION_SIGNING_KEY=replace-with-output-of-secrets-token_urlsafe-48
ABHAYNAYAN_TOKEN_MAX_TTL_SECONDS=3600
# Research-route limits (per research operator); defaults shown.
ABHAYNAYAN_IMAGE_RATE_PER_MINUTE=10
ABHAYNAYAN_IMAGE_RATE_PER_DAY=100
ABHAYNAYAN_IMAGE_MAX_CONCURRENT=2
ABHAYNAYAN_AUTH_FAILURES_PER_MINUTE_PER_IP=20
ABHAYNAYAN_MAX_IMAGE_BYTES=8388608
# Production also needs ABHAYNAYAN_ALLOW_ORIGINS=https://<your-domain> (domain not yet decided).
```

## 3a. QR destination ("Get the AbhayNayan app")

No server variable is involved. The QR code is generated on the client from:
- **Web:** `web-dashboard/js/distribution.js` (`kind`, `url`, `verifiedOn`).
- **Android:** the Gradle properties `abhaynayanAppShareKind` and `abhaynayanAppShareUrl`, which become `BuildConfig.APP_SHARE_KIND` and `APP_SHARE_URL`.

The default is `web_app`, `https://abhaynayan-web.onrender.com/` (verified 24 Oct 2026; there is no public Android release). The URL must be https and a page, not an APK; anything else shows no QR. To switch to an authorized installation page, use `android_install_page` ([build2026/README.md](build2026/README.md)).

## 4. Access tokens until Google sign-in exists

Only a holder of the signing key can mint a token, server-side:

```bash
PYTHONPATH=backend python scripts/issue_access_token.py --user usr-operator-0001 --role research_operator --ttl 900
```

The key is read from the environment only, never from arguments. Tokens are HS256 with `iss=abhaynayan-backend`, `aud=abhaynayan-api`, `sub`, `roles`, `iat`, `nbf`, `exp` and `jti`. The lifetime is capped by `ABHAYNAYAN_TOKEN_MAX_TTL_SECONDS`, and 60 s of clock skew is allowed. See [ADR-007](adr/ADR-007-interim-access-tokens.md).

## 5. Readiness

`GET /api/ready` returns 200 for `ready` / `degraded` and 503 for `not_ready` (production config errors or database unavailable). It reports configuration problems (codes), database, each registered model's `artifacts` (`present`/`missing`), `checksum` (`verified`/`mismatch`/`not_checked`), `loadable` and `reason_code`, the research flag, integrations (`configured`/`not_configured`/`misconfigured`), and `clinical_inference`, which is **always `disabled` / `NO_VALIDATED_MODEL_FOR_TASK` today**. Absent research models do not degrade readiness, since the Docker image ships without them by design. A checksum mismatch or incompatible artifact does. `GET /api/health` is unchanged (liveness).
