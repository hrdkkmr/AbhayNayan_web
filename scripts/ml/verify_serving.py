"""End-to-end serving check on the held-out TEST images (no re-fitting, no selection).

1. Sends every test image through the FastAPI routes (TestClient, research flag on) and recomputes the
   test metrics from the served outputs; they must equal ml/runs/*/final_results.json.
2. Runs the edge-role artifacts on the same images and quantifies edge-vs-backend differences.
3. Measures model-load time, per-request latency, validation overhead and a concurrent-request burst.
Writes aggregate results to ml/runs/serving-v1/serving_report.json.

  .venv/Scripts/python scripts/ml/verify_serving.py
"""
from __future__ import annotations

import _threads  # noqa: F401  must precede numpy

import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from common import RUNS, environment, load_manifest, regression_metrics, binary_metrics

os.environ['ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS'] = '1'
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.ml import features as F, imageio, registry as R  # noqa: E402


def post(client, route: str, path: str) -> tuple[dict, float]:
    data = Path(path).read_bytes()
    ctype = 'image/png' if data.startswith(b'\x89PNG') else 'image/jpeg'
    t0 = time.perf_counter()
    r = client.post(route, content=data, headers={'Content-Type': ctype})
    return {**r.json(), 'http': r.status_code}, (time.perf_counter() - t0) * 1000


def pct(v: list[float]) -> dict:
    return {'n': len(v), 'median_ms': round(statistics.median(v), 2), 'p90_ms': round(float(np.percentile(v, 90)), 2),
            'max_ms': round(max(v), 2)}


def main() -> None:
    from sklearn.metrics import roc_auc_score
    reg = R.Registry()
    t0 = time.perf_counter()
    loaded = {m: reg.get(m) for m in ('hb-hgb-cf', 'hb-ridge-cf', 'njn-mnv3-logreg', 'njn-logreg-cf')}
    load_ms = {m: round(v.load_ms, 1) for m, v in loaded.items()}
    total_load_ms = (time.perf_counter() - t0) * 1000
    import app.main as main
    main.REGISTRY = reg
    report = {'environment': environment(), 'model_load_ms': load_ms, 'all_models_load_ms': round(total_load_ms, 1)}
    with TestClient(app) as client:
        post(client, '/api/ml/hemoglobin', load_manifest('hb_manifest.csv').path.iloc[0])  # warm-up, excluded
        # ---- Hb
        hb = load_manifest('hb_manifest.csv')
        hb = hb[(hb.split == 'test') & (hb.dataset == 'eyes_defy_anemia')].reset_index(drop=True)
        served, lat, edge, rejected = [], [], [], {}
        for p in hb.path:
            body, ms = post(client, '/api/ml/hemoglobin', p)
            if body['http'] != 200:
                rejected[body['error']['code']] = rejected.get(body['error']['code'], 0) + 1
                served.append(np.nan); edge.append(np.nan); continue
            served.append(body['estimate']); lat.append(ms)
            img = imageio.read_path(p)
            edge.append(loaded['hb-ridge-cf'].predict(img, F.extract(img)))
        y, s, e = hb.hb_g_dl.to_numpy(float), np.array(served), np.array(edge)
        ok = ~np.isnan(s)
        final = json.loads((RUNS / 'hb-v1' / 'final_results.json').read_text())['results']
        ref = final['hgb_cf@eyes_defy_anemia']['test']['eyes_defy_anemia']['overall']
        got = regression_metrics(y[ok], s[ok])
        report['hemoglobin'] = {
            'test_images': int(len(hb)), 'served_ok': int(ok.sum()), 'rejected_by_code': rejected,
            'served_metrics_rounded_0.1': got, 'training_side_metrics': {k: ref[k] for k in ('n', 'mae', 'rmse', 'r2')},
            'note': ('Served metrics cover only images that pass the serving quality gate and use estimates rounded to 0.1 g/dL; '
                     'the training-side evaluation covers every test image unrounded.'),
            'edge_metrics': regression_metrics(y[ok], e[ok]),
            'edge_vs_backend': {'mean_abs_diff_g_dl': float(np.abs(e[ok] - s[ok]).mean()), 'max_abs_diff_g_dl': float(np.abs(e[ok] - s[ok]).max()),
                                'pearson_r': float(np.corrcoef(e[ok], s[ok])[0, 1]), 'mean_diff_edge_minus_backend': float((e[ok] - s[ok]).mean()),
                                'screening_agreement_at_population_cutoff': float(np.mean(
                                    (e[ok] < hb.anemia_cutoff_g_dl.to_numpy()[ok]) == (s[ok] < hb.anemia_cutoff_g_dl.to_numpy()[ok])))},
            'request_latency': pct(lat)}
        # ---- NJN
        nj = load_manifest('njn_manifest.csv')
        nj = nj[nj.split == 'test'].reset_index(drop=True)
        served, lat, edge = [], [], []
        for p in nj.path:
            body, ms = post(client, '/api/ml/neonatal-jaundice-class', p)
            assert body['http'] == 200, body
            served.append(body['score']); lat.append(ms)
            img = imageio.read_path(p)
            edge.append(loaded['njn-logreg-cf'].predict(img, F.extract(img)))
        y, s, e = nj.jaundice_label.to_numpy(int), np.array(served), np.array(edge)
        t_b, t_e = loaded['njn-mnv3-logreg'].meta['operating_threshold'], loaded['njn-logreg-cf'].meta['operating_threshold']
        ref = json.loads((RUNS / 'njn-v1' / 'final_results.json').read_text())['results']
        report['neonatal_jaundice_class'] = {
            'test_images': int(len(nj)), 'served_auroc': float(roc_auc_score(y, s)), 'training_side_auroc': ref['logreg_mnv3']['auroc'],
            'served_at_threshold': binary_metrics(y, (s >= t_b).astype(int)), 'edge_auroc': float(roc_auc_score(y, e)),
            'edge_at_threshold': binary_metrics(y, (e >= t_e).astype(int)),
            'edge_vs_backend': {'class_agreement': float(np.mean((s >= t_b) == (e >= t_e))), 'score_spearman':
                                float(np.corrcoef(np.argsort(np.argsort(s)), np.argsort(np.argsort(e)))[0, 1])},
            'request_latency': pct(lat)}
        # ---- validation overhead and concurrency
        bad = []
        for _ in range(50):
            t = time.perf_counter()
            client.post('/api/ml/hemoglobin', content=b'not an image', headers={'Content-Type': 'image/png'})
            bad.append((time.perf_counter() - t) * 1000)
        report['rejected_request_latency'] = pct(bad)
        paths = list(nj.path[:40])
        t = time.perf_counter()
        with ThreadPoolExecutor(8) as ex:
            results = list(ex.map(lambda p: post(client, '/api/ml/neonatal-jaundice-class', p), paths))
        wall = (time.perf_counter() - t) * 1000
        report['concurrency_njn_8_workers'] = {'requests': len(paths), 'all_200': all(r[0]['http'] == 200 for r in results),
                                               'wall_ms': round(wall, 1), 'throughput_rps': round(len(paths) / wall * 1000, 2),
                                               'scores_identical_to_sequential': bool(np.allclose([r[0]['score'] for r in results], s[:40]))}
    try:
        import psutil
        report['process_rss_mb'] = round(psutil.Process().memory_info().rss / 2 ** 20, 1)
    except ImportError:
        report['process_rss_mb'] = None
    out = RUNS / 'serving-v1' / 'serving_report.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=float), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'environment'}, indent=1, default=float))


if __name__ == '__main__':
    main()
