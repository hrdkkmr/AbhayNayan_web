"""Pin the served image-model artifacts by SHA-256 in models/MODEL_REGISTRY.json.

Run after a final training stage. The backend refuses any artifact whose hash differs from this file.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / 'models'

ENTRIES = {
    'hb-hgb-cf': {'task': 'hemoglobin', 'role': 'backend', 'files': ['hb_hgb_cf_v1.json'], 'run': 'ml/runs/hb-v1'},
    'hb-ridge-cf': {'task': 'hemoglobin', 'role': 'edge', 'files': ['hb_ridge_cf_v1.json'], 'run': 'ml/runs/hb-v1'},
    'njn-mnv3-logreg': {'task': 'neonatal_jaundice_class', 'role': 'backend',
                        'files': ['njn_mnv3_logreg_v1.json', 'njn_mnv3_logreg_v1.onnx'], 'run': 'ml/runs/njn-v1'},
    'njn-logreg-cf': {'task': 'neonatal_jaundice_class', 'role': 'edge', 'files': ['njn_logreg_cf_v1.json'], 'run': 'ml/runs/njn-v1'},
}


def main() -> None:
    out = {'schema_version': 1, 'note': 'SHA-256 pins for served artifacts. Regenerate with scripts/ml/write_registry.py.', 'models': {}}
    for model_id, e in ENTRIES.items():
        meta = json.loads((MODELS / e['files'][0]).read_text(encoding='utf-8'))
        out['models'][model_id] = {**e, 'version': meta['version'], 'validation_status': meta['validation_status'],
                                   'sha256': {f: hashlib.sha256((MODELS / f).read_bytes()).hexdigest() for f in e['files']}}
    (MODELS / 'MODEL_REGISTRY.json').write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(out['models'], indent=1))


if __name__ == '__main__':
    main()
