from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass
class QualityReport:
    ready: bool
    quality_score: float
    brightness: float
    blur_score: float
    motion_score: float
    region_confirmed: bool
    region_detected: bool = False
    reasons: tuple[str, ...] = ()
    mode: str = 'LOCAL_MEASURED_MANUAL_ROI'


def assess_quality(brightness: float, blur_score: float, motion_score: float = 0.0,
                   region_confirmed: bool = False) -> QualityReport:
    reasons: list[str] = []
    if brightness < 32:
        reasons.append('Too dark — add soft ambient light.')
    elif brightness > 228:
        reasons.append('Too bright — reduce glare or direct sunlight.')
    if blur_score < 0.10:
        reasons.append('Image may be blurred — steady the phone and refocus.')
    if motion_score > 0.48:
        reasons.append('Too much movement — hold the phone still.')
    if not region_confirmed:
        reasons.append('Manually confirm the target region inside the guide.')
    light_score = max(0.0, min(1.0, 1 - abs(brightness - 126) / 126))
    sharp_score = max(0.0, min(1.0, blur_score))
    motion_quality = max(0.0, min(1.0, 1 - motion_score))
    score = round(light_score * 0.45 + sharp_score * 0.35 + motion_quality * 0.20, 3)
    ready = brightness >= 32 and brightness <= 228 and blur_score >= 0.10 and motion_score <= 0.48 and region_confirmed
    return QualityReport(ready, score, float(brightness), float(blur_score), float(motion_score), region_confirmed, False, tuple(reasons))


def _extract_roi(image: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        raise ValueError('An image array is required.')
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError('Expected a 3-channel image.')
    h, w = image.shape[:2]
    if bbox is None:
        # A safe fallback crop for pipeline visualization; not a face/eye detector.
        x0, y0, x1, y1 = int(w * .22), int(h * .30), int(w * .78), int(h * .72)
        source = 'MANUAL_CENTER_GUIDE'
    else:
        x, y, bw, bh = bbox
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(w, int(x + bw)), min(h, int(y + bh))
        source = 'USER_CONFIRMED_BBOX'
    if x1 <= x0 or y1 <= y0:
        raise ValueError('ROI bounds are empty or outside the image.')
    roi = image[y0:y1, x0:x1].copy()
    if roi.size == 0:
        raise ValueError('ROI crop is empty.')
    return roi, {'x': x0, 'y': y0, 'width': x1 - x0, 'height': y1 - y0, 'source': source, 'landmark_detected': False}


class ConjunctivaROIExtractor:
    def extract(self, image: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
        roi, meta = _extract_roi(image, bbox)
        return {'roi': roi, 'normalized_roi': color_normalize(roi), 'region': 'palpebral_conjunctiva', 'metadata': meta}


class ScleraROIExtractor:
    def extract(self, image: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
        roi, meta = _extract_roi(image, bbox)
        return {'roi': roi, 'normalized_roi': color_normalize(roi), 'region': 'sclera', 'metadata': meta}


def color_normalize(image: np.ndarray) -> np.ndarray:
    if image is None or image.size == 0:
        raise ValueError('Image cannot be empty.')
    # Per-frame luminance normalization is demonstrative only; no reference card is used.
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    target = float(np.clip(np.mean(l), 70, 190))
    scale = target / max(float(np.mean(l)), 1.0)
    l_norm = np.clip(l.astype(np.float32) * scale, 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.merge((l_norm, a, b)), cv2.COLOR_LAB2BGR)


def extract_color_features(roi_bgr: np.ndarray) -> dict[str, float]:
    if roi_bgr is None or roi_bgr.size == 0:
        raise ValueError('ROI cannot be empty.')
    rgb = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    ycc = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    lab = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    means = lambda arr: np.mean(arr.reshape(-1, arr.shape[-1]), axis=0)
    r, g, b = means(rgb)
    h, s, v = means(hsv)
    y, cr, cb = means(ycc)
    l, a, lab_b = means(lab)
    return {
        'r_mean': round(float(r), 3), 'g_mean': round(float(g), 3), 'b_mean': round(float(b), 3),
        'red_pct': round(float(r / max(r + g + b, 1e-6) * 100), 4),
        'green_pct': round(float(g / max(r + g + b, 1e-6) * 100), 4),
        'blue_pct': round(float(b / max(r + g + b, 1e-6) * 100), 4),
        'red_green_ratio': round(float(r / max(g, 1e-6)), 5),
        'h_mean': round(float(h), 3), 's_mean': round(float(s), 3), 'v_mean': round(float(v), 3),
        'y_mean': round(float(y), 3), 'cr_mean': round(float(cr), 3), 'cb_mean': round(float(cb), 3),
        'lab_l_mean': round(float(l), 3), 'lab_a_mean': round(float(a), 3), 'lab_b_mean': round(float(lab_b), 3),
        'feature_note': 'Exploratory color features; camera color is not calibrated and no clinical estimate is derived.',
    }


def blur_score(image_bgr: np.ndarray) -> float:
    if image_bgr is None or image_bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return round(float(np.clip((lap_var - 1.4) / 180.0, 0.0, 1.0)), 4)


class AmbientLightCorrector:
    def correct(self, ambient_bgr: np.ndarray, flash_bgr: np.ndarray | None = None) -> dict[str, Any]:
        if ambient_bgr is None or ambient_bgr.size == 0:
            raise ValueError('Ambient frame required.')
        if flash_bgr is None:
            return {'available': False, 'corrected': False, 'lighting_quality': 0.0,
                    'message': 'Flash frame unavailable; single-frame path used. No subtraction performed.'}
        if ambient_bgr.shape != flash_bgr.shape:
            return {'available': False, 'corrected': False, 'lighting_quality': 0.0,
                    'message': 'Frame dimensions differ; correction skipped.'}
        # Differential is only a prototype visualization; clipping/normalization does not establish clinical validity.
        delta = cv2.subtract(flash_bgr, ambient_bgr)
        mean_delta = float(np.mean(np.abs(delta)))
        corrected = cv2.normalize(delta, None, 0, 255, cv2.NORM_MINMAX)
        lighting_quality = float(np.clip(1 - abs(mean_delta - 42) / 90, 0, 1))
        return {'available': True, 'corrected': True, 'corrected_roi': corrected,
                'mean_frame_delta': round(mean_delta, 4), 'lighting_quality': round(lighting_quality, 3),
                'message': 'Experimental flash/ambient differential; not clinically calibrated.'}
