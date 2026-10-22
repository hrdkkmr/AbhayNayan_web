"""Frozen ImageNet MobileNetV3-Small embeddings (576-d, global-average-pooled) for the CNN comparison.

Preprocessing: backend/app/ml/cnn_preprocess.py (contract cnn-v1). Requires the research venv (.venv-ml) with torch + torchvision.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import PRIVATE, read_path
from app.ml.cnn_preprocess import to_tensor  # same preprocessing as the served ONNX model


def mobilenet_embeddings(df: pd.DataFrame, cache_name: str) -> np.ndarray:
    cache = PRIVATE / f'{cache_name}_mnv3s_emb.npz'
    ids, embs = [], np.zeros((0, 576), np.float32)
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        ids, embs = [str(i) for i in z['ids']], z['emb']
    idx = {k: i for i, k in enumerate(ids)}
    todo = df[~df.image_id.isin(idx)]
    if todo.empty:
        return embs[[idx[i] for i in df.image_id]]
    import torch
    from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small
    torch.manual_seed(0)
    net = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1).eval()
    out = []
    with torch.no_grad():
        paths = list(todo.path)
        for i in range(0, len(paths), 32):
            x = torch.from_numpy(np.concatenate([to_tensor(read_path(p)) for p in paths[i:i + 32]]))
            out.append(net.avgpool(net.features(x)).flatten(1).numpy())
    ids += list(todo.image_id)
    embs = np.concatenate([embs, *out]).astype(np.float32)
    np.savez(cache, ids=np.array(ids, dtype=str), emb=embs)  # fixed-width strings: loadable without pickle
    idx = {k: i for i, k in enumerate(ids)}
    return embs[[idx[i] for i in df.image_id]]
