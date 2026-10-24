"""First-run setup wizard, app settings, model installation and uninstall (installed copies).

Everything here only answers a browser on the computer running Obscura: the wizard runs before any account exists,
and uninstalling or picking folders makes no sense from another machine.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import __version__, appconfig, desktop
from .. import config as _config
from ..db import User, get_db
from ..security import (LOCAL_USERNAME, hash_password, is_local_request, local_user, password_problems, require)
from .common import audit

router = APIRouter(prefix="/api", tags=["setup"])

# what each model folder is for; sizes are what the installer ships
MODEL_PARTS = [
    {"key": "gliner/nvidia-gliner-pii", "label": "Name & identifier finder (GLiNER PII)", "size_gb": 1.7,
     "needed_for": "documents — catches names and IDs the rules miss", "required": True},
    {"key": "vision", "label": "Face, licence plate and object detectors", "size_gb": 0.12,
     "needed_for": "photos, video and pictures inside documents", "required": True},
    {"key": "whisper/medium.en", "label": "English speech recognition (accurate)", "size_gb": 1.4,
     "needed_for": "audio and video transcripts", "required": False},
    {"key": "whisper/small.en", "label": "English speech recognition (fast check)", "size_gb": 0.46,
     "needed_for": "audio verification", "required": False},
    {"key": "whisper/small", "label": "Speech recognition, 99 languages", "size_gb": 0.46,
     "needed_for": "non-English audio and video", "required": False},
    {"key": "translate/m2m100_418m", "label": "Translation (100 languages)", "size_gb": 0.48,
     "needed_for": "translating transcripts", "required": False},
    {"key": "speaker", "label": "Speaker identification", "size_gb": 0.03,
     "needed_for": "Speaker 1 / Speaker 2 labels in transcripts", "required": False},
]

_DOWNLOAD: dict = {"state": "idle"}


def _local(request: Request) -> None:
    if not is_local_request(request):
        raise HTTPException(403, "only available on the computer running Obscura")


def _cfg() -> dict:
    return appconfig.load()


def _setup_open() -> bool:
    """The wizard is open on an installed copy until it has been completed once."""
    return _config.settings.installed and not _cfg().get("setup_complete")


def _models_status() -> list[dict]:
    out = []
    for part in MODEL_PARTS:
        d = _config.MODELS_DIR / part["key"]
        present = d.exists() and any(d.iterdir())
        out.append({**part, "present": present})
    return out


def _spacy_ok() -> bool:
    import importlib.util
    return importlib.util.find_spec(_config.settings.spacy_model or "en_core_web_trf") is not None


# ---- wizard -------------------------------------------------------------------------------------

@router.get("/setup/state")
def setup_state(request: Request):
    """What the first-run wizard needs. Answers only this computer, and only until setup is done."""
    needed = _setup_open()
    if not needed:
        return {"needed": False}
    _local(request)
    cfg = _cfg()
    data_dir = _config.DATA_DIR
    try:
        free = round(shutil.disk_usage(data_dir if data_dir.exists() else data_dir.parent).free / 1e9, 1)
    except OSError:
        free = None
    from ..detection.text import second_opinion
    from ..redact import ocr
    return {"needed": True, "version": __version__, "platform": _platform_name(),
            "defaults": {"mode": cfg.get("mode", "single"), "data_dir": str(data_dir),
                         "port": _config.settings.port, "autostart": False},
            "disk_free_gb": free, "models_dir": str(_config.MODELS_DIR), "models": _models_status(),
            "spacy_model": _spacy_ok(), "ocr": ocr.available(),
            "second_opinion": second_opinion.quick_status()["available"],
            "lan_address": _lan_address(), "can_pick_folder": True,
            "autostart_available": desktop.launch_command() is not None}


class SetupIn(BaseModel):
    mode: Literal["single", "office"] = "single"
    require_login: bool | None = None       # default: off for "single", on for "office"
    admin_username: str | None = None
    admin_password: str | None = None
    admin_full_name: str = ""
    data_dir: str | None = None
    port: int | None = None
    autostart: bool = False


def _check_data_dir(raw: str) -> Path:
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise HTTPException(400, "choose a full folder path")
    if p.exists() and not p.is_dir():
        raise HTTPException(400, "that path is a file, not a folder")
    if p.exists() and any(p.iterdir()) and not (p / "obscura.db").exists():
        p = p / "Obscura Data"  # never mix case data into a folder that already holds other things
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".write-test"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as e:
        raise HTTPException(400, f"cannot write to that folder: {e.strerror or e}")
    return p


@router.post("/setup/complete")
def setup_complete(body: SetupIn, request: Request, db: Session = Depends(get_db)):
    if not _setup_open():
        raise HTTPException(409, "setup has already been completed")
    _local(request)
    office = body.mode == "office"
    # sign-in on this computer: off for a single computer, on for an office server unless the wizard turned it off.
    # Other computers always sign in, so an office server always gets an administrator account.
    need_login = body.require_login if body.require_login is not None else office
    admin = None
    if need_login or office:
        uname = (body.admin_username or "").strip().lower()
        if not uname or uname == LOCAL_USERNAME or not uname.replace(".", "").replace("_", "").replace("-", "").isalnum():
            raise HTTPException(400, "choose an administrator user name (letters, digits, . _ -)")
        probs = password_problems(body.admin_password or "", uname)
        if probs:
            raise HTTPException(400, "password: " + "; ".join(probs))
        admin = {"username": uname, "full_name": body.admin_full_name.strip(),
                 "password_hash": hash_password(body.admin_password or "")}
    port = body.port or int(_cfg().get("port") or appconfig.DEFAULT_PORT)
    if not 1024 <= port <= 65535:
        raise HTTPException(400, "port must be between 1024 and 65535")
    data_dir = _check_data_dir(body.data_dir) if body.data_dir else _config.DATA_DIR
    host = "0.0.0.0" if office else "127.0.0.1"
    cfg = _cfg()
    models_moved = bool(cfg.get("models_dir")) and Path(cfg["models_dir"]).resolve() != _config.MODELS_DIR.resolve()
    restart = (data_dir.resolve() != _config.DATA_DIR.resolve() or port != _config.settings.port or
               host != _config.settings.host or models_moved)
    cfg.update(setup_complete=True, mode=body.mode, require_login=need_login, host=host, port=port,
               data_dir=str(data_dir), autostart=bool(body.autostart))
    if admin and restart:
        cfg["pending_admin"] = admin  # created in the new data folder after the restart
    elif admin:
        if not db.query(User).filter_by(username=admin["username"]).first():
            db.add(User(username=admin["username"], full_name=admin["full_name"], role="admin",
                        password_hash=admin["password_hash"], must_change_password=False))
            db.commit()
    appconfig.save(cfg)
    auto = desktop.set_autostart(True) if body.autostart else desktop.set_autostart(False)
    _config.settings.require_login = need_login
    audit(request, "setup_completed", None, "system", 0, mode=body.mode, require_login=need_login, restart=restart)
    if restart:
        from .. import main
        main.request_exit(main.EXIT_RESTART)
    return {"ok": True, "restart": restart, "require_login": need_login,
            "autostart": bool(body.autostart and auto.get("ok")),
            "url": f"http://127.0.0.1:{port}/", "lan_url": f"http://{_lan_address()}:{port}/" if office else None}


@router.post("/setup/pick-folder")
def pick_folder(request: Request, purpose: str = "data", db: Session = Depends(get_db)):
    """Open this computer's folder chooser (the wizard's "Change…" / "Import models…" buttons)."""
    _local(request)
    if not _setup_open():
        _admin_from_request(request, db)
    prompt = "Choose where Obscura keeps case files" if purpose == "data" else "Choose the folder with the Obscura models"
    path = desktop.pick_folder(prompt, start=str(_config.DATA_DIR.parent if purpose == "data" else Path.home()))
    return {"path": path}


# ---- models -------------------------------------------------------------------------------------

def _writable_models_dir() -> Path:
    d = _config.MODELS_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / ".write-test").write_bytes(b"")
        (d / ".write-test").unlink()
        return d
    except OSError:
        return appconfig.app_home() / "models"


class ImportIn(BaseModel):
    path: str


@router.get("/setup/models")
def models_state(request: Request, db: Session = Depends(get_db)):
    _local(request)
    if not _setup_open():
        _admin_from_request(request, db)
    return {"models_dir": str(_config.MODELS_DIR), "models": _models_status(), "download": _DOWNLOAD}


@router.post("/setup/models/import")
def import_models(body: ImportIn, request: Request, db: Session = Depends(get_db)):
    """Copy a models folder from a USB drive / network share (air-gapped installs)."""
    _local(request)
    if not _setup_open():
        _admin_from_request(request, db)
    src = Path(body.path).expanduser()
    if (src / "models").is_dir():
        src = src / "models"
    keys = [p["key"] for p in MODEL_PARTS]
    found = [k for k in keys if (src / k).is_dir()]
    if not found:
        raise HTTPException(400, "no Obscura models found in that folder (expected gliner/, whisper/, vision/ …)")
    dest = _writable_models_dir()
    for k in found:
        target = dest / k
        if target.exists() and any(target.iterdir()):
            continue
        shutil.copytree(src / k, target, dirs_exist_ok=True)
    restart = dest.resolve() != _config.MODELS_DIR.resolve()
    if restart:
        appconfig.update(models_dir=str(dest))
    return {"ok": True, "imported": found, "models_dir": str(dest), "restart_needed": restart}


@router.post("/setup/models/download")
def download_models(request: Request, db: Session = Depends(get_db)):
    """One-time download of the model files from their publishers (Hugging Face / GitHub). Only model files are
    fetched — no document, setting or usage information is sent. Obscura itself stays offline afterwards."""
    _local(request)
    if not _setup_open():
        _admin_from_request(request, db)
    if _DOWNLOAD.get("state") == "running":
        return _DOWNLOAD
    script = Path(_config.ROOT) / "scripts" / "download_models.py"
    if not script.exists():
        raise HTTPException(404, "the download script is not part of this installation")
    dest = _writable_models_dir()
    env = {k: v for k, v in os.environ.items() if k not in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
                                                           "HF_DATASETS_OFFLINE", "OBSCURA_BLOCK_NET")}
    log = appconfig.app_home() / "model-download.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    _DOWNLOAD.clear()
    _DOWNLOAD.update(state="running", log=str(log), models_dir=str(dest))

    def run():
        with open(log, "w", encoding="utf-8") as fh:
            r = subprocess.run([sys.executable, str(script), "--dest", str(dest), "--skip-spacy"], env=env,
                               stdout=fh, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _DOWNLOAD["state"] = "done" if r.returncode == 0 else "error"
        if r.returncode == 0 and dest.resolve() != _config.MODELS_DIR.resolve():
            appconfig.update(models_dir=str(dest))
            _DOWNLOAD["restart_needed"] = True
    threading.Thread(target=run, daemon=True).start()
    return _DOWNLOAD


# ---- settings, restart and uninstall (System page) ---------------------------------------------------

def _admin_from_request(request: Request, db: Session) -> User:
    from ..security import current_user
    user = current_user(request, db)
    if user.role != "admin":
        raise HTTPException(403, "requires admin role")
    return user


@router.get("/system/app")
def app_info(request: Request, user: User = Depends(require("admin"))):
    cfg = _cfg() if _config.settings.installed else {}
    return {"installed": _config.settings.installed, "version": __version__, "platform": _platform_name(),
            "install_dir": str(appconfig.install_dir() or ""), "config_path": str(appconfig.config_path()),
            "data_dir": str(_config.DATA_DIR), "models_dir": str(_config.MODELS_DIR),
            "mode": cfg.get("mode", "single"), "require_login": _config.settings.require_login,
            "host": _config.settings.host, "port": _config.settings.port,
            "autostart": desktop.autostart_enabled(), "autostart_available": desktop.launch_command() is not None,
            "uninstall_available": desktop.uninstaller() is not None and is_local_request(request),
            "local_request": is_local_request(request), "lan_address": _lan_address()}


class AppSettingsIn(BaseModel):
    require_login: bool | None = None
    autostart: bool | None = None
    mode: Literal["single", "office"] | None = None
    port: int | None = None


@router.patch("/system/app")
def update_app(body: AppSettingsIn, request: Request, user: User = Depends(require("admin")),
               db: Session = Depends(get_db)):
    _local(request)
    if not _config.settings.installed:
        raise HTTPException(409, "settings are managed with environment variables on this server")
    cfg = _cfg()
    restart = False
    if body.require_login is not None:
        if body.require_login and not db.query(User).filter(User.username != LOCAL_USERNAME,
                                                            User.role == "admin", User.is_active).count():
            raise HTTPException(400, "create an administrator with a password first (Users page), "
                                     "or you would lock yourself out")
        cfg["require_login"] = body.require_login
        _config.settings.require_login = body.require_login
    if body.autostart is not None:
        r = desktop.set_autostart(body.autostart)
        if not r.get("ok"):
            raise HTTPException(400, r.get("reason", "could not change start-at-login"))
        cfg["autostart"] = body.autostart
    if body.mode is not None and body.mode != cfg.get("mode"):
        cfg["mode"] = body.mode
        cfg["host"] = "0.0.0.0" if body.mode == "office" else "127.0.0.1"
        restart = True
    if body.port is not None and body.port != cfg.get("port"):
        if not 1024 <= body.port <= 65535:
            raise HTTPException(400, "port must be between 1024 and 65535")
        cfg["port"] = body.port
        restart = True
    appconfig.save(cfg)
    audit(request, "app_settings_changed", user, "system", 0, **{k: v for k, v in body.model_dump().items()
                                                                  if v is not None})
    if restart:
        from .. import main
        main.request_exit(main.EXIT_RESTART)
    return {"ok": True, "restart": restart}


class RestartIn(BaseModel):
    confirm: bool = True


@router.post("/system/restart")
def restart(request: Request, user: User = Depends(require("admin"))):
    _local(request)
    from .. import main
    audit(request, "app_restart", user, "system", 0)
    main.request_exit(main.EXIT_RESTART)
    return {"ok": True}


class UninstallIn(BaseModel):
    confirm: str
    remove_data: bool = False


@router.post("/system/uninstall")
def uninstall(body: UninstallIn, request: Request, user: User = Depends(require("admin"))):
    """Remove Obscura from this computer. With remove_data the case files, database and encryption keys go too
    (keys first, so anything left behind can no longer be decrypted)."""
    _local(request)
    if body.confirm != "UNINSTALL":
        raise HTTPException(400, 'type UNINSTALL to confirm')
    cmd = desktop.uninstall_command(body.remove_data, _config.DATA_DIR,
                                    wait_pid=int(os.environ.get("OBSCURA_LAUNCHER_PID") or os.getpid()))
    if not cmd:
        raise HTTPException(409, "this copy was not installed with the Obscura installer; remove its folder instead")
    audit(request, "app_uninstall", user, "system", 0, remove_data=body.remove_data)
    desktop.run_detached(cmd)
    from .. import main
    main.request_exit(main.EXIT_UNINSTALL, delay=1.0)
    return {"ok": True, "remove_data": body.remove_data, "command": cmd if os.environ.get(
        "OBSCURA_UNINSTALL_DRYRUN") == "1" else None}


# ---- helpers ------------------------------------------------------------------------------------

def _platform_name() -> str:
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]} ({platform.machine()})"
    if sys.platform == "win32":
        return f"Windows {platform.release()} ({platform.machine()})"
    return platform.platform()


def _lan_address() -> str | None:
    """This computer's address on the office network (for the "office server" step), read from the operating system —
    no network traffic, and it works with the outbound network block switched on."""
    import re
    try:
        if sys.platform == "darwin":
            for iface in ("en0", "en1", "en2"):
                r = subprocess.run(["ipconfig", "getifaddr", iface], capture_output=True, text=True, timeout=3)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
            return None
        if sys.platform == "win32":
            r = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ips = re.findall(r"IPv4[^:\n]*:\s*(\d+\.\d+\.\d+\.\d+)", r.stdout)
        else:
            r = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3)
            ips = r.stdout.split()
        ips = [i for i in ips if not i.startswith(("127.", "169.254."))]
        return ips[0] if ips else None
    except (OSError, subprocess.SubprocessError):
        return None


__all__ = ["router", "local_user"]
