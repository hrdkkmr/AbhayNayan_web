"""Train/inference input-mismatch probe on the held-out Eyes-defy test patients. Aggregate output only.

A: the expert-segmented palpebral PNG the models were trained on (the manifest path).
B: the full-eye JPEG of the same patient, EXIF-transposed (an upright photo, as a phone frame would be),
   cropped with the Android manual guide NormalizedRect(.14, .34, .86, .66).
Both go through the served pipeline (quality gate -> cf-v1 -> hb-hgb-cf / hb-ridge-cf).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageOps

web = Path(sys.argv[1])
sys.path.insert(0, str(web / 'backend'))
from app.ml import features as F, quality as Q  # noqa: E402
from app.ml.imageio import read_path  # noqa: E402
from app.ml.registry import Registry  # noqa: E402

reg = Registry(web / 'models')
models = {m: reg.get(m) for m in ('hb-hgb-cf', 'hb-ridge-cf')}
man = pd.read_csv(web / 'data/private/hb_manifest.csv')
test = man[(man.dataset == 'eyes_defy_anemia') & (man.split == 'test') & man.exclusion.isna()]
rows = []
for r in test.itertuples():
    seg = read_path(r.path)
    folder = Path(r.path).parent
    jpgs = list(folder.glob('*.jpg'))
    if not jpgs:
        continue
    full = np.asarray(ImageOps.exif_transpose(Image.open(jpgs[0])).convert('RGB'))
    h, w = full.shape[:2]
    crop = full[int(.34 * h):int(.66 * h), int(.14 * w):int(.86 * w)]
    for variant, img in (('A_segmented', seg), ('B_guide_crop', crop)):
        q = Q.assess(img)
        try:
            fr = F.extract(img)
        except F.FeatureError:
            rows.append({'variant': variant, 'gate': q.passed, 'ok': False}); continue
        rec = {'variant': variant, 'gate': q.passed, 'ok': True, 'hb': r.hb_g_dl}
        for mid, m in models.items():
            rec[mid] = m.predict(img, fr)
            rec[mid + '_ood'] = bool(m.out_of_range_features(fr.vector))
        rows.append(rec)
df = pd.DataFrame(rows)
for variant, g in df.groupby('variant'):
    ok = g[g.ok]
    line = f'{variant}: n={len(g)} gate_pass={int(g.gate.sum())}'
    for mid in models:
        err = ok[mid] - ok.hb
        ss = ((ok.hb - ok.hb.mean()) ** 2).sum()
        line += (f' | {mid}: MAE {err.abs().mean():.2f} bias {err.mean():+.2f} R2 {1 - (err ** 2).sum() / ss:.2f}'
                 f' OOD-flagged {int(ok[mid + "_ood"].sum())}/{len(ok)}')
    print(line)
print('(all images scored, including gate failures; the served API would refuse gate failures)')
