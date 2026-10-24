"""API: authentication, sessions, RBAC matrix, case/file lifecycle, review edits, exports, audit."""
import csv
import io
import re
import time

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

PW = "Str0ng!Passphrase"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    import os
    data = tmp_path_factory.mktemp("apidata")
    os.environ["OBSCURA_DATA"] = str(data)
    import importlib

    import obscura.config as cfg
    importlib.reload(cfg)
    import obscura.storage as storage
    storage._STORAGE = None
    storage._CIPHER = None
    storage.DATA_DIR = cfg.DATA_DIR
    import obscura.db as db
    db.DATA_DIR = cfg.DATA_DIR
    db._engine = db._Session = None
    import obscura.security as sec
    sec.DATA_DIR = cfg.DATA_DIR
    sec._SECRET = None
    import obscura.main as main
    main.DATA_DIR = cfg.DATA_DIR
    app = main.create_app()
    with TestClient(app) as c:
        pw = re.search(r"password: (\S+)", (cfg.DATA_DIR / "INITIAL_ADMIN_PASSWORD.txt").read_text()).group(1)
        tok = c.post("/api/auth/login", json={"username": "admin", "password": pw}).json()["token"]
        r = c.post("/api/auth/change-password", json={"current_password": pw, "new_password": PW},
                   headers={"Authorization": f"Bearer {tok}"})
        admin = {"Authorization": f"Bearer {r.json()['token']}"}
        users = {}
        for name, role in [("sup", "supervisor"), ("red", "redactor"), ("red2", "redactor"), ("view", "viewer")]:
            assert c.post("/api/users", json={"username": name, "role": role, "password": "Kq7!Lm3#Vx9$Pw"}, headers=admin).status_code == 200
            t = c.post("/api/auth/login", json={"username": name, "password": "Kq7!Lm3#Vx9$Pw"}).json()["token"]
            t = c.post("/api/auth/change-password", json={"current_password": "Kq7!Lm3#Vx9$Pw", "new_password": f"Tr0ub4dor&{len(name)}Horse!"},
                       headers={"Authorization": f"Bearer {t}"}).json()["token"]
            users[name] = {"Authorization": f"Bearer {t}"}
        users["admin"] = admin
        ids = {u["username"]: u["id"] for u in c.get("/api/users", headers=admin).json()}
        case = c.post("/api/cases", json={"name": "Delgado v. Navarro", "number": "2023-CA-004821"}, headers=users["red"]).json()
        c.post(f"/api/cases/{case['id']}/members", json={"user_id": ids["view"], "role": "viewer"}, headers=users["red"])
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((72, 72), "Patient: Maria Delgado   SSN: 523-71-9921   Phone: (512) 555-0187", fontsize=10)
        p.insert_text((72, 90), "Assessment: cervical strain.", fontsize=10)
        up = c.post(f"/api/cases/{case['id']}/files", files=[("files", ("records.pdf", doc.tobytes(), "application/pdf"))],
                    headers=users["red"]).json()
        fid = up["files"][0]["id"]
        jid = c.post(f"/api/files/{fid}/analyze", json={"use_ml": False}, headers=users["red"]).json()["job_id"]
        _wait(c, jid, users["red"])
        yield {"c": c, "u": users, "case": case, "fid": fid, "ids": ids}


def _wait(c, jid, h, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get(f"/api/jobs/{jid}", headers=h).json()
        if j["status"] in ("done", "error", "cancelled"):
            assert j["status"] == "done", j
            return j
        time.sleep(0.2)
    raise TimeoutError


def test_health(env):
    assert env["c"].get("/api/health").json()["ok"]


@pytest.mark.parametrize("path", ["/api/cases", "/api/meta", "/api/auth/me", "/api/jobs"])
def test_requires_auth(env, path):
    assert TestClient(env["c"].app).get(path).status_code == 401


def test_bad_token(env):
    assert TestClient(env["c"].app).get("/api/cases", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_rate_limit_on_failures(env):
    from obscura.api import auth
    auth._attempts.clear()
    c = TestClient(env["c"].app)
    codes = [c.post("/api/auth/login", json={"username": "ghost", "password": "x"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    auth._attempts.clear()


def test_login_failures_and_lockout(env):
    c = env["c"]
    c.post("/api/users", json={"username": "lockme", "role": "viewer", "password": "Kq7!Lm3#Vx9$L1"}, headers=env["u"]["admin"])
    codes = [c.post("/api/auth/login", json={"username": "lockme", "password": "wrong"}).status_code for _ in range(5)]
    assert codes[:5] == [401] * 5
    assert c.post("/api/auth/login", json={"username": "lockme", "password": "Kq7!Lm3#Vx9$L1"}).status_code == 423
    from obscura.api import auth
    auth._attempts.clear()
    lid = {u["username"]: u["id"] for u in c.get("/api/users", headers=env["u"]["admin"]).json()}["lockme"]
    c.patch(f"/api/users/{lid}", json={"unlock": True}, headers=env["u"]["admin"])
    assert c.post("/api/auth/login", json={"username": "lockme", "password": "Kq7!Lm3#Vx9$L1"}).status_code == 200


def test_must_change_password_blocks_work(env):
    c = env["c"]
    c.post("/api/users", json={"username": "fresh", "role": "redactor", "password": "Kq7!Lm3#Vx9$F1"}, headers=env["u"]["admin"])
    t = c.post("/api/auth/login", json={"username": "fresh", "password": "Kq7!Lm3#Vx9$F1"}).json()["token"]
    assert c.post("/api/cases", json={"name": "x"}, headers={"Authorization": f"Bearer {t}"}).status_code == 403


def test_weak_password_rejected(env):
    r = env["c"].post("/api/users", json={"username": "weak", "role": "viewer", "password": "short"}, headers=env["u"]["admin"])
    assert r.status_code == 400


def test_logout_revokes_tokens(env):
    c = env["c"]
    c.post("/api/users", json={"username": "outuser", "role": "viewer", "password": "Kq7!Lm3#Vx9$O1"}, headers=env["u"]["admin"])
    t = c.post("/api/auth/login", json={"username": "outuser", "password": "Kq7!Lm3#Vx9$O1"}).json()["token"]
    h = {"Authorization": f"Bearer {t}"}
    assert c.get("/api/auth/me", headers=h).status_code == 200
    c.post("/api/auth/logout", headers=h)
    assert c.get("/api/auth/me", headers=h).status_code == 401


def test_cookie_cannot_authorise_writes(env):
    c2 = TestClient(env["c"].app)
    c2.cookies.set("obscura_token", env["u"]["red"]["Authorization"][7:], path="/api")
    assert c2.get("/api/cases").status_code == 200
    assert c2.post("/api/cases", json={"name": "csrf"}).status_code == 401


def test_query_token_only_for_reads(env):
    tok = env["u"]["red"]["Authorization"][7:]
    assert env["c"].get(f"/api/cases?token={tok}").status_code == 200
    assert TestClient(env["c"].app).post(f"/api/cases?token={tok}", json={"name": "x"}).status_code == 401


# ---- RBAC matrix ----------------------------------------------------------------------------------
@pytest.mark.parametrize("who,expect", [("admin", 200), ("sup", 200), ("red", 200), ("view", 200), ("red2", 404)])
def test_case_visibility(env, who, expect):
    assert env["c"].get(f"/api/cases/{env['case']['id']}", headers=env["u"][who]).status_code == expect


@pytest.mark.parametrize("who,expect", [("admin", 200), ("sup", 200), ("red", 200), ("view", 403), ("red2", 404)])
def test_originals_and_detections(env, who, expect):
    c, fid, h = env["c"], env["fid"], env["u"][who]
    for path in (f"/api/files/{fid}/detections", f"/api/files/{fid}/original", f"/api/files/{fid}/pages/0.png",
                 f"/api/files/{fid}/media", f"/api/files/{fid}/pages/0/text"):
        assert c.get(path, headers=h).status_code == expect, path


@pytest.mark.parametrize("who,expect", [("view", 403), ("red2", 404)])
def test_upload_forbidden(env, who, expect):
    r = env["c"].post(f"/api/cases/{env['case']['id']}/files", files=[("files", ("a.txt", b"hello", "text/plain"))],
                      headers=env["u"][who])
    assert r.status_code == expect


@pytest.mark.parametrize("who,expect", [("red", 403), ("view", 403), ("sup", 200)])
def test_approve_requires_supervisor(env, who, expect):
    r = env["c"].patch(f"/api/files/{env['fid']}", json={"status": "approved"}, headers=env["u"][who])
    assert r.status_code == expect


@pytest.mark.parametrize("who,expect", [("red", 403), ("sup", 403), ("admin", 200)])
def test_user_admin_requires_admin(env, who, expect):
    r = env["c"].post("/api/users", json={"username": f"u{who}", "role": "viewer", "password": "Kq7!Lm3#Vx9$Z1"}, headers=env["u"][who])
    assert r.status_code == expect


@pytest.mark.parametrize("who,expect", [("red", 403), ("sup", 200)])
def test_global_audit(env, who, expect):
    assert env["c"].get("/api/audit", headers=env["u"][who]).status_code == expect


def test_redactor_sees_case_audit(env):
    assert env["c"].get(f"/api/audit?case_id={env['case']['id']}", headers=env["u"]["red"]).status_code == 200


def test_non_admin_user_directory_is_minimal(env):
    users = env["c"].get("/api/users", headers=env["u"]["red"]).json()
    assert users and set(users[0]) == {"id", "username", "full_name", "role"}


# ---- lifecycle -------------------------------------------------------------------------------------
def test_unsupported_upload(env):
    r = env["c"].post(f"/api/cases/{env['case']['id']}/files", files=[("files", ("old.doc", b"x", "application/msword"))],
                      headers=env["u"]["red"]).json()
    assert r["errors"] and "docx" in r["errors"][0]["error"]


def test_review_edits(env):
    c, fid, h = env["c"], env["fid"], env["u"]["red"]
    dets = c.get(f"/api/files/{fid}/detections", headers=h).json()["detections"]
    ssn = next(d for d in dets if d["entity"] == "SSN")
    assert c.patch(f"/api/files/{fid}/detections", json={"updates": [{"id": ssn["id"], "exemption": "(b)(7)(C)"}]},
                   headers=h).status_code == 200
    r = c.post(f"/api/files/{fid}/detections", json={"entity": "CUSTOM", "page": 0,
                                                     "boxes": [{"x0": 72, "y0": 95, "x1": 200, "y1": 110}]}, headers=h)
    assert r.status_code == 200
    txt = c.get(f"/api/files/{fid}/pages/0/text", headers=h).json()["text"]
    i = txt.index("cervical")
    r = c.post(f"/api/files/{fid}/detections", json={"entity": "MEDICAL_CONDITION", "page": 0, "start": i,
                                                     "end": i + len("cervical strain")}, headers=h)
    assert r.json()["text"] == "cervical strain" and r.json()["boxes"]
    assert c.delete(f"/api/files/{fid}/detections/{r.json()['id']}", headers=h).status_code == 200
    s = c.post(f"/api/files/{fid}/search", json={"terms": [{"text": "Assessment"}], "add": True}, headers=h).json()
    assert s["count"] == 1
    r = c.patch(f"/api/files/{fid}/detections", json={"select_entities": {"PHONE": False}}, headers=h).json()
    assert "PHONE" not in r["by_entity"]


def test_export_download_log(env):
    c, fid, h = env["c"], env["fid"], env["u"]["red"]
    jid = c.post(f"/api/files/{fid}/export", json={"style": {"label": "exemption"}, "bates_prefix": "DEL_"}, headers=h).json()["job_id"]
    j = _wait(c, jid, h)
    assert j["result"]["verified"]
    eid = j["result"]["export_id"]
    pdf = c.get(f"/api/exports/{eid}/download", headers=h).content
    d = fitz.open(stream=pdf, filetype="pdf")
    text = d[0].get_text()
    assert "523-71-9921" not in text and "Delgado" not in text and "DEL_000001" in text and "(b)(7)(C)" in text
    assert "(512) 555-0187" in text  # phone was deselected by the reviewer
    log = c.get(f"/api/exports/{eid}/log.csv", headers=h).text
    rows = list(csv.DictReader(io.StringIO(log)))
    assert rows and all("523-71-9921" not in str(r) and "Delgado" not in str(r) for r in rows)
    # the viewer can download the verified, redacted export and view its pages — but never the original
    v = env["u"]["view"]
    assert c.get(f"/api/exports/{eid}/download", headers=v).status_code == 200
    assert c.get(f"/api/exports/{eid}/pages/0.png", headers=v).status_code == 200


def test_case_dictionary_applies_to_other_files(env):
    c, h, cid = env["c"], env["u"]["red"], env["case"]["id"]
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Follow-up letter: Maria Delgado returned the forms.", fontsize=10)
    fid2 = c.post(f"/api/cases/{cid}/files", files=[("files", ("letter.pdf", doc.tobytes(), "application/pdf"))],
                  headers=h).json()["files"][0]["id"]
    _wait(c, c.post(f"/api/files/{fid2}/analyze", json={"use_ml": False}, headers=h).json()["job_id"], h)
    dets = c.get(f"/api/files/{fid2}/detections", headers=h).json()["detections"]
    assert any(d["text"] == "Maria Delgado" for d in dets), dets


def test_lists_and_templates(env):
    c, h = env["c"], env["u"]["red"]
    lst = c.post("/api/lists", json={"name": "Code names", "terms": ["Project Falcon", {"text": r"PRJ-\d+", "regex": True}]},
                 headers=h).json()
    assert lst["count"] == 2
    assert c.post("/api/lists", json={"name": "bad", "terms": [{"text": "(", "regex": True}]}, headers=h).status_code == 400
    tpl = c.post("/api/templates", json={"name": "Header zone", "zones": [{"pages": "all", "x0": 0, "y0": 0, "x1": 1, "y1": 0.08}]},
                 headers=h).json()
    assert tpl["zones"][0]["y1"] == 0.08
    assert c.post("/api/templates", json={"name": "bad", "zones": [{"x0": 0.5, "y0": 0, "x1": 0.2, "y1": 1}]}, headers=h).status_code == 400


def test_audit_chain_and_no_pii(env):
    c, admin = env["c"], env["u"]["admin"]
    v = c.get("/api/audit/verify", headers=admin).json()
    assert v["valid"] and v["events"] > 10
    blob = c.get("/api/audit/export.csv", headers=admin).text
    assert "523-71-9921" not in blob and "Maria Delgado" not in blob and "(512) 555-0187" not in blob


def test_case_report(env):
    r = env["c"].get(f"/api/cases/{env['case']['id']}/report", headers=env["u"]["red"]).json()
    assert r["total_redactions"] >= 2 and r["files"]


def test_meta(env):
    m = env["c"].get("/api/meta", headers=env["u"]["view"]).json()
    assert len(m["entities"]) >= 60 and "frcp_5_2" in [p["key"] for p in m["profiles"]] and "(b)(6)" in m["exemption_codes"]


def test_security_headers(env):
    r = env["c"].get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "DENY"


def test_delete_requires_supervisor_and_destroys_blobs(env):
    c, cid = env["c"], env["case"]["id"]
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "temp", fontsize=10)
    f = c.post(f"/api/cases/{cid}/files", files=[("files", ("tmp.pdf", doc.tobytes(), "application/pdf"))],
               headers=env["u"]["red"]).json()["files"][0]
    assert c.delete(f"/api/files/{f['id']}", headers=env["u"]["red"]).status_code == 403
    assert c.delete(f"/api/files/{f['id']}", headers=env["u"]["sup"]).status_code == 200
    assert c.get(f"/api/files/{f['id']}", headers=env["u"]["sup"]).status_code == 404


# ---- parity features through the API ------------------------------------------------------------

def test_manual_shapes_validated_and_stored(env):
    c, fid, red = env["c"], env["fid"], env["u"]["red"]
    r = c.post(f"/api/files/{fid}/detections", json={"page": 0, "shape": "polygon",
                                                       "points": [[70, 60], [200, 60], [130, 95]],
                                                       "entity": "CUSTOM", "label_text": "(b)(6)", "fill": [0, 0, 0.6]},
               headers=red)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["meta"]["shape"] == "polygon" and len(d["meta"]["points"]) == 3 and d["boxes"]
    assert c.post(f"/api/files/{fid}/detections", json={"page": 0, "shape": "star", "boxes": [{"x0": 1, "y0": 1, "x1": 9, "y1": 9}]},
                  headers=red).status_code == 400
    assert c.post(f"/api/files/{fid}/detections", json={"page": 0, "effect": "melt", "boxes": [{"x0": 1, "y0": 1, "x1": 9, "y1": 9}]},
                  headers=red).status_code == 400
    c.delete(f"/api/files/{fid}/detections/{d['id']}", headers=red)


def test_confidence_report_has_no_values(env):
    c, fid = env["c"], env["fid"]
    r = c.get(f"/api/files/{fid}/confidence.csv", headers=env["u"]["red"])
    assert r.status_code == 200
    body = r.text
    assert "confidence" in body.splitlines()[0]
    for value in ("Maria Delgado", "523-71-9921", "555-0187"):
        assert value not in body
    assert c.get(f"/api/files/{fid}/confidence.csv", headers=env["u"]["view"]).status_code == 403


def test_marked_copy_hidden_from_viewers(env):
    c, fid = env["c"], env["fid"]
    jid = c.post(f"/api/files/{fid}/export", json={"marked_copy": True}, headers=env["u"]["red"]).json()["job_id"]
    j = _wait(c, jid, env["u"]["red"])
    ex = j["result"]["export_id"] if "export_id" in (j.get("result") or {}) else None
    exports = c.get(f"/api/cases/{env['case']['id']}/exports", headers=env["u"]["red"]).json()
    marked = [e for e in exports if e["name"].endswith("_REVIEW-COPY_REDACTED.pdf") or "REVIEW-COPY" in e["name"]]
    assert marked, exports
    eid = ex or marked[-1]["id"]
    assert c.get(f"/api/exports/{eid}/download", headers=env["u"]["red"]).status_code == 200
    assert c.get(f"/api/exports/{eid}/download", headers=env["u"]["view"]).status_code in (403, 404)
    viewer_list = c.get(f"/api/cases/{env['case']['id']}/exports", headers=env["u"]["view"]).json()
    assert not [e for e in viewer_list if "REVIEW-COPY" in e["name"]]


def test_translate_needs_a_transcript(env):
    c, fid = env["c"], env["fid"]
    assert c.post(f"/api/files/{fid}/translate", json={"target": "es"}, headers=env["u"]["red"]).status_code == 409
    assert c.post(f"/api/files/{fid}/translate", json={"target": "xx"}, headers=env["u"]["red"]).status_code in (400, 409)


def test_meta_lists_new_capabilities(env):
    m = env["c"].get("/api/meta", headers=env["u"]["red"]).json()
    assert {"languages", "image_classes", "shapes", "track_modes"} <= set(m)
    assert "IMAGE_ID_CARD" in m["image_classes"]["classes"] and "polygon" in m["shapes"]
    assert any(e["category"] == "VISUAL" for e in m["entities"])


def test_detection_edit_bulk_delete_restore_and_search_ids(env):
    c, fid, red = env["c"], env["fid"], env["u"]["red"]
    d = c.post(f"/api/files/{fid}/detections", json={"page": 0, "boxes": [{"x0": 70, "y0": 60, "x1": 140, "y1": 75}],
                                                     "entity": "CUSTOM", "selected": False, "exemption": ""},
               headers=red).json()
    assert d["selected"] is False and d["exemption"] == ""
    r = c.patch(f"/api/files/{fid}/detections", json={"updates": [{"id": d["id"], "label_text": "(b)(6)", "fill": [0, 0, 1],
                                                                    "shape": "ellipse", "note": "QC"}]}, headers=red)
    assert r.status_code == 200
    got = next(x for x in c.get(f"/api/files/{fid}/detections", headers=red).json()["detections"] if x["id"] == d["id"])
    assert got["meta"]["label_text"] == "(b)(6)" and got["meta"]["shape"] == "ellipse" and got["meta"]["fill"] == [0, 0, 1]
    assert c.patch(f"/api/files/{fid}/detections", json={"updates": [{"id": d["id"], "shape": "hexagon"}]},
                   headers=red).status_code == 400
    # search → added ids → bulk delete → restore exactly
    r = c.post(f"/api/files/{fid}/search", json={"terms": [{"text": "cervical"}], "add": True}, headers=red).json()
    assert r["added_ids"]
    full = [x for x in c.get(f"/api/files/{fid}/detections", headers=red).json()["detections"] if x["id"] in r["added_ids"]]
    assert c.post(f"/api/files/{fid}/detections/delete", json={"ids": r["added_ids"] + [d["id"]]},
                  headers=red).json()["removed"] == len(r["added_ids"]) + 1
    back = c.post(f"/api/files/{fid}/detections/restore", json={"detections": full}, headers=red).json()
    assert sorted(back["ids"]) == sorted(r["added_ids"])
    again = [x for x in c.get(f"/api/files/{fid}/detections", headers=red).json()["detections"] if x["id"] in r["added_ids"]]
    assert [(x["score"], x["source"]) for x in again] == [(x["score"], x["source"]) for x in full]
    c.post(f"/api/files/{fid}/detections/delete", json={"ids": r["added_ids"]}, headers=red)
    assert c.post(f"/api/files/{fid}/detections/delete", json={"ids": ["x"]}, headers=env["u"]["view"]).status_code == 403


def test_translations_list_and_no_storage_ids(env):
    c, fid = env["c"], env["fid"]
    assert c.get(f"/api/files/{fid}/translations", headers=env["u"]["red"]).json() == []
    info = c.get(f"/api/files/{fid}", headers=env["u"]["red"]).json()["info"]
    assert not isinstance(info.get("translations"), dict)


def test_review_copy_does_not_count_as_exported(env):
    c = env["c"]
    rep = c.get(f"/api/cases/{env['case']['id']}/report", headers=env["u"]["red"]).json()
    row = next(r for r in rep["files"] if r["file_id"] == env["fid"])
    assert row["review_copies"] >= 1
    exports = c.get(f"/api/cases/{env['case']['id']}/exports", headers=env["u"]["red"]).json()
    assert any(e["marked_copy"] for e in exports) and any(not e["marked_copy"] for e in exports)


def test_restart_recovers_interrupted_jobs(env):
    from obscura.db import File, Job, tx
    from obscura.jobs import recover_interrupted
    with tx() as s:
        f = s.get(File, env["fid"])
        prev = f.status
        f.status = "analyzing"
        s.add(Job(kind="analyze", status="running", file_id=f.id, case_id=f.case_id))
    assert recover_interrupted() >= 1
    with tx() as s:
        assert s.get(File, env["fid"]).status in ("ready", "uploaded")
        assert not s.query(Job).filter(Job.status.in_(("queued", "running"))).count()
        s.get(File, env["fid"]).status = prev
