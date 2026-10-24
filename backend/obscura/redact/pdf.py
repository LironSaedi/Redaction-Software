"""PDF handling: extraction with per-character geometry, OCR of scanned/hybrid pages, true redaction,
sanitisation and post-redaction verification.

True redaction means the underlying content is destroyed, not covered: MuPDF removes every glyph whose
box intersects a redaction rectangle from the page content stream, blanks the overlapping pixels of
every image, and deletes vector art the box fully covers. Afterwards the file is rewritten from scratch
(garbage collection level 4) so no orphaned objects or incremental-save history survive.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from ..config import settings
from ..detection.text.engine import AnalyzeOptions, SearchTerm, TextAnalyzer, get_analyzer, partial_ranges
from ..detection.text.entities import ENTITIES
from . import ocr as ocrmod
from .model import Box, Detection, ExportOptions, PageText

log = logging.getLogger("obscura.pdf")

PAGE_SEP = "\n\f\n"
_ALNUM = re.compile(r"[^0-9a-z]")


def _norm(s: str) -> str:
    return _ALNUM.sub("", s.lower())


@dataclass
class ExtractStats:
    native_pages: int = 0
    ocr_pages: int = 0
    hybrid_pages: int = 0
    ocr_conf: list[float] = field(default_factory=list)


class PdfDocument:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.doc = fitz.open(str(path))
        if self.doc.needs_pass:
            raise ValueError("PDF is password protected")
        self.pages: list[PageText] = []
        self.stats = ExtractStats()
        self._prepared = False
        self.form_fields: list[tuple[int, tuple, str, str]] = []  # (page, rect, field name, value)

    # ---------------------------------------------------------------------------------------
    # preparation
    # ---------------------------------------------------------------------------------------

    def prepare(self) -> None:
        """Make every piece of content visible to detection and redaction:
        * turn on all optional-content layers (text in a hidden layer is still in the file)
        * bake form-field values and annotation appearances into the page content
        """
        if self._prepared:
            return
        try:  # text in a layer switched off is not extracted unless the layer is turned on
            for i in range(len(self.doc.layer_ui_configs())):
                self.doc.set_layer_ui_config(i, action=0)
        except Exception:  # pragma: no cover
            pass
        # content beyond the crop box is invisible but still in the file: work on the full media box
        self.crops: dict[int, fitz.Rect] = {}
        for page in self.doc:
            if page.cropbox != page.mediabox:
                self.crops[page.number] = fitz.Rect(page.cropbox)
                page.set_cropbox(page.mediabox)
        # remember filled form fields before flattening: the field *name* ("patient_ssn") is the best label
        for page in self.doc:
            for w in page.widgets() or []:
                val = w.field_value
                if isinstance(val, str) and val.strip() and val not in ("Off", "Yes", "On"):
                    self.form_fields.append((page.number, tuple(w.rect), w.field_name or "", val.strip()))
        try:
            self.doc.bake(annots=True, widgets=True)
        except Exception:  # older MuPDF: drop widgets/annots after reading their values
            for page in self.doc:
                for a in list(page.annots() or []):
                    page.delete_annot(a)
        self._prepared = True

    # ---------------------------------------------------------------------------------------
    # extraction
    # ---------------------------------------------------------------------------------------

    def extract(self, ocr: str = "auto", dpi: int | None = None, progress=None) -> list[PageText]:
        """ocr: "auto" (OCR scanned and image-heavy pages), "always", or "never"."""
        self.prepare()
        dpi = dpi or settings.ocr_dpi
        have_ocr = ocrmod.available()
        self.pages = []
        n = len(self.doc)
        for i, page in enumerate(self.doc):
            pt = self._native(page, i)
            need_ocr = False
            if ocr == "always":
                need_ocr = True
            elif ocr == "auto":
                need_ocr = self._needs_ocr(page, pt)
            if need_ocr and have_ocr:
                pt = self._ocr_page(page, i, pt, dpi)
            elif ocr != "never" and have_ocr and self._text_bearing_images(page):
                # a digital page with a chart, screenshot or photo of a card in it: read the pictures too
                # (rotated pages are read whole: clip rectangles and image rectangles use different spaces there)
                pt = self._ocr_page(page, i, pt, dpi, clips=self._text_bearing_images(page) if not page.rotation else None)
            if pt.source == "native":
                self.stats.native_pages += 1
            elif pt.source == "ocr":
                self.stats.ocr_pages += 1
            else:
                self.stats.hybrid_pages += 1
            self.pages.append(pt)
            if progress:
                progress(i + 1, n)
        return self.pages

    @staticmethod
    def _native(page: fitz.Page, i: int) -> PageText:
        """Page text in reading layout. Text lines that share a baseline (table cells, form fields and their
        labels, columns of a flowsheet) are joined into one physical row, and each piece is placed at the
        character column matching its x position — like ``pdftotext -layout`` — so table headers sit above
        their values and a column gap stays a wide gap."""
        flags = fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE  # no MEDIABOX_CLIP: off-page text too
        raw = page.get_text("rawdict", flags=flags, sort=True)
        segs = []  # one per PDF text line: (y0, y1, x0, size, chars, horizontal)
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                chars, size = [], 10.0
                for span in line.get("spans", []):
                    size = span.get("size", 10) or 10
                    chars += [(ch["c"], tuple(ch["bbox"]), size) for ch in span.get("chars", [])]
                if not chars:
                    continue
                d = line.get("dir", (1, 0))
                lb = line.get("bbox", chars[0][1])
                segs.append((lb[1], lb[3], lb[0], size, chars, abs(d[1]) < 0.2 and d[0] > 0))
        horiz = [g for g in segs if g[5]]
        left = min((g[2] for g in horiz), default=0.0)
        rows: list[list] = []
        for g in sorted(horiz, key=lambda g: ((g[0] + g[1]) / 2, g[2])):
            mid = (g[0] + g[1]) / 2
            if rows:
                r = rows[-1]
                ry0, ry1 = min(x[0] for x in r), max(x[1] for x in r)
                overlap = min(ry1, g[1]) - max(ry0, g[0])
                if overlap > 0.5 * min(ry1 - ry0, g[1] - g[0]) and abs(mid - (ry0 + ry1) / 2) < 0.6 * g[3]:
                    r.append(g)
                    continue
            rows.append([g])
        rows += [[g] for g in segs if not g[5]]  # rotated / vertical text: each line on its own

        text: list[str] = []
        boxes: list = []
        lines: list[int] = []

        def put(ch: str, box, ln: int) -> None:
            text.append(ch)
            boxes.append(box)
            lines.append(ln)

        for line_no, row in enumerate(rows, 1):
            col = 0
            prev = None
            for g in sorted(row, key=lambda g: g[2]):
                for c, bb, size in g[4]:
                    cw = size * 0.5
                    if g[5]:
                        target = round((bb[0] - left) / cw)
                        if prev is None:
                            pad = min(60, max(0, target))
                        elif c != " " and text and text[-1] != " " and bb[0] - prev[2] > size * 0.35:
                            pad = max(1, min(60, target - col))  # positioned text with no space glyph
                        elif c != " " and text and text[-1] == " " and bb[0] - prev[2] > size * 1.2:
                            pad = max(0, min(60, target - col))  # a wide jump after a space: next column
                        else:
                            pad = 0
                        for _ in range(pad):
                            put(" ", None, line_no)
                        col += pad
                    put(c, bb, line_no)
                    col += 1
                    prev = bb
            put("\n", None, -1)
        put("\n", None, -1)
        r = page.rect
        return PageText(i, "".join(text), boxes, lines, r.width, r.height, "native")

    def _marked_copy(self, chosen: list[Detection], out_path: str | Path, opts: ExportOptions) -> dict:
        """A review copy: every redaction drawn as a coloured outline with its type and exemption, content left
        in place, stamped REVIEW COPY on every page. For internal QC / supervisor sign-off only — never released."""
        for d in chosen:
            e = ENTITIES.get(d.entity)
            color = _CAT_COLORS.get(e.category if e else "CUSTOM", (0.35, 0.35, 0.35))
            tag = (e.label if e else d.entity) + (f" · {d.exemption}" if d.exemption else "")
            for b in d.boxes:
                if b.page >= len(self.doc):
                    continue
                page = self.doc[b.page]
                r = fitz.Rect(b.x0, b.y0, b.x1, b.y1)
                if r.is_empty:
                    continue
                page.draw_rect(r, color=color, width=1.2, fill=color, fill_opacity=0.18)
                page.insert_text((r.x0, max(6, r.y0 - 1.5)), tag[:40], fontsize=5.5, color=color)
        for page in self.doc:
            _watermark(page, "REVIEW COPY - NOT REDACTED")
        self.doc.save(str(out_path), garbage=3, deflate=True)
        return {"redactions": 0, "detections": len(chosen), "marked_copy": True,
                "verification": {"passed": False, "issues": [{"type": "marked_copy_not_for_release"}]}}

    @staticmethod
    def _needs_ocr(page: fitz.Page, pt: PageText) -> bool:
        n_chars = sum(1 for c in pt.text if c.isalnum())
        page_area = page.rect.width * page.rect.height or 1
        img_area = 0.0
        for img in page.get_images(full=True):
            try:
                for rect in page.get_image_rects(img[0]):
                    img_area += abs(rect & page.rect)
            except Exception:
                continue
        cover = img_area / page_area
        if n_chars < 25 and cover > 0.05:
            return True  # scanned page
        if cover > 0.25:
            return True  # hybrid: digital page with an embedded scan / photo of a document
        if n_chars < 25 and len(page.get_drawings()) > 400:
            return True  # text drawn as vector outlines
        return False

    @staticmethod
    def _text_bearing_images(page: fitz.Page) -> list[fitz.Rect]:
        """Displayed image areas big enough to hold readable text (charts, screenshots, scanned inserts,
        photos of ID cards). Tiny icons and rules are skipped."""
        rects: list[fitz.Rect] = []
        for img in page.get_images(full=True):
            try:
                for r in page.get_image_rects(img[0]):
                    r = r & page.rect
                    if r.width >= 50 and r.height >= 14 and not any(abs(r & x) > 0.8 * abs(r) for x in rects):
                        rects.append(fitz.Rect(r))
            except Exception:
                continue
        return rects

    def _ocr_page(self, page: fitz.Page, i: int, native: PageText, dpi: int,
                  clips: list[fitz.Rect] | None = None) -> PageText:
        zoom = dpi / 72.0
        words = []
        regions = clips or [None]
        for clip in regions:
            # page coordinates of each region are recovered below; OCR runs on the rendered page so the
            # derotation logic is the same for full pages and for image regions
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False, clip=clip)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            ox, oy = (clip.x0 * zoom, clip.y0 * zoom) if clip is not None else (0.0, 0.0)
            for w in ocrmod.ocr_image(img, dpi=dpi):
                w.x0, w.x1, w.y0, w.y1 = w.x0 + ox, w.x1 + ox, w.y0 + oy, w.y1 + oy
                words.append(w)
        if clips:
            words = [w for w in words if w.conf >= 50]
        derot = page.derotation_matrix
        native_boxes = [fitz.Rect(b) for b in native.boxes if b]
        kept = []
        for w in words:
            r = fitz.Rect(w.x0 / zoom, w.y0 / zoom, w.x1 / zoom, w.y1 / zoom) * derot
            if native_boxes and any(abs(r & nb) > 0.3 * abs(r) for nb in native_boxes if nb.intersects(r)):
                continue  # already covered by real text
            w.x0, w.y0, w.x1, w.y1 = r.x0, r.y0, r.x1, r.y1
            kept.append(w)
        if not kept:
            return native
        o_text, o_boxes, o_lines = ocrmod.words_to_text(kept)
        conf = sum(w.conf for w in kept) / len(kept)
        self.stats.ocr_conf.append(conf)
        if native.text.strip():
            base = len(native.lines) and max(native.lines) + 1
            return PageText(i, native.text + "\n" + o_text, native.boxes + [None] + o_boxes,
                            native.lines + [-1] + [ln + base if ln >= 0 else -1 for ln in o_lines],
                            native.width, native.height, "hybrid", conf)
        return PageText(i, o_text, o_boxes, o_lines, native.width, native.height, "ocr", conf)

    # ---------------------------------------------------------------------------------------
    # analysis
    # ---------------------------------------------------------------------------------------

    def full_text(self) -> tuple[str, list[int]]:
        offs, parts, pos = [], [], 0
        for pt in self.pages:
            offs.append(pos)
            parts.append(pt.text)
            pos += len(pt.text) + len(PAGE_SEP)
        return PAGE_SEP.join(parts), offs

    def analyze(self, options: AnalyzeOptions | None = None, analyzer: TextAnalyzer | None = None) -> list[Detection]:
        if not self.pages:
            self.extract()
        opts = options or AnalyzeOptions()
        if any(p.source != "native" for p in self.pages):
            opts.ocr_text = True
        text, offs = self.full_text()
        an = analyzer or get_analyzer()
        spans = an.analyze(text, opts)
        return self.spans_to_detections(spans, offs) + self._form_field_detections(an, opts)

    def _form_field_detections(self, an: TextAnalyzer, opts: AnalyzeOptions) -> list[Detection]:
        """Each filled field is analysed as "Field Name: value"; the whole field box is redacted."""
        out = []
        for pno, rect, name, value in self.form_fields:
            label = _humanize_field(name)
            line = f"{label}: {value}"
            spans = [sp for sp in an.analyze(line, opts) if sp.end > len(label) + 2]
            if spans:
                sp = max(spans, key=lambda x: x.score)
                ent = ENTITIES.get(sp.entity)
                out.append(Detection(entity=sp.entity, text=value, score=max(sp.score, 0.9), source="form:" + sp.source,
                                     boxes=[Box(pno, *rect)], page=pno, explanation=f"filled form field “{label}”",
                                     selected=bool(sp.meta.get("selected", True)),
                                     exemption=ent.exemption if ent else ""))
            elif len(value) >= 2:
                # privacy-first: any other typed-in value is shown to the reviewer as a suggestion
                out.append(Detection(entity="CUSTOM", text=value, score=0.45, source="form:field", boxes=[Box(pno, *rect)],
                                     page=pno, explanation=f"filled form field “{label}”", selected=False))
        return out

    def spans_to_detections(self, spans, offs: list[int]) -> list[Detection]:
        dets: list[Detection] = []
        for sp in spans:
            for p, off in enumerate(offs):
                pt = self.pages[p]
                lo, hi = off, off + len(pt.text)
                if sp.end <= lo or sp.start >= hi:
                    continue
                s, e = max(sp.start, lo) - off, min(sp.end, hi) - off
                partial = sp.meta.get("partial")
                ranges = [(s + a, s + b) for a, b in partial_ranges(pt.text[s:e], partial)] if partial else [(s, e)]
                boxes = []
                for a, b in ranges:
                    boxes += char_range_boxes(pt, a, b, p)
                if not boxes:
                    continue
                ent = ENTITIES.get(sp.entity)
                dets.append(Detection(
                    entity=sp.entity, text=pt.text[s:e], score=sp.score, source=sp.source, boxes=boxes, page=p,
                    start=s, end=e, explanation=sp.explanation, selected=bool(sp.meta.get("selected", True)),
                    exemption=sp.meta.get("exemption") or (ent.exemption if ent else ""), partial=partial,
                    meta={k: v for k, v in sp.meta.items() if k in ("sources", "alt_entities", "sentence")}))
        return dets

    def search(self, terms: list[SearchTerm]) -> list[Detection]:
        if not self.pages:
            self.extract()
        text, offs = self.full_text()
        spans = TextAnalyzer._user_rules(text, terms)
        for s in spans:
            s.meta["selected"] = True
        return self.spans_to_detections(spans, offs)

    # ---------------------------------------------------------------------------------------
    # rendering
    # ---------------------------------------------------------------------------------------

    def render_page(self, i: int, dpi: int = 110, fmt: str = "png") -> bytes:
        page = self.doc[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        return pix.tobytes(fmt)

    def page_info(self) -> list[dict]:
        out = []
        for i, page in enumerate(self.doc):
            pt = self.pages[i] if i < len(self.pages) else None
            out.append({"page": i, "width": page.rect.width, "height": page.rect.height, "rotation": page.rotation,
                        "source": pt.source if pt else "native",
                        "ocr_conf": round(pt.ocr_conf, 1) if pt and pt.ocr_conf else None,
                        "matrix": list(page.rotation_matrix)})
        return out

    # ---------------------------------------------------------------------------------------
    # redaction
    # ---------------------------------------------------------------------------------------

    def apply(self, detections: list[Detection], out_path: str | Path, opts: ExportOptions | None = None) -> dict:
        opts = opts or ExportOptions()
        self.prepare()
        style = opts.style
        chosen = [d for d in detections if d.selected]
        per_page: dict[int, int] = {}
        if opts.marked_copy:
            return self._marked_copy(chosen, out_path, opts)
        pad = max(0.0, float(opts.padding or 0.0))
        for d in chosen:
            label = d.meta.get("label_text") or _label_for(d, style)
            fill = tuple(d.meta["fill"]) if d.meta.get("fill") else style.fill
            for b in d.boxes:
                if b.page >= len(self.doc):
                    continue
                page = self.doc[b.page]
                rect = fitz.Rect(b.x0 - pad, b.y0 - pad, b.x1 + pad, b.y1 + pad) & page.mediabox
                if rect.is_empty or rect.is_infinite:
                    continue
                shape = d.meta.get("shape")
                if shape in ("ellipse", "polygon"):
                    from .shapes import ellipse_points, polygon_strips
                    pts = [tuple(p) for p in d.meta.get("points") or []] if shape == "polygon" else \
                        ellipse_points(rect.x0, rect.y0, rect.x1, rect.y1)
                    for sx0, sy0, sx1, sy1 in polygon_strips(pts):
                        page.add_redact_annot(fitz.Rect(sx0 - pad, sy0, sx1 + pad, sy1), fill=fill, cross_out=False)
                    per_page[b.page] = per_page.get(b.page, 0) + 1
                    continue
                fontsize = max(4.0, min(9.0, rect.height * 0.7))
                page.add_redact_annot(rect, text=label or None, fill=fill, text_color=style.text_color,
                                      fontsize=fontsize, align=fitz.TEXT_ALIGN_CENTER, cross_out=False)
                per_page[b.page] = per_page.get(b.page, 0) + 1
        # anything outside the originally visible area is destroyed outright
        for pno, crop in self.crops.items():
            page = self.doc[pno]
            mb = page.rect
            for strip in (fitz.Rect(mb.x0, mb.y0, mb.x1, crop.y0), fitz.Rect(mb.x0, crop.y1, mb.x1, mb.y1),
                          fitz.Rect(mb.x0, crop.y0, crop.x0, crop.y1), fitz.Rect(crop.x1, crop.y0, mb.x1, crop.y1)):
                if strip.width > 0.5 and strip.height > 0.5:
                    page.add_redact_annot(strip, fill=(1, 1, 1))
                    per_page[pno] = per_page.get(pno, 0) + 1
        for pno in per_page:
            self.doc[pno].apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS,
                                           graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                                           text=fitz.PDF_REDACT_TEXT_REMOVE)
        for pno, crop in self.crops.items():
            self.doc[pno].set_cropbox(crop)
        if opts.flatten_to_image:
            self._flatten()
        if opts.watermark:
            for page in self.doc:
                _watermark(page, opts.watermark)
        if opts.bates_prefix is not None:
            for k, page in enumerate(self.doc):
                stamp = f"{opts.bates_prefix}{opts.bates_start + k:0{opts.bates_digits}d}"
                r = page.rect
                page.insert_text(fitz.Point(r.x1 - 12 - len(stamp) * 5.2, r.y1 - 12), stamp, fontsize=9,
                                 fontname="helv", color=(0, 0, 0))
        sanitized = sanitize(self.doc) if opts.remove_metadata else {}
        save_kwargs = dict(garbage=4, deflate=True, clean=True)
        if opts.password:
            save_kwargs.update(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=opts.password,
                               owner_pw=opts.password + "#owner",
                               permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_ACCESSIBILITY)
        out_path = Path(out_path)
        self.doc.save(str(out_path), **save_kwargs)
        report = {"redactions": sum(len(d.boxes) for d in chosen), "detections": len(chosen),
                  "pages_touched": sorted(per_page), "sanitized": sanitized}
        if opts.verify:
            report["verification"] = verify_pdf(out_path, chosen, self.pages, opts.password)
        return report

    def _flatten(self) -> None:
        new = fitz.open()
        for page in self.doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False)
            np_ = new.new_page(width=page.rect.width, height=page.rect.height)
            np_.insert_image(np_.rect, stream=pix.tobytes("png"))
        self.doc.close()
        self.doc = new

    def close(self) -> None:
        self.doc.close()


def _humanize_field(name: str) -> str:
    """"txtPatientName" / "patient_name" / "Patient.SSN[0]" → "Patient Name" / "Patient SSN"."""
    n = re.sub(r"\[\d+\]", "", name.split(".")[-1] if "." in name else name)
    n = re.sub(r"^(?:txt|fld|field|tb|cb|chk)(?=[A-Z_])", "", n)
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n).replace("_", " ").replace("-", " ")
    words = [w.upper() if w.lower() in ("ssn", "dob", "mrn", "id", "dl", "npi", "ein", "zip", "vin") else w.capitalize()
             for w in n.split()]
    return " ".join(words) or "Field"


def char_range_boxes(pt: PageText, a: int, b: int, page: int) -> list[Box]:
    """Union character boxes per line for text[a:b]."""
    groups: dict[int, list] = {}
    order: list[int] = []
    for k in range(max(0, a), min(b, len(pt.boxes))):
        bb = pt.boxes[k]
        if bb is None:
            continue
        ln = pt.lines[k]
        if ln not in groups:
            groups[ln] = []
            order.append(ln)
        groups[ln].append(bb)
    out = []
    for ln in order:
        bs = groups[ln]
        x0 = min(x[0] for x in bs)
        y0 = min(x[1] for x in bs)
        x1 = max(x[2] for x in bs)
        y1 = max(x[3] for x in bs)
        h = y1 - y0
        # small vertical pad catches descenders/accents; tiny horizontal pad avoids eating neighbours
        out.append(Box(page, x0 - 0.4, y0 - h * 0.06, x1 + 0.4, y1 + h * 0.06))
    return out


_CAT_COLORS = {"PII": (0.85, 0.15, 0.15), "PHI": (0.1, 0.45, 0.85), "PCI": (0.85, 0.5, 0.0),
               "LEGAL": (0.45, 0.2, 0.7), "INDIRECT": (0.0, 0.6, 0.5), "VISUAL": (0.75, 0.1, 0.55),
               "CUSTOM": (0.35, 0.35, 0.35)}


def _label_for(d: Detection, style) -> str:
    if style.label == "entity":
        e = ENTITIES.get(d.entity)
        return (e.label if e else d.entity).upper()
    if style.label == "exemption":
        return d.exemption or ""
    if style.label == "custom":
        return style.custom_text
    return ""


def _watermark(page: fitz.Page, text: str) -> None:
    r = page.rect
    size = max(24, min(72, r.width / max(6, len(text)) * 1.6))
    center = fitz.Point(r.width / 2, r.height / 2)
    width = fitz.get_text_length(text, fontname="helv", fontsize=size)
    page.insert_text(fitz.Point(center.x - width / 2, center.y), text, fontsize=size, fontname="helv",
                     color=(0.6, 0.6, 0.6), fill_opacity=0.25, stroke_opacity=0.25,
                     morph=(center, fitz.Matrix(-35)), overlay=True)


def sanitize(doc: fitz.Document) -> dict:
    """Remove every place sensitive data hides outside the visible page content."""
    done = {}
    try:
        doc.scrub(attached_files=True, clean_pages=True, embedded_files=True, hidden_text=True, javascript=True,
                  metadata=True, redactions=True, redact_images=0, remove_links=True, reset_fields=True,
                  reset_responses=True, thumbnails=True, xml_metadata=True)
        done["scrub"] = True
    except Exception as e:  # pragma: no cover
        done["scrub_error"] = str(e)
    try:  # no hidden layers in a released file
        cat = doc.pdf_catalog()
        if doc.xref_get_key(cat, "OCProperties")[0] != "null":
            doc.xref_set_key(cat, "OCProperties", "null")
            done["layers_flattened"] = True
    except Exception:  # pragma: no cover
        pass
    try:
        for name in list(doc.embfile_names()):
            doc.embfile_del(name)
        doc.set_metadata({})
        doc.del_xml_metadata()
        doc.set_toc([])
        done["metadata"] = done["bookmarks"] = done["embedded_files"] = True
    except Exception as e:  # pragma: no cover
        done["metadata_error"] = str(e)
    try:
        if doc.is_pdf and doc.get_page_labels():
            doc.set_page_labels([])
    except Exception:
        pass
    for page in doc:
        for a in list(page.annots() or []):
            page.delete_annot(a)
        for link in page.get_links():
            page.delete_link(link)
    done["annotations"] = done["links"] = True
    return done


def verify_pdf(path: str | Path, detections: list[Detection], pages_before: list[PageText] | None,
               password: str | None = None) -> dict:
    """Independent check of the exported file. Any issue here means the export must not be released."""
    doc = fitz.open(str(path))
    if doc.needs_pass:
        doc.authenticate(password or "")
    issues: list[dict] = []
    # 1) nothing extractable inside any redaction box
    labels = {_norm(e.label) for e in ENTITIES.values()} | {"redacted"}
    for d in detections:
        for b in d.boxes:
            if b.page >= len(doc):
                continue
            r = fitz.Rect(b.x0 + 0.8, b.y0 + 0.8, b.x1 - 0.8, b.y1 - 0.8)
            if r.is_empty:
                continue
            # characters whose centre lies under the box (a glyph of the line above / below that only grazes
            # the box edge is not hidden text)
            raw = doc[b.page].get_text("rawdict", clip=r)
            left = "".join(ch["c"] for blk in raw.get("blocks", []) for line in blk.get("lines", [])
                           for sp in line.get("spans", []) for ch in sp.get("chars", [])
                           if r.contains(fitz.Point((ch["bbox"][0] + ch["bbox"][2]) / 2,
                                                    (ch["bbox"][1] + ch["bbox"][3]) / 2)))
            ln = _norm(left)
            if ln and ln not in labels and not re.fullmatch(r"b\d+(?:b\d+)*[a-z]*|[a-z]{2,6}", ln or "x"):
                issues.append({"type": "text_under_box", "page": b.page, "entity": d.entity,
                               "characters": len(ln)})  # never store the leaked text itself
    # 2) redacted values must not appear anywhere in the document's text (all pages, no clipping)
    flags = fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE
    all_text = _norm(" ".join(p.get_text("text", flags=flags) for p in doc))
    for d in detections:
        if d.partial:
            continue
        v = _norm(d.text)
        if len(v) >= 5 and not v.isalpha() and v in all_text:
            issues.append({"type": "value_still_present", "page": d.page, "entity": d.entity})
        elif len(v) >= 6 and v.isalpha() and v in all_text and d.entity not in ("PERSON",):
            issues.append({"type": "value_still_present", "page": d.page, "entity": d.entity})
    # 3) image pixels under boxes are solid
    for d in detections:
        for b in d.boxes[:3]:
            if b.page >= len(doc):
                continue
            page = doc[b.page]
            if not page.get_images():
                continue
            r = fitz.Rect(b.x0 + 1, b.y0 + 1, b.x1 - 1, b.y1 - 1)
            if r.is_empty or r.width < 3 or r.height < 3:
                continue
            pix = page.get_pixmap(clip=r, matrix=fitz.Matrix(1, 1), alpha=False, colorspace=fitz.csGRAY)
            data = pix.samples
            if data and (max(data) - min(data)) > 60:
                issues.append({"type": "pixels_not_destroyed", "page": b.page, "entity": d.entity})
    # 4) hidden carriers
    meta = {k: v for k, v in (doc.metadata or {}).items() if v and k not in ("format", "encryption")}
    if meta:
        issues.append({"type": "metadata_present", "fields": sorted(meta)})
    if doc.get_xml_metadata():
        issues.append({"type": "xmp_present"})
    if doc.embfile_count():
        issues.append({"type": "embedded_files_present", "count": doc.embfile_count()})
    for page in doc:
        if list(page.annots() or []):
            issues.append({"type": "annotations_present", "page": page.number})
            break
    n_pages = len(doc)
    doc.close()
    return {"passed": not issues, "issues": issues, "pages": n_pages, "checks": [
        "no_text_under_redactions", "values_absent_from_document", "image_pixels_destroyed", "no_metadata",
        "no_xmp", "no_embedded_files", "no_annotations"]}


def _mask(s: str) -> str:
    s = s.strip()
    return (s[:1] + "…" + s[-1:]) if len(s) > 2 else "…"
