"""Shared helpers for the training/evaluation scripts. Aggregate outputs only; per-image data stays in data/private/."""
from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import _threads  # noqa: E402,F401  (no-op if the entry script imported it first)

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.ml import features as F  # noqa: E402
from app.ml import quality as Q  # noqa: E402
from app.ml.imageio import read_path  # noqa: E402

PRIVATE = ROOT / 'data' / 'private'
RUNS = ROOT / 'ml' / 'runs'
MODELS = ROOT / 'models'


def load_manifest(name: str) -> pd.DataFrame:
    df = pd.read_csv(PRIVATE / name, keep_default_na=False, na_values={'hb_g_dl': ['']})
    return df[df.exclusion == ''].reset_index(drop=True)


def colour_features(df: pd.DataFrame, cache_name: str) -> tuple[np.ndarray, pd.DataFrame]:
    """cf-v1 feature matrix plus per-image quality metrics, cached by image id + file hash of features.py."""
    contract = hashlib.sha256((ROOT / 'backend' / 'app' / 'ml' / 'features.py').read_bytes()).hexdigest()[:12]
    cache = PRIVATE / f'{cache_name}_{F.FEATURE_VERSION}_{contract}.csv'
    cached = pd.read_csv(cache).set_index('image_id') if cache.exists() else pd.DataFrame()
    missing = [i for i in df.image_id if i not in cached.index]
    if missing:
        rows = []
        for iid, p in zip(df.image_id, df.path):
            if iid not in missing:
                continue
            img = read_path(p)
            fr = F.extract(img)
            q = Q.assess(img)
            rows.append({'image_id': iid, **fr.as_dict(), 'valid_fraction': fr.valid_fraction,
                         'quality_passed': q.passed, 'quality_issues': '|'.join(q.issues)})
        cached = pd.concat([cached, pd.DataFrame(rows).set_index('image_id')])
        cached.to_csv(cache)
    c = cached.loc[df.image_id]
    return c[list(F.FEATURE_NAMES)].to_numpy(float), c.reset_index()


def regression_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    err = p - y
    ss_res = float((err ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return {'n': int(len(y)), 'mae': float(np.abs(err).mean()), 'rmse': float(math.sqrt((err ** 2).mean())),
            'r2': 1 - ss_res / ss_tot if ss_tot > 0 else float('nan'), 'bias': float(err.mean())}


def bootstrap_ci(y: np.ndarray, p: np.ndarray, fn, n: int = 2000, seed: int = 0) -> dict[str, list[float]]:
    rng = np.random.default_rng(seed)
    stats: dict[str, list[float]] = {}
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        for k, v in fn(y[idx], p[idx]).items():
            stats.setdefault(k, []).append(v)
    return {k: [float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5))] for k, v in stats.items() if k != 'n'}


def wilson(k: int, n: int, z: float = 1.959964) -> list[float] | None:
    if n == 0:
        return None
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    tp = int(((y_true == 1) & (y_pred == 1)).sum()); fn = int(((y_true == 1) & (y_pred == 0)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum()); fp = int(((y_true == 0) & (y_pred == 1)).sum())
    out = {'tp': tp, 'fn': fn, 'tn': tn, 'fp': fp}
    for name, k, n in (('sensitivity', tp, tp + fn), ('specificity', tn, tn + fp), ('ppv', tp, tp + fp), ('npv', tn, tn + fn)):
        out[name] = k / n if n else None
        out[name + '_ci95'] = wilson(k, n)
    return out


def calibration(y: np.ndarray, p: np.ndarray) -> dict:
    """Linear recalibration of measured on predicted (ideal slope 1, intercept 0)."""
    slope, intercept = np.polyfit(p, y, 1) if np.ptp(p) > 0 else (float('nan'), float('nan'))
    resid = y - p
    r_slope = np.polyfit(y, resid, 1)[0] if np.ptp(y) > 0 else float('nan')
    return {'slope_measured_on_predicted': float(slope), 'intercept': float(intercept),
            'residual_vs_measured_slope': float(r_slope)}


def environment() -> dict:
    pkgs = {}
    for name in ('numpy', 'pandas', 'scikit-learn', 'opencv-python-headless', 'opencv-python', 'torch', 'torchvision', 'matplotlib'):
        try:
            pkgs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    try:
        commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain'], capture_output=True, text=True).stdout.strip())
    except OSError:
        commit, dirty = None, None
    return {'python': sys.version.split()[0], 'platform': platform.platform(), 'processor': platform.processor(),
            'packages': pkgs, 'git_commit': commit, 'git_dirty': dirty, 'feature_version': F.FEATURE_VERSION}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=lambda o: o.item() if hasattr(o, 'item') else str(o)), encoding='utf-8')
