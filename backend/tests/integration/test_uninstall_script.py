"""The macOS uninstall script, run for real against a fake installation (fake HOME: nothing real is touched)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "packaging" / "macos" / "uninstall.sh"
pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not SCRIPT.exists(), reason="macOS uninstall script")


@pytest.fixture()
def fake(tmp_path):
    home = tmp_path / "home"
    app = tmp_path / "Applications" / "Obscura" / "Obscura.app"
    res = app / "Contents" / "Resources"
    res.mkdir(parents=True)
    shutil.copy(SCRIPT, res / "uninstall.sh")
    (app.parent / "Uninstall Obscura.app" / "Contents").mkdir(parents=True)
    support = home / "Library" / "Application Support" / "Obscura"
    data = support / "data"
    (data / "keys").mkdir(parents=True)
    (data / "obscura.db").write_text("db")
    (data / "keys" / "master.key").write_text("k")
    (support / "models" / "vision").mkdir(parents=True)
    (support / "config.json").write_text('{"data_dir": "%s"}' % data)
    agent = home / "Library" / "LaunchAgents" / "com.obscura.redaction.plist"
    agent.parent.mkdir(parents=True)
    agent.write_text("<plist/>")
    return {"tmp": tmp_path, "home": home, "app": app, "res": res, "support": support, "data": data, "agent": agent}


def run(fake, *args):
    env = {"HOME": str(fake["home"]), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": str(fake["tmp"]),
           "OBSCURA_UNINSTALL_TEST": "1"}
    return subprocess.run(["/bin/bash", str(fake["res"] / "uninstall.sh"), "--yes", *args], env=env,
                          capture_output=True, text=True, timeout=60)


def test_removes_program_keeps_data(fake):
    assert run(fake).returncode == 0
    assert not fake["app"].parent.exists()             # the whole Obscura folder, incl. the uninstaller app
    assert (fake["data"] / "obscura.db").exists()      # case data kept by default
    assert (fake["support"] / "config.json").exists()  # so a reinstall finds it
    assert not (fake["support"] / "models").exists()   # downloaded models go with the program
    assert not fake["agent"].exists()                  # start-at-login removed


def test_remove_data(fake):
    assert run(fake, "--remove-data").returncode == 0
    assert not fake["data"].exists() and not fake["support"].exists()


def test_data_dir_from_settings_file(fake):
    custom = fake["tmp"] / "Case Files"
    shutil.move(str(fake["data"]), custom)
    (fake["support"] / "config.json").write_text('{"data_dir": "%s"}' % custom)
    assert run(fake, "--remove-data").returncode == 0
    assert not custom.exists()


def test_refuses_to_delete_a_folder_that_is_not_obscura_data(fake):
    other = fake["tmp"] / "Documents"
    other.mkdir()
    (other / "taxes.xlsx").write_text("keep me")
    assert run(fake, "--remove-data", "--data-dir", str(other)).returncode == 0
    assert (other / "taxes.xlsx").exists()


@pytest.mark.parametrize("bad", ["/", "HOME"])
def test_refuses_dangerous_paths(fake, bad):
    target = str(fake["home"]) if bad == "HOME" else "/"
    (fake["home"] / "precious.txt").write_text("x")
    run(fake, "--remove-data", "--data-dir", target)
    assert (fake["home"] / "precious.txt").exists()


def test_keys_are_deleted_before_data(fake):
    """Even if deleting the data folder were interrupted, the keys are already gone."""
    text = SCRIPT.read_text()
    assert text.index('rm -rf "$DATA/keys"') < text.index('rm -rf "$DATA"\n')
