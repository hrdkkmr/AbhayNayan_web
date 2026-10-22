"""Colour-feature contract `cf-v1`, shared by training, the FastAPI backend and Android.

Every step is written out explicitly (no library colour conversions) so the Kotlin port can match it
to floating-point tolerance. Changing anything here changes the contract: bump FEATURE_VERSION,
regenerate golden vectors and retrain.

Input: a decoded uint8 array, H x W x 3 (RGB) or H x W x 4 (RGBA), in RGB channel order.

1. Subsample: step = ceil(max(H, W) / MAX_SIDE); keep pixels at (y * step, x * step).
2. Valid pixels: alpha >= 128 (when an alpha channel exists), max(R,G,B) < CLIP_LEVEL (not
   specular/clipped) and max(R,G,B) >= DARK_LEVEL (not shadow, eyelash or masked background).
3. Features over valid pixels, with channels scaled to [0, 1]; see FEATURE_NAMES.
   Percentiles use the "lower" definition: sorted[floor(q * (n - 1))].
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

FEATURE_VERSION = 'cf-v1'
MAX_SIDE = 256
ALPHA_MIN = 128
CLIP_LEVEL = 250
DARK_LEVEL = 20
MIN_VALID_PIXELS = 100
EPS = 1e-4

FEATURE_NAMES: tuple[str, ...] = (
    'mean_r', 'mean_g', 'mean_b',
    'std_r', 'std_g', 'std_b',
    'chroma_r', 'chroma_g', 'chroma_b',
    'median_r', 'median_g', 'median_b',
    'p10_r', 'p90_r', 'p10_g', 'p90_g',
    'mean_s', 'mean_v',
    'lab_l', 'lab_a', 'lab_b',
    'p10_lab_a', 'p90_lab_a',
    'erythema_index', 'yellow_index',
)


class FeatureError(ValueError):
    """The image cannot be turned into features (too few usable pixels, wrong shape)."""


@dataclass(frozen=True)
class FeatureResult:
    vector: np.ndarray           # float64, len(FEATURE_NAMES)
    valid_pixels: int
    sampled_pixels: int
    step: int

    @property
    def valid_fraction(self) -> float:
        return self.valid_pixels / self.sampled_pixels if self.sampled_pixels else 0.0

    def as_dict(self) -> dict[str, float]:
        return {name: float(v) for name, v in zip(FEATURE_NAMES, self.vector)}


def subsample(image: np.ndarray) -> tuple[np.ndarray, int]:
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] not in (3, 4):
        raise FeatureError('Expected a uint8 H x W x 3 (RGB) or H x W x 4 (RGBA) image.')
    h, w = image.shape[:2]
    if h == 0 or w == 0:
        raise FeatureError('Image is empty.')
    step = max(1, math.ceil(max(h, w) / MAX_SIDE))
    return image[::step, ::step], step


def valid_mask(sampled: np.ndarray) -> np.ndarray:
    rgb = sampled[..., :3]
    mx = rgb.max(axis=2)
    mask = (mx < CLIP_LEVEL) & (mx >= DARK_LEVEL)
    if sampled.shape[2] == 4:
        mask &= sampled[..., 3] >= ALPHA_MIN
    return mask


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _lab_f(t: np.ndarray) -> np.ndarray:
    d = 6.0 / 29.0
    return np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)


def rgb_to_lab(rgb01: np.ndarray) -> np.ndarray:
    """sRGB (D65) in [0,1], shape (n, 3) -> CIE L*a*b*, shape (n, 3)."""
    lin = _srgb_to_linear(rgb01)
    x = lin[:, 0] * 0.4124564 + lin[:, 1] * 0.3575761 + lin[:, 2] * 0.1804375
    y = lin[:, 0] * 0.2126729 + lin[:, 1] * 0.7151522 + lin[:, 2] * 0.0721750
    z = lin[:, 0] * 0.0193339 + lin[:, 1] * 0.1191920 + lin[:, 2] * 0.9503041
    fx, fy, fz = _lab_f(x / 0.95047), _lab_f(y / 1.0), _lab_f(z / 1.08883)
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=1)


def _lower_percentile(values: np.ndarray, q: float) -> float:
    s = np.sort(values)
    return float(s[int(math.floor(q * (len(s) - 1)))])


def extract(image: np.ndarray) -> FeatureResult:
    sampled, step = subsample(image)
    mask = valid_mask(sampled)
    n = int(mask.sum())
    total = int(mask.size)
    if n < MIN_VALID_PIXELS:
        raise FeatureError(f'Only {n} usable pixels after masking; at least {MIN_VALID_PIXELS} are required.')
    px = sampled[..., :3][mask].astype(np.float64) / 255.0  # (n, 3)
    r, g, b = px[:, 0], px[:, 1], px[:, 2]
    mean = px.mean(axis=0)
    std = px.std(axis=0)  # population SD (ddof=0)
    chroma = mean / max(float(mean.sum()), EPS)
    mx = px.max(axis=1)
    mn = px.min(axis=1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, EPS), 0.0)
    lab = rgb_to_lab(px)
    vec = np.array([
        mean[0], mean[1], mean[2],
        std[0], std[1], std[2],
        chroma[0], chroma[1], chroma[2],
        _lower_percentile(r, .5), _lower_percentile(g, .5), _lower_percentile(b, .5),
        _lower_percentile(r, .1), _lower_percentile(r, .9), _lower_percentile(g, .1), _lower_percentile(g, .9),
        float(sat.mean()), float(mx.mean()),
        float(lab[:, 0].mean()), float(lab[:, 1].mean()), float(lab[:, 2].mean()),
        _lower_percentile(lab[:, 1], .1), _lower_percentile(lab[:, 1], .9),
        math.log(mean[0] + EPS) - math.log(mean[1] + EPS),
        math.log((mean[0] + mean[1]) / 2 + EPS) - math.log(mean[2] + EPS),
    ], dtype=np.float64)
    if not np.all(np.isfinite(vec)):
        raise FeatureError('Feature computation produced a non-finite value.')
    return FeatureResult(vec, n, total, step)
