# Nodus compute workload: knowledge-base and assistant evaluation

## Status

| Item | State |
|---|---|
| Workload | **Implemented and run locally**: 54/54 question cases, 20/20 provider-output cases, 0 knowledge-base problems |
| Bundle | **Built and run in isolation** with `python -I`; the report verifies against the bundle hashes |
| Run on Nodus | **Not done. Blocked on access**: the Nodus CLI (`nodus-compute`) is not installed here, there is no Nodus login, and the event's $30 credits are issued to teams at the venue. No Nodus job was submitted. The integration **must not be described as complete** until a real job ID, its logs and a downloaded report exist |

## What runs and why it belongs here

`scripts/assistant_eval/run_eval.py` (standard library only) does three things:
- validates the curated knowledge base: structure, IDs, allowed https sources, no blocked phrases, English only;
- runs 54 synthetic evaluation questions (normal, ambiguous, out of scope, unsafe, personal, urgent, injection) through the same guard and retrieval code as the API, twice each, to check determinism;
- runs 20 synthetic provider outputs through the Agent37 output validator: grounded answers must be accepted, and invented numbers, URLs, diagnoses, doses, schemes, malformed JSON and wrong language must be rejected with the expected reason.

It writes `report.json` (schema `abhaynayan.assistant-eval-report/1`) with:
- start and finish timestamps, duration and counts;
- per-case pass/fail;
- the Python and platform versions;
- SHA-256 hashes of the core, the knowledge base, both case files and the runner;
- the **names** (never values) of any `NODUS*` environment variables.

The workload is non-clinical:
- it sends no network request;
- it reads no records, images, datasets or `.env`;
- it does not evaluate or validate any clinical model.

## Reproduce

```bash
python scripts/assistant_eval/run_eval.py --out report.json        # local run
python scripts/assistant_eval/build_bundle.py                      # dist/nodus-assistant-eval/ (6 files only)
```

On Nodus (account owner; CLI documented at https://nodus-compute.ai/docs/getting-started/):

```bash
pip install nodus-compute            # Python 3.10+, into a separate virtualenv
nodus login                          # browser sign-in; the CLI keeps its own credentials
python scripts/assistant_eval/nodus_job.py --dry-run               # estimate only
python scripts/assistant_eval/nodus_job.py                          # submit, wait, logs, download, verify
```

`nodus_job.py` does the following:
1. Rebuilds the bundle, then runs `nodus run` **from inside the bundle**. The CLI uploads its working directory, so only those six files can be uploaded.
2. Uses `--image python:3.12-slim --max-cost 1 --timeout 10m --no-warm --output report=/nodus/outputs/report.json`, then `nodus describe`, `nodus logs` and `nodus cp`.
3. Checks the downloaded report: schema, `status: pass`, label `nodus`, and that every input hash equals the bundle manifest.
4. Saves the CLI output and the report under `evidence/local/nodus/<job>/`, which Git ignores.

If the CLI requires a GPU type, add `--gpu L4`. The job itself is CPU-only, and the docs read on 24 Oct 2026 show only GPU examples, so confirm this with `--dry-run`.

## What counts as evidence

The hash check proves which code ran, not where it ran. Proof of execution on Nodus is:
- the job name and ID;
- `nodus describe` showing the job as succeeded;
- the platform logs containing the `run_eval pass:` line;
- the report downloaded with `nodus cp` (the CLI checks its SHA-256);
- a console screenshot of the job.

A local run is labelled `local` and does not count.

## Fallback

The app never calls Nodus, so nothing in it depends on Nodus availability. If Nodus is unavailable, the same workload runs locally and in CI as `tests/test_assistant.py::test_evaluation_workload_passes_in_process`, and is reported as local.
