#!/usr/bin/env python3
"""Aggregate-only data-quality and evaluation audit of the shared anemia CSV.

Never prints or writes Name values, rows, or per-person predictions. Reproduces the research
Ridge metrics and adds the context needed to interpret them: a mean-predictor baseline,
shuffled K-fold variation, group uniqueness, and label/Hb consistency.

    pip install -r requirements-research.txt
    python scripts/audit_anemia_csv.py --csv /private/path/Anemia_Dataset.csv
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, KFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ['%Red Pixel', '%Green pixel', '%Blue pixel']
# WHO non-pregnant adult cut-offs, used only as a label-consistency probe (not a clinical rule here).
WHO_CUTOFF = {'M': 13.0, 'F': 12.0}


def audit(path: Path) -> dict:
    frame = pd.read_csv(path)
    frame.columns = [str(c).strip() for c in frame.columns]
    X = frame[FEATURES].apply(pd.to_numeric, errors='coerce')
    y = pd.to_numeric(frame['Hb'], errors='coerce')
    groups = frame['Name'].astype(str).str.strip().str.lower().to_numpy()  # in-memory only
    sex = frame['Sex'].astype(str).str.strip()
    label = frame['Anaemic'].astype(str).str.strip()
    cutoff = sex.map(WHO_CUTOFF)

    def evaluate(model, cv, use_groups=False) -> dict:
        pred = cross_val_predict(model, X, y, cv=cv, groups=groups if use_groups else None)
        return {'mae_g_dl': round(float(mean_absolute_error(y, pred)), 4),
                'rmse_g_dl': round(float(np.sqrt(mean_squared_error(y, pred))), 4), 'r2': round(float(r2_score(y, pred)), 4)}

    ridge = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    return {
        'rows': int(len(frame)), 'columns': list(frame.columns), 'missing_values': int(frame.isna().sum().sum()),
        'unique_subject_groups': int(len(set(groups))),
        'sex_counts': sex.value_counts().to_dict(), 'anaemic_label_counts': label.value_counts().to_dict(),
        'hb_g_dl': {k: round(float(v), 3) for k, v in y.describe().items()},
        'rgb_row_sum_range': [round(float(X.sum(axis=1).min()), 4), round(float(X.sum(axis=1).max()), 4)],
        'duplicate_feature_rows': int(X.duplicated().sum()),
        'label_consistency': {
            'labelled_yes_but_hb_at_or_above_who_cutoff': int(((label == 'Yes') & (y >= cutoff)).sum()),
            'labelled_no_but_hb_below_who_cutoff': int(((label == 'No') & (y < cutoff)).sum()),
            'hb_below_5_g_dl': int((y < 5).sum()),
        },
        'ridge_groupkfold5': evaluate(ridge, GroupKFold(5), use_groups=True),
        'mean_predictor_groupkfold5': evaluate(DummyRegressor(), GroupKFold(5), use_groups=True),
        'ridge_shuffled_kfold5_seeds_0_4': [evaluate(ridge, KFold(5, shuffle=True, random_state=s)) for s in range(5)],
        'identifiers_written': False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', type=Path, required=True)
    print(json.dumps(audit(parser.parse_args().csv), indent=2))


if __name__ == '__main__':
    main()
