#!/usr/bin/env python3
"""Train a research-only RGB baseline from the supplied anemia CSV.

The direct-identifier Name column is used only as a temporary GroupKFold key and
is dropped before model fitting/output. No rows, names, or per-person predictions
are written. This small exploratory baseline must never drive clinical care.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ['red_pct', 'green_pct', 'blue_pct']


def load_deidentified(path: Path) -> tuple[pd.DataFrame, np.ndarray]:
    frame = pd.read_csv(path)
    by_lower = {str(c).strip().lower(): c for c in frame.columns}
    name_col = next((c for c in frame.columns if str(c).strip().lower() in {'name', 'patient', 'patient_name', 'subject_id'}), None)
    if name_col is None:
        raise ValueError('A subject/group ID column is required for grouped validation; none found.')
    red_col = next((c for c in frame.columns if 'red' in str(c).lower() and 'pixel' in str(c).lower()), None)
    green_col = next((c for c in frame.columns if 'green' in str(c).lower() and 'pixel' in str(c).lower()), None)
    blue_col = next((c for c in frame.columns if 'blue' in str(c).lower() and 'pixel' in str(c).lower()), None)
    hb_col = next((c for c in frame.columns if str(c).strip().lower() in {'hb', 'hgb', 'hemoglobin', 'haemoglobin'}), None)
    if not all([red_col, green_col, blue_col, hb_col]):
        raise ValueError('Expected three RGB-percentage columns and an Hb/Hgb target.')
    groups = frame[name_col].astype(str).to_numpy(copy=True)  # in-memory split key only
    out = pd.DataFrame({
        'red_pct': pd.to_numeric(frame[red_col], errors='coerce'),
        'green_pct': pd.to_numeric(frame[green_col], errors='coerce'),
        'blue_pct': pd.to_numeric(frame[blue_col], errors='coerce'),
        'hb_g_dl': pd.to_numeric(frame[hb_col], errors='coerce'),
    }).replace([np.inf, -np.inf], np.nan).dropna()
    # Align group IDs after dropping invalid rows, without retaining identifier columns.
    valid_mask = pd.DataFrame({
        'red': pd.to_numeric(frame[red_col], errors='coerce'),
        'green': pd.to_numeric(frame[green_col], errors='coerce'),
        'blue': pd.to_numeric(frame[blue_col], errors='coerce'),
        'hb': pd.to_numeric(frame[hb_col], errors='coerce'),
    }).replace([np.inf, -np.inf], np.nan).notna().all(axis=1).to_numpy()
    groups = groups[valid_mask]
    if len(out) < 20 or len(np.unique(groups)) < 5:
        raise ValueError('At least 20 valid rows and 5 subject groups are required for exploratory CV.')
    return out.reset_index(drop=True), groups


def train(input_csv: Path, output_json: Path) -> dict:
    deidentified, groups = load_deidentified(input_csv)
    X = deidentified[FEATURES]
    y = deidentified['hb_g_dl'].to_numpy(dtype=float)
    n_splits = min(5, len(np.unique(groups)))
    cv = GroupKFold(n_splits=n_splits)
    model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    pred = cross_val_predict(model, X, y, groups=groups, cv=cv)
    metrics = {
        'n': int(len(y)), 'unique_subject_groups': int(len(np.unique(groups))),
        'folds': n_splits, 'mae_g_dl': round(float(mean_absolute_error(y, pred)), 4),
        'rmse_g_dl': round(float(np.sqrt(mean_squared_error(y, pred))), 4),
        'r2': round(float(r2_score(y, pred)), 4),
        'validation': 'GroupKFold by subject ID; exploratory internal CV only; not external validation',
    }
    model.fit(X, y)
    scaler = model.named_steps['standardscaler']
    reg = model.named_steps['ridge']
    artifact = {
        'artifact_type': 'RESEARCH_ONLY_COLOR_BASELINE',
        'version': '0.1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'features': FEATURES, 'mean': [float(x) for x in scaler.mean_],
        'scale': [float(x) for x in scaler.scale_], 'coefficients_scaled': [float(x) for x in reg.coef_],
        'intercept': float(reg.intercept_), 'unit': 'g/dL', 'metrics': metrics,
        'source_dataset': 'User-shared Anemia_Dataset.csv; 104-row feature/label file; raw dataset excluded',
        'identifier_handling': 'Name/group ID used only transiently for grouped split; not stored in this artifact.',
        'limitations': [
            'Small single-source dataset; no external validation or prospective evaluation.',
            'MAE is too large for patient-level decision making; do not use for screening, diagnosis, treatment, or referral decisions.',
            'Color-percentage features may be device/lighting dependent and may not match new camera images.',
            'Provenance, license, consent, and population representativeness require confirmation.',
        ],
        'enabled_by_default': False,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(artifact, indent=2), encoding='utf-8')
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', type=Path, required=True, help='Local path to a permitted copy of Anemia_Dataset.csv')
    parser.add_argument('--out', type=Path, default=Path('models/anemia_color_baseline.json'))
    args = parser.parse_args()
    artifact = train(args.csv, args.out)
    print(json.dumps({'output': str(args.out), 'metrics': artifact['metrics'], 'identifiers_written': False}, indent=2))


if __name__ == '__main__':
    main()
