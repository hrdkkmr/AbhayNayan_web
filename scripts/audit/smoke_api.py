"""Black-box smoke test of a running AbhayNayan server. Prints status codes and error codes only (no image data)."""
import io
import json
import sys
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

base = sys.argv[1]
njn_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
c = httpx.Client(base_url=base, timeout=30)


def png(arr, mode='RGB'):
    b = io.BytesIO(); Image.fromarray(arr.astype(np.uint8), mode).save(b, 'PNG'); return b.getvalue()


def jpeg(img, exif_orientation=None):
    b = io.BytesIO()
    kw = {}
    if exif_orientation:
        ex = Image.Exif(); ex[0x0112] = exif_orientation; kw['exif'] = ex.tobytes()
    img.save(b, 'JPEG', quality=95, **kw); return b.getvalue()


def show(label, r):
    try:
        body = r.json()
    except ValueError:
        body = {}
    err = body.get('error') or body
    code = err.get('code') if isinstance(err, dict) else None
    extra = {k: body.get(k) for k in ('status', 'provenance', 'estimate', 'unit', 'score', 'model_version', 'warnings') if k in body}
    issues = [f.get('message') for f in (err.get('fields') or [])] if isinstance(err, dict) else []
    print(f'{label:<46} HTTP {r.status_code}  code={code} {extra or ""} {issues or ""}')
    return body


rng = np.random.default_rng(0)
pink = np.clip(rng.normal([200, 110, 120], 12, (240, 320, 3)), 0, 255)
glare = np.full((240, 320, 3), 255)
flat = np.full((240, 320, 3), 150)

show('GET /api/health', c.get('/api/health'))
st = show('GET /api/ml/models', c.get('/api/ml/models'))
print('   models:', json.dumps({k: (v.get('status'), v.get('reason_code')) for k, v in st.get('models', {}).items()}))
show('POST screening MODEL anemia (no features)', c.post('/api/screenings', json={
    'screening_type': 'maternal_anemia', 'inference_mode': 'MODEL', 'patient': {'patient_id': 'P-SMOKE-1', 'demo': True}}))
show('POST screening MODEL jaundice', c.post('/api/screenings', json={
    'screening_type': 'neonatal_jaundice', 'inference_mode': 'MODEL', 'patient': {'patient_id': 'P-SMOKE-1', 'demo': True},
    'context': {'infant_age_hours': 48}}))
show('POST screening DEMO on real profile', c.post('/api/screenings', json={
    'screening_type': 'maternal_anemia', 'inference_mode': 'DEMO', 'case_id': 'maternal-normal',
    'patient': {'patient_id': 'P-SMOKE-2', 'demo': False}}))
show('POST screening malformed JSON', c.post('/api/screenings', content=b'{bad', headers={'content-type': 'application/json'}))
for ep in ('/api/ml/hemoglobin', '/api/ml/neonatal-jaundice-class'):
    h = {'content-type': 'image/png'}
    show(f'{ep} valid-looking PNG', c.post(ep, content=png(pink), headers=h))
    show(f'{ep} text/plain', c.post(ep, content=b'hello', headers={'content-type': 'text/plain'}))
    show(f'{ep} PNG declared, JPEG bytes', c.post(ep, content=jpeg(Image.fromarray(pink.astype(np.uint8))), headers=h))
    show(f'{ep} empty body', c.post(ep, content=b'', headers=h))
    show(f'{ep} 9 MB body', c.post(ep, content=b'\x89PNG\r\n\x1a\n' + b'0' * (9 * 1024 * 1024), headers=h))
    show(f'{ep} 16x16 image', c.post(ep, content=png(pink[:16, :16]), headers=h))
    show(f'{ep} truncated PNG', c.post(ep, content=png(pink)[:200], headers=h))
    show(f'{ep} all-white (glare)', c.post(ep, content=png(glare), headers=h))
    show(f'{ep} flat grey (blur)', c.post(ep, content=png(flat), headers=h))

if njn_dir:
    files = sorted(njn_dir.glob('*.jpg'))[:20]
    deltas, flips = [], 0
    for p in files:
        im = Image.open(p).convert('RGB')
        upright = c.post('/api/ml/neonatal-jaundice-class', content=jpeg(im), headers={'content-type': 'image/jpeg'}).json()
        # A phone JPEG stored sideways with EXIF orientation 6: pixels rotated, tag says "rotate 90 CW to display".
        sideways = c.post('/api/ml/neonatal-jaundice-class', content=jpeg(im.transpose(Image.Transpose.ROTATE_90), 6),
                          headers={'content-type': 'image/jpeg'}).json()
        if 'score' in upright and 'score' in sideways:
            deltas.append(abs(upright['score'] - sideways['score']))
            flips += upright['dataset_class_at_research_threshold'] != sideways['dataset_class_at_research_threshold']
    if deltas:
        print(f'EXIF-orientation probe (n={len(deltas)} NJN images, CNN): mean |score delta| {np.mean(deltas):.4f}, '
              f'max {np.max(deltas):.4f}, class changed {flips}/{len(deltas)}')
