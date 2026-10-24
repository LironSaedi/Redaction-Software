"""Sign-in turned off: this computer opens straight into the app, everything else still has to sign in."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

PW = "Kq7!Lm3#Vx9$Pw"
LOCAL = dict(base_url="http://127.0.0.1:8600", client=("127.0.0.1", 50000))
REMOTE = dict(base_url="http://192.168.1.10:8600", client=("192.168.1.20", 50000))


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    data = tmp_path_factory.mktemp("localmode")
    old = os.environ.get("OBSCURA_REQUIRE_LOGIN")
    os.environ["OBSCURA_DATA"] = str(data)
    os.environ["OBSCURA_REQUIRE_LOGIN"] = "0"
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
    a = main.create_app()
    with TestClient(a, **LOCAL):  # runs startup
        yield a, cfg
    os.environ["OBSCURA_REQUIRE_LOGIN"] = old or "1"
    importlib.reload(cfg)


def client(app, **kw):
    return TestClient(app[0], **{**LOCAL, **kw})


def local_token(app, **kw):
    r = client(app, **kw).post("/api/auth/local")
    assert r.status_code == 200, r.text
    return r.json()


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


def test_setting_defaults_to_off(app):
    assert app[1].settings.require_login is False


def test_no_initial_password_file(app):
    assert not (app[1].DATA_DIR / "INITIAL_ADMIN_PASSWORD.txt").exists()


def test_mode_on_this_computer(app):
    assert client(app).get("/api/auth/mode").json() == {"require_login": False, "local_access": True}


def test_mode_from_another_computer(app):
    assert client(app, **REMOTE).get("/api/auth/mode").json() == {"require_login": False, "local_access": False}


def test_local_sign_in_gives_admin(app):
    r = local_token(app)
    u = r["user"]
    assert u["username"] == "local" and u["role"] == "admin" and u["local"] is True
    assert u["must_change_password"] is False
    me = client(app).get("/api/auth/me", headers=bearer(r["token"])).json()
    assert me["id"] == u["id"]


def test_local_sign_in_is_idempotent(app):
    assert local_token(app)["user"]["id"] == local_token(app)["user"]["id"]


def test_local_sign_in_sets_read_only_cookie(app):
    r = client(app).post("/api/auth/local")
    assert "obscura_token" in r.headers.get("set-cookie", "")
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()


def test_local_user_can_work(app):
    h = bearer(local_token(app)["token"])
    c = client(app)
    case = c.post("/api/cases", json={"name": "Local mode case"}, headers=h)
    assert case.status_code == 200
    assert any(x["id"] == case.json()["id"] for x in c.get("/api/cases", headers=h).json())


def test_local_sign_in_is_audited(app):
    h = bearer(local_token(app)["token"])
    rows = client(app).get("/api/audit", headers=h, params={"action": "login_local"}).json()
    items = rows["items"] if isinstance(rows, dict) else rows
    assert any(e.get("action") == "login_local" for e in items)


def test_get_is_not_allowed(app):
    assert client(app).get("/api/auth/local").status_code in (404, 405)
    assert client(app).get("/api/no-such-route").status_code == 404


def test_requests_without_token_still_rejected(app):
    """Turning sign-in off does not open the API: the browser still has to fetch a token first."""
    assert client(app).get("/api/cases").status_code == 401
    assert client(app).post("/api/cases", json={"name": "x"}).status_code == 401


@pytest.mark.parametrize("peer", ["192.168.1.20", "10.0.0.5", "172.16.4.4", "8.8.8.8", "testclient"])
def test_remote_computers_must_sign_in(app, peer):
    r = client(app, client=(peer, 50000)).post("/api/auth/local")
    assert r.status_code == 403


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8600", "127.0.0.1.nip.io", "192.168.1.10:8600",
                                  "localhost.evil.example"])
def test_dns_rebinding_host_rejected(app, host):
    r = client(app).post("/api/auth/local", headers={"host": host})
    assert r.status_code == 403


@pytest.mark.parametrize("origin", ["https://evil.example", "http://192.168.1.10:8600", "null",
                                    "http://localhost.evil.example"])
def test_cross_site_origin_rejected(app, origin):
    assert client(app).post("/api/auth/local", headers={"origin": origin}).status_code == 403


@pytest.mark.parametrize("origin", ["http://localhost:8600", "http://127.0.0.1:8600", "http://[::1]:8600",
                                    "https://localhost"])
def test_same_machine_origin_allowed(app, origin):
    assert client(app).post("/api/auth/local", headers={"origin": origin}).status_code == 200


@pytest.mark.parametrize("hdr", ["x-forwarded-for", "x-forwarded-host", "forwarded", "x-real-ip"])
def test_proxied_requests_rejected(app, hdr):
    assert client(app).post("/api/auth/local", headers={hdr: "203.0.113.9"}).status_code == 403


@pytest.mark.parametrize("peer,base", [("::1", "http://[::1]:8600"), ("::ffff:127.0.0.1", "http://127.0.0.1:8600"),
                                       ("127.0.0.1", "http://localhost:8600"), ("127.0.0.1", "http://localhost")])
def test_loopback_variants(app, peer, base):
    assert client(app, client=(peer, 50000), base_url=base).post("/api/auth/local").status_code == 200


def test_local_account_has_no_password_login(app):
    for pw in ("", "x", PW):
        assert client(app).post("/api/auth/login", json={"username": "local", "password": pw}).status_code == 401


def test_local_account_cannot_change_password(app):
    h = bearer(local_token(app)["token"])
    r = client(app).post("/api/auth/change-password", json={"current_password": "x", "new_password": PW}, headers=h)
    assert r.status_code == 400


def test_reserved_username(app):
    h = bearer(local_token(app)["token"])
    r = client(app).post("/api/users", json={"username": "local", "role": "viewer", "password": PW}, headers=h)
    assert r.status_code == 409


def test_team_members_still_sign_in_from_network(app):
    h = bearer(local_token(app)["token"])
    assert client(app).post("/api/users", json={"username": "paralegal", "role": "redactor", "password": PW},
                            headers=h).status_code == 200
    remote = client(app, **REMOTE)
    r = remote.post("/api/auth/login", json={"username": "paralegal", "password": PW})
    assert r.status_code == 200
    assert r.json()["user"]["local"] is False


def test_disabled_local_account(app):
    h = bearer(local_token(app)["token"])
    c = client(app)
    assert c.post("/api/users", json={"username": "boss", "role": "admin", "password": PW}, headers=h).status_code == 200
    remote = client(app, **REMOTE)
    t = remote.post("/api/auth/login", json={"username": "boss", "password": PW}).json()["token"]
    t = remote.post("/api/auth/change-password", json={"current_password": PW, "new_password": "Tr0ub4dor&3Horse!"},
                    headers=bearer(t)).json()["token"]
    ids = {u["username"]: u["id"] for u in remote.get("/api/users", headers=bearer(t)).json()}
    assert remote.patch(f"/api/users/{ids['local']}", json={"is_active": False}, headers=bearer(t)).status_code == 200
    assert c.post("/api/auth/local").status_code == 403
    assert remote.patch(f"/api/users/{ids['local']}", json={"is_active": True}, headers=bearer(t)).status_code == 200
    assert c.post("/api/auth/local").status_code == 200


def test_turning_sign_in_back_on(app):
    cfg = app[1]
    cfg.settings.require_login = True
    try:
        assert client(app).get("/api/auth/mode").json() == {"require_login": True, "local_access": False}
        assert client(app).post("/api/auth/local").status_code == 403
    finally:
        cfg.settings.require_login = False
    assert client(app).post("/api/auth/local").status_code == 200


def test_bootstrap_ignores_local_account(app):
    """Switching to team sign-in later still creates a first admin even though the local account exists."""
    import obscura.main as main
    assert main.bootstrap_admin() is None  # 'paralegal' and 'boss' exist already
    from obscura.db import User, tx
    with tx() as s:
        names = {u.username for u in s.query(User)}
    assert "local" in names


@pytest.mark.parametrize("netloc,expect", [("localhost:8600", "localhost"), ("[::1]:8600", "::1"), ("127.0.0.1", "127.0.0.1"),
                                           ("LOCALHOST", "localhost"), ("evil.example:80", "evil.example"),
                                           ("[::1]", "::1"), ("::1", "::1")])
def test_hostname_parse(netloc, expect):
    from obscura.security import _hostname
    assert _hostname(netloc) == expect
