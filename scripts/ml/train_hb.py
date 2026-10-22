"""Hemoglobin (g/dL) regression from segmented palpebral-conjunctiva images.

Two stages so that model selection never sees the test partition:

  --stage cv     grouped 5-fold CV on the TRAINING partitions only (CP-AnemiC grouped by hospital,
                 Eyes-defy-anemia by patient). Writes ml/runs/<run>/cv_results.json.
  --stage final  refits the candidates recorded in selection.json (chosen from CV) on their training data, evaluates the held-out test
                 partitions once, and writes artifacts to models/ plus metrics to ml/runs/<run>/.

  .venv-ml/Scripts/python scripts/ml/train_hb.py --stage cv
  .venv-ml/Scripts/python scripts/ml/train_hb.py --stage final   # reads ml/runs/<run>/selection.json
"""
from __future__ import annotations

import _threads  # noqa: F401  must precede numpy

import argparse
import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import GroupKFold, learning_curve
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import (F, MODELS, RUNS, binary_metrics, bootstrap_ci, calibration, colour_features, dump, environment,
                    load_manifest, regression_metrics, sha256_file)

SEED = 20261022
ALPHAS = np.logspace(-2, 4, 25)
HGB_PARAMS = dict(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=20, l2_regularization=1.0, random_state=SEED)


class MeanModel:
    def fit(self, X, y):
        self.mu = float(np.mean(y)); return self

    def predict(self, X):
        return np.full(len(X), self.mu)


def candidates(use_cnn: bool) -> dict:
    c = {
        'mean': (lambda: MeanModel(), 'none'),
        'ridge_cf': (lambda: make_pipeline(StandardScaler(), RidgeCV(alphas=ALPHAS)), 'cf'),
        'hgb_cf': (lambda: HistGradientBoostingRegressor(**HGB_PARAMS), 'cf'),
    }
    if use_cnn:
        c['ridge_mnv3'] = (lambda: make_pipeline(StandardScaler(), RidgeCV(alphas=ALPHAS)), 'cnn')
        c['ridge_cf_mnv3'] = (lambda: make_pipeline(StandardScaler(), RidgeCV(alphas=ALPHAS)), 'cf+cnn')
    return c


def matrices(df: pd.DataFrame, use_cnn: bool) -> dict:
    Xcf, qual = colour_features(df, 'hb')
    m = {'none': np.zeros((len(df), 1)), 'cf': Xcf, 'quality': qual}
    if use_cnn:
        from embeddings import mobilenet_embeddings
        emb = mobilenet_embeddings(df, 'hb')
        m['cnn'] = emb
        m['cf+cnn'] = np.hstack([Xcf, emb])
    return m


def cv_groups(df: pd.DataFrame) -> np.ndarray:
    # Whole hospitals for CP-AnemiC (site shift); whole patients for Eyes-defy-anemia.
    return np.where(df.dataset == 'cp_anemic', 'site:' + df.site, df.group)


def stage_cv(args) -> None:
    df = load_manifest('hb_manifest.csv')
    tr = df[df.split == 'train'].reset_index(drop=True)
    mats = matrices(tr, args.cnn)
    y = tr.hb_g_dl.to_numpy(float)
    groups = cv_groups(tr)
    folds = list(GroupKFold(n_splits=5).split(tr, y, groups))
    results = {}
    for train_on in ('pooled', 'cp_anemic', 'eyes_defy_anemia'):
        for name, (make, feat) in candidates(args.cnn).items():
            oof = np.full(len(tr), np.nan)
            for fit_idx, val_idx in folds:
                if train_on != 'pooled':
                    fit_idx = fit_idx[tr.dataset.iloc[fit_idx].to_numpy() == train_on]
                    val_idx = val_idx[tr.dataset.iloc[val_idx].to_numpy() == train_on]
                if len(val_idx) == 0:
                    continue
                X = mats[feat]
                model = make().fit(X[fit_idx], y[fit_idx])
                oof[val_idx] = model.predict(X[val_idx])
            ok = ~np.isnan(oof)
            res = {'all': regression_metrics(y[ok], oof[ok])}
            for ds in ('cp_anemic', 'eyes_defy_anemia'):
                sel = ok & (tr.dataset == ds).to_numpy()
                if sel.any():
                    res[ds] = regression_metrics(y[sel], oof[sel])
            results[f'{train_on}/{name}'] = res
            print(f"{train_on:17s} {name:14s} " + '  '.join(
                f"{k}: MAE {v['mae']:.3f} RMSE {v['rmse']:.3f} R2 {v['r2']:+.3f}" for k, v in res.items() if k != 'all'))
    run = args.run
    dump(RUNS / run / 'cv_results.json', {
        'stage': 'cv', 'created_at': datetime.now(timezone.utc).isoformat(), 'seed': SEED,
        'splits': ['ml/splits/cp_anemic_v1.json', 'ml/splits/eyes_defy_anemia_v1.json'],
        'cv': 'GroupKFold(5); groups = hospital (CP-AnemiC) or patient (Eyes-defy-anemia); training partitions only',
        'n_train': {k: int(v) for k, v in tr.dataset.value_counts().items()},
        'hyperparameters': {'ridge_alphas': [float(a) for a in ALPHAS], 'hgb': HGB_PARAMS},
        'results': results, 'environment': environment(),
    })
    print('wrote', RUNS / run / 'cv_results.json')


def ridge_artifact(model, names, train_info: dict, metrics: dict, version: str) -> dict:
    scaler, ridge = model.named_steps['standardscaler'], model.named_steps['ridgecv']
    return {
        'artifact_type': 'LINEAR_COLOUR_REGRESSOR', 'schema_version': 1, 'model_id': 'hb-ridge-cf', 'version': version,
        'biomarker': 'HEMOGLOBIN', 'output_unit': 'g/dL', 'feature_version': F.FEATURE_VERSION, 'feature_names': list(names),
        'preprocessing': {'max_side': F.MAX_SIDE, 'alpha_min': F.ALPHA_MIN, 'clip_level': F.CLIP_LEVEL,
                          'dark_level': F.DARK_LEVEL, 'min_valid_pixels': F.MIN_VALID_PIXELS},
        'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist(), 'coefficients': ridge.coef_.tolist(),
        'intercept': float(ridge.intercept_), 'ridge_alpha': float(ridge.alpha_),
        'training': train_info, 'evaluation': metrics,
        'validation_status': 'RESEARCH_ONLY', 'intended_input': 'Expert-segmented palpebral conjunctiva crop (masked background)',
    }


def evaluate(name: str, model, X: np.ndarray, te: pd.DataFrame) -> dict:
    y = te.hb_g_dl.to_numpy(float)
    t0 = time.perf_counter()
    p = model.predict(X)
    per_image_ms = (time.perf_counter() - t0) * 1000 / len(X)
    out = {'overall': {**regression_metrics(y, p), 'ci95': bootstrap_ci(y, p, regression_metrics, seed=SEED)},
           'calibration': calibration(y, p), 'predict_ms_per_image_batch': per_image_ms, 'subgroups': {}}
    for col in ('dataset', 'site', 'sex'):
        for val, g in te.groupby(col):
            idx = g.index.to_numpy()
            if len(idx) >= 15:
                out['subgroups'][f'{col}={val}'] = {**regression_metrics(y[idx], p[idx]),
                                                    'ci95': bootstrap_ci(y[idx], p[idx], regression_metrics, n=1000, seed=SEED)}
            else:
                out['subgroups'][f'{col}={val}'] = {'n': int(len(idx)), 'note': 'n < 15: not reported'}
    # Range performance: residuals by measured-Hb band (descriptive, not thresholds).
    bands = pd.cut(y, [0, 7, 10, 12, 30], right=False, labels=['<7', '7-10', '10-12', '>=12'])
    out['by_measured_range'] = {str(b): regression_metrics(y[bands == b], p[bands == b]) for b in bands.categories if (bands == b).sum() >= 5}
    # Screening: predicted Hb below the population-specific WHO cut-off vs measured Hb below it.
    cut = te.anemia_cutoff_g_dl.to_numpy(float)
    out['screening_at_population_cutoff'] = {}
    for ds, g in te.groupby('dataset'):
        idx = g.index.to_numpy()
        out['screening_at_population_cutoff'][ds] = binary_metrics((y[idx] < cut[idx]).astype(int), (p[idx] < cut[idx]).astype(int))
    print(f"[test] {name:14s} MAE {out['overall']['mae']:.3f} RMSE {out['overall']['rmse']:.3f} R2 {out['overall']['r2']:+.3f}")
    return out, p


def plots(run_dir, curves: dict, preds: dict, te: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, len(curves), figsize=(5 * len(curves), 4), squeeze=False)
    for a, (name, (sizes, tr_mae, va_mae)) in zip(ax[0], curves.items()):
        a.plot(sizes, tr_mae, 'o-', label='training (in-fold)')
        a.plot(sizes, va_mae, 'o-', label='validation (grouped CV)')
        a.set_title(f'{name}: learning curve'); a.set_xlabel('training images'); a.set_ylabel('MAE g/dL'); a.legend()
    fig.tight_layout(); fig.savefig(run_dir / 'learning_curves.png', dpi=110); plt.close(fig)
    y = te.hb_g_dl.to_numpy(float)
    fig, ax = plt.subplots(1, len(preds), figsize=(4.5 * len(preds), 4), squeeze=False)
    for a, (name, p) in zip(ax[0], preds.items()):
        for ds, mk in (('cp_anemic', 'o'), ('eyes_defy_anemia', '^')):
            s = (te.dataset == ds).to_numpy()
            a.scatter(y[s], p[s], s=12, marker=mk, alpha=.6, label=ds)
        a.plot([3, 17], [3, 17], 'k--', lw=1); a.set_xlabel('measured Hb g/dL'); a.set_ylabel('predicted'); a.set_title(f'{name} (test)')
        a.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(run_dir / 'test_predicted_vs_measured.png', dpi=110); plt.close(fig)


def stage_final(args) -> None:
    df = load_manifest('hb_manifest.csv')
    tr_all = df[df.split == 'train'].reset_index(drop=True)
    te_all = df[df.split == 'test'].reset_index(drop=True)
    run_dir = RUNS / args.run
    sel = json.loads((run_dir / 'selection.json').read_text())
    cv = json.loads((run_dir / 'cv_results.json').read_text())
    cands = candidates(False)
    edge, backend = sel['edge'], sel['backend']
    # Pre-declared configurations: the selected pair plus reference rows. None is chosen from these results.
    configs = [('mean', edge['train_on']), (edge['candidate'], edge['train_on']), (backend['candidate'], backend['train_on']),
               ('mean', 'cp_anemic'), ('hgb_cf', 'cp_anemic')]
    configs = list(dict.fromkeys(configs))
    test_sets = {ds: te_all[te_all.dataset == ds].reset_index(drop=True) for ds in ('eyes_defy_anemia', 'cp_anemic')}
    Xte = {ds: matrices(t, False)['cf'] for ds, t in test_sets.items()}
    report, preds, curves, fitted = {}, {}, {}, {}
    for name, train_on in configs:
        tr = tr_all[tr_all.dataset == train_on].reset_index(drop=True)
        X = matrices(tr, False)['cf'] if name != 'mean' else np.zeros((len(tr), 1))
        y = tr.hb_g_dl.to_numpy(float)
        make = cands[name][0]
        t0 = time.perf_counter()
        model = make().fit(X, y)
        key = f'{name}@{train_on}'
        fitted[key] = model
        report[key] = {'fit_seconds': time.perf_counter() - t0, 'n_train': int(len(tr)), 'test': {}}
        for ds, te in test_sets.items():
            Xt = Xte[ds] if name != 'mean' else np.zeros((len(te), 1))
            report[key]['test'][ds], preds[(key, ds)] = evaluate(f'{key} -> {ds}', model, Xt, te)
        if name != 'mean' and train_on == edge['train_on']:
            sizes, trs, vas = learning_curve(make(), X, y, groups=tr.group, cv=GroupKFold(5),
                                             train_sizes=np.linspace(.2, 1, 5), scoring='neg_mean_absolute_error')
            curves[key] = (sizes, -trs.mean(1), -vas.mean(1))
    te_plot = test_sets[edge['train_on']]
    plots(run_dir, curves, {k: p for (k, ds), p in preds.items() if ds == edge['train_on'] and not k.startswith('mean')}, te_plot)
    def train_info(train_on):
        Xtr = matrices(tr_all[tr_all.dataset == train_on].reset_index(drop=True), False)['cf']
        return {'dataset': train_on, 'n_train': int((tr_all.dataset == train_on).sum()),
                'feature_min': Xtr.min(0).tolist(), 'feature_max': Xtr.max(0).tolist(),
                'splits': ['ml/splits/eyes_defy_anemia_v1.json', 'ml/splits/cp_anemic_v1.json'], 'seed': SEED,
                'label': 'Measured hemoglobin, g/dL (Eyes-defy-anemia: laboratory Hgb per dataset documentation)'}

    artifacts = {}
    ek, bk = f"{edge['candidate']}@{edge['train_on']}", f"{backend['candidate']}@{backend['train_on']}"
    summary = lambda k: {ds: {m: report[k]['test'][ds]['overall'][m] for m in ('n', 'mae', 'rmse', 'r2', 'ci95')} for ds in test_sets}  # noqa: E731
    art = ridge_artifact(fitted[ek], F.FEATURE_NAMES, train_info(edge['train_on']), {'held_out_test': summary(ek)}, args.version)
    dump(MODELS / 'hb_ridge_cf_v1.json', art)
    artifacts['edge'] = {'path': 'models/hb_ridge_cf_v1.json', 'sha256': sha256_file(MODELS / 'hb_ridge_cf_v1.json')}
    from tree_export import export_hgb, predict_json
    art = export_hgb(fitted[bk], F.FEATURE_NAMES)
    parity = float(np.max(np.abs(predict_json(art, Xte['eyes_defy_anemia']) - fitted[bk].predict(Xte['eyes_defy_anemia']))))
    if parity > 1e-9:
        raise SystemExit(f'JSON tree export does not reproduce sklearn predictions (max diff {parity})')
    art.update({'model_id': 'hb-hgb-cf', 'version': args.version, 'biomarker': 'HEMOGLOBIN', 'output_unit': 'g/dL',
                'feature_version': F.FEATURE_VERSION, 'training': train_info(backend['train_on']),
                'evaluation': {'held_out_test': summary(bk)}, 'hyperparameters': HGB_PARAMS, 'validation_status': 'RESEARCH_ONLY',
                'intended_input': 'Expert-segmented palpebral conjunctiva crop (masked background)', 'json_export_max_abs_diff': parity})
    dump(MODELS / 'hb_hgb_cf_v1.json', art)
    artifacts['backend'] = {'path': 'models/hb_hgb_cf_v1.json', 'sha256': sha256_file(MODELS / 'hb_hgb_cf_v1.json')}
    dump(run_dir / 'final_results.json', {
        'stage': 'final', 'created_at': datetime.now(timezone.utc).isoformat(), 'seed': SEED, 'selection': sel,
        'cv_reference': {k: cv['results'][k] for k in (f"{edge['train_on']}/mean", f"{edge['train_on']}/{edge['candidate']}",
                                                        f"{backend['train_on']}/{backend['candidate']}")},
        'n_test': {ds: int(len(t)) for ds, t in test_sets.items()}, 'results': report, 'artifacts': artifacts,
        'environment': environment(),
    })
    print('wrote', run_dir / 'final_results.json', artifacts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', choices=['cv', 'final'], required=True)
    ap.add_argument('--run', default='hb-v1', help='run directory under ml/runs/ (final reads its selection.json)')
    ap.add_argument('--no-cnn', dest='cnn', action='store_false', help='skip the MobileNetV3 comparison')
    ap.add_argument('--version', default='1.0.0-research')
    args = ap.parse_args()
    stage_cv(args) if args.stage == 'cv' else stage_final(args)


if __name__ == '__main__':
    main()
