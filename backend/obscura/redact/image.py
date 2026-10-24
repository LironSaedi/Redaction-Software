"""Image redaction (photos, scans): faces, plates, people, screens and any PII text in the picture."""
from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from ..detection.text.engine import AnalyzeOptions, SearchTerm, TextAnalyzer, get_analyzer
from ..detection.vision.detectors import VBox, get_detector
from . import ocr as ocrmod
from .effects import apply_effect
from .model import Box, Detection, PageText
from .pdf import PAGE_SEP, PdfDocument, char_range_boxes

VISUAL_PAD = {"face": 0.18, "head": 0.1, "license_plate": 0.12, "person": 0.03, "vehicle": 0.0, "screen": 0.03,
              "document": 0.03}
VISUAL_ENTITY = {"face": "FACE", "head": "FACE", "license_plate": "LICENSE_PLATE", "person": "PERSON_BODY",
                 "vehicle": "VEHICLE", "screen": "SCREEN", "document": "DOCUMENT_REGION"}


def load_image(path: str | Path) -> np.ndarray:
    im = Image.open(str(path))
    im = ImageOps.exif_transpose(im)  # honour camera orientation, then forget EXIF
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    arr = np.asarray(im.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _plate_shaped(vb, w: int, h: int) -> bool:
    bw, bh = vb.x1 - vb.x0, vb.y1 - vb.y0
    if bw <= 0 or bh <= 0:
        return False
    return (bw * bh) / float(w * h) <= 0.15 and 1.2 <= bw / bh <= 6.5


class ImageDocument:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.img = load_image(path)
        self.h, self.w = self.img.shape[:2]
        self.page: PageText | None = None

    def ocr(self) -> PageText:
        if self.page is None:
            words = ocrmod.ocr_image(Image.fromarray(cv2.cvtColor(self.img, cv2.COLOR_BGR2RGB))) \
                if ocrmod.available() else []
            # scene text in photos is noisy: keep only confident, mostly-alphanumeric words
            words = [w for w in words if w.conf >= 55 and sum(c.isalnum() for c in w.text) >= 0.6 * len(w.text)]
            text, boxes, lines = ocrmod.words_to_text(words)
            conf = (sum(w.conf for w in words) / len(words)) if words else None
            self.page = PageText(0, text, boxes, lines, self.w, self.h, "ocr", conf)
        return self.page

    def analyze(self, classes: set[str] | None = None, text: bool = True, options: AnalyzeOptions | None = None,
                analyzer: TextAnalyzer | None = None) -> list[Detection]:
        classes = classes if classes is not None else {"face", "head", "license_plate", "screen"}
        dets: list[Detection] = []
        if classes:
            for vb in get_detector().detect(self.img, classes):
                if vb.label == "license_plate" and not _plate_shaped(vb, self.w, self.h):
                    continue  # a "plate" filling a screenshot / chart is a false alarm on printed text
                pb = vb.padded(VISUAL_PAD.get(vb.label, 0.05), self.w, self.h)
                dets.append(Detection(entity=VISUAL_ENTITY.get(vb.label, vb.label.upper()), text="", score=vb.score,
                                      source=vb.source, boxes=[Box(0, pb.x0, pb.y0, pb.x1, pb.y1)], kind="visual",
                                      selected=vb.score >= (0.3 if vb.label in ("face", "head", "license_plate") else 0.45),
                                      explanation=f"{vb.label} detected ({vb.source}, {vb.score:.2f})",
                                      exemption="(b)(7)(C)" if vb.label in ("face", "head") else "(b)(6)"))
        if text:
            pt = self.ocr()
            if pt.text.strip():
                opts = options or AnalyzeOptions()
                opts.ocr_text = True
                spans = (analyzer or get_analyzer()).analyze(pt.text, opts)
                helper = _PageHelper(pt)
                dets += helper.to_dets(spans)
        return dets

    def classification_detection(self, faces: int | None = None) -> Detection:
        """The whole picture as one reviewable item, labelled with what kind of picture it is."""
        from ..detection.text.entities import ENTITIES
        from ..detection.vision.classify import SELECT_WHOLE, classify_image
        pt = self.page
        words = len(pt.text.split()) if pt is not None else None
        c = classify_image(self.img, ocr_words=words, faces=faces, ocr_conf=pt.ocr_conf if pt is not None else None)
        return Detection(entity=c.label, text="", score=c.confidence, source="classify:picture",
                         boxes=[Box(0, 0, 0, self.w, self.h)], kind="region", selected=c.label in SELECT_WHOLE,
                         explanation=f"picture classified as: {c.description} ({c.confidence:.0%})",
                         exemption=ENTITIES[c.label].exemption, meta={"class": c.label, "whole_picture": True})

    def search(self, terms: list[SearchTerm]) -> list[Detection]:
        pt = self.ocr()
        spans = TextAnalyzer._user_rules(pt.text, terms)
        for s in spans:
            s.meta["selected"] = True
        return _PageHelper(pt).to_dets(spans)

    def render(self, max_side: int = 1600, fmt: str = "PNG") -> bytes:
        im = Image.fromarray(cv2.cvtColor(self.img, cv2.COLOR_BGR2RGB))
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, fmt)
        return buf.getvalue()

    def marked_copy(self, detections: list[Detection], out_path: str | Path) -> dict:
        """Review copy: outlines and labels over the picture, nothing removed. Never for release."""
        out = self.img.copy()
        for d in detections:
            if not d.selected:
                continue
            for b in d.boxes:
                cv2.rectangle(out, (int(b.x0), int(b.y0)), (int(b.x1), int(b.y1)), (40, 40, 220), 2)
                cv2.putText(out, d.entity[:18], (int(b.x0), max(12, int(b.y0) - 4)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (40, 40, 220), 1, cv2.LINE_AA)
        h, w = out.shape[:2]
        cv2.putText(out, "REVIEW COPY - NOT REDACTED", (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, max(0.5, w / 1600),
                    (40, 40, 220), 2, cv2.LINE_AA)
        Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)).save(str(out_path))
        return {"redactions": 0, "marked_copy": True,
                "verification": {"passed": False, "issues": [{"type": "marked_copy_not_for_release"}]}}

    def apply(self, detections: list[Detection], out_path: str | Path, effect: str = "blackout",
              face_effect: str | None = None, verify: bool = True, padding: float = 0.0,
              enhance: dict | None = None) -> dict:
        out = self.img.copy()
        if enhance:
            from .effects import enhance_frame
            out = enhance_frame(out, **enhance)
        n = 0
        for d in detections:
            if not d.selected:
                continue
            eff = d.meta.get("effect") or ((face_effect or effect) if d.entity == "FACE" else effect)
            shape = d.meta.get("shape") or ("ellipse" if d.entity == "FACE" and eff in ("blur", "pixelate") else "rect")
            pts = d.meta.get("points")
            for b in d.boxes:
                apply_effect(out, b.x0 - padding, b.y0 - padding, b.x1 + padding, b.y1 + padding, eff, shape=shape,
                             points=[(p[0], p[1]) for p in pts] if pts else None)
                n += 1
        out_path = Path(out_path)
        rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        im = Image.fromarray(rgb)  # a brand-new image object: no EXIF, GPS, XMP, ICC comments
        fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF", ".webp": "WEBP",
               ".bmp": "BMP"}.get(out_path.suffix.lower(), "PNG")
        im.save(str(out_path), fmt, **({"quality": 95} if fmt == "JPEG" else {}))
        report = {"redactions": n, "metadata_removed": True}
        if verify:
            report["verification"] = verify_image(out, detections, original=self.img)
        return report


class _PageHelper:
    def __init__(self, pt: PageText):
        self.pt = pt

    def to_dets(self, spans) -> list[Detection]:
        from ..detection.text.engine import partial_ranges
        from ..detection.text.entities import ENTITIES
        out = []
        for sp in spans:
            partial = sp.meta.get("partial")
            ranges = [(sp.start + a, sp.start + b) for a, b in partial_ranges(sp.text, partial)] if partial else \
                [(sp.start, sp.end)]
            boxes = [b for a, e in ranges for b in char_range_boxes(self.pt, a, e, 0)]
            if not boxes:
                continue
            # OCR boxes are tight: pad a little more than for native PDF text
            boxes = [Box(0, b.x0 - 2, b.y0 - 2, b.x1 + 2, b.y1 + 2) for b in boxes]
            ent = ENTITIES.get(sp.entity)
            out.append(Detection(entity=sp.entity, text=sp.text, score=sp.score, source=sp.source, boxes=boxes,
                                 start=sp.start, end=sp.end, explanation=sp.explanation,
                                 selected=bool(sp.meta.get("selected", True)), partial=partial,
                                 exemption=sp.meta.get("exemption") or (ent.exemption if ent else "")))
        return out


def verify_image(img: np.ndarray, detections: list[Detection], original: np.ndarray | None = None) -> dict:
    """Re-run face/plate detection on the *output*; any confident detection not inside a redaction is a leak."""
    issues = []
    sel = [b for d in detections if d.selected for b in d.boxes]
    try:
        found = get_detector().detect(img, {"face", "license_plate"}, fast=False)
    except FileNotFoundError:
        found = []
    from .video import covered_fraction
    orig_found = get_detector().detect(original, {"face", "license_plate"}) if original is not None else None
    h, w = img.shape[:2]
    cover = [(b.x0, b.y0, b.x1, b.y1) for b in sel]
    for vb in found:
        if vb.score < 0.5:
            continue
        if vb.label == "license_plate" and not _plate_shaped(vb, w, h):
            continue  # same shape rule as detection: page-sized "plates" are printed text
        if orig_found is not None and not any(vb.iou(o) > 0.25 for o in orig_found if o.label == vb.label):
            continue  # not in the original: an artefact of the redaction itself
        if covered_fraction((vb.x0, vb.y0, vb.x1, vb.y1), cover, w, h) < 0.3:
            issues.append({"type": f"{vb.label}_visible", "score": round(vb.score, 2),
                           "box": [round(vb.x0), round(vb.y0), round(vb.x1), round(vb.y1)]})
    return {"passed": not issues, "issues": issues}


def tiff_to_pdf(path: str | Path, out: str | Path) -> Path:
    """Multi-page TIFF/fax → image PDF so it goes through the OCR'd PDF pipeline."""
    import pymupdf as fitz
    src = Image.open(str(path))
    doc = fitz.open()
    i = 0
    while True:
        try:
            src.seek(i)
        except EOFError:
            break
        frame = src.convert("RGB")
        buf = io.BytesIO()
        frame.save(buf, "PNG")
        dpi = float(src.info.get("dpi", (200, 200))[0] or 200)
        w, h = float(frame.width * 72 / dpi), float(frame.height * 72 / dpi)
        page = doc.new_page(width=w, height=h)
        page.insert_image(page.rect, stream=buf.getvalue())
        i += 1
    doc.save(str(out))
    return Path(out)
