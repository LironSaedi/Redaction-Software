from __future__ import annotations

import csv
import io
import os
import platform
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import processing
from ..audit import verify_chain
from ..config import DATA_DIR, MODELS_DIR, settings
from ..db import AuditEvent, Case, File, Preset, User, Watcher, get_db
from ..security import case_or_404, current_user, file_or_404, require
from ..storage import get_storage
from ..tools import pdf_tools
from .common import audit, file_out

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/audit")
def audit_log(case_id: int | None = None, file_id: int | None = None, user_id: int | None = None,
              action: str | None = None, limit: int = 500, offset: int = 0,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(AuditEvent)
    if case_id:
        case_or_404(db, user, case_id)
        q = q.filter(AuditEvent.case_id == case_id)
    elif user.role not in ("admin", "supervisor"):
        raise HTTPException(403, "supervisor role required for the global audit log")
    if file_id:
        q = q.filter(AuditEvent.object_type == "file", AuditEvent.object_id == str(file_id))
    if user_id:
        q = q.filter(AuditEvent.user_id == user_id)
    if action:
        q = q.filter(AuditEvent.action == action)
    rows = q.order_by(AuditEvent.id.desc()).offset(offset).limit(min(limit, 5000)).all()
    return [{"id": e.id, "ts": e.ts, "user": e.username, "action": e.action, "object_type": e.object_type,
             "object_id": e.object_id, "case_id": e.case_id, "details": e.details, "ip": e.ip, "hash": e.hash[:16]}
            for e in rows]


@router.get("/audit/verify")
def audit_verify(user: User = Depends(require("supervisor")), db: Session = Depends(get_db)):
    return verify_chain(db)


@router.get("/audit/export.csv")
def audit_csv(case_id: int | None = None, request: Request = None, user: User = Depends(require("supervisor")),
              db: Session = Depends(get_db)):
    q = db.query(AuditEvent).order_by(AuditEvent.id)
    if case_id:
        q = q.filter(AuditEvent.case_id == case_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "timestamp_utc", "user", "action", "object_type", "object_id", "case_id", "details", "ip",
                "prev_hash", "hash"])
    for e in q.yield_per(1000):
        w.writerow([e.id, e.ts.isoformat(), e.username, e.action, e.object_type, e.object_id, e.case_id, e.details,
                    e.ip, e.prev_hash, e.hash])
    audit(request, "audit_exported", user, "audit", "", case_id)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="audit_log.csv"'})


# ---- watchers ----------------------------------------------------------------------------------

class WatcherIn(BaseModel):
    name: str
    input_dir: str
    output_dir: str
    case_id: int
    preset_id: int | None = None
    export_settings: dict = {}
    enabled: bool = True


@router.get("/watchers")
def watchers(user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [{"id": w.id, "name": w.name, "input_dir": w.input_dir, "output_dir": w.output_dir, "case_id": w.case_id,
             "preset_id": w.preset_id, "export_settings": w.export_settings, "enabled": w.enabled}
            for w in db.query(Watcher).all()]


@router.post("/watchers")
def create_watcher(body: WatcherIn, request: Request, user: User = Depends(require("admin")),
                   db: Session = Depends(get_db)):
    if not db.get(Case, body.case_id):
        raise HTTPException(404, "no such case")
    if body.preset_id and not db.get(Preset, body.preset_id):
        raise HTTPException(404, "no such preset")
    inp, out = Path(body.input_dir).expanduser(), Path(body.output_dir).expanduser()
    if inp.resolve() == out.resolve():
        raise HTTPException(400, "output folder must differ from input folder")
    inp.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    w = Watcher(name=body.name, input_dir=str(inp), output_dir=str(out), case_id=body.case_id,
                preset_id=body.preset_id, export_settings=body.export_settings, enabled=body.enabled,
                created_by=user.id)
    db.add(w)
    db.commit()
    audit(request, "watcher_created", user, "watcher", w.id, body.case_id)
    return {"id": w.id}


class WatcherPatch(BaseModel):
    enabled: bool


@router.patch("/watchers/{wid}")
def toggle_watcher(wid: int, request: Request, body: WatcherPatch | None = None, enabled: bool | None = None,
                   user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    enabled = body.enabled if body is not None else enabled
    if enabled is None:
        raise HTTPException(400, "enabled is required")
    w = db.get(Watcher, wid)
    if not w:
        raise HTTPException(404, "no such watcher")
    w.enabled = enabled
    db.commit()
    audit(request, "watcher_toggled", user, "watcher", wid, w.case_id, enabled=enabled)
    return {"ok": True}


@router.delete("/watchers/{wid}")
def delete_watcher(wid: int, request: Request, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    w = db.get(Watcher, wid)
    if w:
        db.delete(w)
        db.commit()
        audit(request, "watcher_deleted", user, "watcher", wid)
    return {"ok": True}


# ---- document tools ----------------------------------------------------------------------------

class MergeIn(BaseModel):
    file_ids: list[int]
    name: str = "merged.pdf"


@router.post("/cases/{case_id}/tools/merge")
def merge(case_id: int, body: MergeIn, request: Request, user: User = Depends(require("redactor")),
          db: Session = Depends(get_db)):
    case = case_or_404(db, user, case_id, "redactor")
    files = [file_or_404(db, user, fid, "redactor") for fid in body.file_ids]
    if any(f.kind != "pdf" for f in files) or len(files) < 2:
        raise HTTPException(400, "merge needs two or more PDFs")
    st = get_storage()
    with st.scratch(".pdf") as out:
        pdf_tools.merge([processing.working_path(f) for f in files], out)
        ids = processing.ingest(case.id, out, body.name if body.name.endswith(".pdf") else body.name + ".pdf", user.id)
    audit(request, "files_merged", user, "case", case.id, case.id, sources=body.file_ids, result=ids[0])
    return file_out(db.get(File, ids[0]))


class SplitIn(BaseModel):
    ranges: list[list[int]]


@router.post("/files/{file_id}/tools/split")
def split(file_id: int, body: SplitIn, request: Request, user: User = Depends(require("redactor")),
          db: Session = Depends(get_db)):
    f = file_or_404(db, user, file_id, "redactor")
    if f.kind != "pdf":
        raise HTTPException(400, "split works on PDFs")
    st = get_storage()
    d = st.scratch_dir()
    try:
        outs = pdf_tools.split(processing.working_path(f), [tuple(r) for r in body.ranges], d, Path(f.name).stem)
        ids = [processing.ingest(f.case_id, p, p.name, user.id)[0] for p in outs]
    finally:
        shutil.rmtree(d, ignore_errors=True)
    audit(request, "file_split", user, "file", f.id, f.case_id, parts=len(ids))
    return [file_out(db.get(File, i)) for i in ids]


class OrganizeIn(BaseModel):
    order: list[int] | None = None
    rotate: dict[int, int] | None = None
    delete: list[int] | None = None


@router.post("/files/{file_id}/tools/organize")
def organize(file_id: int, body: OrganizeIn, request: Request, user: User = Depends(require("redactor")),
             db: Session = Depends(get_db)):
    """Creates a new file version with pages re-ordered / rotated / removed (the original is kept)."""
    f = file_or_404(db, user, file_id, "redactor")
    if f.kind != "pdf":
        raise HTTPException(400, "organize works on PDFs")
    st = get_storage()
    with st.scratch(".pdf") as out:
        pdf_tools.organize(processing.working_path(f), out, body.order, body.rotate, body.delete)
        ids = processing.ingest(f.case_id, out, Path(f.name).stem + "_organized.pdf", user.id)
    audit(request, "file_organized", user, "file", f.id, f.case_id, result=ids[0])
    return file_out(db.get(File, ids[0]))


# ---- system --------------------------------------------------------------------------------------

@router.get("/system")
def system(user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    from ..detection.text import ner
    from ..redact import ocr
    disk = shutil.disk_usage(DATA_DIR)
    models = {}
    for sub in ("gliner", "whisper", "vision"):
        d = MODELS_DIR / sub
        models[sub] = sorted(p.name for p in d.iterdir()) if d.exists() else []
    return {"host": settings.host, "port": settings.port, "platform": platform.platform(),
            "python": platform.python_version(), "encrypt_at_rest": settings.encrypt_at_rest,
            "offline": os.environ.get("HF_HUB_OFFLINE") == "1", "ocr_available": ocr.available(),
            "models_on_disk": models, "models_loaded": ner.loaded_models(), "spacy_model": settings.spacy_model,
            "gliner_model": settings.gliner_model, "whisper_model": settings.whisper_model,
            "data_dir": str(DATA_DIR), "disk_free_gb": round(disk.free / 1e9, 1),
            "users": db.query(User).count(), "cases": db.query(Case).count(), "files": db.query(File).count()}
