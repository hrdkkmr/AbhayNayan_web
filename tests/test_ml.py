"""Research image-model pipeline: decoding, quality gate, cf-v1 features, artifact registry and /api/ml routes.

Unit tests use synthetic images and small synthetic artifacts written to a temp dir (mocked models are
named `fake_*`). Tests marked `real_artifact` run the trained artifacts and are skipped when those
files are absent (they are not committed; see docs/ml_integration.md).
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.ml import features as F, imageio, quality as Q, registry as R
from app.models.schemas import API_CONTRACT_VERSION
from app.services import gemini, store
from conftest import research_token_headers

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / 'tests' / 'fixtures' / 'ml_golden'
GOLDEN = json.loads((GOLDEN_DIR / 'golden_cf_v1.json').read_text(encoding='utf-8'))
REAL_ARTIFACTS = all((ROOT / 'models' / f).exists() for m in json.loads((ROOT / 'models' / 'MODEL_REGISTRY.json').read_text())['models'].values()
                     for f in m['files'])
real_artifact = pytest.mark.skipif(not REAL_ARTIFACTS, reason='trained artifacts are not present (not committed)')


def png_bytes(img: np.ndarray) -> bytes:
    bgr = cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA if img.shape[2] == 4 else cv2.COLOR_RGB2BGR)
    return cv2.imencode('.png', bgr)[1].tobytes()


def golden_png(name: str) -> bytes:
    return (GOLDEN_DIR / f'{name}.png').read_bytes()


def conjunctiva_like(h=60, w=120, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    rgb = np.clip(rng.normal((200, 110, 115), 15, (h, w, 3)), 0, 255).astype(np.uint8)
    alpha = np.zeros((h, w), np.uint8)
    alpha[10:50, 15:105] = 255
    return np.dstack([rgb, alpha])


# ----- fake artifacts ---------------------------------------------------------------------------

def write_registry(tmp: Path, entries: dict[str, dict]) -> Path:
    models = {}
    for model_id, e in entries.items():
        for name, content in e['contents'].items():
            (tmp / name).write_bytes(content if isinstance(content, bytes) else json.dumps(content).encode())
        models[model_id] = {'task': e['task'], 'role': 'backend', 'files': list(e['contents']),
                            'sha256': {n: hashlib.sha256((tmp / n).read_bytes()).hexdigest() for n in e['contents']}}
    (tmp / 'MODEL_REGISTRY.json').write_text(json.dumps({'schema_version': 1, 'models': models}))
    return tmp


def fake_linear(intercept=12.0, logistic=False, **over) -> dict:
    n = len(F.FEATURE_NAMES)
    art = {'artifact_type': 'LOGISTIC_COLOUR_CLASSIFIER' if logistic else 'LINEAR_COLOUR_REGRESSOR', 'version': 'fake-1',
           'feature_version': F.FEATURE_VERSION, 'feature_names': list(F.FEATURE_NAMES), 'mean': [0.5] * n, 'scale': [1.0] * n,
           'coefficients': [0.0] * n, 'intercept': intercept, 'validation_status': 'RESEARCH_ONLY', 'operating_threshold': 0.5,
           'training': {'feature_min': [0.0] * n, 'feature_max': [1e6] * n}}
    art.update(over)
    return art


@pytest.fixture
def fake_registry(tmp_path, monkeypatch):
    """Point the served models at fake artifacts: Hb returns `intercept`, NJN returns sigmoid(intercept)."""
    def install(hb=None, njn=None):
        entries = {'hb-hgb-cf': {'task': 'hemoglobin', 'contents': {'hb.json': hb if hb is not None else fake_linear(12.0)}},
                   'njn-mnv3-logreg': {'task': 'neonatal_jaundice_class',
                                       'contents': {'njn.json': njn if njn is not None else fake_linear(0.0, logistic=True)}}}
        reg = R.Registry(write_registry(tmp_path, entries))
        monkeypatch.setattr(R, 'REGISTRY', reg)
        import app.main as main
        monkeypatch.setattr(main, 'REGISTRY', reg)
        return reg
    return install


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Authenticated as a research operator: these tests cover behaviour behind authentication (test_security.py covers the rest)."""
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(gemini, 'API_KEY', '')
    headers = research_token_headers(monkeypatch)
    with TestClient(app) as c:
        c.headers.update(headers)
        yield c


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv(R.IMAGE_MODELS_FLAG, '1')


# ----- features: contract and golden vectors ------------------------------------------------------

def test_feature_vector_shape_and_names():
    fr = F.extract(conjunctiva_like())
    assert fr.vector.shape == (len(F.FEATURE_NAMES),) == (25,)
    assert np.all(np.isfinite(fr.vector))
    assert fr.valid_pixels == 40 * 90 and fr.step == 1


@pytest.mark.parametrize('case', [c for c in GOLDEN['cases'] if 'features' in c], ids=lambda c: c['name'])
def test_golden_features_match(case):
    img = imageio.read_path(GOLDEN_DIR / case['file'])
    fr = F.extract(img)
    assert fr.step == case['step'] and fr.valid_pixels == case['valid_pixels']
    assert np.allclose(fr.vector, case['features'], atol=GOLDEN['tolerance']['features_abs'], rtol=0)


def test_golden_dark_image_rejected():
    case = next(c for c in GOLDEN['cases'] if c['name'] == 'too_dark_rgb')
    with pytest.raises(F.FeatureError):
        F.extract(imageio.read_path(GOLDEN_DIR / case['file']))


def test_masked_background_is_ignored():
    img = conjunctiva_like()
    noisy = img.copy()
    noisy[..., :3][img[..., 3] == 0] = (0, 255, 0)  # bright green behind the mask must not change features
    assert np.array_equal(F.extract(img).vector, F.extract(noisy).vector)


def test_features_are_orientation_invariant_means():
    img = conjunctiva_like()
    a, b = F.extract(img).as_dict(), F.extract(np.ascontiguousarray(img[::-1, ::-1])).as_dict()
    assert math.isclose(a['mean_r'], b['mean_r'], abs_tol=1e-12) and math.isclose(a['lab_a'], b['lab_a'], abs_tol=1e-9)


def test_lab_conversion_reference_points():
    lab = F.rgb_to_lab(np.array([[1.0, 1.0, 1.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]))
    assert np.allclose(lab[0], [100, 0, 0], atol=0.01)
    assert np.allclose(lab[1], [0, 0, 0], atol=1e-9)
    assert np.allclose(lab[2], [53.24, 80.09, 67.20], atol=0.05)  # sRGB red, D65


def test_feature_input_validation():
    with pytest.raises(F.FeatureError):
        F.extract(np.zeros((10, 10), np.uint8))
    with pytest.raises(F.FeatureError):
        F.extract(np.zeros((10, 10, 3), np.float32))


# ----- decoding ---------------------------------------------------------------------------------

def test_decode_png_keeps_alpha_and_rgb_order():
    img = conjunctiva_like()
    out = imageio.decode(png_bytes(img), 'image/png')
    assert out.shape == img.shape and np.array_equal(out, img)


def test_decode_jpeg():
    rgb = conjunctiva_like()[..., :3].copy()
    data = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))[1].tobytes()
    assert imageio.header_dimensions(data, 'jpeg') == (120, 60)
    assert imageio.decode(data, 'image/jpeg').shape == (60, 120, 3)


@pytest.mark.parametrize('data,ctype,code', [
    (b'', 'image/png', 'EMPTY_IMAGE'),
    (b'GIF89a....', 'image/gif', 'UNSUPPORTED_MEDIA_TYPE'),
    (b'not an image at all', 'image/png', 'UNSUPPORTED_MEDIA_TYPE'),
    (b'\x89PNG\r\n\x1a\n' + b'\x00' * 40, 'image/png', 'CORRUPT_IMAGE'),
])
def test_decode_rejects_bad_input(data, ctype, code):
    with pytest.raises(imageio.ImageInputError) as e:
        imageio.decode(data, ctype)
    assert e.value.code == code


def test_decode_rejects_mismatched_type_tiny_huge_and_truncated():
    png = png_bytes(conjunctiva_like())
    with pytest.raises(imageio.ImageInputError, match='matching'):
        imageio.decode(png, 'image/jpeg')
    with pytest.raises(imageio.ImageInputError) as e:
        imageio.decode(png_bytes(np.zeros((8, 8, 3), np.uint8)), 'image/png')
    assert e.value.code == 'IMAGE_TOO_SMALL'
    huge = bytearray(png)
    huge[16:24] = struct.pack('>II', 20000, 20000)  # header claims 400 MP: rejected before decoding
    with pytest.raises(imageio.ImageInputError) as e:
        imageio.decode(bytes(huge), 'image/png')
    assert e.value.code == 'IMAGE_TOO_LARGE' and e.value.status == 413
    with pytest.raises(imageio.ImageInputError) as e:
        imageio.decode(png[:60], 'image/png')
    assert e.value.code == 'CORRUPT_IMAGE'
    with pytest.raises(imageio.ImageInputError) as e:
        imageio.decode(b'\x89PNG\r\n\x1a\n' + b'0' * (imageio.MAX_BYTES + 1), 'image/png')
    assert e.value.status == 413


def test_decode_tolerates_bad_iccp_crc():
    """Eyes-defy-anemia PNGs carry an iCCP chunk with a bad CRC; they must still decode."""
    png = png_bytes(conjunctiva_like())
    body = b'sRGB\x00\x00' + zlib.compress(b'x' * 64)
    chunk = struct.pack('>I', len(body)) + b'iCCP' + body + b'\x00\x00\x00\x00'  # wrong CRC on purpose
    broken = png[:33] + chunk + png[33:]
    assert imageio.decode(broken, 'image/png').shape == (60, 120, 4)


# ----- quality gate (separate from prediction) --------------------------------------------------

def test_quality_passes_reasonable_image_and_rejects_bad_ones():
    assert Q.assess(conjunctiva_like()).passed
    flat = np.full((64, 64, 3), 128, np.uint8)
    assert 'BLURRED_OR_FLAT' in Q.assess(flat).issues
    dark = np.full((64, 64, 3), 5, np.uint8)
    assert 'TOO_FEW_USABLE_PIXELS' in Q.assess(dark).issues
    glare = next(c for c in GOLDEN['cases'] if c['name'] == 'glare_rgb')
    assert not glare['quality_passed'] and 'OVEREXPOSED_OR_GLARE' in glare['quality_issues']


# ----- registry -----------------------------------------------------------------------------------

def test_registry_disabled_without_flag(fake_registry, monkeypatch):
    monkeypatch.delenv(R.IMAGE_MODELS_FLAG, raising=False)
    reg = fake_registry()
    with pytest.raises(R.ModelError) as e:
        reg.served('hemoglobin')
    assert e.value.code == 'MODEL_DISABLED'
    assert all(v['status'] == 'DISABLED' for v in reg.status().values())


def test_registry_missing_artifact(tmp_path, enabled):
    reg = R.Registry(write_registry(tmp_path, {'hb-hgb-cf': {'task': 'hemoglobin', 'contents': {'hb.json': fake_linear()}}}))
    (tmp_path / 'hb.json').unlink()
    with pytest.raises(R.ModelError) as e:
        reg.served('hemoglobin')
    assert e.value.code == 'MODEL_UNAVAILABLE' and 'hb.json' not in e.value.message


def test_registry_missing_registry_file(tmp_path, enabled):
    with pytest.raises(R.ModelError) as e:
        R.Registry(tmp_path).served('hemoglobin')
    assert e.value.code == 'MODEL_UNAVAILABLE'


def test_registry_rejects_tampered_artifact(tmp_path, enabled):
    reg = R.Registry(write_registry(tmp_path, {'hb-hgb-cf': {'task': 'hemoglobin', 'contents': {'hb.json': fake_linear()}}}))
    (tmp_path / 'hb.json').write_text(json.dumps(fake_linear(99.0)))
    with pytest.raises(R.ModelError) as e:
        reg.served('hemoglobin')
    assert e.value.code == 'MODEL_INTEGRITY_FAILED'


@pytest.mark.parametrize('content', [
    b'{not json',
    fake_linear(feature_version='cf-v0'),
    fake_linear(coefficients=[1.0, 2.0]),
    fake_linear(scale=[0.0] * 25),
    fake_linear(artifact_type='PICKLE'),
    fake_linear(validation_status='VALIDATED'),
    {'artifact_type': 'GRADIENT_BOOSTED_TREES_JSON', 'feature_version': F.FEATURE_VERSION, 'feature_names': list(F.FEATURE_NAMES),
     'baseline': 1.0, 'trees': [{'feature': [99], 'threshold': [0.0], 'left': [1], 'right': [2], 'value': [0.0], 'is_leaf': [False]}],
     'version': 'x', 'validation_status': 'RESEARCH_ONLY'},
], ids=['corrupt-json', 'feature-version', 'shape', 'zero-scale', 'unknown-type', 'validated-claim', 'bad-tree'])
def test_registry_rejects_incompatible_artifacts(tmp_path, enabled, content):
    reg = R.Registry(write_registry(tmp_path, {'hb-hgb-cf': {'task': 'hemoglobin', 'contents': {'hb.json': content}}}))
    with pytest.raises(R.ModelError) as e:
        reg.served('hemoglobin')
    assert e.value.code == 'MODEL_INCOMPATIBLE'


def test_registry_onnx_runtime_missing(tmp_path, enabled, monkeypatch):
    import builtins
    real_import = builtins.__import__
    monkeypatch.setattr(builtins, '__import__', lambda n, *a, **k: (_ for _ in ()).throw(ImportError()) if n == 'onnxruntime' else real_import(n, *a, **k))
    meta = {'artifact_type': 'ONNX_CNN_CLASSIFIER', 'version': 'x', 'validation_status': 'RESEARCH_ONLY', 'input_name': 'image',
            'input_shape': [1, 3, 224, 224], 'operating_threshold': .5, 'training': {}}
    reg = R.Registry(write_registry(tmp_path, {'njn-mnv3-logreg': {'task': 'neonatal_jaundice_class',
                                                                    'contents': {'njn.json': meta, 'njn.onnx': b'onnx'}}}))
    with pytest.raises(R.ModelError) as e:
        reg.served('neonatal_jaundice_class')
    assert e.value.code == 'RUNTIME_UNAVAILABLE'


def test_registry_corrupt_onnx(tmp_path, enabled):
    pytest.importorskip('onnxruntime')
    meta = {'artifact_type': 'ONNX_CNN_CLASSIFIER', 'version': 'x', 'validation_status': 'RESEARCH_ONLY', 'input_name': 'image',
            'input_shape': [1, 3, 224, 224], 'operating_threshold': .5, 'training': {}}
    reg = R.Registry(write_registry(tmp_path, {'njn-mnv3-logreg': {'task': 'neonatal_jaundice_class',
                                                                    'contents': {'njn.json': meta, 'njn.onnx': b'garbage bytes'}}}))
    with pytest.raises(R.ModelError) as e:
        reg.served('neonatal_jaundice_class')
    assert e.value.code == 'MODEL_INCOMPATIBLE'


def test_registry_loads_once(fake_registry, enabled):
    reg = fake_registry()
    assert reg.served('hemoglobin') is reg.served('hemoglobin')


def test_tree_runner_matches_manual_traversal():
    n = len(F.FEATURE_NAMES)
    tree = {'feature': [0, -1, -1], 'threshold': [0.5, 0, 0], 'left': [1, 0, 0], 'right': [2, 0, 0], 'value': [0, -1.0, 2.0],
            'is_leaf': [False, True, True]}
    run = R._tree_runner({'feature_version': F.FEATURE_VERSION, 'feature_names': list(F.FEATURE_NAMES), 'baseline': 10.0,
                          'trees': [tree, tree]})
    low = F.FeatureResult(np.zeros(n), 1, 1, 1)
    high = F.FeatureResult(np.ones(n), 1, 1, 1)
    assert run(None, low) == 8.0 and run(None, high) == 14.0


# ----- routes: disabled, failures, no fabricated values ----------------------------------------

ROUTES = ['/api/ml/hemoglobin', '/api/ml/neonatal-jaundice-class']


@pytest.mark.parametrize('route', ROUTES)
def test_routes_disabled_by_default(client, route, monkeypatch):
    monkeypatch.delenv(R.IMAGE_MODELS_FLAG, raising=False)
    r = client.post(route, content=png_bytes(conjunctiva_like()), headers={'Content-Type': 'image/png'})
    assert r.status_code == 503 and r.json()['error']['code'] == 'MODEL_DISABLED'
    assert 'estimate' not in r.json() and 'score' not in r.json()


def test_models_endpoint_reports_status_without_paths(client, fake_registry, enabled):
    fake_registry()
    body = client.get('/api/ml/models').json()
    assert body['enabled'] is True and body['models']['hemoglobin']['status'] == 'READY_EXPERIMENTAL'
    assert 'DISABLED_NO_VALID_MODEL' in body['bilirubin_mg_dl_model']
    text = json.dumps(body)
    assert ':\\' not in text and '/models/' not in text and 'tmp' not in text.lower()


@pytest.mark.usefixtures('test_body_site_verifier')
def test_hemoglobin_route_success_schema(client, fake_registry, enabled):
    fake_registry()
    r = client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={'Content-Type': 'image/png'})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b['estimate'] == 12.0 and b['unit'] == 'g/dL' and b['confidence'] is None
    assert b['provenance'] == 'EXPERIMENTAL_RESEARCH_ONLY' and b['synthetic'] is False
    assert b['model_id'] == 'hb-hgb-cf' and b['model_version'] == 'fake-1' and b['feature_version'] == 'cf-v1'
    assert 'RESEARCH_ONLY_NOT_VALIDATED' in b['warnings'] and b['input']['image_retained'] is False
    assert b['quality']['passed'] is True and 'risk_category' not in b
    assert r.headers['X-AbhayNayan-Contract-Version'] == API_CONTRACT_VERSION


@pytest.mark.usefixtures('test_body_site_verifier')
def test_jaundice_route_is_a_class_score_not_bilirubin(client, fake_registry, enabled):
    fake_registry()
    # The NJN model was trained on whole opaque newborn photos (Phase 5: masked crops are refused), so send an opaque image.
    r = client.post('/api/ml/neonatal-jaundice-class', content=png_bytes(conjunctiva_like()[..., :3].copy()), headers={'Content-Type': 'image/png'})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b['score'] == 0.5 and b['unit'] is None and 'estimate' not in b
    assert b['dataset_class_at_research_threshold'] == 'jaundice_like'
    assert 'NOT a bilirubin' in b['interpretation'] and 'mg/dL' not in json.dumps({k: v for k, v in b.items() if k != 'interpretation'})


@pytest.mark.parametrize('data,ctype,status,code', [
    (b'', 'image/png', 422, 'EMPTY_IMAGE'),
    (b'hello', 'text/plain', 415, 'UNSUPPORTED_MEDIA_TYPE'),
    (b'\xff\xd8\xff' + b'\x00' * 20, 'image/png', 415, 'UNSUPPORTED_MEDIA_TYPE'),
    (b'\x89PNG\r\n\x1a\n' + b'\x00' * 40, 'image/png', 422, 'CORRUPT_IMAGE'),
])
@pytest.mark.parametrize('route', ROUTES)
def test_routes_reject_invalid_images(client, fake_registry, enabled, route, data, ctype, status, code):
    fake_registry()
    r = client.post(route, content=data, headers={'Content-Type': ctype})
    assert r.status_code == status and r.json()['error']['code'] == code
    assert 'estimate' not in r.json() and 'score' not in r.json()


def test_route_rejects_oversized_body(client, fake_registry, enabled):
    fake_registry()
    r = client.post('/api/ml/hemoglobin', content=b'\x89PNG\r\n\x1a\n' + b'0' * (imageio.MAX_BYTES + 10), headers={'Content-Type': 'image/png'})
    assert r.status_code == 413 and r.json()['error']['code'] == 'IMAGE_TOO_LARGE'


def test_route_quality_rejection_lists_issues(client, fake_registry, enabled):
    fake_registry()
    flat = np.full((64, 64, 4), 128, np.uint8)
    flat[:8, :, 3] = 0  # segmented form (mask present), so the quality gate is what refuses it
    r = client.post('/api/ml/hemoglobin', content=png_bytes(flat), headers={'Content-Type': 'image/png'})
    assert r.status_code == 422 and r.json()['error']['code'] == 'IMAGE_QUALITY_REJECTED'
    assert any(f['message'] == 'BLURRED_OR_FLAT' for f in r.json()['error']['fields'])


@pytest.mark.parametrize('intercept,status,code', [(30.0, 422, 'OUTPUT_OUT_OF_RANGE'), (1.0, 422, 'OUTPUT_OUT_OF_RANGE')])
@pytest.mark.usefixtures('test_body_site_verifier')
def test_out_of_range_hb_is_discarded(client, fake_registry, enabled, intercept, status, code):
    fake_registry(hb=fake_linear(intercept))
    r = client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={'Content-Type': 'image/png'})
    assert r.status_code == status and r.json()['error']['code'] == code and 'estimate' not in r.json()


@pytest.mark.usefixtures('test_body_site_verifier')
def test_inference_exception_never_returns_a_value(client, fake_registry, enabled, monkeypatch):
    reg = fake_registry()
    model = reg.get('hb-hgb-cf')

    def boom(*_):
        raise RuntimeError('secret path C:/x')
    monkeypatch.setattr(model, 'runner', boom)
    r = client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={'Content-Type': 'image/png'})
    assert r.status_code == 500 and r.json()['error']['code'] == 'INFERENCE_FAILED'
    assert 'estimate' not in r.json() and 'secret' not in r.text


@pytest.mark.usefixtures('test_body_site_verifier')
def test_non_finite_output_is_an_error(client, fake_registry, enabled, monkeypatch):
    reg = fake_registry()
    monkeypatch.setattr(reg.get('hb-hgb-cf'), 'runner', lambda *_: float('nan'))
    r = client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={'Content-Type': 'image/png'})
    assert r.status_code == 500 and 'estimate' not in r.json()


def test_unavailable_artifact_returns_503(client, tmp_path, enabled, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, 'REGISTRY', R.Registry(tmp_path))  # no registry file
    r = client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={'Content-Type': 'image/png'})
    assert r.status_code == 503 and r.json()['error']['code'] == 'MODEL_UNAVAILABLE'


def test_out_of_distribution_input_is_refused(client, fake_registry, enabled):
    # Phase 5 / contract D3: out-of-distribution inputs give no value (previously: a value plus a warning; audit H2).
    n = len(F.FEATURE_NAMES)
    fake_registry(hb=fake_linear(training={'feature_min': [0.0] * n, 'feature_max': [1e-3] * n}))
    r = client.post('/api/ml/hemoglobin', content=png_bytes(conjunctiva_like()), headers={'Content-Type': 'image/png'})
    b = r.json()
    assert r.status_code == 422 and b['error']['code'] == 'INPUT_OUT_OF_DISTRIBUTION' and 'estimate' not in b
    assert b['error']['fields'] and b['prediction']['reason_code'] == 'INPUT_OUT_OF_DISTRIBUTION' and b['prediction']['estimate'] is None


def test_existing_disabled_safeguards_unchanged(client, monkeypatch):
    """The image routes must not enable the bilirubin adapter or the screening MODEL path."""
    monkeypatch.setenv(R.IMAGE_MODELS_FLAG, '1')
    r = client.post('/api/screenings', json={'patient': {'patient_id': 'ABH-1', 'demo': True}, 'screening_type': 'neonatal_jaundice',
                                             'inference_mode': 'MODEL'})
    assert r.status_code == 503 and r.json()['error']['code'] == 'MODEL_DISABLED'


def test_vision_capabilities_follow_flag(client, monkeypatch):
    monkeypatch.delenv(R.IMAGE_MODELS_FLAG, raising=False)
    assert client.get('/api/vision/capabilities').json()['image_upload_api'] is False
    monkeypatch.setenv(R.IMAGE_MODELS_FLAG, '1')
    assert client.get('/api/vision/capabilities').json()['image_upload_endpoints'] == ROUTES


# ----- genuine inference with the trained artifacts (skipped when absent) -------------------------

@real_artifact
def test_real_artifacts_load_and_match_pins():
    reg = R.Registry()
    for model_id in ('hb-hgb-cf', 'hb-ridge-cf', 'njn-mnv3-logreg', 'njn-logreg-cf'):
        m = reg.get(model_id)
        assert m.meta['validation_status'] == 'RESEARCH_ONLY'
        assert m.sha256 == GOLDEN['model_sha256'][model_id], 'golden vectors are stale: rerun export_golden_vectors.py'


@real_artifact
@pytest.mark.parametrize('case', [c for c in GOLDEN['cases'] if 'outputs' in c], ids=lambda c: c['name'])
def test_real_artifacts_reproduce_golden_outputs(case):
    reg = R.Registry()
    img = imageio.read_path(GOLDEN_DIR / case['file'])
    fr = F.extract(img)
    for model_id, expected in case['outputs'].items():
        tol = GOLDEN['tolerance']['onnx_output_abs'] if 'mnv3' in model_id else GOLDEN['tolerance']['linear_output_abs']
        assert abs(reg.get(model_id).predict(img, fr) - expected) <= tol, model_id


@real_artifact
@pytest.mark.usefixtures('test_body_site_verifier')
def test_real_hemoglobin_route_end_to_end(client, enabled, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, 'REGISTRY', R.Registry())
    case = next(c for c in GOLDEN['cases'] if c['name'] == 'pink_masked')
    b = client.post('/api/ml/hemoglobin', content=golden_png('pink_masked'), headers={'Content-Type': 'image/png'}).json()
    assert b['estimate'] == round(case['outputs']['hb-hgb-cf'], 1) and b['model_id'] == 'hb-hgb-cf'


@real_artifact
def test_real_jaundice_route_end_to_end(client, enabled, monkeypatch):
    # The golden skin image is outside the NJN model's training range on 8 colour features, so since Phase 5 the route
    # refuses it (contract D3). Golden score reproduction is still checked directly in test_real_artifacts_reproduce_golden_outputs.
    import app.main as main
    monkeypatch.setattr(main, 'REGISTRY', R.Registry())
    r = client.post('/api/ml/neonatal-jaundice-class', content=golden_png('skin_rgb_large'), headers={'Content-Type': 'image/png'})
    b = r.json()
    assert r.status_code == 422 and b['error']['code'] == 'INPUT_OUT_OF_DISTRIBUTION' and 'score' not in b
    assert b['prediction']['status'] == 'unable_to_estimate' and b['prediction']['estimate'] is None