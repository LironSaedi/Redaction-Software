from __future__ import annotations

import io
import shutil
import threading
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, File as FormFile, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import jobs, processing
from ..config import settings
from ..db import Export, File, Job, User, get_db
from ..detection.text.engine import SearchTerm
from ..detection.text.entities import ENTITIES
from ..redact.model import Box, Detection
from ..security import can_view_originals, case_or_404, current_user, file_or_404, require
from ..storage import get_storage
from .common import second_opinion_open, audit, file_out

# Detections and tracks are stored as one document per file; every write is load → change → save under a
# per-file lock (and re-reads the row inside it), so two reviewers or two tabs never lose each other's edits.
_LOCKS: dict[int, threading.Lock] = defaultdict(threading.Lock)


@contextmanager
def _locked(db: Session, f: File):
    with _LOCKS[f.id]:
        db.refresh(f)
        yield

router = APIRouter(prefix="/api", tags=["files"])


def _need_originals(user: User) -> None:
    if not can_view_originals(user):
        raise HTTPException(403, "viewers can only see redacted exports")


@router.post("/cases/{case_id}/files")
async def upload(case_id: int, request: Request, files: list[UploadFile] = FormFile(...),
                 user: User = Depends(require("redactor")), db: Session = Depends(get_db)):
    case = case_or_404(db, user, case_id, "redactor")
    st = get_storage()
    created, errors = [], []
    limit = settings.max_upload_mb * 1024 * 1024
    for up in files:
        name = Path(up.filename or "upload").name
        try:
            processing.kind_for(name)
        except ValueError as e:
            errors.append({"name": name, "error": str(e)})
            continue
        with st.scratch(Path(name).suffix) as tmp:
            size = 0
            with open(tmp, "wb") as fh:
                while chunk := await up.read(1 << 20):
                    size += len(chunk)
                    if size > limit:
                        break
                    fh.write(chunk)
            if size > limit:
                errors.append({"name": name, "error": f"larger than {settings.max_upload_mb} MB"})
                continue
            try:
                ids = processing.ingest(case.id, tmp, name, user.id)
            except Exception as e:  # noqa: BLE001
                errors.append({"name": name, "error": str(e)})
                continue
        for fid in ids:
            f = db.get(File, fid)
            created.append(file_out(f))
            audit(request, "file_uploaded", user, "file", fid, case.id, kind=f.kind, size=f.size, sha256=f.sha256,
                  parent_id=f.parent_id)
    return {"files": created, "errors": errors}


@router.get("/files/{file_id}")
def get_file(file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return file_out(file_or_404(db, user, file_id))


class FilePatch(BaseModel):
    status: str | None = None
    assigned_to: int | None = None


@router.patch("/files/{file_id}")
def patch_file(file_id: int, body: FilePatch, request: Request, user: User = Depends(require("redactor")),
               db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id, "redactor")
    data = body.model_dump(exclude_unset=True)
    if data.get("status") == "approved":
        if user.role not in ("admin", "supervisor"):
            raise HTTPException(403, "only supervisors approve files")
        f.approved_by = user.id
    for k, v in data.items():
        setattr(f, k, v)
    db.commit()
    audit(request, "file_updated", user, "file", f.id, f.case_id, **data)
    return file_out(f)


@router.delete("/files/{file_id}")
def delete_file(file_id: int, request: Request, user: User = Depends(require("supervisor")),
                db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    st = get_storage()
    for blob in (f.original_blob, f.working_blob, f.extract_blob, f.detections_blob, f.tracks_blob, f.transcript_blob):
        st.delete(blob)
    for e in f.exports:
        st.delete(e.blob)
        st.delete(e.log_blob)
    case_id = f.case_id
    db.delete(f)
    db.commit()
    audit(request, "file_deleted", user, "file", file_id, case_id)
    return {"ok": True}


@router.get("/files/{file_id}/original")
def download_original(file_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    _need_originals(user)
    audit(request, "original_downloaded", user, "file", f.id, f.case_id)
    return StreamingResponse(get_storage().stream(f.original_blob), media_type=f.mime or "application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="original.{f.ext}"'})


@router.get("/files/{file_id}/media")
def media(file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Range-capable stream of the working copy (video/audio players, image viewer)."""
    f = file_or_404(db, user, file_id)
    _need_originals(user)
    p = processing.working_path(f)
    return FileResponse(p, media_type=f.mime or "application/octet-stream",
                        headers={"Cache-Control": "private, no-store"})


@router.get("/files/{file_id}/pages")
def pages(file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    _need_originals(user)
    st = get_storage()
    if f.extract_blob:
        ex = st.get_json(f.extract_blob)
        if "page_info" in ex:
            return {"pages": ex["page_info"], "stats": ex.get("stats", {})}
        if f.kind == "image":
            return {"pages": [{"page": 0, "width": ex.get("width"), "height": ex.get("height"), "source": "image"}]}
        return {"text": ex.get("text", "")}
    if f.kind in ("docx", "pptx", "xlsx", "text"):
        return {"text": None}
    if f.kind == "pdf":
        from ..redact.pdf import PdfDocument
        d = PdfDocument(processing.working_path(f))
        info = d.page_info()
        d.close()
        return {"pages": info}
    if f.kind == "image":
        return {"pages": [{"page": 0, "width": f.info.get("width"), "height": f.info.get("height"), "source": "image"}]}
    return {"pages": []}


@router.get("/files/{file_id}/pages/{n}/text")
def page_text(file_id: int, n: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    _need_originals(user)
    if not f.extract_blob:
        raise HTTPException(409, "run analysis first")
    ex = get_storage().get_json(f.extract_blob)
    if "pages" not in ex:
        return {"text": ex.get("text", "")}
    p = ex["pages"][n]
    return {"text": p["text"], "boxes": p["boxes"], "width": p["width"], "height": p["height"], "source": p["source"]}


@router.get("/files/{file_id}/pages/{n}.png")
def page_png(file_id: int, n: int, dpi: int = 110, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    _need_originals(user)
    dpi = max(36, min(220, dpi))
    path = processing.working_path(f)
    if f.kind == "pdf":
        from ..redact.pdf import PdfDocument
        d = PdfDocument(path)
        if n >= len(d.doc):
            raise HTTPException(404, "no such page")
        data = d.render_page(n, dpi)
        d.close()
    elif f.kind == "image":
        from ..redact.image import ImageDocument
        data = ImageDocument(path).render(max_side=2400)
    else:
        raise HTTPException(400, "not a paged file")
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


# ---- analysis ----------------------------------------------------------------------------------

class AnalyzeIn(BaseModel):
    profile: str | None = None
    entities: list[str] | None = None
    use_ml: bool = True
    ocr: str = "auto"
    visual_classes: list[str] | None = None
    video_mode: str = "balanced"
    audio: bool = True
    terms: list[dict] = []
    allow_list: list[str] = []
    list_ids: list[int] = []
    template_ids: list[int] = []
    threshold: float = 0.5
    sensitive_sentence_mode: bool = False
    use_case_dictionary: bool = True
    image_text: bool = True
    whisper_model: str | None = None
    language: str = "auto"           # speech language: "auto" (detect) or an ISO code ("en", "es", …)
    classify_images: bool = True     # classify photos / exhibits / charts / ID cards / signatures in documents
    visual_on_pages: bool = True     # look for faces / plates in pictures inside PDFs
    speakers: bool = True            # label who is speaking in transcripts (Speaker 1, Speaker 2, …)
    second_opinion: bool = True      # Microsoft Presidio re-reads the text; extra findings become suggestions


@router.post("/files/{file_id}/analyze")
def analyze(file_id: int, body: AnalyzeIn, request: Request, user: User = Depends(require("redactor")),
            db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id, "redactor")
    params = body.model_dump()
    jid = jobs.submit("analyze", lambda ctx: processing.analyze_file(f.id, params, ctx), file_id=f.id,
                      case_id=f.case_id, params={k: v for k, v in params.items() if k != "terms"}, user_id=user.id)
    audit(request, "analysis_started", user, "file", f.id, f.case_id, profile=params.get("profile"),
          ml=params.get("use_ml"), job=jid)
    return {"job_id": jid}


@router.get("/files/{file_id}/detections")
def get_detections(file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    _need_originals(user)
    dets = processing.load_detections(f)
    return {"detections": [d.to_dict() for d in dets], "summary": processing.summarize(dets)}


class DetPatch(BaseModel):
    id: str
    selected: bool | None = None
    entity: str | None = None
    exemption: str | None = None
    boxes: list[dict] | None = None
    partial: str | None = None
    # appearance / geometry (None = unchanged; "" / [] = clear)
    label_text: str | None = None
    fill: list[float] | None = None
    effect: str | None = None
    note: str | None = None
    shape: str | None = None
    points: list[list[float]] | None = None
    image_boxes: list[dict] | None = None   # Word / PowerPoint pictures: boxes in the picture's pixels


class DetBulk(BaseModel):
    updates: list[DetPatch] = []
    select_entities: dict[str, bool] = {}  # {"PERSON": true} — accept / reject a whole category


@router.patch("/files/{file_id}/detections")
def patch_detections(file_id: int, body: DetBulk, request: Request, user: User = Depends(require("redactor")),
                     db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id, "redactor")
    with _locked(db, f):
        return _patch_detections(f, body, request, user, db)


def _patch_detections(f: File, body: DetBulk, request: Request, user: User, db: Session):
    dets = processing.load_detections(f)
    by_id = {d.id: d for d in dets}
    n = 0
    for ent, sel in body.select_entities.items():
        for d in dets:
            if d.entity == ent:
                d.selected = sel
                n += 1
    for u in body.updates:
        d = by_id.get(u.id)
        if not d:
            continue
        if u.selected is not None:
            d.selected = u.selected
        if u.entity is not None:
            d.entity = u.entity
        if u.exemption is not None:
            d.exemption = u.exemption
        if u.boxes is not None:
            d.boxes = [Box.from_dict(b) for b in u.boxes]
        if u.partial is not None:
            d.partial = u.partial or None
        if u.shape is not None and u.shape not in ("", "rect", "ellipse", "polygon"):
            raise HTTPException(400, "shape must be rect, ellipse or polygon")
        if u.effect is not None and u.effect not in ("", "blur", "pixelate", "blackout", "whiteout"):
            raise HTTPException(400, "unknown effect")
        for key in ("label_text", "fill", "effect", "note", "shape", "points", "image_boxes"):
            val = getattr(u, key)
            if val is None:
                continue
            if val in ("", []) or (key == "shape" and val == "rect"):
                d.meta.pop(key, None)
            else:
                d.meta[key] = val
        if u.points and d.meta.get("shape") == "polygon" and u.boxes is None:  # keep the locating box in step
            xs, ys = [p[0] for p in u.points], [p[1] for p in u.points]
            pg = d.boxes[0].page if d.boxes else d.page
            d.boxes = [Box(pg, min(xs), min(ys), max(xs), max(ys))]
        n += 1
    processing.save_detections(f, dets, db)
    if f.status in ("ready", "exported"):
        f.status = "in_review"
    db.commit()
    audit(request, "detections_reviewed", user, "file", f.id, f.case_id, changed=n,
          categories=sorted(body.select_entities))
    return processing.summarize(dets)


class ManualIn(BaseModel):
    entity: str = "CUSTOM"
    exemption: str | None = None     # None = the type's default reason; "" = none
    selected: bool = True
    partial: str | None = None
    media: str | None = None         # Word / PowerPoint picture part (with image_boxes)
    image_boxes: list[dict] | None = None
    boxes: list[dict] = []           # drawn boxes (page coordinates)
    page: int = 0
    start: int | None = None         # or a text selection on a page
    end: int | None = None
    t0: float | None = None          # or an audio time range
    t1: float | None = None
    note: str = ""
    shape: str = "rect"              # rect | ellipse | polygon
    points: list[list[float]] | None = None   # polygon vertices (page coordinates)
    effect: str | None = None        # images / video: blur | pixelate | blackout | whiteout
    label_text: str | None = None    # text printed on this box ("Redacted per HIPAA", "(b)(6)")
    fill: list[float] | None = None  # box colour (0..1 RGB) for colour-coded redactions


@router.post("/files/{file_id}/detections")
def add_manual(file_id: int, body: ManualIn, request: Request, user: User = Depends(require("redactor")),
               db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id, "redactor")
    with _locked(db, f):
        return _add_manual(f, body, request, user, db)


def _add_manual(f: File, body: "ManualIn", request: Request, user: User, db: Session):
    dets = processing.load_detections(f)
    exemption = body.exemption if body.exemption is not None else (
        ENTITIES[body.entity].exemption if body.entity in ENTITIES else "")
    if body.start is not None and body.end is not None and body.end > body.start:
        if not f.extract_blob:
            raise HTTPException(409, "run analysis first")
        d = processing.text_range_detection(f, body.page, body.start, body.end, body.entity, exemption)
    elif body.t0 is not None and body.t1 is not None and body.t1 > body.t0:
        text = ""
        if f.transcript_blob:  # keep the words, so the value can join the case dictionary
            words = get_storage().get_json(f.transcript_blob).get("words", [])
            text = " ".join(w["text"] for w in words if w["end"] > body.t0 and w["start"] < body.t1).strip()
        d = Detection(entity=body.entity, text=text, score=1.0, source="manual:audio", boxes=[], kind="audio",
                      exemption=exemption, explanation=body.note or "marked by reviewer",
                      meta={"t0": body.t0, "t1": body.t1})
    elif body.media and body.image_boxes:  # a picture inside a Word / PowerPoint file
        d = Detection(entity=body.entity, text="", score=1.0, source="manual:picture", boxes=[], kind="region",
                      exemption=exemption, explanation=body.note or "marked by reviewer",
                      meta={"media": body.media, "image_boxes": body.image_boxes, "whole_picture": True})
    elif body.boxes or (body.shape == "polygon" and body.points and len(body.points) >= 3):
        boxes = [Box.from_dict({"page": body.page, **b}) for b in body.boxes]
        if not boxes:  # a polygon alone: its bounding box locates it on the page
            xs, ys = [p[0] for p in body.points], [p[1] for p in body.points]
            boxes = [Box(body.page, min(xs), min(ys), max(xs), max(ys))]
        d = Detection(entity=body.entity, text="", score=1.0, source="manual:" + (body.shape or "box"),
                      boxes=boxes, page=body.page, kind="manual", exemption=exemption,
                      explanation=body.note or "drawn by reviewer")
    else:
        raise HTTPException(400, "give boxes, a polygon, a text range or a time range")
    if body.shape not in ("rect", "ellipse", "polygon"):
        raise HTTPException(400, "shape must be rect, ellipse or polygon")
    if body.effect and body.effect not in ("blur", "pixelate", "blackout", "whiteout"):
        raise HTTPException(400, "unknown effect")
    d.meta.update({k: v for k, v in (("shape", body.shape if body.shape != "rect" else None),
                                     ("points", body.points if body.shape == "polygon" else None),
                                     ("effect", body.effect), ("label_text", body.label_text),
                                     ("fill", body.fill)) if v})
    if body.note:
        d.meta["note"] = body.note
    d.selected = body.selected
    if body.partial:
        d.partial = body.partial
    dets.append(d)
    processing.save_detections(f, dets, db)
    db.commit()
    audit(request, "manual_redaction", user, "file", f.id, f.case_id, entity=d.entity, kind=d.kind)
    return d.to_dict()


@router.delete("/files/{file_id}/detections/{det_id}")
def delete_detection(file_id: int, det_id: str, request: Request, user: User = Depends(require("redactor")),
                     db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id, "redactor")
    with _locked(db, f):
        dets = [d for d in processing.load_detections(f) if d.id != det_id]
        processing.save_detections(f, dets, db)
        db.commit()
    audit(request, "redaction_removed", user, "file", f.id, f.case_id)
    return {"ok": True}


class IdsIn(BaseModel):
    ids: list[str]


@router.post("/files/{file_id}/detections/delete")
def delete_detections(file_id: int, body: IdsIn, request: Request, user: User = Depends(require("redactor")),
                      db: Session = Depends(get_db)):
    """Remove several redactions at once (undo of "Redact all", clearing a category)."""
    f = file_or_404(db, user, file_id, "redactor")
    gone = set(body.ids)
    with _locked(db, f):
        dets = processing.load_detections(f)
        keep = [d for d in dets if d.id not in gone]
        processing.save_detections(f, keep, db)
        db.commit()
    audit(request, "redactions_removed", user, "file", f.id, f.case_id, count=len(dets) - len(keep))
    return {"removed": len(dets) - len(keep)}


class RestoreIn(BaseModel):
    detections: list[dict]


@router.post("/files/{file_id}/detections/restore")
def restore_detections(file_id: int, body: RestoreIn, request: Request, user: User = Depends(require("redactor")),
                       db: Session = Depends(get_db)):
    """Put back detections exactly as they were (same id, score, detector, reason) — used by undo."""
    f = file_or_404(db, user, file_id, "redactor")
    try:
        items = [Detection.from_dict(d) for d in body.detections]
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "each detection needs at least entity and boxes / offsets")
    with _locked(db, f):
        dets = processing.load_detections(f)
        have = {d.id for d in dets}
        new = [d for d in items if d.id not in have]
        processing.save_detections(f, dets + new, db)
        db.commit()
    audit(request, "redactions_restored", user, "file", f.id, f.case_id, count=len(new))
    return {"restored": len(new), "ids": [d.id for d in new]}


class SearchIn(BaseModel):
    terms: list[dict]
    add: bool = False
    entity: str = "CUSTOM"
    exemption: str = ""


@router.post("/files/{file_id}/search")
def search(file_id: int, body: SearchIn, request: Request, user: User = Depends(require("redactor")),
           db: Session = Depends(get_db)):
    """Find & redact: exact text, whole-word, regex patterns, or a list — preview, or add to the redactions."""
    f = file_or_404(db, user, file_id, "redactor")
    if f.kind in ("pdf", "image") and not f.extract_blob:
        raise HTTPException(409, "run analysis first (text must be extracted)")
    terms = []
    for t in body.terms:
        try:
            terms.append(SearchTerm(text=t["text"], entity=t.get("entity", body.entity), regex=bool(t.get("regex")),
                                    case_sensitive=bool(t.get("case_sensitive")), whole_word=t.get("whole_word", True),
                                    exemption=t.get("exemption") or body.exemption or None))
        except KeyError:
            raise HTTPException(400, "each term needs text")
    found = processing.search_file(f, terms)
    added: list[str] = []
    new_ids: list[str] = []
    switched: list[str] = []
    if body.add and found:
        with _locked(db, f):
            dets = processing.load_detections(f)
            new, switched = processing.merge_found(dets, found)
            processing.save_detections(f, dets + new, db)
            db.commit()
        added = [d.id for d in new] + switched
        new_ids = [d.id for d in new]
        audit(request, "search_redaction", user, "file", f.id, f.case_id, terms=len(terms), added=len(new))
    return {"matches": [d.to_dict() for d in found], "count": len(found), "added_ids": added,
            "new_ids": new_ids, "switched_ids": switched}


# ---- video / audio review ------------------------------------------------------------------------

@router.get("/files/{file_id}/video/tracks")
def video_tracks(file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    _need_originals(user)
    tracks = get_storage().get_json(f.tracks_blob) if f.tracks_blob else []
    return {"tracks": tracks, "info": f.info}


class TrackPatch(BaseModel):
    enabled: bool | None = None
    label: str | None = None
    delete: bool = False
    trim_start: int | None = None
    trim_end: int | None = None
    effect: str | None = None   # "" clears the override
    shape: str | None = None


@router.patch("/files/{file_id}/video/tracks/{tid}")
def patch_track(file_id: int, tid: int, body: TrackPatch, request: Request, user: User = Depends(require("redactor")),
                db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id, "redactor")
    with _locked(db, f):
        st = get_storage()
        tracks = st.get_json(f.tracks_blob) if f.tracks_blob else []
        out = []
        for t in tracks:
            if t["id"] == tid:
                if body.delete:
                    continue
                if body.enabled is not None:
                    t["enabled"] = body.enabled
                if body.label:
                    t["label"] = body.label
                if body.effect is not None:
                    if body.effect not in ("", "blur", "pixelate", "blackout"):
                        raise HTTPException(400, "unknown effect")
                    t["effect"] = body.effect or None
                if body.shape is not None:
                    if body.shape not in ("", "rect", "ellipse"):
                        raise HTTPException(400, "shape must be rect or ellipse")
                    t["shape"] = body.shape or None
                if body.trim_start is not None or body.trim_end is not None:
                    lo = body.trim_start if body.trim_start is not None else -1
                    hi = body.trim_end if body.trim_end is not None else 10 ** 9
                    t["boxes"] = {k: v for k, v in t["boxes"].items() if lo <= int(k) <= hi}
                    if t["boxes"]:
                        t["first"], t["last"] = min(map(int, t["boxes"])), max(map(int, t["boxes"]))
            out.append(t)
        old = f.tracks_blob
        f.tracks_blob = st.put_json(out)
        st.delete(old)
        db.commit()
        audit(request, "track_updated", user, "file", f.id, f.case_id, track=tid, enabled=body.enabled, deleted=body.delete)
        return {"ok": True}


class ManualTrackIn(BaseModel):
    frame: int
    box: list[float] = [0, 0, 0, 0]
    label: str = "manual"
    mode: str = "track"  # track | static | keyframes | full_frame
    end_frame: int | None = None
    keyframes: dict[str, list[float]] | None = None
    effect: str | None = None  # blur | pixelate | blackout (per-track override)
    shape: str | None = None   # rect | ellipse


@router.post("/files/{file_id}/video/tracks")
def add_track(file_id: int, body: ManualTrackIn, request: Request, user: User = Depends(require("redactor")),
              db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id, "redactor")
    with _locked(db, f):
        from ..detection.vision.tracker import Track
        from ..redact.video import VideoDocument
        st = get_storage()
        v = VideoDocument(processing.working_path(f))
        v.tracks = [Track.from_dict(t) for t in (st.get_json(f.tracks_blob) if f.tracks_blob else [])]
        if body.mode not in ("track", "static", "keyframes", "full_frame"):
            raise HTTPException(400, "mode must be track, static, keyframes or full_frame")
        t = v.add_manual_track(body.frame, tuple(body.box), body.label, body.mode, body.end_frame, body.keyframes,
                               effect=body.effect, shape=body.shape)
        old = f.tracks_blob
        f.tracks_blob = st.put_json([x.to_dict() for x in v.tracks])
        st.delete(old)
        db.commit()
        audit(request, "manual_track", user, "file", f.id, f.case_id, mode=body.mode, frames=len(t.boxes))
        return t.to_dict(compact=True)


class TrackRestoreIn(BaseModel):
    track: dict


@router.post("/files/{file_id}/video/tracks/restore")
def restore_track(file_id: int, body: TrackRestoreIn, request: Request, user: User = Depends(require("redactor")),
                  db: Session = Depends(get_db)):
    """Put a deleted / trimmed track back exactly (all its per-frame boxes) — used by undo."""
    from ..detection.vision.tracker import Track
    f = file_or_404(db, user, file_id, "redactor")
    try:
        t = Track.from_dict(body.track)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "track needs id, label and boxes")
    st = get_storage()
    with _locked(db, f):
        tracks = [x for x in (st.get_json(f.tracks_blob) if f.tracks_blob else []) if x["id"] != t.id]
        tracks.append(t.to_dict())
        old = f.tracks_blob
        f.tracks_blob = st.put_json(tracks)
        st.delete(old)
        db.commit()
    audit(request, "track_restored", user, "file", f.id, f.case_id, track=t.id)
    return t.to_dict(compact=True)


@router.get("/files/{file_id}/translations")
def list_translations(file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    keys = ((f.info or {}).get("translations") or {})
    out = [{"lang": k.split(":")[0], "redacted": k.endswith(":r")} for k in sorted(keys)]
    if not can_view_originals(user):
        out = [x for x in out if x["redacted"]]
    return out


@router.get("/files/{file_id}/video/frame/{n}.jpg")
def video_frame(file_id: int, n: int, preview: bool = False, effect: str = "blur", user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    _need_originals(user)
    from ..detection.vision.tracker import Track
    from ..redact.video import VideoDocument
    v = VideoDocument(processing.working_path(f))
    if preview and f.tracks_blob:
        v.tracks = [Track.from_dict(t) for t in get_storage().get_json(f.tracks_blob)]
    try:
        data = v.frame_jpeg(n, preview=preview, effect=effect)
    except IndexError:
        raise HTTPException(404, "no such frame")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@router.get("/files/{file_id}/transcript")
def transcript(file_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    _need_originals(user)
    if not f.transcript_blob:
        raise HTTPException(404, "no transcript yet")
    return get_storage().get_json(f.transcript_blob)


class TranslateIn(BaseModel):
    target: str = "en"
    redacted: bool = True


@router.post("/files/{file_id}/translate")
def translate_transcript(file_id: int, body: TranslateIn, request: Request, user: User = Depends(require("redactor")),
                         db: Session = Depends(get_db)):
    from ..detection.audio.translate import LANGUAGES, available
    f = file_or_404(db, user, file_id, "redactor")
    if not f.transcript_blob:
        raise HTTPException(409, "analyze the recording first")
    if body.target not in LANGUAGES:
        raise HTTPException(400, "unsupported language")
    if not available():
        raise HTTPException(503, "translation model not installed (scripts/download_models.py)")
    jid = jobs.submit("translate", lambda ctx: processing.translate_file(f.id, body.target, body.redacted, user.id, ctx),
                      file_id=f.id, case_id=f.case_id, user_id=user.id)
    audit(request, "translation_started", user, "file", f.id, f.case_id, target=body.target, redacted=body.redacted)
    return {"job_id": jid}


@router.get("/files/{file_id}/translations/{lang}")
def get_translation(file_id: int, lang: str, redacted: bool = True, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    if not redacted:
        _need_originals(user)
    blob = ((f.info or {}).get("translations") or {}).get(f"{lang}:{'r' if redacted else 'o'}")
    if not blob:
        raise HTTPException(404, "no such translation yet")
    return get_storage().get_json(blob)


@router.get("/files/{file_id}/captions.{fmt}")
def captions(file_id: int, fmt: str, redacted: bool = True, lang: str | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id)
    if not redacted:
        _need_originals(user)
    if not f.transcript_blob or fmt not in ("srt", "vtt"):
        raise HTTPException(404, "no transcript")
    from ..detection.audio.transcribe import Transcript
    from ..redact.audio import AudioDocument
    if lang:  # captions in a translation
        blob = ((f.info or {}).get("translations") or {}).get(f"{lang}:{'r' if redacted else 'o'}")
        if not blob:
            raise HTTPException(404, "translate the transcript into this language first")
        from ..redact.audio import _ts
        segs = get_storage().get_json(blob)["segments"]
        body = [(f"{_ts(s['start'], '.')} --> {_ts(s['end'], '.')}\n{s['text']}\n" if fmt == "vtt" else
                 f"{i}\n{_ts(s['start'], ',')} --> {_ts(s['end'], ',')}\n{s['text']}\n") for i, s in enumerate(segs, 1)]
        text = ("WEBVTT\n\n" if fmt == "vtt" else "") + "\n".join(body)
    else:
        a = AudioDocument(Path("unused"), Transcript.from_dict(get_storage().get_json(f.transcript_blob)))
        text = a.captions(processing.load_detections(f), fmt, redact=redacted)
    return Response(text, media_type="text/vtt" if fmt == "vtt" else "application/x-subrip",
                    headers={"Content-Disposition": f'attachment; filename="captions.{fmt}"'})


# ---- export ------------------------------------------------------------------------------------

class ExportIn(BaseModel):
    style: dict = {}
    text_style: str = "block"
    effect: str = "blackout"
    face_effect: str | None = None
    audio_effect: str = "bleep"
    voice_disguise: bool = False
    mute_audio: bool = False
    bates_prefix: str | None = None
    bates_start: int = 1
    bates_digits: int = 6
    watermark: str | None = None
    password: str | None = None
    flatten: bool = False
    padding: float = 0.0               # extra margin around every redaction (PDF points / image pixels)
    marked_copy: bool = False          # PDF / image review copy: outlines + labels, nothing removed
    enhance: dict | None = None        # image / video: {brightness, contrast, sharpen, gamma, denoise}
    burn_captions: bool = False        # video: draw the redacted transcript as captions
    second_opinion: bool = True        # final check of the released file with Microsoft Presidio


@router.post("/files/{file_id}/export")
def export(file_id: int, body: ExportIn, request: Request, user: User = Depends(require("redactor")),
           db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id, "redactor")
    if f.kind != "video" and not f.detections_blob:
        raise HTTPException(409, "analyze the file before exporting")
    params = body.model_dump()
    if f.kind == "video" and params["effect"] == "blackout" and "effect" not in body.model_fields_set:
        params["effect"] = "blur"
    jid = jobs.submit("export", lambda ctx: processing.export_file(f.id, params, user.id, ctx), file_id=f.id,
                      case_id=f.case_id, user_id=user.id)
    audit(request, "export_started", user, "file", f.id, f.case_id, job=jid,
          options={k: v for k, v in params.items() if k != "password"})
    return {"job_id": jid}


@router.get("/files/{file_id}/confidence.csv")
def confidence_report(file_id: int, request: Request, user: User = Depends(require("redactor")),
                      db: Session = Depends(get_db)):
    """AI confidence report: every finding with its type, confidence, detector, decision and reason — never the
    redacted value itself."""
    import csv
    import io

    from fastapi.responses import Response
    f = file_or_404(db, user, file_id, "redactor")
    dets = processing.load_detections(f)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["page", "type", "category", "confidence", "detector", "selected", "kind", "exemption", "reason"])
    for d in sorted(dets, key=lambda x: (x.page, -x.score)):
        e = ENTITIES.get(d.entity)
        w.writerow([d.page + 1, e.label if e else d.entity, e.category if e else "", f"{d.score:.2f}",
                    d.source.split("+")[0], "yes" if d.selected else "no", d.kind, d.exemption,
                    processing._reason(d)])
    audit(request, "confidence_report", user, "file", f.id, f.case_id)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="confidence_report_{f.id}.csv"'})


def _export_or_404(db: Session, user: User, export_id: int) -> Export:
    e = db.get(Export, export_id)
    if not e:
        raise HTTPException(404, "no such export")
    file_or_404(db, user, e.file_id)
    return e


@router.get("/exports/{export_id}")
def export_info(export_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = _export_or_404(db, user, export_id)
    report = e.report or {}
    so = report.get("second_opinion")
    if so and so.get("findings") and not can_view_originals(user):
        # viewers see how many items the final check flagged, not the text itself
        report = {**report, "second_opinion": {**so, "findings": [{k: v for k, v in f.items() if k != "text"}
                                                                    for f in so["findings"]]}}
    return {"id": e.id, "file_id": e.file_id, "name": e.name, "sha256": e.sha256, "size": e.size,
            "settings": e.settings, "report": report, "verified": e.verified, "created_at": e.created_at,
            "second_opinion_open": second_opinion_open(e)}


@router.get("/exports/{export_id}/download")
def export_download(export_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = _export_or_404(db, user, export_id)
    marked = bool((e.settings or {}).get("marked_copy"))
    if marked and user.role == "viewer":
        raise HTTPException(403, "review copies show the original content; viewers cannot open them")
    if not e.verified and not marked and user.role not in ("admin", "supervisor"):
        raise HTTPException(409, "this export failed verification; a supervisor must review it")
    audit(request, "export_downloaded", user, "export", e.id, db.get(File, e.file_id).case_id, sha256=e.sha256)
    import mimetypes
    return StreamingResponse(get_storage().stream(e.blob), media_type=mimetypes.guess_type(e.name)[0] or
                             "application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{_safe(e.name)}"'})


@router.delete("/exports/{export_id}")
def delete_export(export_id: int, request: Request, user: User = Depends(require("supervisor")),
                  db: Session = Depends(get_db)):
    e = _export_or_404(db, user, export_id)
    st = get_storage()
    st.delete(e.blob)
    st.delete(e.log_blob)
    fid = e.file_id
    db.delete(e)
    db.commit()
    audit(request, "export_deleted", user, "export", export_id, db.get(File, fid).case_id)
    return {"ok": True}


@router.get("/cases/{case_id}/exports")
def case_exports(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id)
    out = []
    for f in c.files:
        for e in f.exports:
            if e.verified or user.role in ("admin", "supervisor", "redactor"):
                out.append({"id": e.id, "file_id": f.id, "file_name": f.name, "name": e.name, "verified": e.verified,
                            "marked_copy": bool((e.settings or {}).get("marked_copy")),
                            "second_opinion_open": second_opinion_open(e),
                            "sha256": e.sha256, "size": e.size, "created_at": e.created_at})
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


@router.get("/exports/{export_id}/log.csv")
def export_log(export_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = _export_or_404(db, user, export_id)
    data = get_storage().get_bytes(e.log_blob) if e.log_blob else b""
    return Response(data, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="redaction_log.csv"'})


@router.get("/exports/{export_id}/pages/{n}.png")
def export_page(export_id: int, n: int, dpi: int = 110, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Viewers review the *redacted* document page by page."""
    e = _export_or_404(db, user, export_id)
    if not e.name.lower().endswith(".pdf"):
        raise HTTPException(400, "not a PDF export")
    import pymupdf as fitz
    data = get_storage().get_bytes(e.blob)
    doc = fitz.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        raise HTTPException(400, "export is password protected")
    if n >= len(doc):
        raise HTTPException(404, "no such page")
    png = doc[n].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False).tobytes("png")
    return Response(png, media_type="image/png")


def _safe(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "._- ")[:150] or "export"


# ---- jobs --------------------------------------------------------------------------------------

@router.get("/jobs/{job_id}")
def job(job_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "no such job")
    if j.case_id:
        case_or_404(db, user, j.case_id)
    return {"id": j.id, "kind": j.kind, "file_id": j.file_id, "case_id": j.case_id, "status": j.status,
            "progress": j.progress, "message": j.message, "result": j.result, "created_at": j.created_at,
            "started_at": j.started_at, "finished_at": j.finished_at}


@router.get("/jobs")
def list_jobs(active: bool = True, case_id: int | None = None, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    q = db.query(Job).order_by(Job.id.desc())
    if active:
        q = q.filter(Job.status.in_(("queued", "running")))
    if case_id:
        case_or_404(db, user, case_id)
        q = q.filter(Job.case_id == case_id)
    out = []
    for j in q.limit(200).all():
        if j.case_id and user.role not in ("admin", "supervisor"):
            from ..security import can_access_case
            from ..db import Case
            c = db.get(Case, j.case_id)
            if not c or not can_access_case(db, user, c):
                continue
        out.append({"id": j.id, "kind": j.kind, "file_id": j.file_id, "case_id": j.case_id, "status": j.status,
                    "progress": j.progress, "message": j.message})
    return out


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, request: Request, user: User = Depends(require("redactor")), db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "no such job")
    jobs.cancel(job_id)
    audit(request, "job_cancelled", user, "job", job_id, j.case_id)
    return {"ok": True}
