"""Obscura Redaction Studio — application entry point.

    python -m obscura.main                     # http://127.0.0.1:8600 (this computer only)
    OBSCURA_HOST=0.0.0.0 python -m obscura.main --cert server.crt --key server.key   # office network, HTTPS
"""
from __future__ import annotations

import argparse
import logging
import os
import secrets
import string
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import DATA_DIR, ROOT, settings
from .db import User, init_db, tx
from .security import LOCAL_USERNAME, hash_password, login_required
from .storage import get_storage

log = logging.getLogger("obscura")
BOOT_ID = secrets.token_hex(8)
FRONTEND = Path(os.environ.get("OBSCURA_FRONTEND", ROOT.parent / "frontend" / "dist"))


def bootstrap_admin() -> str | None:
    """First run with sign-in on: create an admin with a random password, written once to a 0600 file."""
    with tx() as s:
        if s.query(User).filter(User.username != LOCAL_USERNAME).count():
            return None
        alphabet = string.ascii_letters + string.digits
        pw = "".join(secrets.choice(alphabet) for _ in range(14)) + "!7a"
        s.add(User(username="admin", full_name="Administrator", role="admin", password_hash=hash_password(pw),
                   must_change_password=True))
    f = DATA_DIR / "INITIAL_ADMIN_PASSWORD.txt"
    f.write_text(f"username: admin\npassword: {pw}\n(you will be asked to change it at first login; delete this file)\n")
    os.chmod(f, 0o600)
    return pw


def create_pending_admin() -> None:
    """The setup wizard stores the first administrator (password already hashed) when the data folder changes; it is
    created here, in the new folder, and removed from the settings file."""
    from . import appconfig
    cfg = appconfig.active()
    pend = (cfg or {}).get("pending_admin")
    if not pend:
        return
    with tx() as s:
        if not s.query(User).filter_by(username=pend["username"]).first():
            s.add(User(username=pend["username"], full_name=pend.get("full_name", ""), role="admin",
                       password_hash=pend["password_hash"], must_change_password=False))
    cfg.pop("pending_admin", None)
    appconfig.save(cfg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    init_db()
    get_storage().wipe_tmp()
    from .jobs import recover_interrupted
    recover_interrupted()
    create_pending_admin()
    if login_required():
        if bootstrap_admin():
            log.warning("Created initial admin account. Credentials written to %s",
                        DATA_DIR / "INITIAL_ADMIN_PASSWORD.txt")
    else:
        log.info("Sign-in is off: browsers on this computer open Obscura directly; other computers must sign in.")
    if os.environ.get("OBSCURA_WATCHER", "1") == "1":
        from .watcher import SERVICE
        SERVICE.start()
    yield
    from .processing import WORK
    WORK.clear()
    get_storage().wipe_tmp()


def create_app() -> FastAPI:
    app = FastAPI(title="Obscura Redaction Studio", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    from .api import admin, auth, cases, files, library, setup
    for r in (auth.router, cases.router, files.router, library.router, admin.router, setup.router):
        app.include_router(r)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        # everything is served from this origin: no CDNs, no third-party requests, ever
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'self'")
        if request.url.scheme == "https":
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.get("/api/health")
    def health():
        # "boot" changes on every start, so a client can tell a restarted server from the old one
        return {"ok": True, "version": __version__, "boot": BOOT_ID}

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    if FRONTEND.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):  # unknown API routes are errors, not the web app
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            target = (FRONTEND / path).resolve()
            if path and target.is_file() and FRONTEND.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(FRONTEND / "index.html")
    return app


app = create_app()

# exit codes understood by the desktop launcher
EXIT_RESTART = 3     # settings changed (data folder, port, network mode): start again with the new settings
EXIT_UNINSTALL = 4   # the uninstaller is taking over: quit without restarting
_SERVER = None
_EXIT_CODE = 0


def request_exit(code: int, delay: float = 0.8) -> None:
    """Stop the server shortly (after the current response is sent) and exit with ``code``."""
    import threading

    def stop():
        global _EXIT_CODE
        _EXIT_CODE = code
        if _SERVER is not None:
            _SERVER.should_exit = True
        else:  # not started through main(): nothing to hand the code back to
            os._exit(code)
    threading.Timer(delay, stop).start()


def main() -> None:
    global _SERVER
    import uvicorn
    ap = argparse.ArgumentParser(description="Obscura Redaction Studio")
    ap.add_argument("--host", default=settings.host)
    ap.add_argument("--port", type=int, default=settings.port)
    ap.add_argument("--cert", default=os.environ.get("OBSCURA_TLS_CERT"))
    ap.add_argument("--key", default=os.environ.get("OBSCURA_TLS_KEY"))
    args = ap.parse_args()
    settings.host, settings.port = args.host, args.port  # what the System page and setup assistant report
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.cert:
        log.warning("Listening on %s WITHOUT TLS. Use --cert/--key (scripts/make_cert.sh) on a shared network.",
                    args.host)
    cfg = uvicorn.Config(app, host=args.host, port=args.port, ssl_certfile=args.cert, ssl_keyfile=args.key,
                         log_level="info", access_log=False, server_header=False)
    _SERVER = uvicorn.Server(cfg)
    _SERVER.run()
    if _EXIT_CODE:
        raise SystemExit(_EXIT_CODE)


if __name__ == "__main__":
    main()
