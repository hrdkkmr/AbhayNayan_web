"""Bounded, fail-closed image decoding for uploaded bytes. Nothing is written to disk or logged.

Orientation: every decoded image is returned **upright**, i.e. as an EXIF-aware viewer would display it.
OpenCV's IMREAD_UNCHANGED ignores EXIF orientation, so the tag is read here (JPEG APP1 `Exif`, PNG `eXIf`)
and applied exactly once after decoding. Missing tag means no rotation; a malformed tag or a value outside
1-8 is reported as orientation status `invalid` and the pixels are left as stored (callers decide whether
the task tolerates that; see docs/capture_protocols.md §1.1).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import cv2
import numpy as np

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000
MIN_SIDE = 32
ALLOWED_TYPES = {'image/png': 'png', 'image/jpeg': 'jpeg'}
ORIENTATION_TAG = 0x0112


class ImageInputError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Orientation:
    exif_tag: int | None
    status: str  # 'absent' | 'valid' | 'invalid'

    @property
    def applied(self) -> str:
        """Contract value for `input.orientation.applied` (docs/prediction_contract.md §6)."""
        if self.status == 'invalid':
            return 'unknown'
        return 'exif_transpose' if self.exif_tag not in (None, 1) else 'none_needed'

    def as_dict(self) -> dict:
        return {'exif_tag': self.exif_tag, 'status': self.status, 'applied': self.applied}


@dataclass(frozen=True)
class DecodedImage:
    pixels: np.ndarray
    orientation: Orientation


def _tiff_orientation(tiff: bytes) -> Orientation:
    """Orientation from a TIFF/EXIF block (IFD0 only). Raises ValueError on malformed structure."""
    if len(tiff) < 8:
        raise ValueError('short TIFF header')
    order = tiff[:2]
    if order not in (b'II', b'MM'):
        raise ValueError('bad byte order')
    end = '<' if order == b'II' else '>'
    if struct.unpack(end + 'H', tiff[2:4])[0] != 42:
        raise ValueError('bad TIFF magic')
    ifd = struct.unpack(end + 'I', tiff[4:8])[0]
    if ifd + 2 > len(tiff):
        raise ValueError('IFD outside block')
    count = struct.unpack(end + 'H', tiff[ifd:ifd + 2])[0]
    if ifd + 2 + 12 * count > len(tiff):
        raise ValueError('IFD entries outside block')
    for i in range(count):
        off = ifd + 2 + 12 * i
        tag, typ, n = struct.unpack(end + 'HHI', tiff[off:off + 8])
        if tag != ORIENTATION_TAG:
            continue
        if typ != 3 or n != 1:  # SHORT, one value
            return Orientation(None, 'invalid')
        value = struct.unpack(end + 'H', tiff[off + 8:off + 10])[0]
        return Orientation(value, 'valid') if 1 <= value <= 8 else Orientation(value, 'invalid')
    return Orientation(None, 'absent')


def read_orientation(data: bytes, fmt: str) -> Orientation:
    """EXIF orientation from JPEG APP1 or PNG eXIf. Never raises; malformed metadata gives status 'invalid'."""
    try:
        if fmt == 'jpeg':
            i = 2
            while True:  # terminates: i grows by at least 2 per step
                if i + 4 > len(data) or data[i] != 0xFF:
                    return Orientation(None, 'absent')
                marker = data[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                if marker == 0xDA:  # start of scan: no metadata after this
                    return Orientation(None, 'absent')
                length = struct.unpack('>H', data[i + 2:i + 4])[0]
                if length < 2 or i + 2 + length > len(data):
                    return Orientation(None, 'invalid')
                payload = data[i + 4:i + 2 + length]
                if marker == 0xE1 and payload.startswith(b'Exif\x00\x00'):
                    return _tiff_orientation(payload[6:])
                i += 2 + length
        if fmt == 'png':
            i = 8
            while True:  # terminates: i grows by at least 12 per chunk
                if i + 8 > len(data):
                    return Orientation(None, 'absent')
                length = struct.unpack('>I', data[i:i + 4])[0]
                kind = data[i + 4:i + 8]
                if i + 12 + length > len(data):
                    return Orientation(None, 'invalid')
                if kind == b'eXIf':
                    return _tiff_orientation(data[i + 8:i + 8 + length])
                if kind == b'IEND':
                    return Orientation(None, 'absent')
                i += 12 + length
    except (ValueError, struct.error):
        return Orientation(None, 'invalid')
    return Orientation(None, 'absent')


def apply_orientation(img: np.ndarray, tag: int | None) -> np.ndarray:
    """Transforms stored pixels to display orientation for EXIF tags 1-8 (same mapping as Pillow's exif_transpose)."""
    if tag in (None, 1):
        return img
    if tag == 2:
        out = img[:, ::-1]
    elif tag == 3:
        out = img[::-1, ::-1]
    elif tag == 4:
        out = img[::-1, :]
    elif tag == 5:
        out = np.swapaxes(img, 0, 1)
    elif tag == 6:
        out = np.rot90(img, k=-1)
    elif tag == 7:
        out = np.swapaxes(img[::-1, ::-1], 0, 1)
    elif tag == 8:
        out = np.rot90(img, k=1)
    else:
        raise ValueError('orientation tag must be 1-8')
    return np.ascontiguousarray(out)


def sniff_format(data: bytes) -> str | None:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    return None


def header_dimensions(data: bytes, fmt: str) -> tuple[int, int] | None:
    """Width/height from the PNG IHDR or the first JPEG SOF marker, read before any decoding."""
    if fmt == 'png':
        if len(data) < 24 or data[12:16] != b'IHDR':
            return None
        w, h = struct.unpack('>II', data[16:24])
        return w, h
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack('>H', data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack('>HH', data[i + 5:i + 9])
            return w, h
        i += 2 + length
    return None


def decode(data: bytes, content_type: str | None) -> np.ndarray:
    """Returns upright uint8 RGB or RGBA (RGB channel order). Raises ImageInputError with a contract code."""
    return decode_image(data, content_type).pixels


def decode_image(data: bytes, content_type: str | None, max_bytes: int = MAX_BYTES) -> DecodedImage:
    """Validated decode plus the orientation that was applied."""
    if not data:
        raise ImageInputError('EMPTY_IMAGE', 'The request body is empty; send PNG or JPEG bytes.')
    if len(data) > max_bytes:
        raise ImageInputError('IMAGE_TOO_LARGE', 'The image is larger than this server accepts.', 413)
    declared = (content_type or '').split(';')[0].strip().lower()
    if declared not in ALLOWED_TYPES:
        raise ImageInputError('UNSUPPORTED_MEDIA_TYPE', 'Content-Type must be image/png or image/jpeg.', 415)
    fmt = sniff_format(data)
    if fmt is None or fmt != ALLOWED_TYPES[declared]:
        raise ImageInputError('UNSUPPORTED_MEDIA_TYPE', 'The bytes are not a PNG/JPEG matching the declared Content-Type.', 415)
    dims = header_dimensions(data, fmt)
    if dims is None:
        raise ImageInputError('CORRUPT_IMAGE', 'The image header could not be read.')
    w, h = dims
    if w < MIN_SIDE or h < MIN_SIDE:
        raise ImageInputError('IMAGE_TOO_SMALL', f'Images must be at least {MIN_SIDE}x{MIN_SIDE} pixels.')
    if w * h > MAX_PIXELS:
        raise ImageInputError('IMAGE_TOO_LARGE', 'The image has too many pixels.', 413)
    # IMREAD_UNCHANGED keeps alpha; libpng tolerates the bad iCCP CRCs found in Eyes-defy-anemia PNGs.
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None or img.ndim not in (2, 3):
        raise ImageInputError('CORRUPT_IMAGE', 'The image could not be decoded.')
    if img.dtype == np.uint16:
        img = (img >> 8).astype(np.uint8)
    if img.dtype != np.uint8:
        raise ImageInputError('CORRUPT_IMAGE', 'Unsupported pixel format.')
    if img.ndim == 2:
        rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    elif img.shape[2] == 4:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
    elif img.shape[2] == 3:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    else:
        raise ImageInputError('CORRUPT_IMAGE', 'Unsupported channel count.')
    orientation = read_orientation(data, fmt)
    pixels = apply_orientation(rgb, orientation.exif_tag) if orientation.status == 'valid' else rgb
    return DecodedImage(pixels, orientation)


def read_path(path) -> np.ndarray:
    """Training-side reader with the same channel and orientation handling as `decode` (no size limits)."""
    data = np.fromfile(str(path), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ImageInputError('CORRUPT_IMAGE', 'unreadable')
    if img.dtype == np.uint16:
        img = (img >> 8).astype(np.uint8)
    if img.ndim == 2:
        rgb = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA if img.shape[2] == 4 else cv2.COLOR_BGR2RGB)
    raw = data.tobytes()
    fmt = sniff_format(raw)
    orientation = read_orientation(raw, fmt) if fmt else Orientation(None, 'absent')
    if orientation.status == 'invalid':
        raise ImageInputError('ORIENTATION_UNKNOWN', 'unreadable orientation metadata')
    return apply_orientation(rgb, orientation.exif_tag)
