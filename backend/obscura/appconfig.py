"""Settings file for installed copies of Obscura (written by the setup wizard, read at start-up).

Where things live once installed (per user, nothing in system folders):

    macOS     ~/Library/Application Support/Obscura/config.json   (case data in …/Obscura/data by default)
    Windows   %LOCALAPPDATA%\\Obscura\\config.json
    Linux     ~/.local/share/obscura/config.json

Environment variables still win over the file, so servers and tests can be configured without it. A developer
checkout ignores the file unless OBSCURA_CONFIG points at one.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "Obscura"
DEFAULT_PORT = 8600

DEFAULTS = {
    "setup_complete": False,
    "mode": "single",          # single: this computer only | office: other computers on the network sign in
    "host": "127.0.0.1",
    "port": DEFAULT_PORT,
    "require_login": False,
    "autostart": False,
    "data_dir": None,           # None: <app home>/data
    "models_dir": None,         # None: the models shipped with the installer (or <app home>/models)
}


def app_home() -> Path:
    if os.environ.get("OBSCURA_HOME_DIR"):
        return Path(os.environ["OBSCURA_HOME_DIR"])
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME.lower()


def config_path() -> Path:
    return Path(os.environ["OBSCURA_CONFIG"]) if os.environ.get("OBSCURA_CONFIG") else app_home() / "config.json"


def load(path: Path | None = None) -> dict:
    p = path or config_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    return {**DEFAULTS, **data}


def save(cfg: dict, path: Path | None = None) -> Path:
    """Write atomically (a crash mid-write never leaves a half file) and readable by this user only."""
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".config-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({k: v for k, v in cfg.items()}, fh, indent=2, sort_keys=True)
        if sys.platform != "win32":
            os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return p


def update(**changes) -> dict:
    cfg = load()
    cfg.update(changes)
    save(cfg)
    return cfg


def active() -> dict | None:
    """The settings file this process runs with, or None for a developer checkout without one."""
    if os.environ.get("OBSCURA_CONFIG") or os.environ.get("OBSCURA_INSTALLED") == "1":
        return load()
    return None


def install_dir() -> Path | None:
    """The folder holding the installed program (set by the launcher), None when running from source."""
    v = os.environ.get("OBSCURA_INSTALL_DIR")
    return Path(v) if v else None
