"""Loads, verifies and runs the research image models. Fails closed and never substitutes a value.

A model is READY only when: the operator flag is set, every artifact file exists and matches its
SHA-256 pin in models/MODEL_REGISTRY.json, the artifact schema validates, and (for ONNX) the
runtime is installed. Artifacts are loaded once per process and reused across requests.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.ml import cnn_preprocess, features as F

PROJECT_DIR = Path(__file__).resolve().parents[3]
MODELS_DIR = PROJECT_DIR / 'models'
IMAGE_MODELS_FLAG = 'ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS'
# Served (backend-role) model per task. Edge-role artifacts are bundled in the Android app.
SERVED = {'hemoglobin': 'hb-hgb-cf', 'neonatal_jaundice_class': 'njn-mnv3-logreg'}
HB_PLAUSIBLE = (2.0, 25.0)


class ModelError(Exception):
    def __init__(self, code: str, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def flag_enabled() -> bool:
    return os.getenv(IMAGE_MODELS_FLAG, '').strip().lower() in {'1', 'true', 'yes'}


@dataclass
class LoadedModel:
    model_id: str
    task: str
    version: str
    meta: dict[str, Any]
    runner: Any
    load_ms: float
    sha256: dict[str, str] = field(default_factory=dict)

    def predict(self, image: np.ndarray, fr: F.FeatureResult) -> float:
        return float(self.runner(image, fr))

    def out_of_range_features(self, vec: np.ndarray, margin: float = 0.10) -> list[str]:
        lo, hi = self.meta['training'].get('feature_min'), self.meta['training'].get('feature_max')
        if not lo or not hi:
            return []
        names = self.meta.get('feature_names', F.FEATURE_NAMES)
        out = []
        for name, v, a, b in zip(names, vec, lo, hi):
            pad = (b - a) * margin
            if v < a - pad or v > b + pad:
                out.append(name)
        return out


def _check_features(meta: dict) -> None:
    if meta.get('feature_version') != F.FEATURE_VERSION or list(meta.get('feature_names', [])) != list(F.FEATURE_NAMES):
        raise ModelError('MODEL_INCOMPATIBLE', 'Model was trained with a different feature contract.')


def _linear_runner(meta: dict, logistic: bool):
    _check_features(meta)
    mean, scale, coef = (np.asarray(meta[k], float) for k in ('mean', 'scale', 'coefficients'))
    n = len(F.FEATURE_NAMES)
    if not (mean.shape == scale.shape == coef.shape == (n,)) or np.any(scale <= 0) or not np.all(np.isfinite(coef)):
        raise ModelError('MODEL_INCOMPATIBLE', 'Model parameters are malformed.')
    intercept = float(meta['intercept'])

    def run(_image, fr):
        z = float(((fr.vector - mean) / scale) @ coef + intercept)
        return 1.0 / (1.0 + math.exp(-z)) if logistic else z
    return run


def _tree_runner(meta: dict):
    _check_features(meta)
    trees = meta['trees']
    n = len(F.FEATURE_NAMES)
    for t in trees:
        size = len(t['value'])
        if not all(len(t[k]) == size for k in ('feature', 'threshold', 'left', 'right', 'is_leaf')):
            raise ModelError('MODEL_INCOMPATIBLE', 'Tree arrays are inconsistent.')
        for i in range(size):
            if not t['is_leaf'][i] and not (0 <= t['feature'][i] < n and 0 < t['left'][i] < size and 0 < t['right'][i] < size):
                raise ModelError('MODEL_INCOMPATIBLE', 'Tree structure is invalid.')
    baseline = float(meta['baseline'])

    def run(_image, fr):
        x, total = fr.vector, baseline
        for t in trees:
            node, steps = 0, 0
            while not t['is_leaf'][node]:
                node = t['left'][node] if x[t['feature'][node]] <= t['threshold'][node] else t['right'][node]
                steps += 1
                if steps > 64:
                    raise ModelError('INFERENCE_FAILED', 'Tree traversal did not terminate.', 500)
            total += t['value'][node]
        return total
    return run


def _onnx_runner(meta: dict, onnx_path: Path):
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise ModelError('RUNTIME_UNAVAILABLE', 'ONNX Runtime is not installed on this server.') from exc
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = int(os.getenv('ABHAYNAYAN_ONNX_THREADS', '1'))
    try:
        sess = ort.InferenceSession(str(onnx_path), sess_options=opts, providers=['CPUExecutionProvider'])
    except Exception as exc:  # corrupt or incompatible graph
        raise ModelError('MODEL_INCOMPATIBLE', 'The ONNX model could not be loaded.') from exc
    inp = sess.get_inputs()[0]
    if inp.name != meta['input_name'] or list(inp.shape) != meta['input_shape']:
        raise ModelError('MODEL_INCOMPATIBLE', 'ONNX input signature does not match the model card.')
    lock = threading.Lock()

    def run(image, _fr):
        x = cnn_preprocess.to_tensor(image)
        with lock:
            out = sess.run(None, {inp.name: x})[0]
        if out.shape != (1, 1):
            raise ModelError('INFERENCE_FAILED', 'Unexpected model output shape.', 500)
        return float(out[0, 0])
    return run


class Registry:
    def __init__(self, models_dir: Path = MODELS_DIR) -> None:
        self.models_dir = models_dir
        self._lock = threading.Lock()
        self._cache: dict[str, LoadedModel | ModelError] = {}

    def reset(self) -> None:
        with self._lock:
            self._cache.clear()

    def _pins(self) -> dict[str, Any]:
        try:
            return json.loads((self.models_dir / 'MODEL_REGISTRY.json').read_text(encoding='utf-8'))['models']
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            raise ModelError('MODEL_UNAVAILABLE', 'Model registry is missing or malformed.') from exc

    def _load(self, model_id: str) -> LoadedModel:
        t0 = time.perf_counter()
        pin = self._pins().get(model_id)
        if pin is None:
            raise ModelError('MODEL_UNAVAILABLE', 'Model is not registered.')
        for name, expected in pin['sha256'].items():
            path = self.models_dir / name
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise ModelError('MODEL_UNAVAILABLE', 'A model artifact is missing.') from exc
            if digest != expected:
                raise ModelError('MODEL_INTEGRITY_FAILED', 'A model artifact does not match its registered checksum.')
        try:
            meta = json.loads((self.models_dir / pin['files'][0]).read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ModelError('MODEL_INCOMPATIBLE', 'Model card could not be parsed.') from exc
        kind = meta.get('artifact_type')
        try:
            if kind == 'GRADIENT_BOOSTED_TREES_JSON':
                runner = _tree_runner(meta)
            elif kind == 'LINEAR_COLOUR_REGRESSOR':
                runner = _linear_runner(meta, logistic=False)
            elif kind == 'LOGISTIC_COLOUR_CLASSIFIER':
                runner = _linear_runner(meta, logistic=True)
            elif kind == 'ONNX_CNN_CLASSIFIER':
                runner = _onnx_runner(meta, self.models_dir / pin['files'][1])
            else:
                raise ModelError('MODEL_INCOMPATIBLE', 'Unknown artifact type.')
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelError('MODEL_INCOMPATIBLE', 'Model card is missing required fields.') from exc
        if meta.get('validation_status') != 'RESEARCH_ONLY':
            raise ModelError('MODEL_INCOMPATIBLE', 'Only research-only image models are supported by this build.')
        return LoadedModel(model_id, pin['task'], meta['version'], meta, runner, (time.perf_counter() - t0) * 1000, pin['sha256'])

    def get(self, model_id: str) -> LoadedModel:
        with self._lock:
            cached = self._cache.get(model_id)
            if cached is None:
                try:
                    cached = self._load(model_id)
                except ModelError as exc:
                    cached = exc
                self._cache[model_id] = cached
        if isinstance(cached, ModelError):
            raise cached
        return cached

    def served(self, task: str) -> LoadedModel:
        if not flag_enabled():
            raise ModelError('MODEL_DISABLED', f'Research image models are disabled. An operator must set {IMAGE_MODELS_FLAG}=1.')
        return self.get(SERVED[task])

    def status(self) -> dict[str, Any]:
        out = {}
        for task, model_id in SERVED.items():
            entry: dict[str, Any] = {'model_id': model_id, 'task': task}
            try:
                m = self.get(model_id)
                entry.update({'loadable': True, 'version': m.version, 'validation_status': m.meta['validation_status'],
                              'load_ms': round(m.load_ms, 1), 'evaluation': m.meta.get('evaluation')})
            except ModelError as exc:
                entry.update({'loadable': False, 'reason_code': exc.code, 'reason': exc.message})
            entry['status'] = ('READY_EXPERIMENTAL' if entry['loadable'] else 'UNAVAILABLE') if flag_enabled() else 'DISABLED'
            out[task] = entry
        return out


REGISTRY = Registry()
