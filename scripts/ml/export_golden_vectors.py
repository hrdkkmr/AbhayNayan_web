"""Write SYNTHETIC golden images + expected outputs for cross-platform tests (no patient pixels).

Outputs tests/fixtures/ml_golden/<name>.png and tests/fixtures/ml_golden/golden_cf_v1.json. Copy the
folder to AbhayNayan_apk/.../app/src/test/resources/ml_golden/ so the Kotlin port is checked against
the same vectors:

  .venv/Scripts/python scripts/ml/export_golden_vectors.py [--android-dir <apk>/AbhayNayan/android/app/src/test/resources/ml_golden]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.ml import features as F, quality as Q  # noqa: E402
from app.ml.imageio import read_path  # noqa: E402
from app.ml.registry import Registry  # noqa: E402

OUT = ROOT / 'tests' / 'fixtures' / 'ml_golden'


def ellipse_mask(h: int, w: int) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    return (((xx - w / 2) / (w * .45)) ** 2 + ((yy - h / 2) / (h * .40)) ** 2 <= 1).astype(np.uint8) * 255


def textured(h: int, w: int, base: tuple[int, int, int], rng: np.random.Generator, amp: float) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.float64)
    for c in range(3):
        img[..., c] = base[c] + amp * np.sin(xx / 7.0 + c) * np.cos(yy / 5.0) + rng.normal(0, amp / 2, (h, w))
    return np.clip(img, 0, 255).astype(np.uint8)


def synthetic_images() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(1234)
    imgs = {}
    for name, (h, w, base) in {'pink_masked': (60, 120, (200, 110, 115)), 'pale_masked': (90, 200, (225, 175, 165)),
                               'red_masked_large': (420, 900, (185, 70, 80))}.items():
        rgb = textured(h, w, base, rng, 18)
        imgs[name] = np.dstack([rgb, ellipse_mask(h, w)])
    imgs['skin_rgb_large'] = textured(640, 520, (215, 170, 120), rng, 25)
    glare = textured(80, 80, (230, 200, 190), rng, 10)
    glare[10:70, 10:70] = 255
    imgs['glare_rgb'] = glare
    imgs['too_dark_rgb'] = textured(64, 64, (8, 6, 6), rng, 2)
    return imgs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--android-dir', type=Path)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    reg = Registry()
    models = {m: reg.get(m) for m in ('hb-ridge-cf', 'njn-logreg-cf', 'hb-hgb-cf', 'njn-mnv3-logreg')}
    cases = []
    for name, img in synthetic_images().items():
        path = OUT / f'{name}.png'
        bgr = cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA if img.shape[2] == 4 else cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(path), bgr)
        decoded = read_path(path)
        assert np.array_equal(decoded, img), 'PNG round trip must be lossless'
        q = Q.assess(decoded)
        case = {'name': name, 'file': path.name, 'width': img.shape[1], 'height': img.shape[0], 'channels': img.shape[2],
                'quality_passed': q.passed, 'quality_issues': q.issues}
        try:
            fr = F.extract(decoded)
            case.update({'features': fr.vector.tolist(), 'valid_pixels': fr.valid_pixels, 'step': fr.step,
                         'outputs': {m: model.predict(decoded, fr) for m, model in models.items()}})
        except F.FeatureError as exc:
            case['feature_error'] = str(exc)
        cases.append(case)
    payload = {'synthetic': True, 'note': 'Procedurally generated test images; no patient or dataset pixels.',
               'feature_version': F.FEATURE_VERSION, 'feature_names': list(F.FEATURE_NAMES),
               'model_versions': {m: model.version for m, model in models.items()},
               'model_sha256': {m: model.sha256 for m, model in models.items()},
               'tolerance': {'features_abs': 1e-6, 'linear_output_abs': 1e-6, 'onnx_output_abs': 1e-4}, 'cases': cases}
    (OUT / 'golden_cf_v1.json').write_text(json.dumps(payload, indent=1), encoding='utf-8')
    for c in cases:
        print(c['name'], c.get('step'), c.get('valid_pixels'), c['quality_passed'], {k: round(v, 4) for k, v in c.get('outputs', {}).items()},
              c.get('feature_error', ''))
    if a.android_dir:
        a.android_dir.mkdir(parents=True, exist_ok=True)
        for f in OUT.iterdir():
            shutil.copy2(f, a.android_dir / f.name)
        print('copied to', a.android_dir)


if __name__ == '__main__':
    main()
