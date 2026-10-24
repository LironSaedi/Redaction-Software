"""Second opinion end to end: suggestions after analysis, final check on the released file."""
import importlib
import os
import re
import time

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from obscura.detection.text import second_opinion as so

pytestmark = pytest.mark.skipif(not so.installed(), reason="presidio-analyzer not installed")
PW = "Str0ng!Passphrase"


def _wait(c, jid, h, timeout=300):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get(f"/api/jobs/{jid}", headers=h).json()
        if j["status"] in ("done", "error", "cancelled"):
            assert j["status"] == "done", j
            return j
        time.sleep(0.2)
    raise TimeoutError


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    os.environ["OBSCURA_DATA"] = str(tmp_path_factory.mktemp("so_api"))
    import obscura.config as cfg
    importlib.reload(cfg)
    import obscura.db as db
    import obscura.main as main
    import obscura.security as sec
    import obscura.storage as storage
    storage._STORAGE = storage._CIPHER = None
    storage.DATA_DIR = db.DATA_DIR = sec.DATA_DIR = main.DATA_DIR = cfg.DATA_DIR
    db._engine = db._Session = None
    sec._SECRET = None
    with TestClient(main.create_app()) as c:
        pw = re.search(r"password: (\S+)", (cfg.DATA_DIR / "INITIAL_ADMIN_PASSWORD.txt").read_text()).group(1)
        t = c.post("/api/auth/login", json={"username": "admin", "password": pw}).json()["token"]
        t = c.post("/api/auth/change-password", json={"current_password": pw, "new_password": PW},
                   headers={"Authorization": f"Bearer {t}"}).json()["token"]
        h = {"Authorization": f"Bearer {t}"}
        cid = c.post("/api/cases", json={"name": "Second opinion"}, headers=h).json()["id"]
        yield c, h, cid


def _upload(c, h, cid, name, data, analyze):
    fid = c.post(f"/api/cases/{cid}/files", files=[("files", (name, data, "application/octet-stream"))],
                 headers=h).json()["files"][0]["id"]
    _wait(c, c.post(f"/api/files/{fid}/analyze", json=analyze, headers=h).json()["job_id"], h)
    return fid


def test_meta_reports_engine(env):
    c, h, _ = env
    st = c.get("/api/meta", headers=h).json()["second_opinion"]
    assert st["available"] and st["engine"] == "Microsoft Presidio" and st["version"]


def test_analysis_adds_unselected_second_opinion(env):
    """Profile limited to e-mail and IBAN; the main engine's own IBAN rule is not asked for, Presidio's is."""
    c, h, cid = env
    text = b"Wire to GB82 WEST 1234 5698 7654 32 and send the receipt to ops@example.org.\n"
    fid = _upload(c, h, cid, "wire.txt", text, {"use_ml": False, "entities": ["EMAIL", "IBAN"]})
    dets = c.get(f"/api/files/{fid}/detections", headers=h).json()["detections"]
    ours = [d for d in dets if not d["source"].startswith("presidio:")]
    theirs = [d for d in dets if d["source"].startswith("presidio:")]
    assert any(d["entity"] == "EMAIL" and d["selected"] for d in ours)
    assert not any(d["text"] == "ops@example.org" for d in theirs)  # already covered: no duplicate
    for d in theirs:
        assert d["selected"] is False and "Microsoft Presidio" in d["explanation"]


def test_second_opinion_can_be_turned_off(env):
    c, h, cid = env
    fid = _upload(c, h, cid, "off.txt", b"Card 4111 1111 1111 1111 on file.\n",
                  {"use_ml": False, "entities": ["EMAIL"], "second_opinion": False})
    dets = c.get(f"/api/files/{fid}/detections", headers=h).json()["detections"]
    assert not any(d["source"].startswith("presidio:") for d in dets)


def _letter(c, h, cid, name):
    doc = fitz.open()
    p = doc.new_page()
    p.insert_text((72, 72), "Claimant SSN 523-71-9921. Adjuster email adj.smith@example.com.", fontsize=10)
    fid = _upload(c, h, cid, name, doc.tobytes(), {"use_ml": False, "entities": ["SSN", "EMAIL"], "second_opinion": False})
    email = next(d for d in c.get(f"/api/files/{fid}/detections", headers=h).json()["detections"] if d["entity"] == "EMAIL")
    return fid, email["id"]


def test_export_final_check_lists_leftovers(env):
    """A redaction deleted by mistake: the final check finds the e-mail still readable in the export."""
    c, h, cid = env
    fid, eid = _letter(c, h, cid, "deleted.pdf")
    assert c.post(f"/api/files/{fid}/detections/delete", json={"ids": [eid]}, headers=h).status_code == 200
    j = _wait(c, c.post(f"/api/files/{fid}/export", json={}, headers=h).json()["job_id"], h)
    assert j["result"]["second_opinion_open"] >= 1
    rep = c.get(f"/api/exports/{j['result']['export_id']}", headers=h).json()["report"]["second_opinion"]
    assert rep["checked"] and rep["engine"].startswith("Microsoft Presidio")
    assert any(f["entity"] == "EMAIL" and "adj.smith@example.com" in f["text"] and not f["reviewed"]
               for f in rep["findings"])
    assert not any("523-71-9921" in f["text"] for f in rep["findings"])  # the SSN really is gone


def test_export_final_check_respects_reviewer_choice(env):
    """Switched off on purpose: still listed, but marked as reviewed rather than open."""
    c, h, cid = env
    fid, eid = _letter(c, h, cid, "kept.pdf")
    c.patch(f"/api/files/{fid}/detections", json={"updates": [{"id": eid, "selected": False}]}, headers=h)
    j = _wait(c, c.post(f"/api/files/{fid}/export", json={}, headers=h).json()["job_id"], h)
    rep = c.get(f"/api/exports/{j['result']['export_id']}", headers=h).json()["report"]["second_opinion"]
    assert j["result"]["second_opinion_open"] == 0
    assert any(f["reviewed"] for f in rep["findings"])


def test_export_final_check_clean_file(env):
    c, h, cid = env
    fid = _upload(c, h, cid, "clean.txt", b"Contact ops@example.org for the forms.\n", {"use_ml": False, "entities": ["EMAIL"]})
    j = _wait(c, c.post(f"/api/files/{fid}/export", json={}, headers=h).json()["job_id"], h)
    assert j["result"]["second_opinion_open"] == 0


def test_export_final_check_can_be_skipped(env):
    c, h, cid = env
    fid = _upload(c, h, cid, "skip.txt", b"Contact ops@example.org.\n", {"use_ml": False, "entities": ["EMAIL"]})
    j = _wait(c, c.post(f"/api/files/{fid}/export", json={"second_opinion": False}, headers=h).json()["job_id"], h)
    assert j["result"]["second_opinion_open"] is None
