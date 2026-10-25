"""Golden vectors for the Android cnn-v1 preprocessing (CnnInput) and the bundled CNN outputs.

Writes android test resource `cnn_golden.json`: for a few deterministic synthetic images, the ARGB pixels, sampled
values of backend/app/ml/cnn_preprocess.to_tensor, per-channel sums, and both ONNX models' outputs.
Usage: .venv-ml/Scripts/python.exe scripts/ml/export_cnn_golden.py <android app/src/test/resources dir>
"""
from __future__ import annotations

import _threads  # noqa: F401

import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort

from common import MODELS
from app.ml.cnn_preprocess import to_tensor


def images() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    a = rng.integers(0, 256, (200, 300, 3), dtype=np.uint8)  # shrink, non-integer scale
    yy, xx = np.mgrid[0:120, 0:90]
    b = np.dstack([(xx * 2) % 256, (yy * 2) % 256, (xx + yy) % 256, np.where((xx - 45) ** 2 + (yy - 60) ** 2 < 1600, 255, 0)]).astype(np.uint8)  # enlarge, masked
    c = np.full((240, 240, 3), (190, 80, 70), np.uint8)  # flat eyelid-like colour
    c[100:140, 60:180] = (215, 120, 110)
    return {'shrink_rgb': a, 'enlarge_masked_rgba': b, 'flat_red': c}


def main() -> None:
    out_dir = Path(sys.argv[1])
    sessions = {name: ort.InferenceSession(str(MODELS / f), providers=['CPUExecutionProvider'])
                for name, f in (('hb_cnn', 'hb_mnv3_ft_v1.onnx'), ('jaundice_cnn', 'njn_mnv3_logreg_v1.onnx'))}
    rng = np.random.default_rng(11)
    cases = []
    for name, img in images().items():
        h, w = img.shape[:2]
        rgba = img if img.shape[2] == 4 else np.dstack([img, np.full((h, w), 255, np.uint8)])
        argb = ((rgba[..., 3].astype(np.int64) << 24) | (rgba[..., 0].astype(np.int64) << 16) | (rgba[..., 1].astype(np.int64) << 8) | rgba[..., 2]).ravel()
        argb = np.where(argb >= 2 ** 31, argb - 2 ** 32, argb)  # Java signed int
        x = to_tensor(img)
        flat = x.ravel()
        idx = np.sort(rng.choice(flat.size, 3000, replace=False))
        cases.append({
            'name': name, 'width': w, 'height': h, 'argb': argb.tolist(),
            'sample_index': idx.tolist(), 'sample_value': flat[idx].astype(float).tolist(),
            'channel_sum': x[0].reshape(3, -1).sum(1).astype(float).tolist(),
            'outputs': {k: float(np.ravel(s.run(None, {'image': x})[0])[0]) for k, s in sessions.items()},
        })
    (out_dir / 'cnn_golden.json').write_text(json.dumps({'contract': 'cnn-v1', 'cases': cases}))
    print('wrote', out_dir / 'cnn_golden.json', [(c['name'], c['outputs']) for c in cases])


if __name__ == '__main__':
    main()
