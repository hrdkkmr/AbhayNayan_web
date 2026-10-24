"""EXIF orientation normalisation (audit M2; acceptance criteria AC-CAP-06, AC-CAP-07).

Two independent oracles: Pillow's ImageOps.exif_transpose for the pixel mapping, and OpenCV's own
orientation-aware decode (IMREAD_COLOR) for JPEG, which also proves the tag is applied exactly once.
All images are synthetic software fixtures; none says anything about clinical accuracy.
"""
from __future__ import annotations

import io
import struct

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageOps

from app.main import app
from app.ml import cnn_preprocess, features as F, imageio
from app.services import gemini, store
from conftest import research_token_headers
from test_ml import conjunctiva_like, fake_registry  # noqa: F401  (fixture re-export)

TAGS = range(1, 9)
# Pillow transpose that undoes each tag (display -> stored), used to build stored pixels for a known display image.
INVERSE = {1: None, 2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
           5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_90, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_270}


def base_image(mode='RGB', h=48, w=80, seed=3) -> np.ndarray:
    """Asymmetric synthetic image: every orientation error changes it."""
    rng = np.random.default_rng(seed)
    img = rng.integers(30, 230, (h, w, 4 if mode == 'RGBA' else 3), dtype=np.uint8)
    img[:8, :16, :3] = (240, 20, 20)
    if mode == 'RGBA':
        img[..., 3] = 255
        img[-6:, -10:, 3] = 0
    return img


def exif_bytes(tag: int) -> bytes:
    ex = Image.Exif()
    ex[0x0112] = tag
    return ex.tobytes()


def stored_for(display: np.ndarray, tag: int) -> Image.Image:
    im = Image.fromarray(display)
    return im if INVERSE[tag] is None else im.transpose(INVERSE[tag])


def encode(display: np.ndarray, tag: int, fmt: str) -> bytes:
    buf = io.BytesIO()
    stored = stored_for(display, tag)
    if fmt == 'PNG':
        stored.save(buf, 'PNG', exif=exif_bytes(tag))
    else:
        stored.save(buf, 'JPEG', quality=100, subsampling=0, exif=exif_bytes(tag))
    return buf.getvalue()


def with_app1(jpeg: bytes, payload: bytes) -> bytes:
    """Inserts an APP1 segment with `payload` directly after SOI."""
    return jpeg[:2] + b'\xff\xe1' + struct.pack('>H', len(payload) + 2) + payload + jpeg[2:]


def plain_jpeg(img: np.ndarray) -> bytes:
    return cv2.imencode('.jpg', cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def tiff(order=b'II', tag=0x0112, typ=3, count=1, value=6, ifd_offset=8, entries=1) -> bytes:
    end = '<' if order == b'II' else '>'
    head = order + struct.pack(end + 'HI', 42, ifd_offset)
    entry = struct.pack(end + 'HHI', tag, typ, count) + struct.pack(end + 'H', value) + b'\x00\x00'
    return head + struct.pack(end + 'H', entries) + entry * min(entries, 1) + b'\x00\x00\x00\x00'


# ----- pixel mapping ------------------------------------------------------------------------------

@pytest.mark.parametrize('mode', ['RGB', 'RGBA'])
@pytest.mark.parametrize('tag', TAGS)
def test_apply_orientation_matches_pillow(tag, mode):
    stored = np.asarray(stored_for(base_image(mode), tag))
    ours = imageio.apply_orientation(stored, tag)
    exif_im = Image.fromarray(stored)
    exif_im.info['exif'] = exif_bytes(tag)
    exif_im.getexif()[0x0112] = tag
    pillow = np.asarray(ImageOps.exif_transpose(exif_im))
    assert ours.shape == pillow.shape and ours.dtype == np.uint8
    assert np.array_equal(ours, pillow)


def test_apply_orientation_rejects_bad_tag():
    with pytest.raises(ValueError):
        imageio.apply_orientation(base_image(), 9)


# ----- end to end: decode returns the display image exactly once ------------------------------------

@pytest.mark.parametrize('mode', ['RGB', 'RGBA'])
@pytest.mark.parametrize('tag', TAGS)
def test_png_all_orientations_decode_to_identical_pixels(tag, mode):
    display = base_image(mode)
    out = imageio.decode_image(encode(display, tag, 'PNG'), 'image/png')
    assert out.orientation.status == 'valid' and out.orientation.exif_tag == tag
    assert out.orientation.applied == ('none_needed' if tag == 1 else 'exif_transpose')
    assert out.pixels.shape == display.shape  # height, width and channel count restored
    assert np.array_equal(out.pixels, display)  # lossless: identical content and RGB(A) channel order


@pytest.mark.parametrize('tag', TAGS)
def test_png_orientations_give_identical_features_and_cnn_tensors(tag):
    display = conjunctiva_like(64, 96)
    reference = imageio.decode(encode(display, 1, 'PNG'), 'image/png')
    rotated = imageio.decode(encode(display, tag, 'PNG'), 'image/png')
    assert np.allclose(F.extract(rotated).vector, F.extract(reference).vector, atol=1e-6, rtol=0)
    assert np.array_equal(cnn_preprocess.to_tensor(rotated), cnn_preprocess.to_tensor(reference))


@pytest.mark.parametrize('tag', TAGS)
def test_jpeg_orientation_applied_once_matches_opencv_exif_decode(tag):
    data = encode(base_image(), tag, 'JPEG')
    ours = imageio.decode_image(data, 'image/jpeg')
    # IMREAD_COLOR applies EXIF orientation itself: equal output proves no double or missing rotation.
    opencv = cv2.cvtColor(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    assert ours.orientation.exif_tag == tag
    assert ours.pixels.shape == opencv.shape == base_image().shape
    assert np.array_equal(ours.pixels, opencv)


def test_jpeg_orientation_close_to_display_image():
    display = base_image()
    for tag in TAGS:
        out = imageio.decode(encode(display, tag, 'JPEG'), 'image/jpeg')
        assert out.shape == display.shape
        assert np.abs(out.astype(int) - display.astype(int)).mean() < 3.0  # JPEG is lossy; orientation errors give ~60


def test_no_exif_means_no_rotation():
    img = base_image()
    jpg = imageio.decode_image(plain_jpeg(img), 'image/jpeg')
    png = imageio.decode_image(cv2.imencode('.png', cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes(), 'image/png')
    assert jpg.orientation.status == png.orientation.status == 'absent'
    assert jpg.orientation.applied == png.orientation.applied == 'none_needed'
    assert jpg.pixels.shape == png.pixels.shape == img.shape


# ----- malformed metadata never crashes and never rotates -----------------------------------------

@pytest.mark.parametrize('payload', [
    b'Exif\x00\x00' + tiff(value=0),                 # value outside 1-8
    b'Exif\x00\x00' + tiff(value=9),
    b'Exif\x00\x00' + tiff(typ=4),                   # wrong type (LONG)
    b'Exif\x00\x00' + tiff(count=2),                 # wrong count
    b'Exif\x00\x00' + tiff(order=b'XX'),             # bad byte order
    b'Exif\x00\x00' + tiff(ifd_offset=10_000),       # IFD outside the block
    b'Exif\x00\x00' + tiff(entries=500),             # entry table runs past the end
    b'Exif\x00\x00' + b'II*\x00',                    # truncated header
], ids=['zero', 'nine', 'type', 'count', 'order', 'ifd', 'entries', 'short'])
def test_malformed_exif_is_reported_invalid_and_pixels_left_as_stored(payload):
    img = base_image()
    out = imageio.decode_image(with_app1(plain_jpeg(img), payload), 'image/jpeg')
    assert out.orientation.status == 'invalid' and out.orientation.applied == 'unknown'
    assert out.pixels.shape == img.shape


def test_big_endian_exif_is_read():
    img = base_image()
    out = imageio.decode_image(with_app1(plain_jpeg(img), b'Exif\x00\x00' + tiff(order=b'MM', value=6)), 'image/jpeg')
    assert out.orientation.exif_tag == 6 and out.pixels.shape == (img.shape[1], img.shape[0], 3)


def test_exif_without_orientation_tag_is_absent():
    out = imageio.decode_image(with_app1(plain_jpeg(base_image()), b'Exif\x00\x00' + tiff(tag=0x010F)), 'image/jpeg')
    assert out.orientation.status == 'absent'


@pytest.mark.parametrize('data,ctype,code', [
    (b'', 'image/jpeg', 'EMPTY_IMAGE'),
    (b'GIF89a' + b'\x00' * 40, 'image/png', 'UNSUPPORTED_MEDIA_TYPE'),
    (b'\xff\xd8\xff\xe1\x00\x10Exif\x00\x00II*\x00', 'image/jpeg', 'CORRUPT_IMAGE'),  # EXIF but no image data
])
def test_corrupt_and_unsupported_inputs_still_rejected(data, ctype, code):
    with pytest.raises(imageio.ImageInputError) as e:
        imageio.decode_image(data, ctype)
    assert e.value.code == code


def test_size_limit_is_enforced_before_decoding():
    with pytest.raises(imageio.ImageInputError) as e:
        imageio.decode_image(b'\x89PNG\r\n\x1a\n' + b'0' * 2048, 'image/png', max_bytes=1024)
    assert e.value.code == 'IMAGE_TOO_LARGE' and e.value.status == 413


# ----- training reader parity ---------------------------------------------------------------------

@pytest.mark.parametrize('tag', [1, 3, 6, 8])
def test_read_path_matches_decode(tmp_path, tag):
    data = encode(base_image('RGBA'), tag, 'PNG')
    p = tmp_path / 'x.png'
    p.write_bytes(data)
    assert np.array_equal(imageio.read_path(p), imageio.decode(data, 'image/png'))


def test_read_path_refuses_unreadable_orientation(tmp_path):
    p = tmp_path / 'bad.jpg'
    p.write_bytes(with_app1(plain_jpeg(base_image()), b'Exif\x00\x00' + tiff(value=0)))
    with pytest.raises(imageio.ImageInputError) as e:
        imageio.read_path(p)
    assert e.value.code == 'ORIENTATION_UNKNOWN'


# ----- routes: orientation reported; CNN refuses unknown orientation; no new bypass ------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DB_PATH', tmp_path / 'test.sqlite3')
    monkeypatch.setattr(gemini, 'API_KEY', '')
    monkeypatch.setenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS', '1')
    headers = research_token_headers(monkeypatch)
    with TestClient(app) as c:
        c.headers.update(headers)
        yield c


def png_rgba_masked() -> bytes:
    rgba = conjunctiva_like(64, 96)
    return cv2.imencode('.png', cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))[1].tobytes()


def png_with_exif_chunk(png: bytes, payload: bytes) -> bytes:
    """Inserts an eXIf chunk (with a correct CRC) right after IHDR."""
    import zlib
    ihdr_end = 8 + 8 + 13 + 4
    chunk = struct.pack('>I', len(payload)) + b'eXIf' + payload + struct.pack('>I', zlib.crc32(b'eXIf' + payload) & 0xFFFFFFFF)
    return png[:ihdr_end] + chunk + png[ihdr_end:]


def skin_like_jpeg(tag: int | None) -> bytes:
    rng = np.random.default_rng(7)
    img = np.clip(rng.normal((205, 150, 120), 14, (90, 140, 3)), 0, 255).astype(np.uint8)
    data = encode(img, tag, 'JPEG') if tag else plain_jpeg(img)
    return data


@pytest.mark.usefixtures('test_body_site_verifier')
def test_route_reports_applied_orientation(client, fake_registry):
    fake_registry()
    # Opaque photo: the NJN route accepts this form (the Hb route needs a segmented, masked image).
    r = client.post('/api/ml/neonatal-jaundice-class', content=skin_like_jpeg(6), headers={'Content-Type': 'image/jpeg'})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b['input']['orientation'] == {'exif_tag': 6, 'status': 'valid', 'applied': 'exif_transpose'}
    # Display image is 140 wide x 90 high; the file stores it sideways (90 x 140) with tag 6. Normalised = display.
    assert (b['input']['width'], b['input']['height']) == (140, 90)


@pytest.mark.usefixtures('test_body_site_verifier')
def test_unknown_orientation_blocks_cnn_but_warns_for_colour_model(client, fake_registry):
    fake_registry()
    bad = with_app1(skin_like_jpeg(None), b'Exif\x00\x00' + tiff(value=0))
    cnn = client.post('/api/ml/neonatal-jaundice-class', content=bad, headers={'Content-Type': 'image/jpeg'})
    assert cnn.status_code == 422 and cnn.json()['error']['code'] == 'ORIENTATION_UNKNOWN'
    assert 'score' not in cnn.json() and cnn.json()['prediction']['reason_code'] == 'MODALITY_UNVERIFIED'
    # Colour model: a segmented (masked) PNG whose eXIf chunk is malformed is still scored, with a warning.
    hb = client.post('/api/ml/hemoglobin', content=png_with_exif_chunk(png_rgba_masked(), b'II*\x00'), headers={'Content-Type': 'image/png'})
    assert hb.status_code == 200 and 'ORIENTATION_UNKNOWN' in hb.json()['warnings']
    assert hb.json()['input']['orientation']['applied'] == 'unknown'


def test_orientation_change_adds_no_route_and_keeps_flag(client, monkeypatch):
    monkeypatch.delenv('ABHAYNAYAN_ENABLE_EXPERIMENTAL_IMAGE_MODELS')
    r = client.post('/api/ml/hemoglobin', content=skin_like_jpeg(6), headers={'Content-Type': 'image/jpeg'})
    assert r.status_code == 503 and r.json()['error']['code'] == 'MODEL_DISABLED'
    paths = {route.path for route in app.routes}
    assert not any('orient' in p for p in paths)
