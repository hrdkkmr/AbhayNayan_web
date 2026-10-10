# Gemini integration and token-usage telemetry

Applies to `backend/app/services/gemini.py`, `backend/app/services/store.py` (`llm_usage` table) and `GET /api/admin/usage`.

## 1. What Gemini does here

Gemini is optional and server-side only. It may reword three explanatory fields of the counselling response: `summary`, `risk_explanation` and `counselling_script`. Everything safety-critical always comes from the reviewed deterministic copy in `backend/app/services/language.py`, whatever the model returns:

- `urgency`
- `referral_required`
- `recommended_next_step`
- `safety_note`

When Gemini is unavailable, the same deterministic English, Hindi or Bhojpuri copy is returned with `mode: LOCAL_FALLBACK` and a `fallback_reason`.

## 2. Configuration (server environment only)

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | empty → Gemini off | Never in frontend JS, Android code, logs or Git |
| `GEMINI_MODEL` | **empty → Gemini off** | No model ID is hard-coded. Choose one from the [current model list](https://ai.google.dev/gemini-api/docs/models). On 10 Oct 2026 that page listed `gemini-3.8-flash` as stable; this was not exercised with a live key |
| `GEMINI_TIMEOUT_SECONDS` | `12` | Per HTTP call |
| `GEMINI_MAX_OUTPUT_TOKENS` | `512` | Sent as `generationConfig.maxOutputTokens`. Thinking tokens count against output on thinking models; a `MAX_TOKENS` finish falls back |
| `ABHAYNAYAN_ADMIN_TOKEN` | empty → usage report disabled | 16+ characters; bearer token for `/api/admin/usage` |

**Model verification.** Before the first generation, and again every 10 minutes (60 s after a failure), the server calls `GET v1beta/models/{GEMINI_MODEL}`. It checks that the model exists and that `supportedGenerationMethods` includes `generateContent`. A 404 gives `MODEL_UNAVAILABLE`; a model without that method gives `MODEL_UNSUPPORTED`. In both cases no generation request is sent.

## 3. Failure handling

| Condition | `fallback_reason` | Provider called? |
|---|---|---|
| No key | `NO_API_KEY` | no |
| No model configured | `MODEL_NOT_CONFIGURED` | no |
| Model missing / lacks generateContent | `MODEL_UNAVAILABLE` / `MODEL_UNSUPPORTED` | models.get only |
| 400 | `INVALID_REQUEST_OR_MODEL` | yes |
| 401 / 403 | `AUTH_ERROR` | yes |
| 429 with a per-minute quota violation, or unspecified | `RATE_LIMITED` | yes |
| 429 with a per-day or billing quota violation | `QUOTA_EXHAUSTED` | yes |
| 5xx | `PROVIDER_ERROR` | yes |
| Timeout / connection error | `TIMEOUT` / `NETWORK_ERROR` | yes |
| Non-JSON body or no candidates | `MALFORMED_RESPONSE` | yes |
| `promptFeedback.blockReason` set | `BLOCKED_BY_PROVIDER` | yes |
| `finishReason: MAX_TOKENS` | `INCOMPLETE_OUTPUT` | yes |
| Output JSON unparseable | `MALFORMED_OUTPUT` | yes |
| Wrong `language`, or Hindi/Bhojpuri text with no Devanagari | `LANGUAGE_MISMATCH` | yes |
| Empty field, >1400 chars, or diagnosis/dose wording | `UNSAFE_OR_INCOMPLETE_OUTPUT` | yes |

The rate-limit vs quota split relies on `QuotaFailure.violations[].quotaId` text. Gemini returns HTTP 429 `RESOURCE_EXHAUSTED` for both, so treat the split as best effort.

## 4. What is recorded

One row per counselling request in `llm_usage`. **Recorded:** timestamp, request type, configured model ID, provider-reported `modelVersion`, whether the provider was called, outcome code, HTTP status, latency (ms), finish reason, screening type and language. The token fields are copied from the response's `usageMetadata`:

| Column | Gemini field |
|---|---|
| `prompt_tokens` | `promptTokenCount` |
| `candidates_tokens` | `candidatesTokenCount` |
| `total_tokens` | `totalTokenCount` (prompt + thoughts + candidates) |
| `cached_tokens` | `cachedContentTokenCount` |
| `thoughts_tokens` | `thoughtsTokenCount` |
| `tool_use_prompt_tokens` | `toolUsePromptTokenCount` |

Field names were checked against the [GenerateContentResponse reference](https://ai.google.dev/api/generate-content) on 10 Oct 2026. Any field the response omits, or reports as a non-integer, is stored as `NULL` (**unavailable**). Tokens are never estimated from text. Modality breakdowns (`promptTokensDetails` and similar) and `serviceTier` are not stored. Tokens are recorded even when the output is then rejected, because they were consumed.

**Never recorded:** API key, prompt text, response text, request ID, estimate value, patient ID, names, images.

Logs (`abhaynayan.gemini`) contain only outcome code, provider-called flag, HTTP status and latency. Tests assert that neither the key nor prompt text appears in logs or the table.

## 5. Cost and duplicate controls

- **Idempotency.** A request with the same `request_id` within 15 minutes returns the first response with no provider call (`IDEMPOTENT_REPLAY`). Concurrent duplicates wait for the in-flight call. The cache is in process memory, so it is lost on restart and not shared between workers.
- **Demo cache.** For `provenance: DEMO_SYNTHETIC` inputs (fixed, non-personal values), an accepted Gemini response is cached for 6 hours per (model, language, context) (`DEMO_CACHE_HIT`). Non-demo inputs are never cached across requests.
- Bounded output (`maxOutputTokens`), low temperature (0.15) and a structured `responseSchema` with only three short fields.
- Safety-critical text is deterministic and never generated.

## 6. Usage report

`GET /api/admin/usage?since=<ISO>&until=<ISO>` with `Authorization: Bearer $ABHAYNAYAN_ADMIN_TOKEN`. It is also available in the PWA under **AI usage (admin)**, where the token is held only for that request.

| Field | Meaning |
|---|---|
| `counselling_requests` | All rows in the period |
| `provider_requests` / `provider_successful` / `provider_failed_or_rejected` | Calls that reached Gemini; success means the output was accepted |
| `served_without_provider_call` | Missing key or model, cache hits, replays, failed model checks |
| `outcomes` | Count per outcome code |
| `tokens_provider_reported.{prompt,output_candidates,thoughts,cached,tool_use_prompt,total}` | Sums of reported values, or `null` if none were reported |
| `requests_missing_usage_metadata` | Provider calls with no usable `usageMetadata` |
| `avg_tokens_per_successful_request` | Over successful calls that reported usage |
| `latency_ms.{count,mean,p50,max}` | Provider calls only |
| `models`, `model_versions_reported`, `period` | Configured IDs, provider-reported versions, time range |
| `estimated_cost` | Always `null`: no verified pricing is configured, so no cost is shown |

The report is aggregate only and never lists individual interactions. Without `ABHAYNAYAN_ADMIN_TOKEN` it returns `403 ADMIN_DISABLED`. The token is compared in constant time. For real deployments, put the endpoint behind network-level access control as well.

## 7. Verification status

All behaviour above is covered by `tests/test_gemini.py` using mocked provider responses: success, missing or partial usage metadata, 429 rate vs quota, 5xx, 403, missing model, unsupported model, timeout, network error, malformed or blocked or truncated output, language mismatch, unsafe text, idempotent retry, demo cache, privacy of logs, admin access, and period filter. **No call to the live Gemini API was made**, so real latency, token counts and model behaviour are unverified.
