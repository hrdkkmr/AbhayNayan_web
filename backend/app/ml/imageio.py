"""Bounded, fail-closed image decoding for uploaded bytes. Nothing is written to disk or logged."""
from __future__ import annotations

import struct

import cv2
import numpy as np

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000
MIN_SIDE = 32
ALLOWED_TYPES = {'image/png': 'png', 'image/jpeg': 'jpeg'}


class ImageInputError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


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
    """Returns uint8 RGB or RGBA (RGB channel order). Raises ImageInputError with a contract code."""
    if not data:
        raise ImageInputError('EMPTY_IMAGE', 'The request body is empty; send PNG or JPEG bytes.')
    if len(data) > MAX_BYTES:
        raise ImageInputError('IMAGE_TOO_LARGE', f'Images larger than {MAX_BYTES // (1024 * 1024)} MB are not accepted.', 413)
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
        return cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
    if img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    raise ImageInputError('CORRUPT_IMAGE', 'Unsupported channel count.')


def read_path(path) -> np.ndarray:
    """Training-side reader with the same channel handling as `decode` (no size limits)."""
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ImageInputError('CORRUPT_IMAGE', 'unreadable')
    if img.dtype == np.uint16:
        img = (img >> 8).astype(np.uint8)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    return cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA if img.shape[2] == 4 else cv2.COLOR_BGR2RGB)
