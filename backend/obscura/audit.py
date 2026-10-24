"""Tamper-evident audit trail.

Each event stores the SHA-256 of the previous event; ``hash = sha256(prev_hash || canonical(event))``.
Editing, deleting or re-ordering any historical row breaks the chain from that point on, which
:func:`verify_chain` reports. Event details never contain redacted values — only ids, counts and
settings — so the log itself is safe to hand to an auditor.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import timezone

from sqlalchemy.orm import Session

from .db import AuditEvent, tx, utcnow

_lock = threading.Lock()


def _canonical(ev: AuditEvent) -> bytes:
    ts = ev.ts.astimezone(timezone.utc).isoformat(timespec="microseconds") if ev.ts.tzinfo else \
        ev.ts.replace(tzinfo=timezone.utc).isoformat(timespec="microseconds")
    body = {"id": ev.id, "ts": ts, "user_id": ev.user_id, "username": ev.username, "action": ev.action,
            "object_type": ev.object_type, "object_id": ev.object_id, "case_id": ev.case_id,
            "details": ev.details or {}, "ip": ev.ip}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()


def record(action: str, user=None, object_type: str = "", object_id: str | int = "", case_id: int | None = None,
           details: dict | None = None, ip: str = "", db: Session | None = None) -> None:
    with _lock, tx() as s:
        last = s.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
        ev = AuditEvent(ts=utcnow(), user_id=getattr(user, "id", None), username=getattr(user, "username", "system"),
                        action=action, object_type=object_type, object_id=str(object_id), case_id=case_id,
                        details=details or {}, ip=ip or "", prev_hash=last.hash if last else "0" * 64)
        s.add(ev)
        s.flush()
        ev.hash = hashlib.sha256(ev.prev_hash.encode() + _canonical(ev)).hexdigest()


def verify_chain(s: Session) -> dict:
    prev = "0" * 64
    n = 0
    for ev in s.query(AuditEvent).order_by(AuditEvent.id).yield_per(1000):
        n += 1
        if ev.prev_hash != prev:
            return {"valid": False, "events": n, "broken_at": ev.id, "reason": "chain link mismatch"}
        h = hashlib.sha256(ev.prev_hash.encode() + _canonical(ev)).hexdigest()
        if h != ev.hash:
            return {"valid": False, "events": n, "broken_at": ev.id, "reason": "event content altered"}
        prev = ev.hash
    return {"valid": True, "events": n, "head": prev}
