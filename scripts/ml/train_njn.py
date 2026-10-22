"""NJN newborn image classifier: dataset class `jaundice` vs `normal`. NOT a bilirubin (mg/dL) estimator.

The NJN archive provides only a folder-level class per image. It has no bilirubin values, no patient
IDs and no documented labelling rule in this copy, so the output is a research score for the
dataset's class, not a clinical measurement or diagnosis.

  --stage cv     StratifiedGroupKFold(5) on the training split only (groups = perceptual-hash groups)
  --stage final  refits the candidates in ml/runs/<run>/selection.json and evaluates the test split once.
                 The operating threshold is fixed from out-of-fold TRAINING predictions (sensitivity >= 0.90).
"""
from __future__ import annotations

import _threads  # noqa: F401  must precede numpy

import argparse
import json
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegressionCV
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold, learning_curve
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import F, MODELS, RUNS, binary_metrics, colour_features, dump, environment, load_manifest, sha256_file

SEED = 20261022
TARGET_SENSITIVITY = 0.90
HGB_PARAMS = dict(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=20, l2_regularization=1.0, random_state=SEED)


def candidates(use_cnn: bool) -> dict:
    lr = lambda: make_pipeline(StandardScaler(), LogisticRegressionCV(Cs=np.logspace(-3, 2, 11), cv=5, max_iter=5000,  # noqa: E731
                                                                       scoring='roc_auc'))
    c = {'logreg_cf': (lr, 'cf'), 'hgb_cf': (lambda: HistGradientBoostingClassifier(**HGB_PARAMS), 'cf')}
    if use_cnn:
        c['logreg_mnv3'] = (lr, 'cnn')
    return c


def matrices(df, use_cnn: bool) -> dict:
    X, qual = colour_features(df, 'njn')
    m = {'cf': X, 'quality': qual}
    if use_cnn:
        from embeddings import mobilenet_embeddings
        m['cnn'] = mobilenet_embeddings(df, 'njn')
    return m


def oof_scores(make, X, y, groups) -> np.ndarray:
    oof = np.zeros(len(y))
    for fit_idx, val_idx in StratifiedGroupKFold(5, shuffle=True, random_state=SEED).split(X, y, groups):
        oof[val_idx] = make().fit(X[fit_idx], y[fit_idx]).predict_proba(X[val_idx])[:, 1]
    return oof


def threshold_for_sensitivity(y, s, target=TARGET_SENSITIVITY) -> float:
    pos = np.sort(s[y == 1])
    return float(pos[int(np.floor((1 - target) * len(pos)))])


def auc_ci(y, s, n=2000):
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() != y[i].max():
            vals.append(roc_auc_score(y[i], s[i]))
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def stage_cv(args) -> None:
    df = load_manifest('njn_manifest.csv')
    tr = df[df.split == 'train'].reset_index(drop=True)
    m, y = matrices(tr, args.cnn), tr.jaundice_label.to_numpy(int)
    results = {}
    for name, (make, feat) in candidates(args.cnn).items():
        s = oof_scores(make, m[feat], y, tr.group)
        t = threshold_for_sensitivity(y, s)
        results[name] = {'auroc': float(roc_auc_score(y, s)), 'brier': float(brier_score_loss(y, s)),
                         'at_oof_threshold': binary_metrics(y, (s >= t).astype(int)), 'threshold': t}
        print(f"{name:12s} AUROC {results[name]['auroc']:.3f} Brier {results[name]['brier']:.3f} "
              f"spec@sens0.90 {results[name]['at_oof_threshold']['specificity']:.3f}")
    dump(RUNS / args.run / 'cv_results.json', {
        'stage': 'cv', 'created_at': datetime.now(timezone.utc).isoformat(), 'seed': SEED, 'split': 'ml/splits/njn_v1.json',
        'cv': 'StratifiedGroupKFold(5, shuffle, seed) on training split; groups = dHash<=8 near-duplicate groups',
        'n_train': int(len(tr)), 'positive_rate': float(y.mean()), 'results': results, 'environment': environment()})


def logreg_artifact(model, threshold: float, info: dict, version: str) -> dict:
    sc, lr = model.named_steps['standardscaler'], model.named_steps['logisticregressioncv']
    return {
        'artifact_type': 'LOGISTIC_COLOUR_CLASSIFIER', 'schema_version': 1, 'model_id': 'njn-logreg-cf', 'version': version,
        'task': 'NJN_DATASET_CLASS_JAUNDICE_VS_NORMAL', 'output': 'score in [0,1] for the dataset class "jaundice"; not bilirubin',
        'feature_version': F.FEATURE_VERSION, 'feature_names': list(F.FEATURE_NAMES),
        'mean': sc.mean_.tolist(), 'scale': sc.scale_.tolist(), 'coefficients': lr.coef_[0].tolist(),
        'intercept': float(lr.intercept_[0]), 'C': float(lr.C_[0]),
        'operating_threshold': threshold,
        'operating_threshold_basis': f'Out-of-fold training scores, sensitivity >= {TARGET_SENSITIVITY}. A research operating point, not a clinical cut-off.',
        **info, 'validation_status': 'RESEARCH_ONLY',
    }


def export_onnx(model, path, emb_test: np.ndarray, te) -> float:
    """Backbone + folded StandardScaler/LogisticRegression head + sigmoid, as one ONNX graph."""
    import onnxruntime as ort
    import torch
    from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

    from common import read_path
    from app.ml.cnn_preprocess import to_tensor
    sc, lr = model.named_steps['standardscaler'], model.named_steps['logisticregressioncv']
    w = lr.coef_[0] / sc.scale_
    b = lr.intercept_[0] - float((lr.coef_[0] * sc.mean_ / sc.scale_).sum())

    class Net(torch.nn.Module):
        def __init__(self):
            super().__init__()
            base = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1).eval()
            self.features, self.pool = base.features, base.avgpool
            self.head = torch.nn.Linear(576, 1)
            with torch.no_grad():
                self.head.weight.copy_(torch.tensor(w, dtype=torch.float32)[None])
                self.head.bias.fill_(float(b))

        def forward(self, image):
            return torch.sigmoid(self.head(self.pool(self.features(image)).flatten(1)))

    net = Net().eval()
    torch.onnx.export(net, (torch.zeros(1, 3, 224, 224),), str(path), input_names=['image'], output_names=['score'],
                      opset_version=17, dynamo=False)
    sess = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    onnx_scores = np.array([sess.run(None, {'image': to_tensor(read_path(p))})[0][0, 0] for p in te.path])
    parity = float(np.max(np.abs(onnx_scores - model.predict_proba(emb_test)[:, 1])))
    if parity > 1e-3:
        raise SystemExit(f'ONNX export does not reproduce the sklearn pipeline (max diff {parity})')
    return parity


def stage_final(args) -> None:
    df = load_manifest('njn_manifest.csv')
    tr, te = df[df.split == 'train'].reset_index(drop=True), df[df.split == 'test'].reset_index(drop=True)
    sel = json.loads((RUNS / args.run / 'selection.json').read_text())
    names = list(dict.fromkeys([sel['edge'], sel['backend']]))
    need_cnn = any('mnv3' in n for n in names)
    mtr, mte = matrices(tr, need_cnn), matrices(te, need_cnn)
    ytr, yte = tr.jaundice_label.to_numpy(int), te.jaundice_label.to_numpy(int)
    cands = candidates(need_cnn)
    report, fitted, curves = {}, {}, {}
    for name in names:
        make, feat = cands[name]
        thr = threshold_for_sensitivity(ytr, oof_scores(make, mtr[feat], ytr, tr.group))
        model = make().fit(mtr[feat], ytr)
        s = model.predict_proba(mte[feat])[:, 1]
        fitted[name] = (model, thr)
        report[name] = {'auroc': float(roc_auc_score(yte, s)), 'auroc_ci95': auc_ci(yte, s), 'brier': float(brier_score_loss(yte, s)),
                        'threshold_from_training_oof': thr, 'at_threshold': binary_metrics(yte, (s >= thr).astype(int)),
                        'test_quality_gate_pass_rate': float(mte['quality'].quality_passed.mean())}
        bins = np.clip((s * 5).astype(int), 0, 4)
        report[name]['reliability'] = [{'bin': f'{b / 5:.1f}-{(b + 1) / 5:.1f}', 'n': int((bins == b).sum()),
                                        'mean_score': float(s[bins == b].mean()) if (bins == b).any() else None,
                                        'observed_rate': float(yte[bins == b].mean()) if (bins == b).any() else None} for b in range(5)]
        sizes, trs, vas = learning_curve(make(), mtr[feat], ytr, groups=tr.group, cv=StratifiedGroupKFold(5, shuffle=True, random_state=SEED),
                                         train_sizes=np.linspace(.2, 1, 5), scoring='roc_auc', shuffle=True, random_state=SEED)
        curves[name] = (sizes, trs.mean(1), vas.mean(1))
        r = report[name]
        print(f"[test] {name:12s} AUROC {r['auroc']:.3f} {np.round(r['auroc_ci95'], 3)} sens {r['at_threshold']['sensitivity']:.3f} "
              f"spec {r['at_threshold']['specificity']:.3f}")
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, len(curves), figsize=(5 * len(curves), 4), squeeze=False)
    for a, (name, (sz, t, v)) in zip(ax[0], curves.items()):
        a.plot(sz, t, 'o-', label='training (in-fold)'); a.plot(sz, v, 'o-', label='validation (grouped CV)')
        a.set_title(f'{name}: learning curve'); a.set_xlabel('training images'); a.set_ylabel('AUROC'); a.legend()
    fig.tight_layout(); fig.savefig(RUNS / args.run / 'learning_curves.png', dpi=110); plt.close(fig)
    artifacts = {}
    info = {'training': {'dataset': 'NJN (folder classes normal/jaundice)', 'n_train': int(len(tr)), 'split': 'ml/splits/njn_v1.json', 'seed': SEED,
                         'feature_min': mtr['cf'].min(0).tolist(), 'feature_max': mtr['cf'].max(0).tolist()},
            'evaluation': {'held_out_test': {k: report[sel['edge']][k] for k in ('auroc', 'auroc_ci95', 'at_threshold')}}}
    if sel['edge'] == 'logreg_cf':
        model, thr = fitted['logreg_cf']
        dump(MODELS / 'njn_logreg_cf_v1.json', logreg_artifact(model, thr, info, args.version))
        artifacts['edge'] = artifacts['backend'] = {'path': 'models/njn_logreg_cf_v1.json', 'sha256': sha256_file(MODELS / 'njn_logreg_cf_v1.json')}
    if sel['backend'] == 'logreg_mnv3':
        model, thr = fitted['logreg_mnv3']
        path = MODELS / 'njn_mnv3_logreg_v1.onnx'
        parity = export_onnx(model, path, mte['cnn'], te)
        meta = {'artifact_type': 'ONNX_CNN_CLASSIFIER', 'schema_version': 1, 'model_id': 'njn-mnv3-logreg', 'version': args.version,
                'task': 'NJN_DATASET_CLASS_JAUNDICE_VS_NORMAL', 'output': 'score in [0,1] for the dataset class "jaundice"; not bilirubin',
                'onnx_file': path.name, 'onnx_sha256': sha256_file(path), 'input_name': 'image', 'input_shape': [1, 3, 224, 224],
                'preprocessing': 'cnn-v1 (backend/app/ml/cnn_preprocess.py)', 'backbone': 'torchvision mobilenet_v3_small IMAGENET1K_V1, frozen',
                'operating_threshold': thr,
                'operating_threshold_basis': f'Out-of-fold training scores, sensitivity >= {TARGET_SENSITIVITY}. A research operating point, not a clinical cut-off.',
                'onnx_vs_sklearn_max_abs_diff': parity,
                'training': info['training'],
                'evaluation': {'held_out_test': {k: report['logreg_mnv3'][k] for k in ('auroc', 'auroc_ci95', 'at_threshold')}},
                'validation_status': 'RESEARCH_ONLY'}
        dump(MODELS / 'njn_mnv3_logreg_v1.json', meta)
        artifacts['backend'] = {'path': 'models/njn_mnv3_logreg_v1.json', 'sha256': sha256_file(MODELS / 'njn_mnv3_logreg_v1.json'),
                                'onnx': {'path': 'models/' + path.name, 'sha256': meta['onnx_sha256'], 'bytes': path.stat().st_size}}
    dump(RUNS / args.run / 'final_results.json', {
        'stage': 'final', 'created_at': datetime.now(timezone.utc).isoformat(), 'selection': sel, 'n_test': int(len(te)),
        'test_positive_rate': float(yte.mean()), 'results': report, 'artifacts': artifacts, 'environment': environment()})
    print('artifacts', artifacts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', choices=['cv', 'final'], required=True)
    ap.add_argument('--run', default='njn-v1')
    ap.add_argument('--no-cnn', dest='cnn', action='store_false')
    ap.add_argument('--version', default='1.0.0-research')
    a = ap.parse_args()
    stage_cv(a) if a.stage == 'cv' else stage_final(a)


if __name__ == '__main__':
    main()
