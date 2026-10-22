"""Copy the edge-role artifacts into the Android app's assets with a model card (metadata.json).

  .venv/Scripts/python scripts/ml/export_android_assets.py --apk-android <AbhayNayan_apk>/AbhayNayan/android

Writes app/src/main/assets/models/hemoglobin/{model.json,metadata.json} and
app/src/main/assets/models/jaundice_class/model.json. These folders are gitignored in the Android repo:
the artifacts derive from datasets without verified redistribution rights.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--apk-android', type=Path, required=True)
    a = ap.parse_args()
    pins = json.loads((ROOT / 'models' / 'MODEL_REGISTRY.json').read_text(encoding='utf-8'))['models']
    assets = a.apk_android / 'app' / 'src' / 'main' / 'assets' / 'models'
    for model_id, folder in (('hb-ridge-cf', 'hemoglobin'), ('njn-logreg-cf', 'jaundice_class')):
        name = pins[model_id]['files'][0]
        data = (ROOT / 'models' / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != pins[model_id]['sha256'][name]:
            raise SystemExit(f'{name} does not match MODEL_REGISTRY.json')
        out = assets / folder
        out.mkdir(parents=True, exist_ok=True)
        (out / 'model.json').write_bytes(data)
        if folder == 'hemoglobin':
            art = json.loads(data)
            test = art['evaluation']['held_out_test']
            card = {
                'name': art['model_id'], 'version': art['version'], 'biomarker': 'HEMOGLOBIN',
                'input_kind': 'colour_features', 'feature_version': art['feature_version'], 'feature_count': len(art['feature_names']),
                'artifact_sha256': hashlib.sha256(data).hexdigest(),
                'normalization': 'cf-v1 features standardised with mean/scale stored in model.json',
                'output_shape': [1], 'output_unit': 'g/dL', 'runtime': 'kotlin-linear-cf-v1',
                'training_label_source': art['training']['label'],
                'subjects': art['training']['n_train'], 'samples': art['training']['n_train'], 'subject_level_split': True,
                'validation_status': art['validation_status'], 'redistribution_approved': False,
                'limitations': [
                    'Research only; not validated for screening, diagnosis or treatment.',
                    f"Held-out patients (same device): MAE {test['eyes_defy_anemia']['mae']:.2f} g/dL, R2 {test['eyes_defy_anemia']['r2']:.2f}.",
                    f"Different population/device (CP-AnemiC hospitals): MAE {test['cp_anemic']['mae']:.2f} g/dL, R2 {test['cp_anemic']['r2']:.2f}.",
                    'Trained on expert-segmented conjunctiva crops from one standardized device; manual phone crops differ.',
                    'Over-estimates low hemoglobin (regression to the mean).',
                ],
            }
            (out / 'metadata.json').write_text(json.dumps(card, indent=1), encoding='utf-8')
        print('wrote', out)


if __name__ == '__main__':
    main()
