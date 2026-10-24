"""Runs the assistant evaluation on Nodus compute and verifies the downloaded report (docs/build2026/nodus.md).

Requires the Nodus CLI (`pip install nodus-compute`, Python 3.10+) and `nodus login` by the account owner.
No credential is read, stored or printed by this script; the CLI keeps its own login.

  python scripts/assistant_eval/nodus_job.py --dry-run          # estimate only, creates no job
  python scripts/assistant_eval/nodus_job.py                    # submit, wait, fetch logs and report, verify
  python scripts/assistant_eval/nodus_job.py --verify-only PATH # re-check a downloaded report against the bundle

Evidence (redaction-free by construction: job name, CLI output, report) goes to evidence/local/nodus/<job>/,
which is ignored by Git. Review it before sharing.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build_bundle  # noqa: E402

EVIDENCE_ROOT = ROOT / 'evidence' / 'local' / 'nodus'
REPORT_PATH = '/nodus/outputs/report.json'


def verify_report(report_path: Path, manifest: dict) -> list[str]:
    """Problems with a downloaded report; empty when it is a passing run of exactly this bundle."""
    problems = []
    try:
        report = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return [f'report unreadable: {type(exc).__name__}']
    files, inputs = manifest['files'], report.get('inputs', {})
    if report.get('schema') != 'abhaynayan.assistant-eval-report/1':
        problems.append('unexpected report schema')
    if report.get('status') != 'pass':
        problems.append(f'report status is {report.get("status")!r}')
    for key, name in (('core_sha256', 'assistant_core.py'), ('kb_sha256', 'knowledge_base.json'),
                      ('cases_sha256', 'eval_cases.json'), ('provider_cases_sha256', 'provider_cases.json'),
                      ('runner_sha256', 'run_eval.py')):
        if inputs.get(key) != files[name]:
            problems.append(f'{key} does not match the bundle ({name})')
    if report.get('label') != 'nodus':
        problems.append('report label is not "nodus"')
    return problems


def _run(cmd: list[str], log: Path, timeout: int) -> subprocess.CompletedProcess:
    print('$', ' '.join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    log.write_text(f'$ {" ".join(cmd)}\nexit {proc.returncode}\n--- stdout\n{proc.stdout}\n--- stderr\n{proc.stderr}\n', encoding='utf-8')
    print(proc.stdout[-4000:], proc.stderr[-2000:], sep='\n')
    return proc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--name', default=f'abhaynayan-kb-eval-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}')
    parser.add_argument('--image', default='python:3.12-slim')
    parser.add_argument('--gpu', default=None, help='only if the CLI requires a GPU type (e.g. L4); the job is CPU-only')
    parser.add_argument('--max-cost', default='1')
    parser.add_argument('--timeout', default='10m')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verify-only', type=Path, default=None)
    args = parser.parse_args()

    bundle = build_bundle.DEFAULT_OUT
    manifest = build_bundle.build(bundle)
    if args.verify_only:
        problems = verify_report(args.verify_only, manifest)
        print('verified' if not problems else '\n'.join(problems))
        return 0 if not problems else 1
    nodus = shutil.which('nodus')
    if nodus is None:
        print('The Nodus CLI is not installed. Install it with `pip install nodus-compute` and run `nodus login`.')
        return 2
    evidence = EVIDENCE_ROOT / args.name
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / 'bundle_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

    run = [nodus, 'run', '--name', args.name, '--image', args.image, '--max-cost', args.max_cost, '--timeout', args.timeout,
           '--no-warm', '--output', f'report={REPORT_PATH}']
    if args.gpu:
        run += ['--gpu', args.gpu]
    if args.dry_run:
        run.append('--dry-run')
    run += ['--', 'python', 'run_eval.py', '--label', 'nodus', '--out', REPORT_PATH]
    # The CLI uploads its working directory: run it from the bundle so nothing else can be uploaded.
    os.chdir(bundle)
    proc = _run(run, evidence / '01_run.log', timeout=1800)
    if args.dry_run or proc.returncode != 0:
        return proc.returncode
    _run([nodus, 'describe', f'job/{args.name}'], evidence / '02_describe.log', timeout=120)
    _run([nodus, 'logs', f'job/{args.name}'], evidence / '03_logs.log', timeout=300)
    report = evidence / 'report.json'
    cp = _run([nodus, 'cp', f'job/{args.name}:outputs/report', str(report)], evidence / '04_cp.log', timeout=300)
    if cp.returncode != 0:
        return cp.returncode
    problems = verify_report(report, manifest)
    (evidence / '05_verification.txt').write_text('verified\n' if not problems else '\n'.join(problems) + '\n', encoding='utf-8')
    print('verified: the report is a passing run of this exact bundle' if not problems else '\n'.join(problems))
    return 0 if not problems else 1


if __name__ == '__main__':
    raise SystemExit(main())
