"""Build cleaned manifests and fixed train/test splits for the labelled image datasets.

Outputs
  <out>/hb_manifest.csv, <out>/njn_manifest.csv   per-image labels and paths (PRIVATE: default data/private/, gitignored)
  ml/splits/*.json                                  split definitions with image IDs only (no labels)
  stdout                                            aggregate counts only

Usage
  python scripts/ml/prepare_datasets.py --data-root ../ --extracted-root ../datasets_extracted

Exclusion rules (applied before any model is fitted):
  CP-AnemiC  byte-identical images assigned to different children (conflicting Hb/hospital/age) -> every member dropped;
             perceptual near-duplicates (dHash distance <= 4 of 256 bits) -> every member dropped (owner unknown);
             dHash distance <= 8 -> same split group so near-copies cannot straddle train/test.
  Eyes-defy  rows without a numeric Hb, rows marked ELIMINATO, folders without a palpebral segmentation.
  NJN        exact duplicates: one copy kept when the class agrees, all dropped when it conflicts;
             dHash <= 8 -> same split group.
"""
from __future__ import annotations

import _threads  # noqa: F401  must precede numpy

import argparse
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.ml.imageio import read_path  # noqa: E402

SEED = 20261022
CP_TEST_HOSPITALS = ('Bolgatanga Regional Hospital', 'Kintampo Municipal Hospital', 'Manhyia District Hospital')
NEAR_DUP_DROP = 4
NEAR_DUP_GROUP = 8  # 24 chained transitively across hospitals on similarly shaped conjunctiva crops
TEST_FRACTION = 0.25


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dhash(path: Path, size: int = 16) -> np.ndarray:
    img = read_path(path)
    rgb = img[..., :3].astype(np.float32)
    if img.shape[2] == 4:  # composite masked images on black so the mask outline is part of the hash
        rgb *= (img[..., 3:4] >= 128)
    gray = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    return (small[:, 1:] > small[:, :-1]).ravel()


def components(hashes: np.ndarray, threshold: int) -> list[int]:
    n = len(hashes)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    dist = (hashes[:, None, :] != hashes[None, :, :]).sum(-1)
    for i, j in zip(*np.where(np.triu(dist <= threshold, 1))):
        parent[find(i)] = find(j)
    return [find(i) for i in range(n)]


def strip_all(df: pd.DataFrame) -> pd.DataFrame:
    return df.apply(lambda c: c.str.strip() if c.dtype == object or str(c.dtype) in ('str', 'string') else c)


def prepare_cp(root: Path) -> pd.DataFrame:
    df = strip_all(pd.read_excel(root / 'Anemia_Data_Collection_Sheet.xlsx'))
    paths = {p.stem: p for d in ('Anemic', 'Non-anemic') for p in (root / d).glob('*.png')}
    assert set(paths) == set(df.IMAGE_ID), 'image files and label sheet do not match one to one'
    df['path'] = df.IMAGE_ID.map(lambda i: str(paths[i]))
    df['sha256'] = df.path.map(lambda p: sha256(Path(p)))
    sizes = df.groupby('sha256').IMAGE_ID.transform('size')
    df['exclusion'] = np.where(sizes > 1, 'exact_duplicate_conflicting_labels', '')
    keep = df[df.exclusion == ''].copy()
    hashes = np.array([dhash(Path(p)) for p in keep.path])
    drop_comp = components(hashes, NEAR_DUP_DROP)
    counts = pd.Series(drop_comp).value_counts()
    near = [counts[c] > 1 for c in drop_comp]
    df.loc[keep.index[near], 'exclusion'] = 'near_duplicate_image'
    keep['group'] = [f'cp-g{c}' for c in components(hashes, NEAR_DUP_GROUP)]
    df['group'] = keep['group']
    df['dataset'] = 'cp_anemic'
    df['image_id'] = 'cp:' + df.IMAGE_ID
    df['hb_g_dl'] = df.HB_LEVEL.astype(float)
    df['site'] = df.HOSPITAL
    df['sex'] = df.GENDER.str.upper().str[0]
    df['age_years'] = df['Age(Months)'] / 12.0
    # WHO (2011) cut-off for children 6-59 months, as encoded by the dataset's own REMARK column.
    df['anemia_cutoff_g_dl'] = 11.0
    df['anemic_label'] = (df.REMARK == 'Anemic').astype(int)
    df['split'] = np.where(df.site.isin(CP_TEST_HOSPITALS), 'test', 'train')
    df['population'] = 'children_6_60_months_ghana'
    # Group IDs that touch a test hospital are forced to test so near-copies never straddle the split.
    test_groups = set(df.loc[(df.split == 'test') & (df.exclusion == ''), 'group'])
    df.loc[df.group.isin(test_groups) & (df.exclusion == ''), 'split'] = 'test'
    return df


PALPEBRAL = re.compile(r'_(palpebral|papebral|palplebral)\.png$', re.I)


def prepare_eda(root: Path) -> pd.DataFrame:
    rows = []
    for country in ('India', 'Italy'):
        sheet = pd.read_excel(root / country / f'{country}.xlsx')
        eliminated = sheet.apply(lambda r: any(str(v).strip().upper() == 'ELIMINATO' for v in r.values), axis=1)
        for _, r in sheet.iterrows():
            number = int(r.Number)
            folder = root / country / str(number)
            hb = pd.to_numeric(str(r.Hgb).replace(',', '.').strip(), errors='coerce')
            pics = sorted(p for p in folder.glob('*.png') if PALPEBRAL.search(p.name) and 'forn' not in p.name.lower()) if folder.is_dir() else []
            exclusion = ''
            if eliminated[_]:
                exclusion = 'marked_eliminato'
            elif not np.isfinite(hb):
                exclusion = 'hb_missing'
            elif not pics:
                exclusion = 'no_palpebral_segmentation'
            sex = str(r.Gender).strip().upper()[:1]
            rows.append({
                'dataset': 'eyes_defy_anemia', 'image_id': f'eda:{country}:{number}', 'path': str(pics[0]) if pics else '',
                'hb_g_dl': float(hb) if np.isfinite(hb) else np.nan, 'site': country, 'sex': sex,
                'age_years': float(r.Age), 'group': f'eda-{country}-{number}', 'exclusion': exclusion,
                'population': f'adults_{country.lower()}',
                # WHO (2011) non-pregnant adult cut-offs by sex; pregnancy status is not recorded in this dataset.
                'anemia_cutoff_g_dl': 13.0 if sex == 'M' else 12.0,
            })
    df = pd.DataFrame(rows)
    df['anemic_label'] = (df.hb_g_dl < df.anemia_cutoff_g_dl).astype(int)
    rng = random.Random(SEED)
    df['split'] = 'train'
    for country in ('India', 'Italy'):
        ids = sorted(df.loc[(df.site == country) & (df.exclusion == ''), 'image_id'])
        rng.shuffle(ids)
        df.loc[df.image_id.isin(ids[:round(len(ids) * TEST_FRACTION)]), 'split'] = 'test'
    ok = df[df.exclusion == '']
    dup = ok.path.map(lambda p: sha256(Path(p))).duplicated(keep=False)
    df.loc[ok.index[dup.values], 'exclusion'] = 'exact_duplicate_image'
    return df


def prepare_njn(root: Path) -> pd.DataFrame:
    rows = []
    for cls, label in (('normal', 0), ('jaundice', 1)):
        for p in sorted((root / cls).glob('*.jpg')):
            rows.append({'dataset': 'njn', 'image_id': f'njn:{cls}:{p.stem}', 'path': str(p), 'jaundice_label': label})
    df = pd.DataFrame(rows)
    df['sha256'] = df.path.map(lambda p: sha256(Path(p)))
    df['exclusion'] = ''
    for _, g in df.groupby('sha256'):
        if len(g) > 1:
            if g.jaundice_label.nunique() > 1:
                df.loc[g.index, 'exclusion'] = 'exact_duplicate_conflicting_labels'
            else:
                df.loc[g.index[1:], 'exclusion'] = 'exact_duplicate'
    keep = df[df.exclusion == '']
    hashes = np.array([dhash(Path(p)) for p in keep.path])
    df.loc[keep.index, 'group'] = [f'njn-g{c}' for c in components(hashes, NEAR_DUP_GROUP)]
    conflicting = df.loc[keep.index].groupby('group').jaundice_label.transform('nunique') > 1
    df.loc[conflicting[conflicting].index, 'exclusion'] = 'near_duplicate_conflicting_labels'
    # Group-stratified split: whole groups go to test until each class reaches TEST_FRACTION.
    rng = random.Random(SEED)
    df['split'] = 'train'
    ok = df[df.exclusion == '']
    for label in (0, 1):
        groups = sorted(ok.loc[ok.jaundice_label == label, 'group'].unique())
        rng.shuffle(groups)
        target, taken = round((ok.jaundice_label == label).sum() * TEST_FRACTION), 0
        for g in groups:
            if taken >= target:
                break
            members = ok.group == g
            df.loc[ok.index[members.values], 'split'] = 'test'
            taken += int(members.sum())
    return df


def write_split(df: pd.DataFrame, name: str, note: str) -> None:
    ok = df[df.exclusion == '']
    payload = {
        'name': name, 'seed': SEED, 'note': note,
        'train': sorted(ok.loc[ok.split == 'train', 'image_id']),
        'test': sorted(ok.loc[ok.split == 'test', 'image_id']),
        'excluded': {k: sorted(v.image_id) for k, v in df[df.exclusion != ''].groupby('exclusion')},
    }
    (ROOT / 'ml' / 'splits' / f'{name}.json').write_text(json.dumps(payload, indent=1), encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-root', type=Path, required=True, help='folder holding archive/ (Eyes-defy-anemia)')
    ap.add_argument('--extracted-root', type=Path, required=True, help='folder holding cp_anemic/ and njn/')
    ap.add_argument('--out', type=Path, default=ROOT / 'data' / 'private')
    a = ap.parse_args()
    a.data_root, a.extracted_root = a.data_root.resolve(), a.extracted_root.resolve()  # manifests hold absolute paths
    a.out.mkdir(parents=True, exist_ok=True)

    cp = prepare_cp(a.extracted_root / 'cp_anemic')
    eda = prepare_eda(a.data_root / 'archive' / 'dataset anemia')
    cols = ['dataset', 'image_id', 'path', 'hb_g_dl', 'site', 'sex', 'age_years', 'group', 'split', 'exclusion',
            'population', 'anemia_cutoff_g_dl', 'anemic_label']
    hb = pd.concat([cp[cols], eda[cols]], ignore_index=True)
    hb.to_csv(a.out / 'hb_manifest.csv', index=False)
    write_split(cp, 'cp_anemic_v1', 'Site-level test: hospitals ' + ', '.join(CP_TEST_HOSPITALS) + '. Near-duplicate groups forced to test.')
    write_split(eda, 'eyes_defy_anemia_v1', 'Patient-level 75/25 random split per country (one palpebral image per patient).')

    njn = prepare_njn(a.extracted_root / 'njn')
    njn.to_csv(a.out / 'njn_manifest.csv', index=False)
    write_split(njn, 'njn_v1', 'No patient IDs exist. Group-stratified 75/25 split over perceptual-hash groups (dHash<=8).')

    for name, df, lab in (('Hb', hb, 'anemic_label'), ('NJN', njn, 'jaundice_label')):
        print(f'== {name}: rows={len(df)}')
        print(' exclusions:', df.exclusion.replace('', 'kept').value_counts().to_dict())
        ok = df[df.exclusion == '']
        by = ['dataset', 'split'] if 'dataset' in ok and ok.dataset.nunique() > 1 else ['split']
        print(ok.groupby(by).agg(n=(lab, 'size'), positive_rate=(lab, 'mean'), groups=('group', 'nunique')).round(3).to_string())
        if name == 'Hb':
            print(ok.groupby(['dataset', 'split']).hb_g_dl.describe()[['mean', 'std', 'min', 'max']].round(2).to_string())


if __name__ == '__main__':
    main()
