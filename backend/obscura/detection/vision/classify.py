"""What kind of picture is this? Exhibits, photos, charts and scans inside documents are classified so a reviewer
can see them all in one list and redact any of them whole with one click.

Classes (entity keys):
    IMAGE_ID_CARD       driver's licence / ID / insurance card (a face plus card-shaped text)
    IMAGE_PHOTO_PERSON  a photograph with one or more people in it
    IMAGE_PHOTO         any other photograph (scene, vehicle damage, injury, property)
    IMAGE_SIGNATURE     a handwritten signature or initials
    IMAGE_MEDICAL       radiology / clinical image (X-ray, CT, MRI, ultrasound)
    IMAGE_CHART         a chart or graph (bar, line, pie, plot)
    IMAGE_TABLE         a picture of a table or form grid
    IMAGE_SCREENSHOT    a screenshot (text messages, a web page, an app screen)
    IMAGE_DOCUMENT      a picture of a document page (scan, photo of a letter)
    IMAGE_GRAPHIC       logo, icon, letterhead art, stamp

All local and fast: colour statistics, ink and line structure from OpenCV, the OCR word count the pipeline
already has, and the face detector. No extra model is downloaded.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

IMAGE_CLASSES = {
    "IMAGE_ID_CARD": "ID / licence / insurance card",
    "IMAGE_PHOTO_PERSON": "Photo of a person",
    "IMAGE_PHOTO": "Photo (scene / property / injury)",
    "IMAGE_SIGNATURE": "Handwritten signature",
    "IMAGE_MEDICAL": "Medical image (X-ray / CT / MRI / ultrasound)",
    "IMAGE_CHART": "Chart / graph",
    "IMAGE_TABLE": "Table / form image",
    "IMAGE_SCREENSHOT": "Screenshot (texts, web, app)",
    "IMAGE_DOCUMENT": "Picture of a document",
    "IMAGE_GRAPHIC": "Logo / graphic / stamp",
}
# whole-picture redaction pre-selected for these; the others are listed for the reviewer to decide
SELECT_WHOLE = {"IMAGE_ID_CARD", "IMAGE_SIGNATURE"}


@dataclass
class ImageClass:
    label: str
    confidence: float
    features: dict = field(default_factory=dict)

    @property
    def description(self) -> str:
        return IMAGE_CLASSES[self.label]


def _features(bgr: np.ndarray) -> dict:
    import cv2
    h, w = bgr.shape[:2]
    small = bgr if max(h, w) <= 800 else cv2.resize(bgr, (int(w * 800 / max(h, w)), int(h * 800 / max(h, w))),
                                                     interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    b, g, r = [c.astype(np.float32) for c in cv2.split(small)]
    rg, yb = np.abs(r - g), np.abs(0.5 * (r + g) - b)
    colorful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    white = float((gray > 225).mean())
    dark = float((gray < 40).mean())
    ink = float((gray < 128).mean())
    # distinct colours after coarse quantisation (charts / logos use a handful; photos thousands)
    q = (small // 32).reshape(-1, 3)
    palette = len(np.unique(q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]))
    qf = (small // 8).reshape(-1, 3).astype(np.int32)
    shades = len(np.unique(qf[:, 0] * 1024 + qf[:, 1] * 32 + qf[:, 2]))
    edges = cv2.Canny(gray, 60, 160)
    edge_density = float((edges > 0).mean())
    bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, sw // 6), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, sh // 6)))
    hl = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk)
    vl = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk)
    h_lines = int(cv2.connectedComponents((hl > 0).astype(np.uint8))[0] - 1)
    v_lines = int(cv2.connectedComponents((vl > 0).astype(np.uint8))[0] - 1)
    # texture: local variance is high and continuous in photos, concentrated at edges in graphics
    lap = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    return {"w": w, "h": h, "aspect": round(w / max(h, 1), 3), "colorful": round(colorful, 1), "white": round(white, 3),
            "dark": round(dark, 3), "ink": round(ink, 3), "palette": palette, "shades": shades, "edges": round(edge_density, 4),
            "h_lines": h_lines, "v_lines": v_lines, "texture": round(lap, 1),
            "gray_std": round(float(gray.std()), 1)}


def classify_image(bgr: np.ndarray, ocr_words: int | None = None, faces: int | None = None,
                   ocr_conf: float | None = None) -> ImageClass:
    """Classify one picture. ``ocr_words`` / ``faces`` may be passed when the caller already ran OCR / the face
    detector; otherwise they are computed here (OCR only when the picture looks text-bearing)."""
    f = _features(bgr)
    if faces is None:
        try:
            from .detectors import get_detector
            faces = sum(1 for vb in get_detector().detect(bgr, {"face"}) if vb.score >= 0.5)
        except Exception:
            faces = 0
    if ocr_words is None:
        ocr_words, ocr_conf = 0, 0.0
        if f["white"] > 0.25 or f["palette"] < 160:
            try:
                from PIL import Image
                import cv2

                from ...redact import ocr
                words = ocr.ocr_image(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
                good = [x for x in words if x.conf >= 55 and sum(c.isalnum() for c in x.text) >= 2]
                ocr_words = len(good)
                ocr_conf = (sum(x.conf for x in good) / len(good)) if good else 0.0
            except Exception:
                pass
    f.update(faces=faces, ocr_words=ocr_words, ocr_conf=round(ocr_conf or 0.0, 1))
    w, h, a = f["w"], f["h"], f["aspect"]
    # photographs: thousands of distinct shades and little flat background
    photo_like = f["shades"] > 1500 and f["white"] < 0.5
    grayish = f["colorful"] < 12

    def out(label: str, conf: float) -> ImageClass:
        return ImageClass(label, round(min(0.99, conf), 2), f)

    # ID / insurance card: card shape (ISO 7810 ~1.586), a face and a fair amount of text
    if faces and 1.35 <= a <= 1.85 and ocr_words >= 6:
        return out("IMAGE_ID_CARD", 0.85)
    if faces and photo_like:
        return out("IMAGE_PHOTO_PERSON", 0.8 + min(0.15, 0.05 * faces))
    # radiology: grey, mostly dark background, smooth gradations, almost no text
    if grayish and f["dark"] > 0.35 and ocr_words < 12:
        return out("IMAGE_MEDICAL", 0.75)
    # signature: a few thin dark strokes on white, wide, no recognisable words
    if f["white"] > 0.8 and f["ink"] < 0.08 and a >= 1.8 and ocr_words <= 3 and f["h_lines"] <= 2 and f["v_lines"] == 0:
        return out("IMAGE_SIGNATURE", 0.7)
    # table / form grid: several long rules both ways, with text
    if f["h_lines"] >= 3 and f["v_lines"] >= 2 and ocr_words >= 4:
        return out("IMAGE_TABLE", 0.75)
    # phone screenshot: tall, flat colours, several lines of text
    if ocr_words >= 8 and h / max(w, 1) >= 1.6 and f["shades"] < 1500:
        return out("IMAGE_SCREENSHOT", 0.7)
    # chart: few colours, mostly background, axes, some labels but not a page of text
    if f["palette"] < 140 and f["white"] > 0.45 and ocr_words <= 60 and (
            (f["h_lines"] >= 1 and f["v_lines"] >= 1) or f["colorful"] > 18):
        return out("IMAGE_CHART", 0.7)
    # screenshot: phone-shaped or screen-shaped, flat colours, lots of text
    if ocr_words >= 8 and f["shades"] < 1500 and a >= 1.7 and f["white"] < 0.9:
        return out("IMAGE_SCREENSHOT", 0.6)
    if ocr_words >= 20 and f["white"] > 0.4:
        return out("IMAGE_DOCUMENT", 0.75)
    if ocr_words >= 8 and f["palette"] < 200:
        return out("IMAGE_SCREENSHOT", 0.55)
    if photo_like:
        return out("IMAGE_PHOTO", 0.7)
    if max(w, h) < 260 or f["palette"] < 60:
        return out("IMAGE_GRAPHIC", 0.6)
    return out("IMAGE_PHOTO" if f["shades"] > 800 else "IMAGE_GRAPHIC", 0.45)
