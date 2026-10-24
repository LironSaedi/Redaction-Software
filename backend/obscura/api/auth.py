from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import User, get_db, utcnow
from ..security import (LOCAL_USERNAME, ROLES, current_user, hash_password, is_local_request, is_locked, issue_token,
                        local_user, login_required, password_problems, register_failure, require, verify_password)
from .common import audit, user_out

router = APIRouter(prefix="/api", tags=["auth"])
_attempts: dict[str, deque] = defaultdict(deque)


class LoginIn(BaseModel):
    username: str
    password: str


def _check_rate(key: str, limit: int = 10, per: float = 60.0) -> None:
    """Throttle *failed* attempts per client address (successful logins are never throttled)."""
    q = _attempts[key]
    now = time.time()
    while q and now - q[0] > per:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "too many failed attempts, wait a minute")


def _failed(key: str) -> None:
    _attempts[key].append(time.time())


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie("obscura_token", token, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                        max_age=36000, path="/api")


@router.get("/auth/mode")
def auth_mode(request: Request):
    """Lets the sign-in screen decide whether to ask for a password at all."""
    need = login_required()
    return {"require_login": need, "local_access": not need and is_local_request(request)}


@router.post("/auth/local")
def local_login(request: Request, response: Response, db: Session = Depends(get_db)):
    """Sign-in-free access for a browser on the computer running Obscura (when sign-in is turned off)."""
    if login_required():
        raise HTTPException(403, "sign-in is required on this server")
    if not is_local_request(request):
        raise HTTPException(403, "automatic sign-in only works on the computer running Obscura; sign in instead")
    user = local_user(db)
    if not user.is_active:
        raise HTTPException(403, "the local account has been disabled by an administrator")
    user.last_login = utcnow()
    db.commit()
    token = issue_token(user)
    _set_cookie(request, response, token)
    audit(request, "login_local", user, "user", user.id)
    return {"token": token, "user": user_out(user)}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    client = request.client.host if request.client else "?"
    _check_rate(client)
    user = db.query(User).filter(User.username == body.username.strip().lower()).first()
    if user and user.username == LOCAL_USERNAME:  # no password sign-in for the built-in account
        user = None
    if not user or not user.is_active:
        _failed(client)
        audit(request, "login_failed", None, "user", body.username[:40], reason="unknown or inactive")
        raise HTTPException(401, "invalid username or password")
    if is_locked(user):
        audit(request, "login_locked", user, "user", user.id)
        raise HTTPException(423, "account temporarily locked after repeated failures")
    if not verify_password(body.password, user.password_hash):
        _failed(client)
        register_failure(user)
        db.commit()
        audit(request, "login_failed", user, "user", user.id, reason="bad password")
        raise HTTPException(401, "invalid username or password")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login = utcnow()
    db.commit()
    token = issue_token(user)
    _set_cookie(request, response, token)
    audit(request, "login", user, "user", user.id)
    return {"token": token, "user": user_out(user)}


@router.post("/auth/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.token_version += 1  # revokes every outstanding token for this user
    db.commit()
    response.delete_cookie("obscura_token", path="/api")
    audit(request, "logout", user, "user", user.id)
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


class PwIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
def change_password(body: PwIn, request: Request, response: Response, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if user.username == LOCAL_USERNAME:
        raise HTTPException(400, "the built-in local account has no password")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "current password is incorrect")
    probs = password_problems(body.new_password, user.username)
    if probs:
        raise HTTPException(400, "password: " + "; ".join(probs))
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.token_version += 1
    db.commit()
    audit(request, "password_changed", user, "user", user.id)
    token = issue_token(user)
    _set_cookie(request, response, token)
    return {"token": token, "user": user_out(user)}


# ---- user administration ------------------------------------------------------------------------

class UserIn(BaseModel):
    username: str
    full_name: str = ""
    email: str = ""
    role: str = "redactor"
    password: str


class UserPatch(BaseModel):
    full_name: str | None = None
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None
    unlock: bool | None = None


@router.get("/users")
def list_users(user: User = Depends(require("redactor")), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.username).all()
    if user.role != "admin":  # non-admins get a directory for assignment, not account details
        return [{"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role} for u in users
                if u.is_active]
    return [user_out(u) for u in users]


@router.post("/users")
def create_user(body: UserIn, request: Request, admin: User = Depends(require("admin")), db: Session = Depends(get_db)):
    uname = body.username.strip().lower()
    if not uname or not uname.replace(".", "").replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "username may contain letters, digits, . _ -")
    if body.role not in ROLES:
        raise HTTPException(400, "bad role")
    if uname == LOCAL_USERNAME or db.query(User).filter_by(username=uname).first():
        raise HTTPException(409, "username taken")
    probs = password_problems(body.password, uname)
    if probs:
        raise HTTPException(400, "password: " + "; ".join(probs))
    u = User(username=uname, full_name=body.full_name, email=body.email, role=body.role,
             password_hash=hash_password(body.password), must_change_password=True)
    db.add(u)
    db.commit()
    audit(request, "user_created", admin, "user", u.id, role=u.role)
    return user_out(u)


@router.patch("/users/{uid}")
def patch_user(uid: int, body: UserPatch, request: Request, admin: User = Depends(require("admin")),
               db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "no such user")
    changes = {}
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(400, "bad role")
        if u.id == admin.id and body.role != "admin":
            raise HTTPException(400, "you cannot demote yourself")
        u.role = body.role
        u.token_version += 1
        changes["role"] = body.role
    if body.is_active is not None:
        if u.id == admin.id and not body.is_active:
            raise HTTPException(400, "you cannot deactivate yourself")
        u.is_active = body.is_active
        u.token_version += 1
        changes["is_active"] = body.is_active
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.email is not None:
        u.email = body.email
    if body.unlock:
        u.locked_until = None
        u.failed_logins = 0
        changes["unlocked"] = True
    db.commit()
    audit(request, "user_updated", admin, "user", u.id, **changes)
    return user_out(u)


class ResetIn(BaseModel):
    password: str


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, body: ResetIn, request: Request, admin: User = Depends(require("admin")),
                   db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "no such user")
    probs = password_problems(body.password, u.username)
    if probs:
        raise HTTPException(400, "password: " + "; ".join(probs))
    u.password_hash = hash_password(body.password)
    u.must_change_password = True
    u.token_version += 1
    u.locked_until = None
    db.commit()
    audit(request, "password_reset", admin, "user", u.id)
    return {"ok": True}
