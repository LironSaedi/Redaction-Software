"""Pixel redaction effects shared by image and video redaction. All effects are irreversible:
blur is applied to a heavily pixelated copy (pure Gaussian blur can be partially inverted)."""
from __future__ import annotations

import cv2
import numpy as np

EFFECTS = ("blackout", "pixelate", "blur", "whiteout")


def apply_effect(img: np.ndarray, x0: float, y0: float, x1: float, y1: float, effect: str = "blackout",
                 shape: str = "rect", strength: float = 1.0, color=(0, 0, 0), points=None) -> None:
    """In-place. img is BGR uint8."""
    h, w = img.shape[:2]
    x0, y0 = max(0, int(np.floor(x0))), max(0, int(np.floor(y0)))
    x1, y1 = min(w, int(np.ceil(x1))), min(h, int(np.ceil(y1)))
    if x1 <= x0 or y1 <= y0:
        return
    roi = img[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    if effect == "blackout":
        out = np.empty_like(roi)
        out[:] = color
    elif effect == "whiteout":
        out = np.full_like(roi, 255)
    elif effect == "pixelate":
        blocks = max(3, int(8 / max(strength, 0.25)))
        small = cv2.resize(roi, (max(1, min(rw, blocks)), max(1, min(rh, blocks))), interpolation=cv2.INTER_AREA)
        out = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)
    elif effect == "blur":
        small = cv2.resize(roi, (max(1, min(rw, 6)), max(1, min(rh, 6))), interpolation=cv2.INTER_AREA)
        out = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_LINEAR)
        k = max(3, int(max(rw, rh) * 0.25 * strength) | 1)
        out = cv2.GaussianBlur(out, (k, k), 0)
    else:
        raise ValueError(f"unknown effect {effect}")
    if shape == "polygon" and points:
        from .shapes import polygon_mask
        m = polygon_mask((rh, rw), [(px - x0, py - y0) for px, py in points])
        roi[m] = out[m]
    elif shape == "ellipse":
        mask = np.zeros((rh, rw), np.uint8)
        cv2.ellipse(mask, (rw // 2, rh // 2), (max(1, rw // 2), max(1, rh // 2)), 0, 0, 360, 255, -1)
        m = mask.astype(bool)
        roi[m] = out[m]
    else:
        roi[:] = out


def enhance_frame(img: np.ndarray, brightness: float = 0.0, contrast: float = 1.0, sharpen: float = 0.0,
                  denoise: bool = False, gamma: float = 1.0) -> np.ndarray:
    """Enhancement for dark / blurry footage and photos (body-cam at night, a blurry plate): brightness -1..1,
    contrast 0.5..2, sharpen 0..2 (unsharp mask), gamma 0.3..3, optional denoise. Returns a new image."""
    out = img
    if denoise:
        out = cv2.fastNlMeansDenoisingColored(out, None, 5, 5, 7, 21)
    if gamma and abs(gamma - 1.0) > 1e-3:
        lut = np.array([((i / 255.0) ** (1.0 / gamma)) * 255 for i in range(256)], np.uint8)
        out = cv2.LUT(out, lut)
    if abs(contrast - 1.0) > 1e-3 or abs(brightness) > 1e-3:
        out = cv2.convertScaleAbs(out, alpha=float(contrast), beta=float(brightness) * 127)
    if sharpen > 0:
        blur = cv2.GaussianBlur(out, (0, 0), 2.0)
        out = cv2.addWeighted(out, 1 + sharpen, blur, -sharpen, 0)
    return out
