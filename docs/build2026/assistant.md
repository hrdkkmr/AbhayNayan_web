# Help assistant and Agent37

## Status

| Item | State |
|---|---|
| Assistant (knowledge-base mode) | **Implemented and tested** (`tests/test_assistant.py`, `tests/build2026-ui.test.mjs`). Checked against a locally running server on 24 Oct 2026 |
| Agent37 adapter | **Implemented and tested against a mocked Agent37 API only** (request shape, headers, every failure path) |
| Real Agent37 use | **Not done. Blocked on access**: no Agent37 account, API key or instance was available in this environment, and creating an account needs the owner's card. No instance was created and no real request was made. This integration must not be described as verified until the checklist below is complete |

## What it is

The assistant gives general, non-clinical information about using AbhayNayan. Example topics:
- what the app does;
- why a photo was rejected;
- what `unable_to_estimate` means;
- offline use and privacy;
- where to find the terms or official health information.

It never estimates hemoglobin or bilirubin, diagnoses, looks at photos, interprets results, advises on medicines, says anyone is healthy, or invents schemes, clinics or statistics.

## Pipeline (`backend/app/assistant/`)

1. **Guard** (`core.guard_question`). These questions are refused and **never sent to a provider**:
   - personal details (email, Indian phone numbers, 12-digit ID numbers, "my name is", addresses);
   - emergencies, which get a fixed message: call 112 or go to the nearest facility;
   - instruction-injection phrases;
   - clinical requests: values, diagnosis, photo analysis, medicines, "is my baby jaundiced", numbers with g/dL or mg/dL.
2. **Retrieve.** The question is keyword-scored against `knowledge_base.json`:
   - 18 entries, version `2026-10-24.1`, English only;
   - drafted by the project team and **not reviewed by a clinician**.

   If nothing matches, the result is `NO_ANSWER` and nothing is generated.
3. **Answer**:
   - `ABHAYNAYAN_ASSISTANT_PROVIDER=knowledge_base` (the default) returns the approved text of the best entry.
   - With `agent37`, the guarded question and **only the retrieved passages** are sent to the Agent37 instance with strict instructions to reply in JSON.
4. **Validate** (`core.validate_provider_output`). The provider's text is accepted only if all of these hold:
   - it is valid JSON;
   - it cites retrieved entries only;
   - it is at most 1200 characters and in English;
   - it contains no unsafe claim (diagnosis, "is healthy", doses, units, schemes, "no need to see");
   - **every number and URL in it appears in the cited passages**.

   Otherwise the approved text is returned with `fallback_reason`. The service never invents an answer and never reports `AGENT37` mode for an answer Agent37 did not produce.

## Configuration (server environment only)

| Variable | Default | Notes |
|---|---|---|
| `ABHAYNAYAN_ASSISTANT_ENABLED` | `1` | `0` returns `503 ASSISTANT_DISABLED`; the rest of the app is unaffected |
| `ABHAYNAYAN_ASSISTANT_PROVIDER` | `knowledge_base` | `agent37` to use Agent37 |
| `AGENT37_API_KEY` | unset | Workspace key `sk_live_…`. **Never** in Git, the PWA, Android, logs or evidence |
| `AGENT37_INSTANCE_URL` | unset | Must match `https://<10 lowercase letters/digits>.agent37.app` |
| `AGENT37_TIMEOUT_SECONDS` | `30` | Clamped to 5–120 |
| `ABHAYNAYAN_ASSISTANT_RATE_PER_MINUTE` | `6` | Per client IP |
| `ABHAYNAYAN_ASSISTANT_GLOBAL_RATE_PER_MINUTE` | `60` | All clients together (behind a proxy, client IPs may collapse into one) |

The adapter follows the documented API (read 24 Oct 2026):
- `POST {instance}/v1/responses` with `X-Agent37-Key` and `{"input", "stream": false, "reasoning_effort": "low", "metadata"}`;
- it checks `status == "completed"`, because a failed turn can return HTTP 200.

Other limits:
- at most 2 provider calls run at once; a third falls back immediately (`PROVIDER_BUSY`);
- responses are capped at 256 KB;
- `httpx` request log lines for Agent37 hosts are filtered out, so the instance URL is never logged.

## Verification checklist (to complete with access)

Run by the account owner; the key stays in the shell environment.

1. Create an account at https://www.agent37.com/personal. Check the current credit offer and pricing, and read https://www.agent37.com/terms.
2. Create an API key in the dashboard and run `export AGENT37_API_KEY=…` in the shell. Never put it in a file in Git.
3. `python scripts/agent37/agent37_instance.py create` creates a Hermes instance with a $2 credit cap and prints its ID and URL. Billing starts at this point.
4. `python scripts/agent37/agent37_instance.py health --instance-url https://<id>.agent37.app` must print `healthy`.
5. `python scripts/agent37/agent37_instance.py smoke --instance-url https://<id>.agent37.app` passes when:
   - at least one answer is `AGENT37`;
   - refused questions show `provider_called: false`.
6. Set `ABHAYNAYAN_ASSISTANT_PROVIDER=agent37`, `AGENT37_API_KEY` and `AGENT37_INSTANCE_URL` in the **server** environment, ask a question on the web Help assistant page, and check that the badge reads "Worded by the Agent37-hosted assistant".
7. Evidence (raw files go to `evidence/local/agent37/`, which Git ignores):
   - the instance ID;
   - a dashboard screenshot with the key hidden;
   - the `create`, `health` and `smoke` JSON files.
8. Record the results in [evidence.md](evidence.md). Delete the instance when finished (`delete --instance-id … --yes`).

The Build 2026 Agent37 challenge asks for a project link, the instance ID and a dashboard screenshot (https://hackyard.org/build2026/agent37). Submitting is the owner's decision.

## Data sent to Agent37

Only these are sent:
- the guarded question text;
- up to two approved knowledge-base passages;
- `metadata.app` and `metadata.kb_version`.

No records, images, patient fields, worker labels or identifiers are sent. Agent37 may keep conversation data under its own terms, and the Terms & Conditions (§6) say so.
