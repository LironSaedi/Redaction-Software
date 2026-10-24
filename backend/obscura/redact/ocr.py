"""Local OCR (Tesseract) with word geometry.

Returns words with pixel boxes and confidences; callers convert to page coordinates. Images are
pre-processed (grayscale, upscale for low resolution, deskew) before recognition, and pages that
come back with low confidence get a second pass with a different segmentation mode.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

from ..config import settings

log = logging.getLogger("obscura.ocr")


@dataclass
class OcrWord:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float
    block: int
    par: int
    line: int


def _tess():
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    return pytesseract


def available() -> bool:
    try:
        _tess().get_tesseract_version()
        return True
    except Exception:
        return False


def _deskew_angle(gray: np.ndarray) -> float:
    """Skew estimate by projection-profile search: the rotation that makes text rows sharpest
    (maximum variance of the row sums) is the page's skew. Robust for multi-column pages."""
    import cv2
    h, w = gray.shape
    if h < 100 or w < 100:
        return 0.0
    f = 1000 / max(h, w)
    small = cv2.resize(gray, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA)
    ink = (255 - cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]).astype(np.float32)
    if ink.sum() < 255 * 200:
        return 0.0
    center = (ink.shape[1] / 2, ink.shape[0] / 2)

    def score(a: float) -> float:
        m = cv2.getRotationMatrix2D(center, a, 1.0)
        rot = cv2.warpAffine(ink, m, (ink.shape[1], ink.shape[0]), flags=cv2.INTER_NEAREST, borderValue=0)
        return float(np.var(rot.sum(axis=1)))

    best = max(np.arange(-4.0, 4.01, 0.5), key=score)
    fine = max(np.arange(best - 0.5, best + 0.51, 0.1), key=score)
    return float(round(fine, 2))


def preprocess(img: Image.Image, dpi: int | None) -> tuple[Image.Image, float, float]:
    """Returns (image for OCR, scale factor applied, deskew angle applied)."""
    g = ImageOps.grayscale(img)
    scale = 1.0
    if dpi and dpi < 250:
        scale = 300 / dpi
    elif not dpi and max(g.size) < 1600:
        scale = 1600 / max(g.size)
    if scale > 1.01:
        g = g.resize((int(g.width * scale), int(g.height * scale)), Image.LANCZOS)
    arr = np.asarray(g)
    angle = _deskew_angle(arr)
    if abs(angle) > 0.3:
        g = g.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    else:
        angle = 0.0
    return _remove_rules(g), scale, angle


def _remove_rules(g: Image.Image) -> Image.Image:
    """Erase long horizontal / vertical lines (table grids, form boxes, chart axes and gridlines). Tesseract
    reads text inside ruled cells badly — a lab table often comes back with only one row — and the lines
    are never content. Geometry is unchanged, so word boxes stay valid."""
    import cv2
    arr = np.asarray(g)
    h, w = arr.shape[:2]
    if h < 60 or w < 60:
        return g
    bw = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    # far longer than any glyph stroke (a 24 pt capital at 300 dpi is ~100 px): only real rules match
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(150, w // 20), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(150, h // 12)))
    lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk) | cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk)
    if int(lines.sum()) < 255 * min(w, h) // 2:
        return g  # no real rules on this image
    lines = cv2.dilate(lines, np.ones((3, 3), np.uint8))
    out = arr.copy()
    out[lines > 0] = 255
    return Image.fromarray(out)


def ocr_image(img: Image.Image, dpi: int | None = None, lang: str = "eng") -> list[OcrWord]:
    """OCR an image; word boxes are returned in the *original* image's pixel coordinates."""
    t = _tess()
    proc, scale, angle = preprocess(img, dpi)
    words = _run(t, proc, lang, psm=3)
    mean_conf = np.mean([w.conf for w in words]) if words else 0
    if not words or mean_conf < 60:
        alt = _run(t, proc, lang, psm=6)
        if alt and (not words or np.mean([w.conf for w in alt]) > mean_conf + 5):
            words = alt
    if angle:
        words = _unrotate(words, angle, proc.size)
    if scale != 1.0:
        for w in words:
            w.x0, w.y0, w.x1, w.y1 = w.x0 / scale, w.y0 / scale, w.x1 / scale, w.y1 / scale
    return words


def _run(t, img: Image.Image, lang: str, psm: int) -> list[OcrWord]:
    data = t.image_to_data(img, lang=lang, config=f"--oem 1 --psm {psm} -c preserve_interword_spaces=1",
                           output_type=t.Output.DICT)
    out: list[OcrWord] = []
    for i, txt in enumerate(data["text"]):
        txt = (txt or "").strip()
        if not txt:
            continue
        conf = float(data["conf"][i]) if data["conf"][i] not in ("-1", -1) else 0.0
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        out.append(OcrWord(txt, x, y, x + w, y + h, conf, data["block_num"][i], data["par_num"][i],
                           data["line_num"][i]))
    return out


def _unrotate(words: list[OcrWord], angle: float, size: tuple[int, int]) -> list[OcrWord]:
    """Map boxes found on the deskewed image back onto the original (axis-aligned bounding box)."""
    cx, cy = size[0] / 2, size[1] / 2
    a = np.radians(angle)
    ca, sa = np.cos(a), np.sin(a)
    for w in words:
        pts = []
        for x, y in ((w.x0, w.y0), (w.x1, w.y0), (w.x0, w.y1), (w.x1, w.y1)):
            dx, dy = x - cx, y - cy
            # PIL rotates counter-clockwise by `angle`; invert it
            pts.append((cx + dx * ca - dy * sa, cy + dx * sa + dy * ca))
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        w.x0, w.y0, w.x1, w.y1 = min(xs), min(ys), max(xs), max(ys)
    return words


def words_to_text(words: list[OcrWord]) -> tuple[str, list[tuple[float, float, float, float] | None], list[int]]:
    """Build page text from OCR words. Returns (text, per-char boxes, per-char line ids)."""
    text_parts: list[str] = []
    boxes: list[tuple[float, float, float, float] | None] = []
    line_ids: list[int] = []
    prev_key = None
    prev_block = None
    line_no = 0
    # layout: words are placed at the character column matching their x position (like pdftotext -layout),
    # so a wide gap stays a column break and table headers line up with the values under them
    widths = sorted((w.x1 - w.x0) / max(len(w.text), 1) for w in words if w.text)
    cw = widths[len(widths) // 2] if widths else 10.0
    left = round(min(w.x0 for w in words) / cw) if words else 0
    col = 0
    for w in sorted(words, key=lambda w: (w.block, w.par, w.line, w.x0)):
        key = (w.block, w.par, w.line)
        if prev_key is not None:
            if key == prev_key:
                sep = " " * max(1, min(60, round(w.x0 / cw) - left - col))
            else:
                sep = "\n\n" if w.block != prev_block else "\n"
                col = 0
                sep += " " * min(60, max(0, round(w.x0 / cw) - left))
            col += len(sep) if "\n" not in sep else len(sep.rsplit("\n", 1)[1])
            for ch in sep:
                text_parts.append(ch)
                boxes.append(None)
                line_ids.append(-1)
        if key != prev_key:
            line_no += 1
        n = len(w.text)
        wcw = (w.x1 - w.x0) / max(n, 1)
        for k, ch in enumerate(w.text):
            text_parts.append(ch)
            boxes.append((w.x0 + k * wcw, w.y0, w.x0 + (k + 1) * wcw, w.y1))
            line_ids.append(line_no)
        col += n
        prev_key, prev_block = key, w.block
    return "".join(text_parts), boxes, line_ids

