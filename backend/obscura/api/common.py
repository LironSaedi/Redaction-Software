from __future__ import annotations

from fastapi import Request

from ..audit import record
from ..db import Case, File, User


def ip(request: Request) -> str:
    return request.client.host if request.client else ""


def audit(request: Request, action: str, user: User | None, obj_type: str = "", obj_id="", case_id=None,
          **details) -> None:
    record(action, user, obj_type, obj_id, case_id, details, ip(request))


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email, "role": u.role,
            "is_active": u.is_active, "must_change_password": u.must_change_password,
            "locked": bool(u.locked_until), "created_at": u.created_at, "last_login": u.last_login,
            "local": u.username == "local"}


def case_out(c: Case, counts: dict | None = None) -> dict:
    return {"id": c.id, "name": c.name, "number": c.number, "description": c.description, "status": c.status,
            "request_type": c.request_type, "due_date": c.due_date, "default_profile": c.default_profile,
            "created_by": c.created_by, "created_at": c.created_at, "updated_at": c.updated_at, **(counts or {})}


def file_out(f: File) -> dict:
    return {"id": f.id, "case_id": f.case_id, "parent_id": f.parent_id, "name": f.name, "kind": f.kind, "ext": f.ext,
            "mime": f.mime, "size": f.size, "sha256": f.sha256, "page_count": f.page_count, "duration": f.duration,
            "info": _public_info(f.info), "status": f.status, "assigned_to": f.assigned_to, "uploaded_by": f.uploaded_by,
            "uploaded_at": f.uploaded_at, "analyzed_at": f.analyzed_at, "approved_by": f.approved_by,
            "error": f.error, "approved": bool(f.approved_by), "has_detections": bool(f.detections_blob), "has_tracks": bool(f.tracks_blob),
            "has_transcript": bool(f.transcript_blob),
            "exports": [{"id": e.id, "name": e.name, "verified": e.verified, "created_at": e.created_at,
                         "sha256": e.sha256, "size": e.size, "marked_copy": bool((e.settings or {}).get("marked_copy")),
                         "second_opinion_open": second_opinion_open(e)}
                        for e in f.exports]}


def second_opinion_open(e) -> int | None:
    """Items the Presidio final check still found in an export (None: not checked)."""
    so = (e.report or {}).get("second_opinion") or {}
    return so.get("open") if so.get("checked") else None


def _public_info(info: dict | None) -> dict:
    """File info without internal storage ids: translations are listed as language keys only."""
    out = dict(info or {})
    if "translations" in out:
        out["translations"] = sorted(out["translations"])  # ["es:r", "fr:o", …] (r = redacted, o = original)
    return out
