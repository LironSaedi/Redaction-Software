from __future__ import annotations

from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import jobs, processing
from ..db import Case, CaseMember, CaseNote, File, User, get_db
from ..detection.text.entities import PROFILES
from ..security import can_access_case, case_or_404, current_user, require
from .common import audit, case_out, file_out

router = APIRouter(prefix="/api/cases", tags=["cases"])


class CaseIn(BaseModel):
    name: str
    number: str = ""
    description: str = ""
    request_type: str = ""
    due_date: datetime | None = None
    default_profile: str = "standard"
    members: list[dict] = []


class CasePatch(BaseModel):
    name: str | None = None
    number: str | None = None
    description: str | None = None
    status: str | None = None
    request_type: str | None = None
    due_date: datetime | None = None
    default_profile: str | None = None


def _counts(db: Session, case: Case) -> dict:
    files = case.files
    st = Counter(f.status for f in files)  # (review copies never set "exported")
    return {"file_count": len(files), "status_counts": dict(st),
            "exported": st.get("exported", 0), "member_count": len(case.members)}


@router.get("")
def list_cases(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cases = db.query(Case).order_by(Case.updated_at.desc()).all()
    return [case_out(c, _counts(db, c)) for c in cases if can_access_case(db, user, c)]


@router.post("")
def create_case(body: CaseIn, request: Request, user: User = Depends(require("redactor")), db: Session = Depends(get_db)):
    if body.default_profile not in PROFILES:
        raise HTTPException(400, "unknown profile")
    c = Case(name=body.name.strip() or "Untitled case", number=body.number, description=body.description,
             request_type=body.request_type, due_date=body.due_date, default_profile=body.default_profile,
             created_by=user.id)
    db.add(c)
    db.flush()
    db.add(CaseMember(case_id=c.id, user_id=user.id, role="reviewer"))
    for m in body.members:
        if db.get(User, int(m["user_id"])) and int(m["user_id"]) != user.id:
            db.add(CaseMember(case_id=c.id, user_id=int(m["user_id"]), role=m.get("role", "redactor")))
    db.commit()
    audit(request, "case_created", user, "case", c.id, c.id)
    return case_out(c, _counts(db, c))


@router.get("/{case_id}")
def get_case(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id)
    members = [{"user_id": m.user_id, "role": m.role, "username": db.get(User, m.user_id).username,
                "full_name": db.get(User, m.user_id).full_name} for m in c.members]
    files = sorted(c.files, key=lambda f: f.uploaded_at)
    return case_out(c, _counts(db, c)) | {"members": members, "files": [file_out(f) for f in files]}


@router.patch("/{case_id}")
def patch_case(case_id: int, body: CasePatch, request: Request, user: User = Depends(require("redactor")),
               db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id, "redactor")
    data = body.model_dump(exclude_unset=True)
    if "default_profile" in data and data["default_profile"] not in PROFILES:
        raise HTTPException(400, "unknown profile")
    if data.get("status") == "closed" and user.role not in ("admin", "supervisor"):
        raise HTTPException(403, "only supervisors can close cases")
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    audit(request, "case_updated", user, "case", c.id, c.id, fields=sorted(data))
    return case_out(c, _counts(db, c))


@router.delete("/{case_id}")
def delete_case(case_id: int, request: Request, user: User = Depends(require("supervisor")),
                db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id)
    from ..storage import get_storage
    st = get_storage()
    n = 0
    for f in c.files:
        for blob in (f.original_blob, f.working_blob, f.extract_blob, f.detections_blob, f.tracks_blob, f.transcript_blob):
            st.delete(blob)
        for e in f.exports:
            st.delete(e.blob)
            st.delete(e.log_blob)
        n += 1
    st.delete(c.dictionary_blob)
    db.delete(c)
    db.commit()
    audit(request, "case_deleted", user, "case", case_id, case_id, files_destroyed=n)
    return {"ok": True}


class MemberIn(BaseModel):
    user_id: int
    role: str = "redactor"


@router.post("/{case_id}/members")
def add_member(case_id: int, body: MemberIn, request: Request, user: User = Depends(require("redactor")),
               db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id, "reviewer")
    if body.role not in ("redactor", "reviewer", "viewer"):
        raise HTTPException(400, "bad member role")
    if not db.get(User, body.user_id):
        raise HTTPException(404, "no such user")
    m = db.query(CaseMember).filter_by(case_id=c.id, user_id=body.user_id).first()
    if m:
        m.role = body.role
    else:
        db.add(CaseMember(case_id=c.id, user_id=body.user_id, role=body.role))
    db.commit()
    audit(request, "member_added", user, "case", c.id, c.id, member=body.user_id, role=body.role)
    return {"ok": True}


@router.delete("/{case_id}/members/{uid}")
def remove_member(case_id: int, uid: int, request: Request, user: User = Depends(require("redactor")),
                  db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id, "reviewer")
    db.query(CaseMember).filter_by(case_id=c.id, user_id=uid).delete()
    db.commit()
    audit(request, "member_removed", user, "case", c.id, c.id, member=uid)
    return {"ok": True}


class NoteIn(BaseModel):
    body: str
    file_id: int | None = None


@router.get("/{case_id}/notes")
def notes(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id)
    out = []
    for n in db.query(CaseNote).filter_by(case_id=c.id).order_by(CaseNote.created_at).all():
        u = db.get(User, n.user_id)
        out.append({"id": n.id, "file_id": n.file_id, "body": n.body, "user": u.username if u else "?",
                    "created_at": n.created_at})
    return out


@router.post("/{case_id}/notes")
def add_note(case_id: int, body: NoteIn, request: Request, user: User = Depends(require("viewer")),
             db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id)
    n = CaseNote(case_id=c.id, file_id=body.file_id, user_id=user.id, body=body.body[:5000])
    db.add(n)
    db.commit()
    audit(request, "note_added", user, "case", c.id, c.id, file_id=body.file_id)
    return {"id": n.id}


class BulkIn(BaseModel):
    file_ids: list[int] | None = None
    params: dict = {}


@router.post("/{case_id}/bulk/analyze")
def bulk_analyze(case_id: int, body: BulkIn, request: Request, user: User = Depends(require("redactor")),
                 db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id, "redactor")
    ids = body.file_ids or [f.id for f in c.files]
    job_ids = [jobs.submit("analyze", lambda ctx, fid=fid: processing.analyze_file(fid, body.params, ctx), file_id=fid,
                           case_id=c.id, params=body.params, user_id=user.id) for fid in ids]
    audit(request, "bulk_analyze", user, "case", c.id, c.id, files=len(ids))
    return {"jobs": job_ids}


@router.post("/{case_id}/bulk/export")
def bulk_export(case_id: int, body: BulkIn, request: Request, user: User = Depends(require("redactor")),
                db: Session = Depends(get_db)):
    c = case_or_404(db, user, case_id, "redactor")
    ids = body.file_ids or [f.id for f in c.files if f.detections_blob]
    job_ids = [jobs.submit("export", lambda ctx, fid=fid: processing.export_file(fid, body.params, user.id, ctx),
                           file_id=fid, case_id=c.id, user_id=user.id) for fid in ids]
    audit(request, "bulk_export", user, "case", c.id, c.id, files=len(ids))
    return {"jobs": job_ids}


@router.get("/{case_id}/report")
def case_report(case_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Redaction summary for the request: per file and per category counts, exemptions used."""
    c = case_or_404(db, user, case_id)
    rows, by_ent, by_ex = [], Counter(), Counter()
    for f in c.files:
        dets = processing.load_detections(f)
        sel = [d for d in dets if d.selected]
        by_ent.update(d.entity for d in sel)
        by_ex.update(d.exemption for d in sel if d.exemption)
        rows.append({"file_id": f.id, "name": f.name, "kind": f.kind, "status": f.status, "pages": f.page_count,
                     "redactions": len(sel),
                     "exports": len([e for e in f.exports if not (e.settings or {}).get("marked_copy")]),
                     "review_copies": len([e for e in f.exports if (e.settings or {}).get("marked_copy")]),
                     "verified": all(e.verified for e in f.exports if not (e.settings or {}).get("marked_copy"))
                     if any(not (e.settings or {}).get("marked_copy") for e in f.exports) else None})
    return {"case": case_out(c), "files": rows, "by_entity": dict(by_ent), "by_exemption": dict(by_ex),
            "total_redactions": sum(by_ent.values())}


# ---- additional text to redact (case-wide) --------------------------------------------------------

EXTRA_LIST_NAME = "Additional text to redact"
_MAX_TERMS = 500


class ExtraTerm(BaseModel):
    text: str
    regex: bool = False
    case_sensitive: bool = False
    whole_word: bool = True
    entity: str | None = None


class RedactTextIn(BaseModel):
    terms: list[ExtraTerm]
    file_ids: list[int] | None = None  # None: every file in the case
    remember: bool = True              # also redact these in files added or analysed later
    preview: bool = False              # count matches without adding redactions
    entity: str = "CUSTOM"
    exemption: str = ""


class ExtraListIn(BaseModel):
    terms: list[ExtraTerm]


def _extra_list(db: Session, case: Case):
    from ..db import TermList
    return (db.query(TermList).filter_by(case_id=case.id, kind="redact", name=EXTRA_LIST_NAME)
            .order_by(TermList.id).first())


def _clean_terms(terms: list[ExtraTerm]) -> list[dict]:
    import re
    out, seen = [], set()
    for t in terms:
        txt = t.text.strip()
        if not txt:
            continue
        if len(txt) > 500:
            raise HTTPException(400, "each entry must be under 500 characters")
        if t.regex:
            try:
                rx = re.compile(txt)
            except re.error as e:
                raise HTTPException(400, f"bad pattern {txt!r}: {e}")
            if rx.match(""):
                raise HTTPException(400, f"pattern {txt!r} matches empty text")
        key = (txt if t.case_sensitive else txt.lower(), t.regex, t.case_sensitive, t.whole_word)
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": txt, "regex": t.regex, "case_sensitive": t.case_sensitive, "whole_word": t.whole_word,
                    "entity": t.entity})
    if len(out) > _MAX_TERMS:
        raise HTTPException(400, f"at most {_MAX_TERMS} entries at a time")
    return out


def _save_extra(db: Session, case: Case, user: User, terms: list[dict], replace: bool) -> int:
    from ..db import TermList
    from ..storage import get_storage
    st = get_storage()
    tl = _extra_list(db, case)
    if tl is None:
        tl = TermList(name=EXTRA_LIST_NAME, kind="redact", terms_blob=st.put_json([]), entity="CUSTOM",
                      case_id=case.id, created_by=user.id)
        db.add(tl)
        db.flush()
    cur = [] if replace else st.get_json(tl.terms_blob)
    have = {(t["text"] if t.get("case_sensitive") else t["text"].lower(), bool(t.get("regex")),
             bool(t.get("case_sensitive")), t.get("whole_word", True)) for t in cur}
    for t in terms:
        k = (t["text"] if t["case_sensitive"] else t["text"].lower(), t["regex"], t["case_sensitive"], t["whole_word"])
        if k not in have:
            have.add(k)
            cur.append(t)
    old = tl.terms_blob
    tl.terms_blob = st.put_json(cur[-5000:])
    st.delete(old)
    db.commit()
    return tl.id


@router.get("/{case_id}/redact-text")
def get_extra_text(case_id: int, user: User = Depends(require("redactor")), db: Session = Depends(get_db)):
    """The words, names, numbers and patterns redacted in every file of this case."""
    from ..storage import get_storage
    case = case_or_404(db, user, case_id)
    tl = _extra_list(db, case)
    return {"list_id": tl.id if tl else None, "terms": get_storage().get_json(tl.terms_blob) if tl else []}


@router.put("/{case_id}/redact-text")
def put_extra_text(case_id: int, body: ExtraListIn, request: Request, user: User = Depends(require("redactor")),
                   db: Session = Depends(get_db)):
    """Replace the remembered list (removing an entry does not undo redactions already added)."""
    case = case_or_404(db, user, case_id, "redactor")
    terms = _clean_terms(body.terms)
    lid = _save_extra(db, case, user, terms, replace=True)
    audit(request, "case_extra_text_updated", user, "case", case.id, case.id, terms=len(terms))
    return {"list_id": lid, "terms": terms}


@router.post("/{case_id}/redact-text")
def redact_text(case_id: int, body: RedactTextIn, request: Request, user: User = Depends(require("redactor")),
                db: Session = Depends(get_db)):
    """Redact extra text — exact words, phrases, numbers or patterns — in every file of the case (or the chosen
    files) right now, and optionally in every file added or analysed later."""
    from ..detection.text.engine import SearchTerm
    from .files import _locked
    case = case_or_404(db, user, case_id, "redactor")
    terms = _clean_terms(body.terms)
    if not terms:
        raise HTTPException(400, "enter at least one word, phrase, number or pattern")
    search = [SearchTerm(text=t["text"], entity=t.get("entity") or body.entity, regex=t["regex"],
                         case_sensitive=t["case_sensitive"], whole_word=t["whole_word"],
                         exemption=body.exemption or None, label=EXTRA_LIST_NAME.lower()) for t in terms]
    files = db.query(File).filter(File.case_id == case.id).order_by(File.id).all()
    if body.file_ids is not None:
        want = set(body.file_ids)
        files = [f for f in files if f.id in want]
        if len(files) != len(want):
            raise HTTPException(404, "file not found in this case")
    results, total_m, total_a = [], 0, 0
    for f in files:
        row = {"file_id": f.id, "name": f.name, "matches": 0, "added": 0, "added_ids": [], "new_ids": [],
               "switched_ids": []}
        if f.status in ("analyzing", "uploaded") or (f.status == "error" and not f.detections_blob):
            row["skipped"] = "not analysed yet" + (" — it will be redacted when analysed" if body.remember else "")
            results.append(row)
            continue
        if f.kind in ("mailbox", "zip", "archive"):
            continue
        try:
            found = processing.search_file(f, search)
        except Exception as e:  # one unreadable file must not stop the rest
            row["skipped"] = f"could not search: {type(e).__name__}"
            results.append(row)
            continue
        row["matches"] = len(found)
        total_m += len(found)
        if found and not body.preview:
            with _locked(db, f):
                dets = processing.load_detections(f)
                new, switched = processing.merge_found(dets, found)
                if new or switched:
                    processing.save_detections(f, dets + new, db)
                    db.commit()
            row["added"], row["added_ids"] = len(new) + len(switched), [d.id for d in new] + switched
            row["new_ids"], row["switched_ids"] = [d.id for d in new], switched  # undo: delete new, un-select switched
            total_a += row["added"]
            if row["added"] and f.status in ("approved", "exported"):
                row["needs_reexport"] = True
        results.append(row)
    list_id = None
    if body.remember and not body.preview:
        list_id = _save_extra(db, case, user, terms, replace=False)
    if not body.preview:
        # never log the terms themselves: they are usually names and numbers
        audit(request, "case_text_redaction", user, "case", case.id, case.id, terms=len(terms),
              files=len(results), added=total_a, remembered=bool(list_id))
    return {"files": results, "total_matches": total_m, "total_added": total_a, "remembered": bool(list_id),
            "list_id": list_id, "preview": body.preview}
