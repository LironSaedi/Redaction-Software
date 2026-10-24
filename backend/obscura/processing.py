"""File-type orchestration: ingest → analyze → (review) → export, for every supported format."""
from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
import re
import shutil
import threading
import time
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

from .db import Case, Export, File, Template, TermList, tx, utcnow
from .detection.text.engine import AnalyzeOptions, SearchTerm
from .detection.text.entities import ENTITIES, entities_for_profile
from .redact.model import Box, Detection, ExportOptions, PageText, RedactionStyle
from .storage import get_storage

log = logging.getLogger("obscura.processing")

KIND_BY_EXT = {
    "pdf": "pdf", "png": "image", "jpg": "image", "jpeg": "image", "webp": "image", "bmp": "image", "heic": "image",
    "tif": "tiff", "tiff": "tiff", "gif": "image",
    "mp4": "video", "mov": "video", "avi": "video", "mkv": "video", "m4v": "video", "wmv": "video", "webm": "video",
    "mpg": "video", "mpeg": "video", "ts": "video", "3gp": "video",
    "wav": "audio", "mp3": "audio", "m4a": "audio", "aac": "audio", "flac": "audio", "ogg": "audio", "wma": "audio",
    "aiff": "audio", "aif": "audio", "opus": "audio",
    "docx": "docx", "docm": "docx", "pptx": "pptx", "xlsx": "xlsx", "xlsm": "xlsx",
    "eml": "email", "msg": "email", "mbox": "mailbox", "mbx": "mailbox", "pst": "mailbox", "ost": "mailbox",
    "txt": "text", "csv": "text", "md": "text", "json": "text", "log": "text", "html": "text", "htm": "text",
    "xml": "text", "rtf": "text", "tsv": "text",
    # bank / accounting downloads (Quicken, QuickBooks, SWIFT MT940 statements)
    "ofx": "text", "qfx": "text", "qbo": "text", "qif": "text", "iif": "text", "sta": "text", "mt940": "text",
}
UNSUPPORTED_HINT = {"doc": "legacy Word .doc — save as .docx", "xls": "legacy Excel .xls — save as .xlsx",
                    "ppt": "legacy PowerPoint .ppt — save as .pptx"}
VIDEO_OUT = ".mp4"


def kind_for(name: str) -> tuple[str, str]:
    ext = Path(name).suffix.lower().lstrip(".")
    if ext in UNSUPPORTED_HINT:
        raise ValueError(f"unsupported format: {UNSUPPORTED_HINT[ext]}")
    if ext not in KIND_BY_EXT:
        raise ValueError(f"unsupported file type .{ext}")
    return KIND_BY_EXT[ext], ext


# ---------------------------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------------------------

def split_mailbox(src: Path, filename: str, out_dir: Path) -> list[Path]:
    """A mailbox (MBOX, or Outlook PST / OST via the open-source ``readpst``) becomes one .eml per message."""
    import mailbox
    import shutil
    import subprocess
    ext = filename.rsplit(".", 1)[-1].lower()
    out: list[Path] = []
    if ext in ("pst", "ost"):
        exe = shutil.which("readpst")
        if not exe:
            raise ValueError("Outlook PST/OST import needs the open-source 'readpst' tool "
                             "(macOS: brew install libpst · Debian/Ubuntu: apt install pst-utils); "
                             "or export the folder from Outlook as .msg/.eml")
        subprocess.run([exe, "-e", "-q", "-o", str(out_dir), str(src)], check=True, capture_output=True, timeout=3600)
        out = sorted(p for p in out_dir.rglob("*") if p.is_file() and p.suffix.lower() in (".eml", "") and p.stat().st_size)
    else:
        box = mailbox.mbox(str(src), create=False)
        for i, msg in enumerate(box, 1):
            p = out_dir / f"message-{i:05d}.eml"
            p.write_bytes(msg.as_bytes())
            out.append(p)
    return out


def ingest(case_id: int, src: Path, filename: str, user_id: int | None, parent_id: int | None = None) -> list[int]:
    """Store an uploaded file (encrypted) and prepare its working representation. Returns file ids
    created (an email yields itself plus one file per attachment; a mailbox yields every message)."""
    st = get_storage()
    kind, ext = kind_for(filename)
    if kind == "mailbox":
        stem = filename.rsplit(".", 1)[0]
        d = st.scratch_dir()
        try:
            ids: list[int] = []
            for k, p in enumerate(split_mailbox(src, filename, d), 1):
                ids += ingest(case_id, p, f"{stem} - message {k:05d}.eml", user_id, parent_id)
            if not ids:
                raise ValueError("no messages found in the mailbox")
            return ids
        finally:
            import shutil as _sh
            _sh.rmtree(d, ignore_errors=True)
    blob, sha, size = st.put_file(src)
    info: dict = {}
    working = None
    page_count, duration = 0, 0.0
    children: list[tuple[str, bytes]] = []
    if kind == "pdf":
        import pymupdf as fitz
        with fitz.open(str(src)) as d:
            if d.needs_pass:
                raise ValueError("password-protected PDF: remove the password before uploading")
            page_count = len(d)
            info["metadata"] = {k: bool(v) for k, v in (d.metadata or {}).items() if k not in ("format", "encryption")}
            info["has_forms"] = bool(d.is_form_pdf)
    elif kind == "tiff":
        from .redact.image import tiff_to_pdf
        with st.scratch(".pdf") as tmp:
            tiff_to_pdf(src, tmp)
            working = st.put_file(tmp)[0]
            import pymupdf as fitz
            with fitz.open(str(tmp)) as d:
                page_count = len(d)
        kind = "pdf"
        info["converted_from"] = "tiff"
    elif kind == "email":
        from .redact.email_doc import email_to_pdf, load_email
        parsed = load_email(src)
        with st.scratch(".pdf") as tmp:
            email_to_pdf(parsed, tmp)
            working = st.put_file(tmp)[0]
            import pymupdf as fitz
            with fitz.open(str(tmp)) as d:
                page_count = len(d)
        children = parsed.attachments
        info["attachments"] = len(children)
        info["converted_from"] = "email"
        kind = "pdf"  # reviewed and redacted as its PDF print
    elif kind == "image":
        from PIL import Image
        with Image.open(str(src)) as im:
            info["width"], info["height"] = im.size
            info["exif"] = bool(im.info.get("exif")) or bool(getattr(im, "getexif", lambda: {})())
        page_count = 1
    elif kind == "video":
        from .redact.video import probe
        vi = probe(src)
        info.update(vi.to_dict())
        duration = vi.duration
    elif kind == "audio":
        from .redact.video import probe_duration
        duration = probe_duration(src)
    with tx() as s:
        f = File(case_id=case_id, parent_id=parent_id, name=Path(filename).name, kind=kind, ext=ext,
                 mime=mimetypes.guess_type(filename)[0] or "", size=size, sha256=sha, original_blob=blob,
                 working_blob=working, page_count=page_count, duration=duration, info=info, uploaded_by=user_id)
        s.add(f)
        s.flush()
        ids = [f.id]
    for name, data in children:
        try:
            kind_for(name)
        except ValueError:
            continue
        with st.scratch(Path(name).suffix) as tmp:
            tmp.write_bytes(data)
            ids += ingest(case_id, tmp, name, user_id, parent_id=ids[0])
    return ids


# ---------------------------------------------------------------------------------------------
# working copies (decrypted, cached briefly for page rendering / review)
# ---------------------------------------------------------------------------------------------

class _WorkCache:
    def __init__(self, cap: int = 6, ttl: float = 900):
        self.cap, self.ttl = cap, ttl
        self.items: OrderedDict[str, tuple[Path, float]] = OrderedDict()
        self.lock = threading.Lock()

    def path(self, blob: str, suffix: str) -> Path:
        st = get_storage()
        with self.lock:
            now = time.time()
            for k in [k for k, (_, t) in self.items.items() if now - t > self.ttl]:
                self._drop(k)
            if blob in self.items:
                p, _ = self.items.pop(blob)
                if p.exists():
                    self.items[blob] = (p, now)
                    return p
            d = st.scratch_dir()
            p = d / f"work{suffix}"
            with open(p, "wb") as fh:
                for chunk in st.stream(blob):
                    fh.write(chunk)
            self.items[blob] = (p, now)
            while len(self.items) > self.cap:
                self._drop(next(iter(self.items)))
            return p

    def _drop(self, k: str) -> None:
        p, _ = self.items.pop(k)
        from .storage import _wipe_tree
        _wipe_tree(p.parent)

    def clear(self) -> None:
        with self.lock:
            for k in list(self.items):
                self._drop(k)


WORK = _WorkCache()


def working_path(f: File) -> Path:
    blob = f.working_blob or f.original_blob
    suffix = ".pdf" if f.working_blob and f.kind == "pdf" else f".{f.ext}"
    return WORK.path(blob, suffix)


# ---------------------------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------------------------

def build_options(params: dict, case: Case | None, s) -> AnalyzeOptions:
    profile = params.get("profile") or (case.default_profile if case else "standard")
    entities = set(params["entities"]) if params.get("entities") else None
    terms = [SearchTerm(**t) if isinstance(t, dict) else SearchTerm(text=str(t)) for t in params.get("terms", [])]
    allow: list[str] = list(params.get("allow_list", []))
    st = get_storage()
    list_ids = params.get("list_ids") or []
    q = s.query(TermList)
    lists = q.filter((TermList.id.in_(list_ids)) | (TermList.case_id == (case.id if case else -1))).all() if list_ids \
        else q.filter(TermList.case_id == (case.id if case else -1)).all()
    for tl in lists:
        for t in st.get_json(tl.terms_blob):
            if tl.kind == "allow":
                allow.append(t["text"] if isinstance(t, dict) else str(t))
            else:
                d = t if isinstance(t, dict) else {"text": str(t)}
                terms.append(SearchTerm(text=d["text"], entity=d.get("entity") or tl.entity, regex=d.get("regex", False),
                                        case_sensitive=d.get("case_sensitive", False),
                                        whole_word=d.get("whole_word", True), exemption=tl.exemption or None,
                                        label=tl.name))
    if case and case.dictionary_blob and params.get("use_case_dictionary", True):
        for v in st.get_json(case.dictionary_blob):
            terms.append(SearchTerm(text=v["text"], entity=v["entity"], label="case dictionary"))
    use_ml = params.get("use_ml", True)
    return AnalyzeOptions(entities=entities, profile=profile if not entities else None,
                          use_spacy=use_ml and params.get("use_spacy", True),
                          use_gliner=use_ml and params.get("use_gliner", True), terms=terms, allow_list=allow,
                          threshold=float(params.get("threshold", 0.5)),
                          sensitive_sentence_mode=bool(params.get("sensitive_sentence_mode", False)),
                          second_opinion=bool(params.get("second_opinion", True)))


def analyze_file(file_id: int, params: dict, ctx) -> dict:
    try:
        return _analyze_file(file_id, params, ctx)
    except Exception as e:
        _mark_error(file_id, e, "analysis")
        raise


def _mark_error(file_id: int, e: Exception, what: str) -> None:
    from .jobs import JobCancelled
    with tx() as s:
        f = s.get(File, file_id)
        if f:
            if isinstance(e, JobCancelled):
                f.status = "ready" if f.detections_blob else "uploaded"
                f.error = f"{what} cancelled"
            else:
                f.status = "error"
                f.error = f"{what} failed: {type(e).__name__}: {e}"[:1000]


def _analyze_file(file_id: int, params: dict, ctx) -> dict:
    st = get_storage()
    with tx() as s:
        f = s.get(File, file_id)
        f.status = "analyzing"
        case = f.case
        opts = build_options(params, case, s)
        kind = f.kind
        templates = [t for t in s.query(Template).filter(Template.id.in_(params.get("template_ids") or [])).all()]
        tmpl_zones = [(t.name, z) for t in templates for z in t.zones]
    path = working_path(f)
    visual = set(params.get("visual_classes") or ["face", "head", "license_plate"])
    result: dict = {}
    dets: list[Detection] = []
    tracks_blob = transcript_blob = extract_blob = None
    if kind == "pdf":
        from .redact.pdf import PdfDocument
        doc = PdfDocument(path)
        doc.extract(ocr=params.get("ocr", "auto"), progress=ctx.stage(0.0, 0.35, "reading pages / OCR"))
        ctx.progress(0.4, "detecting sensitive information")
        dets = doc.analyze(opts)
        if visual & {"face", "license_plate", "head"} and params.get("visual_on_pages", True):
            ctx.progress(0.75, "scanning page images for faces / plates")
            dets += _visual_on_pdf(doc, visual & {"face", "license_plate", "head"})
        if params.get("classify_images", True):
            ctx.progress(0.85, "classifying photos, exhibits and charts")
            dets += _picture_regions(doc)
        dets += _template_dets(doc, tmpl_zones)
        extract_blob = st.put_json({"pages": [_page_json(p) for p in doc.pages], "stats": asdict(doc.stats),
                                    "page_info": doc.page_info()})
        result["pages"] = len(doc.pages)
        result["ocr_pages"] = doc.stats.ocr_pages + doc.stats.hybrid_pages
        doc.close()
    elif kind == "image":
        from .redact.image import ImageDocument
        img = ImageDocument(path)
        ctx.progress(0.2, "detecting faces, plates and text")
        dets = img.analyze(visual, text=params.get("image_text", True), options=opts)
        if params.get("classify_images", True):
            dets.append(img.classification_detection(faces=sum(1 for d in dets if d.entity == "FACE")))
        pt = img.page
        extract_blob = st.put_json({"pages": [_page_json(pt)] if pt else [], "width": img.w, "height": img.h})
    elif kind in ("docx", "pptx", "xlsx", "text"):
        doc = _text_handler(kind, path)
        ctx.progress(0.3, "detecting sensitive information")
        dets = doc.analyze(opts)
        extract_blob = st.put_json({"text": doc.text})
    elif kind == "video":
        from .redact.video import VideoDocument, extract_audio
        v = VideoDocument(path)
        v.analyze(visual, mode=params.get("video_mode", "balanced"), progress=ctx.stage(0.0, 0.8, "tracking faces / plates"))
        tracks_blob = st.put_json([t.to_dict() for t in v.tracks])
        result["tracks"] = len(v.tracks)
        if v.info.has_audio and params.get("audio", True):
            ctx.progress(0.82, "transcribing audio")
            from .redact.audio import AudioDocument
            with st.scratch(".wav") as wav:
                extract_audio(path, wav)
                a = AudioDocument(wav)
                a.transcribe(params.get("whisper_model"), language=params.get("language") or "auto")
                if params.get("speakers", True):
                    from .detection.audio.speakers import label_transcript
                    result["speakers"] = label_transcript(wav, a.transcript)
                dets = a.analyze(opts)
                transcript_blob = st.put_json(a.transcript.to_dict())
        result["audio_detections"] = len(dets)
    elif kind == "audio":
        from .redact.audio import AudioDocument
        ctx.progress(0.1, "transcribing")
        a = AudioDocument(path)
        a.transcribe(params.get("whisper_model"), language=params.get("language") or "auto")
        if params.get("speakers", True):
            ctx.progress(0.7, "identifying speakers")
            from .detection.audio.speakers import label_transcript
            result["speakers"] = label_transcript(path, a.transcript)
        ctx.progress(0.8, "detecting sensitive information")
        dets = a.analyze(opts)
        transcript_blob = st.put_json(a.transcript.to_dict())
    else:
        raise ValueError(f"cannot analyze {kind}")
    det_blob = st.put_json([d.to_dict() for d in dets])
    with tx() as s:
        f = s.get(File, file_id)
        for old in (f.detections_blob, f.extract_blob if extract_blob else None,
                    f.tracks_blob if tracks_blob else None, f.transcript_blob if transcript_blob else None):
            st.delete(old)
        f.detections_blob = det_blob
        if extract_blob:
            f.extract_blob = extract_blob
        if tracks_blob:
            f.tracks_blob = tracks_blob
        if transcript_blob:
            f.transcript_blob = transcript_blob
        f.status, f.analyzed_at, f.error = "ready", utcnow(), ""
        f.info = {**(f.info or {}), "last_analysis": {k: v for k, v in params.items() if k not in ("terms",)}}
    result.update(summarize(dets))
    return result


def summarize(dets: list[Detection]) -> dict:
    by: dict[str, int] = {}
    for d in dets:
        if d.selected:
            by[d.entity] = by.get(d.entity, 0) + 1
    return {"detections": len(dets), "selected": sum(d.selected for d in dets), "by_entity": by}


def _page_json(p: PageText) -> dict:
    return {"page": p.page, "text": p.text, "boxes": [list(map(lambda v: round(v, 2), b)) if b else None for b in p.boxes],
            "lines": p.lines, "width": p.width, "height": p.height, "source": p.source, "ocr_conf": p.ocr_conf}


def page_from_json(d: dict) -> PageText:
    return PageText(d["page"], d["text"], [tuple(b) if b else None for b in d["boxes"]], d["lines"], d["width"],
                    d["height"], d.get("source", "native"), d.get("ocr_conf"))


def _visual_on_pdf(doc, classes: set[str], dpi: int = 150) -> list[Detection]:
    """Faces / plates in photos inside PDFs (ID cards, accident photos)."""
    import cv2
    import numpy as np
    import pymupdf as fitz

    from .detection.vision.detectors import get_detector
    from .redact.image import VISUAL_ENTITY, VISUAL_PAD
    out = []
    det = get_detector()
    for i, page in enumerate(doc.doc):
        if not page.get_images():
            continue
        zoom = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR) if pix.n == 3 else cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        derot = page.derotation_matrix
        for vb in det.detect(bgr, classes):
            if vb.score < 0.35:
                continue
            pb = vb.padded(VISUAL_PAD.get(vb.label, 0.05), pix.width, pix.height)
            r = fitz.Rect(pb.x0 / zoom, pb.y0 / zoom, pb.x1 / zoom, pb.y1 / zoom) * derot
            out.append(Detection(entity=VISUAL_ENTITY.get(vb.label, vb.label.upper()), text="", score=vb.score,
                                 source=vb.source, boxes=[Box(i, r.x0, r.y0, r.x1, r.y1)], page=i, kind="visual",
                                 explanation=f"{vb.label} in page image ({vb.score:.2f})", exemption="(b)(6)"))
    return out


def _picture_regions(doc, dpi: int = 150) -> list[Detection]:
    """Every picture placed on a PDF page — photos, exhibits, charts, ID cards, signatures — classified and listed
    so it can be redacted whole. A picture that is the whole page (a scan) is the page itself, not an exhibit."""
    import cv2
    import numpy as np
    import pymupdf as fitz

    from .detection.text.entities import ENTITIES
    from .detection.vision.classify import SELECT_WHOLE, classify_image
    out = []
    for i, page in enumerate(doc.doc):
        seen: list = []
        area = abs(page.rect) or 1
        for img in page.get_images(full=True):
            try:
                rects = page.get_image_rects(img[0])
            except Exception:
                continue
            for r in rects:
                r = r & page.rect
                if r.is_empty or r.width < 36 or r.height < 18 or abs(r) > 0.85 * area:
                    continue
                if any(abs(r & x) > 0.8 * abs(r) for x in seen):
                    continue
                seen.append(fitz.Rect(r))
                zoom = dpi / 72
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=r, alpha=False)
                arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
                bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR) if pix.n == 3 else cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
                c = classify_image(bgr)
                ent = ENTITIES[c.label]
                out.append(Detection(entity=c.label, text="", score=c.confidence, source="classify:picture",
                                     boxes=[Box(i, r.x0, r.y0, r.x1, r.y1)], page=i, kind="region",
                                     selected=c.label in SELECT_WHOLE,
                                     explanation=f"picture classified as: {c.description} ({c.confidence:.0%})",
                                     exemption=ent.exemption, meta={"class": c.label, "whole_picture": True}))
    return out


def _template_dets(doc, zones: list[tuple[str, dict]]) -> list[Detection]:
    out = []
    n = len(doc.doc)
    for name, z in zones:
        sel = str(z.get("pages", "all"))
        pages = range(n) if sel == "all" else [0] if sel == "first" else [n - 1] if sel == "last" else \
            [int(p) - 1 for p in re.split(r"[,\s]+", sel) if p.strip().isdigit() and 0 < int(p) <= n]
        for i in pages:
            r = doc.doc[i].rect
            out.append(Detection(entity=z.get("entity", "CUSTOM"), text="", score=1.0, source=f"template:{name}",
                                 boxes=[Box(i, z["x0"] * r.width, z["y0"] * r.height, z["x1"] * r.width,
                                            z["y1"] * r.height)], page=i, kind="template",
                                 exemption=z.get("exemption", ""), explanation=f"template “{name}” zone"))
    return out


class TextDocument:
    """Plain text formats (txt, csv, json, html, md…)."""

    def __init__(self, path: Path):
        self.path = path
        raw = path.read_bytes()
        for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
            try:
                self.text = raw.decode(enc)
                self.encoding = enc
                break
            except UnicodeDecodeError:
                continue

    def analyze(self, opts):
        from .detection.text.engine import get_analyzer
        from .redact.office import _span_to_det
        return [_span_to_det(sp) for sp in get_analyzer().analyze(self.text, opts)]

    def search(self, terms):
        from .detection.text.engine import TextAnalyzer
        from .redact.office import _span_to_det
        return [_span_to_det(sp) for sp in TextAnalyzer._user_rules(self.text, terms)]

    def apply(self, detections, out_path, style: str = "block") -> dict:
        from .detection.text.engine import partial_ranges
        from .redact.office import redaction_text
        text = self.text
        edits = []
        for d in detections:
            if not d.selected or d.start < 0:
                continue
            if d.partial:
                for a, b in partial_ranges(text[d.start:d.end], d.partial):
                    edits.append((d.start + a, d.start + b, "█" * (b - a)))
            else:
                edits.append((d.start, d.end, redaction_text(d, style, text[d.start:d.end])))
        for a, b, rep in sorted(edits, reverse=True):
            text = text[:a] + rep + text[b:]
        Path(out_path).write_text(text, encoding="utf-8")
        leaks = [d.entity for d in detections if d.selected and not d.partial and len(d.text) >= 5 and d.text in text]
        return {"redactions": len(edits), "verification": {"passed": not leaks,
                                                           "issues": [{"type": "value_still_present", "entity": e}
                                                                      for e in leaks]}}


def _text_handler(kind: str, path: Path):
    if kind in ("docx", "pptx"):
        from .redact.office import OoxmlDocument
        return OoxmlDocument(path)
    if kind == "xlsx":
        from .redact.office import XlsxDocument
        return XlsxDocument(path)
    return TextDocument(path)


def merge_found(dets: list[Detection], found: list[Detection]) -> tuple[list[Detection], list[str]]:
    """Search matches to add to a file's detections: new ones, plus the ids of existing unselected suggestions on the
    exact same text that are switched on (asking to redact a phrase must not leave a suggestion of it off)."""
    by_span = {}
    for d in dets:
        if d.start >= 0:
            by_span.setdefault((d.page, d.start, d.end), d)
    new, switched = [], []
    for d in found:
        old = by_span.get((d.page, d.start, d.end))
        if old is None:
            by_span[(d.page, d.start, d.end)] = d
            new.append(d)
        elif not old.selected:
            old.selected = True
            switched.append(old.id)
    return new, switched


def search_file(f: File, terms: list[SearchTerm]) -> list[Detection]:
    path = working_path(f)
    if f.kind == "pdf":
        from .redact.pdf import PdfDocument
        doc = PdfDocument(path)
        if f.extract_blob:
            doc.pages = [page_from_json(p) for p in get_storage().get_json(f.extract_blob)["pages"]]
        dets = doc.search(terms)
        doc.close()
        return dets
    if f.kind == "image":
        from .redact.image import ImageDocument
        img = ImageDocument(path)
        if f.extract_blob:
            pages = get_storage().get_json(f.extract_blob).get("pages") or []
            if pages:
                img.page = page_from_json(pages[0])
        return img.search(terms)
    if f.kind in ("docx", "pptx", "xlsx", "text"):
        return _text_handler(f.kind, path).search(terms)
    if f.kind in ("audio", "video") and f.transcript_blob:
        from .detection.audio.transcribe import Transcript
        from .redact.audio import AudioDocument
        a = AudioDocument(path, Transcript.from_dict(get_storage().get_json(f.transcript_blob)))
        return a.search(terms)
    return []


def text_range_detection(f: File, page: int, start: int, end: int, entity: str, exemption: str = "") -> Detection:
    """A manual redaction made by selecting text in the viewer."""
    st = get_storage()
    if f.kind in ("pdf", "image"):
        from .redact.pdf import char_range_boxes
        pages = st.get_json(f.extract_blob)["pages"]
        pt = page_from_json(pages[page])
        boxes = char_range_boxes(pt, start, end, page)
        text = pt.text[start:end]
    else:
        boxes, text = [], st.get_json(f.extract_blob)["text"][start:end]
    return Detection(entity=entity, text=text, score=1.0, source="manual:text", boxes=boxes, page=page, start=start,
                     end=end, kind="manual", exemption=exemption or (ENTITIES[entity].exemption if entity in ENTITIES else ""),
                     explanation="selected by reviewer")


# ---------------------------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------------------------

def load_detections(f: File) -> list[Detection]:
    if not f.detections_blob:
        return []
    return [Detection.from_dict(d) for d in get_storage().get_json(f.detections_blob)]


def save_detections(f: File, dets: list[Detection], s) -> None:
    st = get_storage()
    old = f.detections_blob
    f.detections_blob = st.put_json([d.to_dict() for d in dets])
    st.delete(old)


def export_file(file_id: int, params: dict, user_id: int | None, ctx) -> dict:
    try:
        return _export_file(file_id, params, user_id, ctx)
    except Exception as e:
        _mark_error(file_id, e, "export")
        raise


def _export_file(file_id: int, params: dict, user_id: int | None, ctx) -> dict:
    st = get_storage()
    with tx() as s:
        f = s.get(File, file_id)
        dets = load_detections(f)
        kind, name, ext = f.kind, f.name, f.ext
        tracks_json = st.get_json(f.tracks_blob) if f.tracks_blob else None
        transcript = st.get_json(f.transcript_blob) if f.transcript_blob else None
    path = working_path(f)
    stem = Path(name).stem + ("_REVIEW-COPY" if params.get("marked_copy") else "")
    if params.get("marked_copy") and kind not in ("pdf", "image"):
        raise ValueError("a marked review copy is available for PDFs and images")
    style = params.get("style", {})
    out_dir = st.scratch_dir()
    try:
        if kind == "pdf":
            from .redact.pdf import PdfDocument
            out = out_dir / f"{stem}_REDACTED.pdf"
            opts = ExportOptions(
                style=RedactionStyle(fill=tuple(style.get("fill", (0, 0, 0))), label=style.get("label", "none"),
                                     custom_text=style.get("custom_text", "REDACTED"),
                                     text_color=tuple(style.get("text_color", (1, 1, 1)))),
                bates_prefix=params.get("bates_prefix"), bates_start=int(params.get("bates_start", 1)),
                bates_digits=int(params.get("bates_digits", 6)), watermark=params.get("watermark") or None,
                password=params.get("password") or None, flatten_to_image=bool(params.get("flatten", False)),
                padding=float(params.get("padding") or 0.0), marked_copy=bool(params.get("marked_copy")))
            ctx.progress(0.2, "applying redactions")
            doc = PdfDocument(path)
            report = doc.apply(dets, out, opts)
            doc.close()
        elif kind == "image":
            from .redact.image import ImageDocument
            out = out_dir / f"{stem}_REDACTED.{'png' if ext in ('png', 'gif', 'bmp', 'webp') else 'jpg'}"
            ctx.progress(0.2, "applying redactions")
            img = ImageDocument(path)
            ctx.progress(0.5, "verifying (re-detecting faces / plates)")
            if params.get("marked_copy"):
                report = img.marked_copy(dets, out)
            else:
                report = img.apply(dets, out, effect=params.get("effect", "blackout"),
                                   face_effect=params.get("face_effect"), padding=float(params.get("padding") or 0.0),
                                   enhance=params.get("enhance") or None)
        elif kind in ("docx", "pptx", "xlsx", "text"):
            out = out_dir / f"{stem}_REDACTED.{ext if kind != 'text' else ext}"
            doc = _text_handler(kind, path)
            report = doc.apply(dets, out, style=params.get("text_style", "block"))
        elif kind == "video":
            from .detection.vision.tracker import Track
            from .redact.video import VideoDocument, extract_audio
            v = VideoDocument(path)
            v.tracks = [Track.from_dict(t) for t in (tracks_json or [])]
            out = out_dir / f"{stem}_REDACTED{VIDEO_OUT}"
            audio_arg = "original"
            if params.get("mute_audio"):
                audio_arg = None
            elif transcript and any(d.selected for d in dets):
                from .detection.audio.transcribe import Transcript
                from .redact.audio import AudioDocument
                wav = out_dir / "audio.wav"
                extract_audio(path, wav)
                a = AudioDocument(wav, Transcript.from_dict(transcript))
                red = out_dir / "audio_red.wav"
                a.apply(dets, red, effect=params.get("audio_effect", "bleep"),
                        voice_disguise=bool(params.get("voice_disguise")), verify=False)
                audio_arg = red
            cues = None
            if params.get("burn_captions") and transcript:
                from .detection.audio.transcribe import Transcript
                from .redact.audio import AudioDocument
                cues = AudioDocument(path, Transcript.from_dict(transcript)).cues(dets)
            report = v.render(out, effect=params.get("effect", "blur"), audio=audio_arg,
                              progress=ctx.stage(0.05, 0.85, "rendering video"), enhance=params.get("enhance") or None,
                              captions=cues, padding=float(params.get("padding") or 0.0))
        elif kind == "audio":
            from .detection.audio.transcribe import Transcript
            from .redact.audio import AudioDocument
            out = out_dir / f"{stem}_REDACTED.{ext if ext in ('wav', 'mp3', 'm4a', 'flac', 'ogg') else 'wav'}"
            a = AudioDocument(path, Transcript.from_dict(transcript) if transcript else None)
            report = a.apply(dets, out, effect=params.get("audio_effect", "bleep"),
                             voice_disguise=bool(params.get("voice_disguise")))
            report["captions_srt"] = a.captions(dets, "srt")
            report["redacted_transcript"] = a.redacted_transcript(dets)
        else:
            raise ValueError(kind)
        if params.get("second_opinion", True) and not params.get("marked_copy"):
            ctx.progress(0.85, "second opinion: Microsoft Presidio re-checks the redacted file")
            try:
                report["second_opinion"] = final_check(kind, out, dets, report, file_id)
            except Exception as e:  # advisory only: never blocks an export
                report["second_opinion"] = {"checked": False, "reason": f"{type(e).__name__}: {e}"[:200]}
        ctx.progress(0.9, "storing export")
        blob, sha, size = st.put_file(out)
        log_csv = redaction_log_csv(name, dets)
        log_blob = st.put_bytes(log_csv.encode())
        verified = bool(report.get("verification", {}).get("passed", True))
        with tx() as s:
            ex = Export(file_id=file_id, blob=blob, log_blob=log_blob, name=out.name, sha256=sha, size=size,
                        settings={k: v for k, v in params.items() if k != "password"} | (
                            {"password_protected": True} if params.get("password") else {}),
                        report={k: v for k, v in report.items() if k not in ("captions_srt", "redacted_transcript")},
                        verified=verified, created_by=user_id)
            s.add(ex)
            f = s.get(File, file_id)
            if not params.get("marked_copy"):  # a review copy is not a release: status / dictionary unchanged
                f.status = "exported"
            s.flush()
            ex_id = ex.id
            case = f.case
            if not params.get("marked_copy"):
                update_case_dictionary(case, dets, s)
        so = report.get("second_opinion") or {}
        return {"export_id": ex_id, "verified": verified, "sha256": sha, "issues": report.get("verification", {}).get(
            "issues", [])[:20], "second_opinion_open": so.get("open", 0) if so.get("checked") else None}
    finally:
        from .storage import _wipe_tree
        _wipe_tree(out_dir)


def _output_text(kind: str, out: Path, report: dict) -> list[str] | None:
    """The text a recipient of the export can read, page by page (None when there is no text to check)."""
    if kind == "pdf":
        import pymupdf as fitz
        with fitz.open(out) as d:
            pages = [p.get_text() for p in d]
        return pages if any(p.strip() for p in pages) else None
    if kind in ("docx", "pptx", "xlsx", "text"):
        return [_text_handler(kind, out).text]
    if kind in ("audio", "video") and report.get("redacted_transcript"):
        return [report["redacted_transcript"]]
    return None


def final_check(kind: str, out: Path, dets: list[Detection], report: dict, file_id: int) -> dict:
    """Independent last look at the released file with Microsoft Presidio: anything it still recognises is listed
    in the export report. Text the reviewer deliberately left unredacted is marked as reviewed."""
    from .detection.text import second_opinion
    pages = _output_text(kind, out, report)
    if pages is None:
        return {"checked": False, "reason": "no readable text in this export (images are checked visually)"}
    with tx() as s:
        f = s.get(File, file_id)
        params = (f.info or {}).get("last_analysis", {})
        opts = build_options({k: v for k, v in params.items() if k != "list_ids"}, f.case, s)
    dismissed = {d.text for d in dets if not d.selected and d.text}
    return second_opinion.check_output(pages, opts.enabled(), dismissed)


def redaction_log_csv(file_name: str, dets: list[Detection]) -> str:
    """Exemption / redaction log (Vaughn-index style): one row per redaction, never the redacted value."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["file", "page", "start_time", "category", "type", "exemption", "exemption_description", "reason",
                "confidence", "source", "partial"])
    from .detection.text.entities import EXEMPTION_CODES
    for d in sorted((d for d in dets if d.selected), key=lambda d: (d.page, d.meta.get("t0", 0), d.start)):
        e = ENTITIES.get(d.entity)
        w.writerow([file_name, d.page + 1 if d.kind != "audio" else "", d.meta.get("t0", ""),
                    e.category if e else "VISUAL", e.label if e else d.entity.replace("_", " ").title(), d.exemption,
                    EXEMPTION_CODES.get(d.exemption, ""), _reason(d), f"{d.score:.2f}", d.source.split(":")[0],
                    d.partial or ""])
    return buf.getvalue()


def _reason(d: Detection) -> str:
    """First clause of the explanation, guaranteed not to contain the redacted value."""
    r = d.explanation.split(";")[0].strip()
    v = d.text.strip()
    if v and len(v) >= 3 and v.lower() in r.lower():
        r = ENTITIES[d.entity].label if d.entity in ENTITIES else "sensitive content"
    return r[:160]


_DICT_TYPES = {"PERSON", "SSN", "PHONE", "EMAIL", "ADDRESS", "DATE_OF_BIRTH", "MRN", "HEALTH_PLAN_ID", "DRIVERS_LICENSE",
               "LICENSE_PLATE", "VIN", "BANK_ACCOUNT", "CREDIT_CARD", "CLAIM_NUMBER", "POLICY_NUMBER", "EMPLOYER",
               "MEDICARE_ID", "PASSPORT", "USERNAME"}


def update_case_dictionary(case: Case, dets: list[Detection], s) -> None:
    """Values a reviewer confirmed in one file are looked for in every other file of the case."""
    st = get_storage()
    cur = st.get_json(case.dictionary_blob) if case.dictionary_blob else []
    seen = {(v["entity"], v["text"].lower()) for v in cur}
    for d in dets:
        t = d.text.strip()
        if not d.selected or d.entity not in _DICT_TYPES or len(t) < 4 or d.partial or d.kind not in ("text", "manual"):
            continue
        if d.entity == "PERSON" and len(t.split()) < 2:
            continue
        key = (d.entity, t.lower())
        if key not in seen:
            seen.add(key)
            cur.append({"entity": d.entity, "text": t})
    old = case.dictionary_blob
    case.dictionary_blob = st.put_json(cur[-5000:])
    st.delete(old)


def _speaker_at(tr, a: float, b: float):
    best, ov = None, 0.0
    for s in tr.segments:
        o = min(b, s["end"]) - max(a, s["start"])
        if o > ov and s.get("speaker"):
            best, ov = s["speaker"], o
    return best


def translate_file(file_id: int, target: str, redacted: bool, user_id: int | None, ctx) -> dict:
    """Translate a file's transcript into ``target`` (local M2M100). With ``redacted`` the source segments are
    redacted first, so no redacted word can appear in the translation."""
    from .detection.audio.transcribe import Transcript
    from .detection.audio.translate import translate
    from .redact.audio import AudioDocument
    st = get_storage()
    with tx() as s:
        f = s.get(File, file_id)
        if not f.transcript_blob:
            raise ValueError("no transcript: analyze the recording first")
        tr = Transcript.from_dict(st.get_json(f.transcript_blob))
        dets = load_detections(f)
        path = working_path(f)
    cues = AudioDocument(path, tr).cues(dets, redact=redacted)
    src = tr.language or "en"
    out, n = [], len(cues)
    for i in range(0, n, 16):
        chunk = cues[i:i + 16]
        texts = translate([c[2] for c in chunk], src, target)
        out += [{"start": a, "end": b, "text": t, "speaker": _speaker_at(tr, a, b)} for (a, b, _), t in zip(chunk, texts)]
        ctx.progress(min(0.95, (i + 16) / max(n, 1)), f"translating {min(n, i + 16)}/{n} segments")
    blob = st.put_json({"source": src, "target": target, "redacted": redacted, "segments": out})
    with tx() as s:
        f = s.get(File, file_id)
        info = dict(f.info or {})
        tl = dict(info.get("translations") or {})
        old = tl.get(f"{target}:{'r' if redacted else 'o'}")
        tl[f"{target}:{'r' if redacted else 'o'}"] = blob
        info["translations"] = tl
        f.info = info
    if old:
        st.delete(old)
    return {"segments": len(out), "source": src, "target": target, "redacted": redacted}
