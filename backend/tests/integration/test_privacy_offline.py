"""The whole pipeline must work with every outbound connection blocked (air-gapped server)."""
import io
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = r"""
import os, sys, json
sys.path.insert(0, %(root)r)
os.environ["OBSCURA_BLOCK_NET"] = "1"
os.environ["OBSCURA_DATA"] = %(data)r
from obscura import config  # installs the guard
import socket
try:
    socket.create_connection(("1.1.1.1", 443), timeout=2)
    print("GUARD_FAILED"); sys.exit(1)
except Exception as e:
    assert "blocked" in str(e), e
from obscura.detection.text.engine import TextAnalyzer, AnalyzeOptions
from obscura.detection.text import ner
an = TextAnalyzer()
spans = an.analyze("Patient Maria Delgado (DOB 01/15/1980) was seen by Dr. Will Hunter. Her son Ethan, 7, was present.",
                   AnalyzeOptions())
assert ner.loaded_models()["spacy"] and ner.loaded_models()["gliner"], ner.loaded_models()
assert any(s.text == "Maria Delgado" for s in spans), [(s.entity, s.text) for s in spans]
import cv2
from obscura.detection.vision.detectors import get_detector
img = cv2.imread(%(img)r)
faces = get_detector().detect(img, {"face", "license_plate", "head"})
assert sum(1 for f in faces if f.label == "face") >= 2
from obscura.redact import ocr
from PIL import Image, ImageDraw
im = Image.new("L", (1200, 300), 255); ImageDraw.Draw(im).text((40, 120), "SSN 523-71-9921", fill=0)
ocr.ocr_image(im)
from obscura.detection.audio.transcribe import transcribe
tr = transcribe(%(audio)r, model="small.en")
assert "Delgado" in tr.text or "security" in tr.text.lower(), tr.text
print("OFFLINE_OK", len(spans), len(faces), len(tr.words))
"""


@pytest.mark.ml
@pytest.mark.vision
@pytest.mark.audio
def test_full_pipeline_with_network_blocked(tmp_path):
    code = SCRIPT % {"root": str(ROOT), "data": str(tmp_path / "data"),
                     "img": str(ROOT / "tests/fixtures/images/zidane.jpg"),
                     "audio": str(ROOT / "tests/fixtures/media/speech.aiff")}
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HF_", "TRANSFORMERS_"))}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=900, env=env)
    assert "OFFLINE_OK" in r.stdout, r.stdout[-2000:] + r.stderr[-4000:]


def test_offline_env_forced():
    import obscura.config  # noqa: F401
    for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
        assert os.environ.get(k) == "1", k


def test_guard_allows_loopback_and_blocks_internet():
    code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); from obscura import netguard; netguard.block(); import socket\n"
            "s = socket.socket(); s.settimeout(0.2)\n"
            "try:\n    s.connect(('127.0.0.1', 9))\nexcept OSError as e:\n    pass\n"
            "try:\n    socket.getaddrinfo('example.com', 443); print('LEAK')\nexcept Exception as e:\n    print('BLOCKED', type(e).__name__)\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert "BLOCKED" in r.stdout and "LEAK" not in r.stdout, r.stdout + r.stderr


def test_no_remote_urls_in_runtime_code():
    """Runtime code must not reference remote endpoints (download script excluded)."""
    import re
    bad = []
    for p in (ROOT / "obscura").rglob("*.py"):
        for m in re.finditer(r"https?://[^\s\"')]+", p.read_text()):
            url = m.group()
            if any(ok in url for ok in ("schemas.openxmlformats.org", "www.w3.org", "purl.org", "schemas.microsoft.com",
                                        "ns.adobe.com", "localhost", "127.0.0.1")):
                continue
            if re.match(r"https?://\{", url):
                continue  # a template filled with this computer's own LAN address ("http://{ip}:{port}/")
            bad.append(f"{p.name}: {url}")
    assert not bad, bad


def test_frontend_bundle_has_no_external_urls():
    dist = ROOT.parent / "frontend" / "dist"
    if not dist.exists():
        pytest.skip("frontend not built")
    import re
    bad = []
    for p in dist.rglob("*"):
        if p.suffix in (".js", ".css", ".html"):
            for m in re.finditer(r"""(?:src|href|url\()\s*=?\s*["']?(https?://[^"')\s]+)""", p.read_text(errors="ignore")):
                if not any(h in m.group(1) for h in ("localhost", "127.0.0.1", "www.w3.org", "reactjs.org", "react.dev")):
                    bad.append(m.group(1))
    assert not bad, bad[:10]
