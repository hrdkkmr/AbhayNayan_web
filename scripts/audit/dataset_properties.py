"""Read-only, aggregate-only dataset property audit. Prints no rows, names or pixels."""
import collections
import hashlib
import sys
from pathlib import Path

import pandas as pd
from PIL import Image

root = Path(sys.argv[1])          # Programming/AbhayNayan
web = Path(sys.argv[2])           # AbhayNayan_web

sets = {
    'eyes_defy_full_eye_jpg': list((root / 'archive/dataset anemia').rglob('*.jpg')),
    'eyes_defy_png': list((root / 'archive/dataset anemia').rglob('*.png')),
    'cp_anemic_png': list((root / 'datasets_extracted/cp_anemic').rglob('*.png')),
    'njn_jpg': list((root / 'datasets_extracted/njn').rglob('*.jpg')),
    'neonatal_forehead_sternum_jpg': list(root.glob('Neonatal Jaundice Assessment*/*/*/*.jpg')),
}
for name, files in sets.items():
    modes, sizes, orient, icc, errs = collections.Counter(), collections.Counter(), collections.Counter(), 0, 0
    for p in files:
        try:
            with Image.open(p) as im:
                modes[im.mode] += 1
                sizes[im.size] += 1
                o = im.getexif().get(0x0112) if hasattr(im, 'getexif') else None
                orient[o] += 1
                icc += 'icc_profile' in im.info
        except Exception:
            errs += 1
    print(f'{name}: n={len(files)} modes={dict(modes)} top_sizes={sizes.most_common(3)} distinct_sizes={len(sizes)} '
          f'exif_orientation={dict(orient)} icc_profile={icc} pillow_errors={errs}')

def sheet(path, **kw):
    df = pd.read_excel(path, **kw)
    return df

for label, path in [('India.xlsx', root / 'archive/dataset anemia/India/India.xlsx'),
                    ('Italy.xlsx', root / 'archive/dataset anemia/Italy/Italy.xlsx'),
                    ('CP-AnemiC sheet', root / 'datasets_extracted/cp_anemic/Anemia_Data_Collection_Sheet.xlsx')]:
    df = sheet(path)
    hb_col = next((c for c in df.columns if str(c).strip().lower() in {'hgb', 'hb_level'}), None)
    hb = pd.to_numeric(df[hb_col].astype(str).str.replace(',', '.'), errors='coerce') if hb_col else None
    print(f'{label}: rows={len(df)} columns={[str(c) for c in df.columns]}'
          + (f' {hb_col}: n_numeric={int(hb.notna().sum())} min={hb.min():.1f} max={hb.max():.1f}' if hb is not None else ''))

csv = pd.read_csv(root / 'Anemia_Dataset.csv')
print(f'Anemia_Dataset.csv: rows={len(csv)} columns={[c.strip() for c in csv.columns]} Hb range={csv["Hb"].min()}-{csv["Hb"].max()}')
tr = pd.read_csv(root / 'datasets_extracted/njn/Pythons_Code_AI_Testing_Data/Excel File/train.csv')
print(f'NJN train.csv: rows={len(tr)} columns={list(tr.columns)}')

contract = hashlib.sha256((web / 'backend/app/ml/features.py').read_bytes()).hexdigest()[:12]
cached = sorted(p.name for p in (web / 'data/private').glob('*cf-v1_*.csv'))
print('features.py contract hash now:', contract, '| cached feature files:', cached)
