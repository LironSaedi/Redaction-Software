"""Installed-app behaviour: first-run wizard, app settings, model import, uninstall and the desktop launcher."""
import importlib
import json
import os
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

LOCAL = dict(base_url="http://127.0.0.1:8600", client=("127.0.0.1", 50000))
REMOTE = dict(base_url="http://192.168.1.10:8600", client=("192.168.1.20", 50000))
PW = "Kq7!Lm3#Vx9$Pw"
_KEYS = ("OBSCURA_DATA", "OBSCURA_REQUIRE_LOGIN", "OBSCURA_INSTALLED", "OBSCURA_CONFIG", "OBSCURA_HOME_DIR",
         "OBSCURA_INSTALL_DIR", "OBSCURA_UNINSTALL_DRYRUN", "OBSCURA_MODELS")


def _boot(tmp: Path, install_dir: Path | None = None):
    os.environ.pop("OBSCURA_DATA", None)
    os.environ.pop("OBSCURA_REQUIRE_LOGIN", None)
    os.environ["OBSCURA_INSTALLED"] = "1"
    os.environ["OBSCURA_HOME_DIR"] = str(tmp / "home")
    os.environ["OBSCURA_CONFIG"] = str(tmp / "home" / "config.json")
    os.environ["OBSCURA_MODELS"] = str(tmp / "models")
    if install_dir:
        os.environ["OBSCURA_INSTALL_DIR"] = str(install_dir)
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
    return cfg, main


@pytest.fixture()
def installed(tmp_path, monkeypatch):
    saved = {k: os.environ.get(k) for k in _KEYS}
    monkeypatch.setenv("HOME", str(tmp_path / "userhome"))  # start-at-login files go here, never in the real home
    inst = tmp_path / "install"
    inst.mkdir()
    cfg, main = _boot(tmp_path, inst)
    exits = []
    monkeypatch.setattr(main, "request_exit", lambda code, delay=0.8: exits.append(code))
    app = main.create_app()
    with TestClient(app, **LOCAL) as c:
        yield {"c": c, "app": app, "cfg": cfg, "main": main, "tmp": tmp_path, "inst": inst, "exits": exits}
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    importlib.reload(cfg)


def remote(env):
    return TestClient(env["app"], **REMOTE)


def conf(env):
    return json.loads((env["tmp"] / "home" / "config.json").read_text())


def local_auth(env):
    return {"Authorization": "Bearer " + env["c"].post("/api/auth/local").json()["token"]}


# ---- wizard ---------------------------------------------------------------------------------------

def test_data_lives_in_app_home(installed):
    assert installed["cfg"].DATA_DIR == installed["tmp"] / "home" / "data"


def test_state_needed_on_first_run(installed):
    st = installed["c"].get("/api/setup/state").json()
    assert st["needed"] is True and st["defaults"]["mode"] == "single"
    assert st["defaults"]["data_dir"].endswith("data")
    assert {m["key"] for m in st["models"]} >= {"gliner/nvidia-gliner-pii", "vision", "whisper/medium.en"}


def test_state_refused_from_network(installed):
    assert remote(installed).get("/api/setup/state").status_code == 403


def test_complete_single_computer(installed):
    r = installed["c"].post("/api/setup/complete", json={"mode": "single"}).json()
    assert r["ok"] and r["restart"] is False and r["require_login"] is False
    c = conf(installed)
    assert c["setup_complete"] and c["host"] == "127.0.0.1" and c["require_login"] is False
    assert installed["c"].get("/api/setup/state").json() == {"needed": False}
    assert installed["c"].post("/api/auth/local").status_code == 200   # straight in, no sign-in
    assert installed["exits"] == []


def test_complete_only_once(installed):
    installed["c"].post("/api/setup/complete", json={"mode": "single"})
    assert installed["c"].post("/api/setup/complete", json={"mode": "single"}).status_code == 409


def test_complete_refused_from_network(installed):
    assert remote(installed).post("/api/setup/complete", json={"mode": "single"}).status_code in (403, 409)
    assert not conf(installed).get("setup_complete") if (installed["tmp"] / "home" / "config.json").exists() else True


def test_office_needs_admin(installed):
    assert installed["c"].post("/api/setup/complete", json={"mode": "office"}).status_code == 400
    r = installed["c"].post("/api/setup/complete", json={"mode": "office", "admin_username": "boss",
                                                        "admin_password": "short"})
    assert r.status_code == 400 and "password" in r.json()["detail"]


def test_office_server_restarts_and_creates_admin(installed):
    r = installed["c"].post("/api/setup/complete", json={
        "mode": "office", "admin_username": "Boss", "admin_password": PW, "admin_full_name": "Pat Lee"}).json()
    assert r["restart"] is True and r["require_login"] is True
    assert r["lan_url"] is None or r["lan_url"].startswith("http://")
    c = conf(installed)
    assert c["host"] == "0.0.0.0" and c["require_login"] is True and c["mode"] == "office"
    assert installed["exits"] == [installed["main"].EXIT_RESTART]
    raw = (installed["tmp"] / "home" / "config.json").read_text()
    assert PW not in raw and c["pending_admin"]["password_hash"].startswith("$argon2")   # never stored in clear
    installed["main"].create_pending_admin()   # what the next start does
    assert "pending_admin" not in conf(installed)
    assert remote(installed).post("/api/auth/login", json={"username": "boss", "password": PW}).status_code == 200


def test_new_data_folder_triggers_restart(installed):
    target = installed["tmp"] / "Case Files"
    r = installed["c"].post("/api/setup/complete", json={"mode": "single", "data_dir": str(target)}).json()
    assert r["restart"] is True and conf(installed)["data_dir"] == str(target)
    assert target.is_dir()


def test_busy_folder_gets_a_subfolder(installed):
    busy = installed["tmp"] / "Documents"
    busy.mkdir()
    (busy / "taxes.xlsx").write_text("x")
    installed["c"].post("/api/setup/complete", json={"mode": "single", "data_dir": str(busy)})
    assert conf(installed)["data_dir"] == str(busy / "Obscura Data")


@pytest.mark.parametrize("body", [{"data_dir": "relative/path"}, {"port": 80}, {"port": 70000}])
def test_validation(installed, body):
    assert installed["c"].post("/api/setup/complete", json={"mode": "single", **body}).status_code == 400


def test_file_instead_of_folder(installed):
    f = installed["tmp"] / "afile"
    f.write_text("x")
    assert installed["c"].post("/api/setup/complete", json={"mode": "single", "data_dir": str(f)}).status_code == 400


def test_pick_folder_uses_native_dialog(installed, monkeypatch):
    from obscura import desktop
    monkeypatch.setattr(desktop, "pick_folder", lambda prompt, start=None: "/Volumes/USB/models")
    assert installed["c"].post("/api/setup/pick-folder?purpose=models").json() == {"path": "/Volumes/USB/models"}
    assert remote(installed).post("/api/setup/pick-folder").status_code == 403


def test_model_import(installed):
    src = installed["tmp"] / "usb" / "models"
    for k in ("vision", "gliner/nvidia-gliner-pii"):
        (src / k).mkdir(parents=True)
        (src / k / "weights.bin").write_bytes(b"x" * 10)
    r = installed["c"].post("/api/setup/models/import", json={"path": str(src.parent)}).json()
    assert set(r["imported"]) == {"vision", "gliner/nvidia-gliner-pii"}
    assert (installed["tmp"] / "models" / "vision" / "weights.bin").exists()
    st = installed["c"].get("/api/setup/models").json()["models"]
    assert next(m for m in st if m["key"] == "vision")["present"]


def test_model_import_rejects_wrong_folder(installed):
    (installed["tmp"] / "random").mkdir()
    assert installed["c"].post("/api/setup/models/import", json={"path": str(installed["tmp"] / "random")}).status_code == 400


def test_setup_endpoints_need_admin_after_setup(installed):
    installed["c"].post("/api/setup/complete", json={"mode": "single"})
    assert installed["c"].get("/api/setup/models").status_code == 401
    assert installed["c"].get("/api/setup/models", headers=local_auth(installed)).status_code == 200


# ---- settings / uninstall ------------------------------------------------------------------------------

def test_app_info(installed):
    installed["c"].post("/api/setup/complete", json={"mode": "single"})
    info = installed["c"].get("/api/system/app", headers=local_auth(installed)).json()
    assert info["installed"] and info["mode"] == "single" and info["require_login"] is False
    assert info["uninstall_available"] is False   # no uninstaller in this fake install folder


def test_turning_sign_in_on_needs_a_password_admin(installed):
    installed["c"].post("/api/setup/complete", json={"mode": "single"})
    h = local_auth(installed)
    assert installed["c"].patch("/api/system/app", json={"require_login": True}, headers=h).status_code == 400
    installed["c"].post("/api/users", json={"username": "boss", "role": "admin", "password": PW}, headers=h)
    assert installed["c"].patch("/api/system/app", json={"require_login": True}, headers=h).json()["ok"]
    assert conf(installed)["require_login"] is True
    assert installed["c"].post("/api/auth/local").status_code == 403


def test_mode_change_restarts(installed):
    installed["c"].post("/api/setup/complete", json={"mode": "single"})
    r = installed["c"].patch("/api/system/app", json={"mode": "office"}, headers=local_auth(installed)).json()
    assert r["restart"] and conf(installed)["host"] == "0.0.0.0"


def test_uninstall_without_installer(installed):
    installed["c"].post("/api/setup/complete", json={"mode": "single"})
    r = installed["c"].post("/api/system/uninstall", json={"confirm": "UNINSTALL"}, headers=local_auth(installed))
    assert r.status_code == 409


@pytest.mark.skipif(sys.platform == "win32", reason="mac / linux uninstall script")
def test_uninstall_runs_the_installer_script(installed, monkeypatch):
    monkeypatch.setenv("OBSCURA_UNINSTALL_DRYRUN", "1")
    (installed["inst"] / "uninstall.sh").write_text("#!/bin/bash\n")
    installed["c"].post("/api/setup/complete", json={"mode": "single"})
    h = local_auth(installed)
    assert installed["c"].post("/api/system/uninstall", json={"confirm": "yes"}, headers=h).status_code == 400
    r = installed["c"].post("/api/system/uninstall", json={"confirm": "UNINSTALL", "remove_data": True}, headers=h).json()
    assert r["ok"] and "--remove-data" in r["command"] and str(installed["inst"] / "uninstall.sh") in r["command"]
    assert installed["exits"] == [installed["main"].EXIT_UNINSTALL]


def test_uninstall_refused_from_network(installed, monkeypatch):
    monkeypatch.setenv("OBSCURA_UNINSTALL_DRYRUN", "1")
    (installed["inst"] / "uninstall.sh").write_text("#!/bin/bash\n")
    installed["c"].post("/api/setup/complete", json={"mode": "office", "admin_username": "boss", "admin_password": PW})
    installed["main"].create_pending_admin()
    rc = remote(installed)
    t = rc.post("/api/auth/login", json={"username": "boss", "password": PW}).json()["token"]
    r = rc.post("/api/system/uninstall", json={"confirm": "UNINSTALL"}, headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 403


def test_uninstall_needs_admin(installed):
    installed["c"].post("/api/setup/complete", json={"mode": "single"})
    assert installed["c"].post("/api/system/uninstall", json={"confirm": "UNINSTALL"}).status_code == 401


# ---- desktop integration ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "darwin", reason="macOS login item")
def test_autostart_plist(tmp_path, monkeypatch):
    import plistlib

    from obscura import desktop
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("OBSCURA_LAUNCH_CMD", json.dumps(["/Applications/Obscura/Obscura.app/Contents/MacOS/Obscura"]))
    assert desktop.set_autostart(True)["ok"]
    pl = plistlib.loads(desktop.autostart_path().read_bytes())
    assert pl["ProgramArguments"][-1] == "--background" and pl["RunAtLoad"] is True
    assert desktop.autostart_enabled()
    desktop.set_autostart(False)
    assert not desktop.autostart_enabled()


def test_autostart_unavailable_from_source(monkeypatch):
    from obscura import desktop
    monkeypatch.delenv("OBSCURA_LAUNCH_CMD", raising=False)
    assert desktop.set_autostart(True)["ok"] is False


# ---- launcher -------------------------------------------------------------------------------------------

def test_launcher_layout_and_env(tmp_path, monkeypatch):
    from obscura import launcher
    inst = tmp_path / "Resources"
    (inst / "models" / "vision").mkdir(parents=True)
    (inst / "tesseract" / "share" / "tessdata").mkdir(parents=True)
    (inst / "tesseract" / "bin").mkdir(parents=True)
    (inst / "tesseract" / "bin" / "tesseract").write_text("")
    lay = launcher.layout(inst)
    assert lay["models"] == inst / "models" and lay["tessdata"] == inst / "tesseract" / "share" / "tessdata"
    monkeypatch.setenv("OBSCURA_HOME_DIR", str(tmp_path / "home"))
    env = launcher.server_env({"models_dir": None}, lay, base={"OBSCURA_DATA": "/dev/data", "PATH": "/bin"})
    assert env["OBSCURA_INSTALLED"] == "1" and env["OBSCURA_BLOCK_NET"] == "1"
    assert env["OBSCURA_MODELS"] == str(inst / "models") and "OBSCURA_DATA" not in env
    assert env["TESSDATA_PREFIX"].endswith("tessdata") and env["OBSCURA_TESSERACT"].endswith("tesseract")
    assert json.loads(env["OBSCURA_LAUNCH_CMD"])


def test_launcher_port_choice():
    import socket

    from obscura import launcher
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    busy = s.getsockname()[1]
    try:
        assert launcher.choose_port(busy) != busy
        assert launcher.health(busy, timeout=0.3) is None
    finally:
        s.close()


def test_launcher_restarts_then_stops_for_uninstall(tmp_path, monkeypatch):
    """The server asks for a restart (code 3), then hands over to the uninstaller (code 4)."""
    from obscura import launcher
    app = tmp_path / "app"
    (app / "obscura").mkdir(parents=True)
    (app / "obscura" / "__init__.py").write_text("")
    marker = tmp_path / "ran"
    (app / "obscura" / "main.py").write_text(textwrap.dedent(f"""
        import pathlib, sys
        m = pathlib.Path({str(marker)!r})
        n = int(m.read_text()) if m.exists() else 0
        m.write_text(str(n + 1))
        sys.exit(3 if n == 0 else 4)
    """))
    monkeypatch.setenv("OBSCURA_HOME_DIR", str(tmp_path / "home"))
    monkeypatch.setenv("OBSCURA_CONFIG", str(tmp_path / "home" / "config.json"))
    lay = {"install_dir": tmp_path, "python": Path(sys.executable), "app_dir": app, "frontend": None, "models": None,
           "tesseract": None, "tessdata": None}
    states = []
    srv = launcher.Server(lay, on_state=lambda s, d="": states.append(s))
    assert srv.supervise() == launcher.EXIT_UNINSTALL
    assert marker.read_text() == "2"
    assert states == ["starting", "restarting", "starting", "uninstalling"]


def test_launcher_gives_up_after_repeated_crashes(tmp_path, monkeypatch):
    from obscura import launcher
    app = tmp_path / "app"
    (app / "obscura").mkdir(parents=True)
    (app / "obscura" / "__init__.py").write_text("")
    (app / "obscura" / "main.py").write_text("raise SystemExit(1)\n")
    monkeypatch.setenv("OBSCURA_HOME_DIR", str(tmp_path / "home"))
    monkeypatch.setenv("OBSCURA_CONFIG", str(tmp_path / "home" / "config.json"))
    lay = {"install_dir": tmp_path, "python": Path(sys.executable), "app_dir": app, "frontend": None, "models": None,
           "tesseract": None, "tessdata": None}
    states = []
    assert launcher.Server(lay, on_state=lambda s, d="": states.append(s)).supervise() == 1
    assert states[-1] == "error" and states.count("starting") == 4


def test_launcher_sigterm_stops_the_server_too(tmp_path, monkeypatch):
    """Logging out / `kill` must never leave the server running without its launcher."""
    import signal
    import subprocess
    import time
    app = tmp_path / "app"
    (app / "obscura").mkdir(parents=True)
    (app / "obscura" / "__init__.py").write_text("")
    (app / "obscura" / "main.py").write_text("import time\nwhile True: time.sleep(0.2)\n")
    real = Path(__file__).resolve().parents[2]
    runner = tmp_path / "run_launcher.py"
    runner.write_text(textwrap.dedent(f"""
        import sys, pathlib
        sys.path.insert(0, {str(real)!r})
        from obscura import launcher
        lay = {{"install_dir": pathlib.Path({str(tmp_path)!r}), "python": pathlib.Path(sys.executable),
               "app_dir": pathlib.Path({str(app)!r}), "frontend": None, "models": None, "tesseract": None,
               "tessdata": None}}
        srv = launcher.Server(lay)
        launcher.install_stop_handlers(srv)
        code = srv.supervise()
        print("supervise returned", code, flush=True)
    """))
    env = {**os.environ, "OBSCURA_HOME_DIR": str(tmp_path / "home"), "OBSCURA_CONFIG": str(tmp_path / "home" / "c.json")}
    proc = subprocess.Popen([sys.executable, str(runner)], env=env, stdout=subprocess.PIPE, text=True)
    running = tmp_path / "home" / "running.json"
    for _ in range(100):
        if running.exists():
            break
        time.sleep(0.1)
    server_pid = json.loads(running.read_text())["server_pid"]
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=30)
    assert "supervise returned 0" in out
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(server_pid, 0)
    assert not running.exists()


def test_setup_restarts_after_models_moved(installed):
    src = installed["tmp"] / "usb" / "models" / "vision"
    src.mkdir(parents=True)
    (src / "w.bin").write_bytes(b"x")
    import obscura.appconfig as ac
    ac.update(models_dir=str(installed["tmp"] / "elsewhere"))
    r = installed["c"].post("/api/setup/complete", json={"mode": "single"}).json()
    assert r["restart"] is True


def test_state_reports_the_running_port(installed):
    installed["cfg"].settings.port = 8620
    try:
        assert installed["c"].get("/api/setup/state").json()["defaults"]["port"] == 8620
    finally:
        installed["cfg"].settings.port = 8600
