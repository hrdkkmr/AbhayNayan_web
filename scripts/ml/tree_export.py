"""Export a fitted HistGradientBoostingRegressor to plain JSON so the server never unpickles a model.

Prediction = baseline + sum over trees of the reached leaf value (sklearn folds the learning rate
into leaf values). A sample goes left when x <= threshold. Inputs are never NaN (features.py
rejects non-finite vectors) and categorical splits are not used.
"""
from __future__ import annotations

import numpy as np


def export_hgb(model, feature_names) -> dict:
    trees = []
    for (predictor,) in model._predictors:
        nodes = predictor.nodes
        if nodes['is_categorical'].any():
            raise ValueError('categorical splits are not supported by the JSON evaluator')
        trees.append({
            'feature': [int(f) if not leaf else -1 for f, leaf in zip(nodes['feature_idx'], nodes['is_leaf'])],
            'threshold': [float(t) for t in nodes['num_threshold']],
            'left': [int(v) for v in nodes['left']],
            'right': [int(v) for v in nodes['right']],
            'value': [float(v) for v in nodes['value']],
            'is_leaf': [bool(v) for v in nodes['is_leaf']],
        })
    art = {'artifact_type': 'GRADIENT_BOOSTED_TREES_JSON', 'schema_version': 1, 'feature_names': list(feature_names),
           'baseline': float(np.ravel(model._baseline_prediction)[0]), 'trees': trees}
    return art


def predict_json(art: dict, X: np.ndarray) -> np.ndarray:
    out = np.full(len(X), art['baseline'], dtype=np.float64)
    for t in art['trees']:
        for i, row in enumerate(X):
            n = 0
            while not t['is_leaf'][n]:
                n = t['left'][n] if row[t['feature'][n]] <= t['threshold'][n] else t['right'][n]
            out[i] += t['value'][n]
    return out
