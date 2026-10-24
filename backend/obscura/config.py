"""Runtime configuration.

Importing this module *forces offline mode* for every ML library before any of them is imported,
so nothing in Obscura can reach the network at runtime.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import appconfig as _appconfig

ROOT = Path(__file__).resolve().parent.parent
# installed copies read the setup wizard's settings file; environment variables always win
APP = _appconfig.active() or {}
_HOME = _appconfig.app_home()
MODELS_DIR = Path(os.environ.get("OBSCURA_MODELS") or APP.get("models_dir") or ROOT / "models")
DATA_DIR = Path(os.environ.get("OBSCURA_DATA") or APP.get("data_dir") or (_HOME / "data" if APP else ROOT / "data"))

# ---- hard offline: set before torch / transformers / ultralytics / huggingface are imported ----
for _k, _v in {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "DO_NOT_TRACK": "1",
    "YOLO_OFFLINE": "1",
    "YOLO_AUTOINSTALL": "False",  # never let a library pip-install anything at runtime
    "YOLO_VERBOSE": "False",
    "TOKENIZERS_PARALLELISM": "false",
    "PYTORCH_ENABLE_MPS_FALLBACK": "1",
    "SPACY_WARNING_IGNORE": "W095,W108",
    "HF_HOME": str(MODELS_DIR / "hf"),
}.items():
    os.environ.setdefault(_k, _v)


def _flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _app_flag(name: str, key: str, default: bool) -> bool:
    return _flag(name, bool(APP.get(key, default)))


class Settings:
    host: str = os.environ.get("OBSCURA_HOST") or APP.get("host") or "127.0.0.1"  # 0.0.0.0: on-prem LAN server
    port: int = int(os.environ.get("OBSCURA_PORT") or APP.get("port") or 8600)
    # NER models (empty string disables)
    spacy_model: str = os.environ.get("OBSCURA_SPACY", "en_core_web_trf")
    gliner_model: str = os.environ.get("OBSCURA_GLINER", "nvidia-gliner-pii")
    whisper_model: str = os.environ.get("OBSCURA_WHISPER", "medium.en")
    device: str = os.environ.get("OBSCURA_DEVICE", "auto")  # auto | cpu | mps | cuda
    encrypt_at_rest: bool = _flag("OBSCURA_ENCRYPT", True)
    tesseract_cmd: str = os.environ.get("OBSCURA_TESSERACT", "tesseract")
    ocr_dpi: int = int(os.environ.get("OBSCURA_OCR_DPI", "300"))
    auto_threshold: float = float(os.environ.get("OBSCURA_THRESHOLD", "0.5"))
    suggest_threshold: float = float(os.environ.get("OBSCURA_SUGGEST_THRESHOLD", "0.3"))
    jwt_hours: int = int(os.environ.get("OBSCURA_JWT_HOURS", "10"))
    max_upload_mb: int = int(os.environ.get("OBSCURA_MAX_UPLOAD_MB", "4096"))
    workers: int = int(os.environ.get("OBSCURA_WORKERS", "2"))
    # Off: a browser on this computer opens straight into the app as the built-in "local" admin. Other computers on
    # the network (office-server installs) must still sign in with a username and password.
    require_login: bool = _app_flag("OBSCURA_REQUIRE_LOGIN", "require_login", False)
    installed: bool = os.environ.get("OBSCURA_INSTALLED") == "1"


settings = Settings()

from . import netguard as _netguard  # noqa: E402

_netguard.maybe_block()


def torch_device() -> str:
    if settings.device != "auto":
        return settings.device
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def vision_model(name: str) -> Path:
    return MODELS_DIR / "vision" / name


def disable_ultralytics_network() -> None:
    """Ultralytics phones home for settings sync / analytics unless told not to."""
    try:
        from ultralytics import settings as ul_settings
        ul_settings.update({"sync": False, "hub": False, "api_key": "", "openai_api_key": ""})
    except Exception:
        pass
