"""CNN input contract `cnn-v1` (MobileNetV3-Small, ImageNet weights), shared by training and serving.

RGBA is composited on black (alpha >= 128 kept), the image is letterboxed onto a black 224x224
canvas with INTER_AREA resizing, scaled to [0,1], then normalised with ImageNet mean/std.
Output tensor: float32 NCHW [1, 3, 224, 224].
"""
from __future__ import annotations

import cv2
import numpy as np

CNN_VERSION = 'cnn-v1'
SIZE = 224
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


def letterbox(img: np.ndarray) -> np.ndarray:
    """uint8 RGB/RGBA -> float32 HWC in [0,1], 224x224."""
    rgb = img[..., :3].astype(np.float32)
    if img.shape[2] == 4:
        rgb *= (img[..., 3:4] >= 128)
    h, w = rgb.shape[:2]
    s = SIZE / max(h, w)
    nh, nw = max(1, round(h * s)), max(1, round(w * s))
    small = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((SIZE, SIZE, 3), np.float32)
    y0, x0 = (SIZE - nh) // 2, (SIZE - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = small
    return out / 255.0


def to_tensor(img: np.ndarray) -> np.ndarray:
    x = (letterbox(img) - MEAN) / STD
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None], dtype=np.float32)
