"""Redact additional text: words, phrases, numbers and patterns typed by the user, across a whole case."""
import importlib
import os
import re
import time

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

PW = "Str0ng!Passphrase"
URL = "/api/cases/{}/redact-text"

PDF_LINES = [
    "Claimant: Ana Torres   Claim 77-40912",
    "Witness Bob the bartender at the Rusty Anchor saw the collision.",
    "Project Bluebird budget memo, internal code ZX-4471.",
    "The Rusty",
    "Anchor closed early that night.",
]
TXT = ("Interview notes. The Rusty Anchor manager said Project Bluebird was cancelled.\n"
       "Code ZX-4471 and code ZX-9902 were both used. rusty anchor (lower case) appears here too.\n")


def _wait(c, jid, h, timeout=180):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get(f"/api/jobs/{jid}", headers=h).json()
        if j["status"] in ("done", "error", "cancelled"):
            assert j["status"] == "done", j
            return j
        time.sleep(0.2)
    raise TimeoutError


def _pdf(lines):
    doc = fitz.open()
    p = doc.new_page()
    for i, line in enumerate(lines):
        p.insert_text((72, 72 + 16 * i), line, fontsize=10)
    return doc.tobytes()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    data = tmp_path_factory.mktemp("extratext")
    os.environ["OBSCURA_DATA"] = str(data)
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
    app = main.create_app()
    with TestClient(app) as c:
        pw = re.search(r"password: (\S+)", (cfg.DATA_DIR / "INITIAL_ADMIN_PASSWORD.txt").read_text()).group(1)
        t = c.post("/api/auth/login", json={"username": "admin", "password": pw}).json()["token"]
        t = c.post("/api/auth/change-password", json={"current_password": pw, "new_password": PW},
                   headers={"Authorization": f"Bearer {t}"}).json()["token"]
        admin = {"Authorization": f"Bearer {t}"}
        users = {"admin": admin}
        for name, role in [("red", "redactor"), ("view", "viewer"), ("outsider", "redactor")]:
            c.post("/api/users", json={"username": name, "role": role, "password": "Kq7!Lm3#Vx9$Pw"}, headers=admin)
            tk = c.post("/api/auth/login", json={"username": name, "password": "Kq7!Lm3#Vx9$Pw"}).json()["token"]
            tk = c.post("/api/auth/change-password", json={"current_password": "Kq7!Lm3#Vx9$Pw",
                                                           "new_password": f"Tr0ub4dor&{len(name)}Horse!"},
                        headers={"Authorization": f"Bearer {tk}"}).json()["token"]
            users[name] = {"Authorization": f"Bearer {tk}"}
        ids = {u["username"]: u["id"] for u in c.get("/api/users", headers=admin).json()}
        h = users["red"]
        case = c.post("/api/cases", json={"name": "Torres v. Anchor LLC"}, headers=h).json()
        c.post(f"/api/cases/{case['id']}/members", json={"user_id": ids["view"], "role": "viewer"}, headers=h)
        up = c.post(f"/api/cases/{case['id']}/files", headers=h, files=[
            ("files", ("memo.pdf", _pdf(PDF_LINES), "application/pdf")),
            ("files", ("notes.txt", TXT.encode(), "text/plain")),
            ("files", ("later.txt", b"Rusty Anchor receipts. ZX-4471.", "text/plain"))]).json()
        fids = {f["name"]: f["id"] for f in up["files"]}
        for name in ("memo.pdf", "notes.txt"):
            jid = c.post(f"/api/files/{fids[name]}/analyze", json={"use_ml": False}, headers=h).json()["job_id"]
            _wait(c, jid, h)
        yield {"c": c, "u": users, "case": case["id"], "f": fids}


def _dets(env, fid, h=None):
    return env["c"].get(f"/api/files/{fid}/detections", headers=h or env["u"]["red"]).json()["detections"]


def _post(env, body, who="red"):
    return env["c"].post(URL.format(env["case"]), json=body, headers=env["u"][who])


def test_empty_list_initially(env):
    r = env["c"].get(URL.format(env["case"]), headers=env["u"]["red"]).json()
    assert r == {"list_id": None, "terms": []}


def test_preview_counts_without_adding(env):
    before = len(_dets(env, env["f"]["notes.txt"]))
    r = _post(env, {"terms": [{"text": "Rusty Anchor"}], "preview": True}).json()
    assert r["preview"] and r["total_added"] == 0 and r["total_matches"] >= 4
    assert len(_dets(env, env["f"]["notes.txt"])) == before
    assert env["c"].get(URL.format(env["case"]), headers=env["u"]["red"]).json()["terms"] == []


def test_unanalysed_file_is_skipped_with_reason(env):
    r = _post(env, {"terms": [{"text": "Rusty Anchor"}], "preview": True}).json()
    row = next(x for x in r["files"] if x["file_id"] == env["f"]["later.txt"])
    assert "not analysed" in row["skipped"]


def test_apply_across_case(env):
    r = _post(env, {"terms": [{"text": "Rusty Anchor"}, {"text": "Project Bluebird"}]}).json()
    by = {x["name"]: x for x in r["files"]}
    assert by["memo.pdf"]["matches"] == 3    # includes the phrase split over two lines
    assert by["notes.txt"]["added"] >= 3     # whole word, case-insensitive by default
    assert r["remembered"] and r["list_id"]
    texts = [d["text"].lower() for d in _dets(env, env["f"]["notes.txt"]) if d["entity"] == "CUSTOM"]
    assert texts.count("rusty anchor") == 2 and "project bluebird" in texts


def test_added_detections_are_selected_and_explained(env):
    d = [x for x in _dets(env, env["f"]["memo.pdf"]) if x["entity"] == "CUSTOM"]
    assert d and all(x["selected"] for x in d)
    assert all("additional text to redact" in x["explanation"] for x in d)
    assert all(x["boxes"] for x in d)  # PDF matches have page boxes


def test_phrase_across_line_break_on_pdf(env):
    d = [x for x in _dets(env, env["f"]["memo.pdf"]) if x["entity"] == "CUSTOM"]
    assert any(len(x["boxes"]) >= 2 for x in d)


def test_apply_twice_adds_nothing(env):
    r = _post(env, {"terms": [{"text": "Rusty Anchor"}]}).json()
    assert r["total_added"] == 0 and r["total_matches"] > 0


def test_remembered_list(env):
    r = env["c"].get(URL.format(env["case"]), headers=env["u"]["red"]).json()
    assert [t["text"] for t in r["terms"]] == ["Rusty Anchor", "Project Bluebird"]


def test_remember_dedupes_case_insensitively(env):
    _post(env, {"terms": [{"text": "rusty anchor"}]})
    r = env["c"].get(URL.format(env["case"]), headers=env["u"]["red"]).json()
    assert sum(t["text"].lower() == "rusty anchor" for t in r["terms"]) == 1


def test_regex_pattern(env):
    r = _post(env, {"terms": [{"text": r"ZX-\d{4}", "regex": True}], "file_ids": [env["f"]["notes.txt"]]}).json()
    assert r["total_added"] == 2
    texts = {d["text"] for d in _dets(env, env["f"]["notes.txt"]) if d["entity"] == "CUSTOM"}
    assert {"ZX-4471", "ZX-9902"} <= texts


def test_file_subset_only(env):
    before = len(_dets(env, env["f"]["memo.pdf"]))
    r = _post(env, {"terms": [{"text": "collision"}], "file_ids": [env["f"]["notes.txt"]], "remember": False}).json()
    assert [x["file_id"] for x in r["files"]] == [env["f"]["notes.txt"]]
    assert len(_dets(env, env["f"]["memo.pdf"])) == before


def test_case_sensitive(env):
    r = _post(env, {"terms": [{"text": "rusty anchor", "case_sensitive": True}], "preview": True,
                    "file_ids": [env["f"]["notes.txt"]]}).json()
    assert r["total_matches"] == 1


def test_whole_word_off_matches_inside_words(env):
    on = _post(env, {"terms": [{"text": "Blue"}], "preview": True, "file_ids": [env["f"]["notes.txt"]]}).json()
    off = _post(env, {"terms": [{"text": "Blue", "whole_word": False}], "preview": True,
                      "file_ids": [env["f"]["notes.txt"]]}).json()
    assert on["total_matches"] == 0 and off["total_matches"] == 1


def test_custom_entity_and_exemption(env):
    _post(env, {"terms": [{"text": "bartender", "entity": "INDIRECT_ROLE"}], "exemption": "(b)(6)", "remember": False,
                "file_ids": [env["f"]["memo.pdf"]]})
    d = next(x for x in _dets(env, env["f"]["memo.pdf"]) if x["text"].lower() == "bartender")
    assert d["entity"] == "INDIRECT_ROLE" and d["exemption"] == "(b)(6)"


@pytest.mark.parametrize("body,code", [
    ({"terms": []}, 400),
    ({"terms": [{"text": "   "}]}, 400),
    ({"terms": [{"text": "(unclosed", "regex": True}]}, 400),
    ({"terms": [{"text": "a*", "regex": True}]}, 400),
    ({"terms": [{"text": "x" * 501}]}, 400),
    ({"terms": [{"text": f"t{i}"} for i in range(501)]}, 400),
    ({"terms": [{"text": "x"}], "file_ids": [999999]}, 404),
])
def test_validation(env, body, code):
    assert _post(env, body).status_code == code


def test_viewer_cannot_redact(env):
    assert _post(env, {"terms": [{"text": "Torres"}]}, who="view").status_code == 403


def test_outsider_cannot_see_case(env):
    assert _post(env, {"terms": [{"text": "Torres"}]}, who="outsider").status_code == 404
    assert env["c"].get(URL.format(env["case"]), headers=env["u"]["outsider"]).status_code == 404


def test_outsider_cannot_edit_case_list_through_library(env):
    lid = env["c"].get(URL.format(env["case"]), headers=env["u"]["red"]).json()["list_id"]
    o = env["u"]["outsider"]
    r = env["c"].put(f"/api/lists/{lid}", json={"name": "x", "terms": []}, headers=o)
    assert r.status_code == 404
    assert env["c"].delete(f"/api/lists/{lid}", headers=o).status_code == 404
    assert env["c"].get(URL.format(env["case"]), headers=env["u"]["red"]).json()["terms"]


def test_new_files_get_remembered_text(env):
    """A file analysed after the text was added is redacted automatically."""
    c, h = env["c"], env["u"]["red"]
    jid = c.post(f"/api/files/{env['f']['later.txt']}/analyze", json={"use_ml": False}, headers=h).json()["job_id"]
    _wait(c, jid, h)
    texts = [d["text"] for d in _dets(env, env["f"]["later.txt"]) if d["entity"] == "CUSTOM"]
    assert "Rusty Anchor" in texts and "ZX-4471" in texts


def test_export_removes_the_text(env):
    c, h, fid = env["c"], env["u"]["red"], env["f"]["memo.pdf"]
    j = _wait(c, c.post(f"/api/files/{fid}/export", json={}, headers=h).json()["job_id"], h)
    assert j["result"]["verified"]
    pdf = fitz.open(stream=c.get(f"/api/exports/{j['result']['export_id']}/download", headers=h).content,
                    filetype="pdf")
    text = pdf[0].get_text()
    assert "Rusty" not in text and "Anchor" not in text and "Bluebird" not in text
    assert "collision" in text  # untouched text stays


def test_exported_file_flags_reexport(env):
    r = _post(env, {"terms": [{"text": "closed early"}], "file_ids": [env["f"]["memo.pdf"]], "remember": False}).json()
    row = r["files"][0]
    assert row["added"] == 1 and row.get("needs_reexport") is True


def test_put_replaces_list(env):
    c, h = env["c"], env["u"]["red"]
    r = c.put(URL.format(env["case"]), json={"terms": [{"text": "Project Bluebird"}]}, headers=h).json()
    assert [t["text"] for t in r["terms"]] == ["Project Bluebird"]
    assert [t["text"] for t in c.get(URL.format(env["case"]), headers=h).json()["terms"]] == ["Project Bluebird"]


def test_audit_never_contains_the_terms(env):
    rows = env["c"].get("/api/audit", headers=env["u"]["admin"], params={"limit": 500}).json()
    items = rows["items"] if isinstance(rows, dict) else rows
    blob = repr([e for e in items if "text" in str(e.get("action", ""))])
    assert "case_text_redaction" in blob
    assert "Rusty" not in blob and "Bluebird" not in blob and "ZX-" not in blob


def test_new_and_switched_ids_for_undo(env):
    """Matches on existing unselected suggestions are switched on, and reported apart from new redactions."""
    c, h, fid = env["c"], env["u"]["red"], env["f"]["notes.txt"]
    dets = c.get(f"/api/files/{fid}/detections", headers=h).json()["detections"]
    target = next(d for d in dets if d["entity"] == "CUSTOM" and d["text"] == "ZX-9902")
    c.patch(f"/api/files/{fid}/detections", json={"updates": [{"id": target["id"], "selected": False}]}, headers=h)
    r = _post(env, {"terms": [{"text": "ZX-9902"}, {"text": "Interview notes"}], "file_ids": [fid],
                    "remember": False}).json()
    row = r["files"][0]
    assert row["switched_ids"] == [target["id"]] and len(row["new_ids"]) == 1
    assert set(row["added_ids"]) == set(row["new_ids"]) | set(row["switched_ids"])


def test_export_lists_carry_final_check_count(env):
    c, h = env["c"], env["u"]["red"]
    rows = c.get(f"/api/cases/{env['case']}/exports", headers=h).json()
    assert rows and all("second_opinion_open" in r for r in rows)
    f = c.get(f"/api/files/{env['f']['memo.pdf']}", headers=h).json()
    assert all("second_opinion_open" in e for e in f["exports"])


def test_viewer_sees_final_check_counts_not_text(env):
    c = env["c"]
    eid = c.get(f"/api/cases/{env['case']}/exports", headers=env["u"]["red"]).json()[0]["id"]
    info = c.get(f"/api/exports/{eid}", headers=env["u"]["view"])
    if info.status_code != 200:
        pytest.skip("viewer cannot open unverified export")
    so = info.json()["report"].get("second_opinion") or {}
    assert all("text" not in f for f in so.get("findings", []))


def test_health_has_boot_id(env):
    a = env["c"].get("/api/health").json()
    assert a["ok"] and len(a["boot"]) == 16 and env["c"].get("/api/health").json()["boot"] == a["boot"]


def test_financial_statement_pdf_export(env):
    """A bank statement page through the whole pipeline with the financial profile: names in transaction lines,
    masked accounts and MICR numbers are removed from the exported PDF; form text and amounts stay."""
    c, h = env["c"], env["u"]["red"]
    lines = ["EVERYDAY CHECKING   Account Number: 4831 0072 9915   Routing Number: 021000021",
             "03/04  ZELLE TO MARIA GOMEZ ON 03/04 REF #PP0ABC1234            -250.00",
             "03/12  ONLINE TRANSFER TO DAVID CHEN XXXXXX8812 REF #IB0Q2W        -500.00",
             "03/15  CHECK 1042 PAID TO R. OKAFOR                                 -300.00",
             "A021000021A 4831007299C 1042",
             "Page 2 of 6   APR 24.99%"]
    fid = c.post(f"/api/cases/{env['case']}/files", headers=h,
                 files=[("files", ("statement.pdf", _pdf(lines), "application/pdf"))]).json()["files"][0]["id"]
    _wait(c, c.post(f"/api/files/{fid}/analyze", json={"use_ml": False, "profile": "financial"}, headers=h).json()["job_id"], h)
    j = _wait(c, c.post(f"/api/files/{fid}/export", json={}, headers=h).json()["job_id"], h)
    assert j["result"]["verified"]
    pdf = fitz.open(stream=c.get(f"/api/exports/{j['result']['export_id']}/download", headers=h).content, filetype="pdf")
    text = pdf[0].get_text()
    for gone in ("4831 0072 9915", "021000021", "MARIA GOMEZ", "DAVID CHEN", "8812", "OKAFOR", "4831007299"):
        assert gone not in text, gone
    for kept in ("Page 2 of 6", "24.99%", "-250.00", "EVERYDAY CHECKING"):
        assert kept in text, kept
