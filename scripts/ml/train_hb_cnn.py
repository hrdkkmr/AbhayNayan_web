"""Fine-tuned MobileNetV3-Small hemoglobin regressor for the Android app (contract cnn-v1 input), v2.

Selection is decided by 5-fold patient-grouped cross-validation on the training split only, before the test split is
scored: the candidates are the CNN alone, the existing ridge colour model (hb-ridge-cf) alone, and their mean. The
test split (manifest `split == test`, held-out patients) is then scored once for every candidate.

The anemia probability used by the app is P(Hb < cut-off) under a normal error model with sigma = out-of-fold RMSE of
the selected candidate; its AUROC and Brier score are reported against the dataset's anemia labels.

Outputs: models/hb_mnv3_ft_v1.onnx (+ .json card), ml/runs/hb-cnn-v1/results.json. Requires .venv-ml.
"""
from __future__ import annotations

import _threads  # noqa: F401

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone

import numpy as np
import torch
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from torch import nn
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

from common import MODELS, RUNS, bootstrap_ci, colour_features, load_manifest, read_path, regression_metrics
from app.ml.cnn_preprocess import to_tensor

SEED = 20261025
FROZEN_BLOCKS = 7  # of the 13 MobileNetV3-Small feature blocks


def auroc(y: np.ndarray, s: np.ndarray) -> float:
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float('nan')
    return float(((pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()) / (len(pos) * len(neg)))


def phi(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1 + np.vectorize(math.erf)(z / math.sqrt(2)))


def anemia_metrics(p: np.ndarray, cut: np.ndarray, lab: np.ndarray, sigma: float) -> dict:
    prob = phi((cut - p) / sigma)
    yes = prob >= 0.5
    pos, neg = lab == 1, lab == 0
    return {'n': int(len(lab)), 'positives': int(pos.sum()), 'auroc': auroc(lab, prob), 'brier': float(((prob - lab) ** 2).mean()),
            'sensitivity': float((yes & pos).sum() / max(1, pos.sum())), 'specificity': float((~yes & neg).sum() / max(1, neg.sum())),
            'accuracy': float((yes == pos).mean())}


class HbNet(nn.Module):
    """MobileNetV3-Small features -> 576-d pooled -> dropout -> 1 (standardised Hb); output de-standardised to g/dL."""

    def __init__(self, mean: float, std: float):
        super().__init__()
        base = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
        self.features, self.pool = base.features, base.avgpool
        self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(576, 1))
        self.register_buffer('mean', torch.tensor(mean))
        self.register_buffer('std', torch.tensor(std))
        for block in self.features[:FROZEN_BLOCKS]:
            for p in block.parameters():
                p.requires_grad = False

    def train(self, mode: bool = True):
        super().train(mode)
        for m in self.modules():  # BatchNorm keeps its ImageNet statistics: batches here are too small to estimate them
            if isinstance(m, nn.BatchNorm2d):
                m.eval()
        return self

    def forward(self, x):
        z = self.head(self.pool(self.features(x)).flatten(1)).squeeze(1)
        return z * self.std + self.mean


def augment(x: torch.Tensor, g: torch.Generator) -> torch.Tensor:
    """Geometry only: colour is the signal, so no colour jitter."""
    if torch.rand(1, generator=g) < 0.5:
        x = x.flip(-1)
    if torch.rand(1, generator=g) < 0.5:
        x = x.flip(-2)
    x = torch.rot90(x, int(torch.randint(0, 4, (1,), generator=g)), (-2, -1))
    return torch.roll(x, (int(torch.randint(-12, 13, (1,), generator=g)), int(torch.randint(-12, 13, (1,), generator=g))), (-2, -1))


def predict(net: nn.Module, X: torch.Tensor) -> np.ndarray:
    net.eval()
    with torch.no_grad():
        return torch.stack([net(v) for v in (X, X.flip(-1), X.flip(-2), torch.rot90(X, 1, (-2, -1)))]).mean(0).numpy()


def train_cnn(X, y, idx, epochs, seed, eval_idx=None):
    """Returns the net and, if eval_idx is given, predictions for eval_idx after every epoch."""
    torch.manual_seed(seed)
    g = torch.Generator().manual_seed(seed)
    net = HbNet(float(y[idx].mean()), float(y[idx].std()))
    params = [{'params': [p for p in net.features.parameters() if p.requires_grad], 'lr': 3e-4},
              {'params': net.head.parameters(), 'lr': 3e-3}]
    opt = torch.optim.AdamW(params, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    loss_fn = nn.HuberLoss(delta=1.5)
    yt = torch.tensor(y, dtype=torch.float32)
    history = []
    for _ in range(epochs):
        net.train()
        perm = idx[torch.randperm(len(idx), generator=g).numpy()]
        for i in range(0, len(perm), 16):
            b = perm[i:i + 16]
            opt.zero_grad()
            loss_fn(net(torch.stack([augment(X[j], g) for j in b])), yt[b]).backward()
            opt.step()
        sched.step()
        if eval_idx is not None:
            history.append(predict(net, X[eval_idx]))
    return net, history


def ridge_predict(art: dict, Xcf: np.ndarray) -> np.ndarray:
    m, s, c = (np.array(art[k]) for k in ('mean', 'scale', 'coefficients'))
    return art['intercept'] + ((Xcf - m) / s) @ c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=30)
    ap.add_argument('--folds', type=int, default=5)
    args = ap.parse_args()

    df = load_manifest('hb_manifest.csv')
    df = df[df.dataset == 'eyes_defy_anemia'].reset_index(drop=True)
    X = torch.from_numpy(np.concatenate([to_tensor(read_path(p)) for p in df.path]))
    Xcf, _ = colour_features(df, 'hb')
    y = df.hb_g_dl.to_numpy(float)
    cut = df.anemia_cutoff_g_dl.to_numpy(float)
    lab = df.anemic_label.to_numpy(int)
    tr = np.where(df.split == 'train')[0]
    te = np.where(df.split == 'test')[0]
    print(f'train {len(tr)} test {len(te)}', flush=True)

    # ---- cross-validation on the training split ------------------------------------------------------------
    oof_cnn = np.zeros((args.epochs, len(tr)))
    oof_ridge = np.zeros(len(tr))
    folds = list(GroupKFold(n_splits=args.folds).split(tr, groups=df.group.to_numpy()[tr]))
    for k, (a, b) in enumerate(folds):
        _, hist = train_cnn(X, y, tr[a], args.epochs, SEED + k, eval_idx=tr[b])
        oof_cnn[:, b] = np.stack(hist)
        ridge = make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-3, 3, 13))).fit(Xcf[tr[a]], y[tr[a]])
        oof_ridge[b] = ridge.predict(Xcf[tr[b]])
        print(f'fold {k + 1}: CNN MAE by epoch', np.round(np.abs(oof_cnn[:, b] - y[tr[b]]).mean(1), 2).tolist(), flush=True)
    epoch_mae = np.abs(oof_cnn - y[tr]).mean(1)
    best_epochs = int(epoch_mae.argmin()) + 1
    cands = {'cnn': oof_cnn[best_epochs - 1], 'ridge_cf': oof_ridge, 'mean_cnn_ridge': (oof_cnn[best_epochs - 1] + oof_ridge) / 2}
    cv = {}
    for name, p in cands.items():
        sigma = float(np.sqrt(((p - y[tr]) ** 2).mean()))
        cv[name] = {**regression_metrics(y[tr], p), 'sigma': sigma, 'anemia': anemia_metrics(p, cut[tr], lab[tr], sigma)}
    selected = min(cv, key=lambda n: cv[n]['mae'])
    print('CV', json.dumps(cv, indent=1), '\nselected', selected, 'epochs', best_epochs, flush=True)

    # ---- final fit and one test evaluation -----------------------------------------------------------------
    net, _ = train_cnn(X, y, tr, best_epochs, SEED)
    ridge_art = json.loads((MODELS / 'hb_ridge_cf_v1.json').read_text())
    test_preds = {'cnn': predict(net, X[te]), 'ridge_cf': ridge_predict(ridge_art, Xcf[te])}
    test_preds['mean_cnn_ridge'] = (test_preds['cnn'] + test_preds['ridge_cf']) / 2
    test = {n: {**regression_metrics(y[te], p), 'ci95': bootstrap_ci(y[te], p, regression_metrics, seed=SEED),
                'anemia': anemia_metrics(p, cut[te], lab[te], cv[n]['sigma'])} for n, p in test_preds.items()}
    print('TEST', json.dumps({n: {k: v for k, v in t.items() if k != 'ci95'} for n, t in test.items()}, indent=1), flush=True)

    onnx_path = MODELS / 'hb_mnv3_ft_v1.onnx'
    net.eval()
    torch.onnx.export(net, torch.zeros(1, 3, 224, 224), onnx_path, input_names=['image'], output_names=['hb'], opset_version=17, dynamo=False)
    sha = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    import onnxruntime as ort
    sess = ort.InferenceSession(str(onnx_path), providers=['CPUExecutionProvider'])
    with torch.no_grad():
        onnx_diff = float(max(abs(sess.run(None, {'image': X[i:i + 1].numpy()})[0][0] - float(net(X[i:i + 1])[0])) for i in te[:10]))
    card = {
        'artifact_type': 'ONNX_CNN_REGRESSOR', 'schema_version': 1, 'model_id': 'hb-mnv3-ft', 'version': '1.0.0',
        'task': 'HEMOGLOBIN_G_DL_FROM_PALPEBRAL_CONJUNCTIVA', 'onnx_file': onnx_path.name, 'onnx_sha256': sha,
        'input_name': 'image', 'input_shape': [1, 3, 224, 224], 'output_name': 'hb', 'output_unit': 'g/dL',
        'preprocessing': 'cnn-v1 (backend/app/ml/cnn_preprocess.py)',
        'backbone': f'torchvision mobilenet_v3_small IMAGENET1K_V1; blocks {FROZEN_BLOCKS}-12 and head fine-tuned, BatchNorm frozen',
        'epochs': best_epochs, 'selected_combination': selected,
        'error_sigma_g_dl': cv[selected]['sigma'], 'error_sigma_basis': 'out-of-fold RMSE of the selected combination (5-fold, patient-grouped)',
        'training': {'dataset': 'Eyes-defy-anemia palpebral crops (India + Italy)', 'n_train': int(len(tr)), 'split': 'manifest split (patient level)', 'seed': SEED},
        'cv': cv, 'test': test, 'onnx_vs_torch_max_abs_diff': onnx_diff,
    }
    (MODELS / 'hb_mnv3_ft_v1.json').write_text(json.dumps(card, indent=1))
    out_dir = RUNS / 'hb-cnn-v1'
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'results.json').write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), 'seed': SEED,
                                                      'cv_epoch_mae': epoch_mae.tolist(), **{k: card[k] for k in ('epochs', 'selected_combination', 'cv', 'test')}}, indent=1))
    print('wrote', onnx_path, sha, 'onnx diff', onnx_diff, flush=True)


if __name__ == '__main__':
    main()
