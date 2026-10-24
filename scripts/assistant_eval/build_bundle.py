"""Builds the minimal, self-contained upload directory for the Nodus evaluation job.

The Nodus CLI uploads the directory it is run from, so the job is run from this bundle, never from the repository:
the bundle holds exactly the six files below, so `.env`, datasets, model files and records cannot be uploaded.

  python scripts/assistant_eval/build_bundle.py            # -> dist/nodus-assistant-eval/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FILES = {
    'assistant_core.py': ROOT / 'backend' / 'app' / 'assistant' / 'core.py',
    'knowledge_base.json': ROOT / 'backend' / 'app' / 'assistant' / 'knowledge_base.json',
    'eval_cases.json': HERE / 'eval_cases.json',
    'provider_cases.json': HERE / 'provider_cases.json',
    'run_eval.py': HERE / 'run_eval.py',
}
DEFAULT_OUT = ROOT / 'dist' / 'nodus-assistant-eval'


def build(out: Path = DEFAULT_OUT) -> dict:
    if out.exists():
        # Only ever remove a directory this script created (it always contains its MANIFEST.json).
        if not (out / 'MANIFEST.json').exists():
            raise SystemExit(f'{out} exists and is not a bundle directory; refusing to replace it')
        shutil.rmtree(out)
    out.mkdir(parents=True)
    manifest = {'schema': 'abhaynayan.nodus-bundle/1', 'files': {}}
    for name, source in FILES.items():
        data = source.read_bytes()
        (out / name).write_bytes(data)
        manifest['files'][name] = hashlib.sha256(data).hexdigest()
    (out / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = build(args.out)
    print(f'bundle {args.out}: ' + ', '.join(f'{k} {v[:12]}' for k, v in result['files'].items()))
