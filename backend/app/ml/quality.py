"""Image-quality gate for model inputs. Kept separate from prediction: passing says nothing about accuracy.

Thresholds are engineering heuristics, not clinically derived limits. Measured on the training
partitions: 12.9 % of Eyes-defy-anemia, 4.1 % of CP-AnemiC and 0 % of NJN images fail, all for
specular glare (> 25 % of the target region clipped). The models were trained on those images'
remaining valid pixels; at serving time such images are refused. See docs/ml_evaluation.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.ml import features as F

MIN_VALID_FRACTION = 0.10
MIN_MEAN_V = 0.15
MAX_CLIPPED_FRACTION = 0.25
MIN_SHARPNESS = 2.0


@dataclass
class QualityResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {'passed': self.passed, 'issues': list(self.issues), 'metrics': dict(self.metrics)}


def _laplacian_variance(gray: np.ndarray, mask: np.ndarray) -> float:
    g = gray.astype(np.float64)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    m = mask[1:-1, 1:-1]
    vals = lap[m] if m.sum() > 10 else lap.ravel()
    return float(vals.var()) if vals.size else 0.0


def assess(image: np.ndarray) -> QualityResult:
    sampled, _ = F.subsample(image)
    rgb = sampled[..., :3]
    in_subject = sampled[..., 3] >= F.ALPHA_MIN if sampled.shape[2] == 4 else np.ones(rgb.shape[:2], bool)
    mask = F.valid_mask(sampled)
    subject_px = max(int(in_subject.sum()), 1)
    mx = rgb.max(axis=2)
    clipped = float(((mx >= F.CLIP_LEVEL) & in_subject).sum()) / subject_px
    valid_fraction = float(mask.sum()) / subject_px
    mean_v = float(mx[mask].mean() / 255.0) if mask.any() else 0.0
    gray = rgb.astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    sharp = _laplacian_variance(gray, mask)
    issues: list[str] = []
    if int(mask.sum()) < F.MIN_VALID_PIXELS:
        issues.append('TOO_FEW_USABLE_PIXELS')
    if valid_fraction < MIN_VALID_FRACTION:
        issues.append('TARGET_REGION_TOO_SMALL_OR_DARK')
    if clipped > MAX_CLIPPED_FRACTION:
        issues.append('OVEREXPOSED_OR_GLARE')
    if mask.any() and mean_v < MIN_MEAN_V:
        issues.append('TOO_DARK')
    if sharp < MIN_SHARPNESS:
        issues.append('BLURRED_OR_FLAT')
    return QualityResult(not issues, issues, {
        'valid_pixels': float(mask.sum()), 'valid_fraction': round(valid_fraction, 4),
        'clipped_fraction': round(clipped, 4), 'mean_brightness': round(mean_v, 4), 'sharpness': round(sharp, 3),
    })
