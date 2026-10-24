from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import __version__
from ..db import ExemptionCode, Preset, Template, TermList, User, get_db
from ..detection.text import ner
from ..detection.text.entities import CATEGORIES, ENTITIES, EXEMPTION_CODES, PARTIAL_RULES, PROFILES, entities_for_profile
from ..detection.vision.detectors import VISUAL_CLASSES
from ..redact.audio import AUDIO_EFFECTS
from ..redact.effects import EFFECTS
from ..security import case_or_404, current_user, require
from ..storage import get_storage
from .common import audit

router = APIRouter(prefix="/api", tags=["library"])


@router.get("/meta")
def meta(user: User = Depends(current_user), db: Session = Depends(get_db)):
    custom_codes = {c.code: c.description for c in db.query(ExemptionCode).all()}
    return {
        "version": __version__,
        "entities": [{"key": e.key, "label": e.label, "category": e.category, "description": e.description,
                      "default_on": e.default_on, "exemption": e.exemption, "hipaa": e.hipaa} for e in ENTITIES.values()],
        "categories": CATEGORIES,
        "profiles": [{"key": k, "label": v, "entities": sorted(entities_for_profile(k)),
                      "partial": PARTIAL_RULES.get(k, {})} for k, v in PROFILES.items()],
        "exemption_codes": EXEMPTION_CODES | custom_codes,
        "visual_classes": VISUAL_CLASSES,
        "effects": EFFECTS,
        "audio_effects": AUDIO_EFFECTS,
        "models": ner.loaded_models(),
        "video_modes": ["balanced", "max_accuracy", "fast"],
        "languages": _languages(),
        "image_classes": _image_classes(),
        "shapes": ["rect", "ellipse", "polygon"],
        "track_modes": ["track", "static", "keyframes", "full_frame"],
        "second_opinion": _second_opinion_status(),
    }


def _languages() -> dict:
    from ..config import MODELS_DIR
    from ..detection.audio.translate import LANGUAGES, available
    return {"transcription": "auto" if (MODELS_DIR / "whisper" / "small").exists() else "en",
            "translation_available": available(), "codes": LANGUAGES}


def _image_classes() -> dict:
    from ..detection.vision.classify import IMAGE_CLASSES, SELECT_WHOLE
    return {"classes": IMAGE_CLASSES, "selected_by_default": sorted(SELECT_WHOLE)}


# ---- term lists ---------------------------------------------------------------------------------

class ListIn(BaseModel):
    name: str
    kind: str = "redact"
    terms: list[dict | str]
    entity: str = "CUSTOM"
    exemption: str = ""
    case_id: int | None = None


def _list_out(tl: TermList, with_terms: bool = False) -> dict:
    d = {"id": tl.id, "name": tl.name, "kind": tl.kind, "entity": tl.entity, "exemption": tl.exemption,
         "case_id": tl.case_id, "created_at": tl.created_at}
    terms = get_storage().get_json(tl.terms_blob)
    d["count"] = len(terms)
    if with_terms:
        d["terms"] = terms
    return d


def _second_opinion_status() -> dict:
    from ..detection.text import second_opinion
    st = second_opinion.quick_status()
    return {"available": st["available"], "engine": "Microsoft Presidio", "version": st.get("version"),
            "reason": st.get("reason")}


@router.get("/lists")
def lists(case_id: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(TermList)
    if case_id:
        case_or_404(db, user, case_id)
        q = q.filter((TermList.case_id == case_id) | (TermList.case_id.is_(None)))
    else:
        q = q.filter(TermList.case_id.is_(None))
    return [_list_out(t) for t in q.order_by(TermList.name).all()]


@router.get("/lists/{lid}")
def get_list(lid: int, user: User = Depends(require("redactor")), db: Session = Depends(get_db)):
    tl = db.get(TermList, lid)
    if not tl:
        raise HTTPException(404, "no such list")
    if tl.case_id:
        case_or_404(db, user, tl.case_id)
    return _list_out(tl, True)


def _norm_terms(terms) -> list[dict]:
    out = []
    for t in terms:
        if isinstance(t, str):
            t = {"text": t}
        txt = str(t.get("text", "")).strip()
        if txt:
            out.append({"text": txt, "regex": bool(t.get("regex")), "case_sensitive": bool(t.get("case_sensitive")),
                        "whole_word": t.get("whole_word", True), "entity": t.get("entity")})
    if any(t["regex"] for t in out):
        import re
        for t in out:
            if t["regex"]:
                try:
                    re.compile(t["text"])
                except re.error as e:
                    raise HTTPException(400, f"bad pattern {t['text']!r}: {e}")
    return out


@router.post("/lists")
def create_list(body: ListIn, request: Request, user: User = Depends(require("redactor")), db: Session = Depends(get_db)):
    if body.kind not in ("redact", "allow"):
        raise HTTPException(400, "kind must be redact or allow")
    if body.case_id:
        case_or_404(db, user, body.case_id, "redactor")
    tl = TermList(name=body.name, kind=body.kind, terms_blob=get_storage().put_json(_norm_terms(body.terms)),
                  entity=body.entity, exemption=body.exemption, case_id=body.case_id, created_by=user.id)
    db.add(tl)
    db.commit()
    audit(request, "list_created", user, "list", tl.id, body.case_id, kind=tl.kind)
    return _list_out(tl)


@router.put("/lists/{lid}")
def update_list(lid: int, body: ListIn, request: Request, user: User = Depends(require("redactor")),
                db: Session = Depends(get_db)):
    tl = db.get(TermList, lid)
    if not tl:
        raise HTTPException(404, "no such list")
    if tl.case_id:
        case_or_404(db, user, tl.case_id, "redactor")
    if body.case_id is not None and body.case_id != tl.case_id:
        raise HTTPException(400, "a list cannot be moved to another case")
    st = get_storage()
    old = tl.terms_blob
    tl.name, tl.kind, tl.entity, tl.exemption = body.name, body.kind, body.entity, body.exemption
    tl.terms_blob = st.put_json(_norm_terms(body.terms))
    st.delete(old)
    db.commit()
    audit(request, "list_updated", user, "list", tl.id, tl.case_id)
    return _list_out(tl)


@router.delete("/lists/{lid}")
def delete_list(lid: int, request: Request, user: User = Depends(require("redactor")), db: Session = Depends(get_db)):
    tl = db.get(TermList, lid)
    if tl:
        if tl.case_id:
            case_or_404(db, user, tl.case_id, "redactor")
        get_storage().delete(tl.terms_blob)
        db.delete(tl)
        db.commit()
        audit(request, "list_deleted", user, "list", lid)
    return {"ok": True}


# ---- templates ----------------------------------------------------------------------------------

class TemplateIn(BaseModel):
    name: str
    description: str = ""
    zones: list[dict]


def _check_zones(zones: list[dict]) -> list[dict]:
    out = []
    for z in zones:
        try:
            x0, y0, x1, y1 = (float(z[k]) for k in ("x0", "y0", "x1", "y1"))
        except (KeyError, ValueError):
            raise HTTPException(400, "zone needs x0,y0,x1,y1 as fractions of the page")
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise HTTPException(400, "zone coordinates must be fractions 0..1")
        out.append({"pages": str(z.get("pages", "all")), "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                    "entity": z.get("entity", "CUSTOM"), "exemption": z.get("exemption", ""),
                    "label": z.get("label", "")})
    return out


@router.get("/templates")
def templates(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": t.id, "name": t.name, "description": t.description, "zones": t.zones} for t in
            db.query(Template).order_by(Template.name).all()]


@router.post("/templates")
def create_template(body: TemplateIn, request: Request, user: User = Depends(require("redactor")),
                    db: Session = Depends(get_db)):
    t = Template(name=body.name, description=body.description, zones=_check_zones(body.zones), created_by=user.id)
    db.add(t)
    db.commit()
    audit(request, "template_created", user, "template", t.id, zones=len(t.zones))
    return {"id": t.id, "name": t.name, "description": t.description, "zones": t.zones}


@router.put("/templates/{tid}")
def update_template(tid: int, body: TemplateIn, request: Request, user: User = Depends(require("redactor")),
                    db: Session = Depends(get_db)):
    t = db.get(Template, tid)
    if not t:
        raise HTTPException(404, "no such template")
    t.name, t.description, t.zones = body.name, body.description, _check_zones(body.zones)
    db.commit()
    audit(request, "template_updated", user, "template", t.id)
    return {"id": t.id, "name": t.name, "description": t.description, "zones": t.zones}


@router.delete("/templates/{tid}")
def delete_template(tid: int, request: Request, user: User = Depends(require("redactor")), db: Session = Depends(get_db)):
    t = db.get(Template, tid)
    if t:
        db.delete(t)
        db.commit()
        audit(request, "template_deleted", user, "template", tid)
    return {"ok": True}


# ---- presets & exemption codes -------------------------------------------------------------------

class PresetIn(BaseModel):
    name: str
    settings: dict


@router.get("/presets")
def presets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name, "settings": p.settings} for p in db.query(Preset).order_by(Preset.name).all()]


@router.post("/presets")
def create_preset(body: PresetIn, request: Request, user: User = Depends(require("supervisor")),
                  db: Session = Depends(get_db)):
    if db.query(Preset).filter_by(name=body.name).first():
        raise HTTPException(409, "preset name exists")
    p = Preset(name=body.name, settings=body.settings, created_by=user.id)
    db.add(p)
    db.commit()
    audit(request, "preset_created", user, "preset", p.id)
    return {"id": p.id, "name": p.name, "settings": p.settings}


@router.delete("/presets/{pid}")
def delete_preset(pid: int, request: Request, user: User = Depends(require("supervisor")), db: Session = Depends(get_db)):
    p = db.get(Preset, pid)
    if p:
        db.delete(p)
        db.commit()
        audit(request, "preset_deleted", user, "preset", pid)
    return {"ok": True}


class CodeIn(BaseModel):
    code: str
    description: str = ""


@router.post("/exemption-codes")
def add_code(body: CodeIn, request: Request, user: User = Depends(require("supervisor")), db: Session = Depends(get_db)):
    code = body.code.strip()
    if not code or len(code) > 40:
        raise HTTPException(400, "bad code")
    c = db.query(ExemptionCode).filter_by(code=code).first() or ExemptionCode(code=code)
    c.description = body.description
    db.add(c)
    db.commit()
    audit(request, "exemption_code_saved", user, "exemption", code)
    return {"code": c.code, "description": c.description}


@router.delete("/exemption-codes/{code:path}")
def delete_code(code: str, request: Request, user: User = Depends(require("supervisor")), db: Session = Depends(get_db)):
    from ..detection.text.entities import EXEMPTION_CODES as BUILTIN
    if code in BUILTIN:
        raise HTTPException(400, "built-in codes cannot be deleted")
    c = db.query(ExemptionCode).filter_by(code=code).first()
    if c:
        db.delete(c)
        db.commit()
        audit(request, "exemption_code_deleted", user, "exemption", code)
    return {"ok": True}
