"""Authentication, sessions and role-based access control."""
from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import config as _config
from .config import DATA_DIR, settings
from .db import Case, CaseMember, File, User, get_db

ROLES = ("admin", "supervisor", "redactor", "viewer")
ROLE_RANK = {"viewer": 0, "redactor": 1, "supervisor": 2, "admin": 3}
_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 12
LOCAL_USERNAME = "local"
_LOOPBACK_PEERS = ("127.0.0.1", "::1")
_LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")
_PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "x-real-ip")


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, h: str) -> bool:
    try:
        return _ph.verify(h, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_problems(pw: str, username: str = "") -> list[str]:
    probs = []
    if len(pw) < MIN_PASSWORD:
        probs.append(f"at least {MIN_PASSWORD} characters")
    if username and username.lower() in pw.lower():
        probs.append("must not contain the username")
    classes = sum(bool(any(f(c) for c in pw)) for f in (str.islower, str.isupper, str.isdigit,
                                                        lambda c: not c.isalnum()))
    if classes < 3:
        probs.append("use at least three of: lower case, upper case, digits, symbols")
    if pw.lower() in {"password1234", "passwordpassword", "123456789012", "qwertyuiopas"}:
        probs.append("too common")
    return probs


def _jwt_secret() -> bytes:
    env = os.environ.get("OBSCURA_JWT_SECRET")
    if env:
        return env.encode()
    kdir = DATA_DIR / "keys"
    kdir.mkdir(parents=True, exist_ok=True)
    f = kdir / "jwt.key"
    if not f.exists():
        f.write_bytes(secrets.token_bytes(48))
        os.chmod(f, 0o600)
    return f.read_bytes()


_SECRET: bytes | None = None


def secret() -> bytes:
    global _SECRET
    if _SECRET is None:
        _SECRET = _jwt_secret()
    return _SECRET


def issue_token(user: User) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user.id), "ver": user.token_version, "role": user.role, "iat": now,
                       "exp": now + settings.jwt_hours * 3600, "jti": secrets.token_hex(8)}, secret(), algorithm="HS256")


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # Cookie / query tokens exist so <img>/<video>/download links work. They are accepted for
    # read-only requests only — state changes need the Authorization header (CSRF protection).
    if request.method in ("GET", "HEAD"):
        return request.cookies.get("obscura_token") or request.query_params.get("token")
    return None


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    tok = _token_from(request)
    if not tok:
        raise HTTPException(401, "not authenticated")
    try:
        claims = jwt.decode(tok, secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired session")
    user = db.get(User, int(claims["sub"]))
    if not user or not user.is_active or claims.get("ver") != user.token_version:
        raise HTTPException(401, "session revoked")
    request.state.user = user
    return user


def require(role: str):
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[role]:
            raise HTTPException(403, f"requires {role} role")
        if user.must_change_password and role != "viewer":
            raise HTTPException(403, "password change required")
        return user
    return dep


def can_access_case(db: Session, user: User, case: Case, need: str = "viewer") -> bool:
    if user.role in ("admin", "supervisor"):
        return True
    m = db.query(CaseMember).filter_by(case_id=case.id, user_id=user.id).first()
    if not m:
        return False
    member_rank = {"viewer": 0, "redactor": 1, "reviewer": 2}
    need_rank = {"viewer": 0, "redactor": 1, "reviewer": 2}
    if need == "redactor" and user.role == "viewer":
        return False
    return member_rank.get(m.role, 0) >= need_rank.get(need, 0)


def case_or_404(db: Session, user: User, case_id: int, need: str = "viewer") -> Case:
    case = db.get(Case, case_id)
    if not case or not can_access_case(db, user, case, need):
        raise HTTPException(404, "case not found")
    return case


def file_or_404(db: Session, user: User, file_id: int, need: str = "viewer") -> File:
    f = db.get(File, file_id)
    if not f or not can_access_case(db, user, f.case, need):
        raise HTTPException(404, "file not found")
    return f


def can_view_originals(user: User) -> bool:
    """Viewers only ever see redacted exports."""
    return user.role in ("admin", "supervisor", "redactor")


def login_required() -> bool:
    return _config.settings.require_login


def _hostname(netloc: str) -> str:
    netloc = netloc.strip().lower()
    if netloc.startswith("["):
        return netloc[1:].split("]", 1)[0]
    return netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc


def is_local_request(request: Request) -> bool:
    """True only for a browser on this computer talking straight to this server: a loopback peer, a loopback Host
    header (defeats DNS rebinding), a loopback Origin when one is sent (defeats cross-site requests) and no proxy
    forwarding headers (a reverse proxy on this machine would otherwise make every visitor look local)."""
    peer = request.client.host if request.client else ""
    if peer.startswith("::ffff:"):
        peer = peer[7:]
    if peer not in _LOOPBACK_PEERS:
        return False
    if _hostname(request.headers.get("host", "")) not in _LOOPBACK_NAMES:
        return False
    origin = request.headers.get("origin")
    if origin is not None and _hostname(origin.split("://", 1)[-1]) not in _LOOPBACK_NAMES:
        return False
    return not any(h in request.headers for h in _PROXY_HEADERS)


def local_user(db: Session) -> User:
    """The built-in account used when sign-in is off. Its password is random and never shown, so it can only be
    reached through automatic local sign-in."""
    u = db.query(User).filter_by(username=LOCAL_USERNAME).first()
    if u is None:
        u = User(username=LOCAL_USERNAME, full_name="This computer", role="admin",
                 password_hash=hash_password(secrets.token_urlsafe(32)), must_change_password=False)
        db.add(u)
        db.commit()
    return u


def register_failure(user: User) -> None:
    user.failed_logins += 1
    if user.failed_logins >= MAX_FAILED:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)
        user.failed_logins = 0


def is_locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > datetime.now(timezone.utc))
