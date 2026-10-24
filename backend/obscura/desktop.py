"""Desktop integration for installed copies: native folder picker, start at login, uninstall."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import appconfig

LAUNCH_AGENT = "com.obscura.redaction"


def launch_command() -> list[str] | None:
    """How to start Obscura in the background (set by the launcher of an installed copy)."""
    raw = os.environ.get("OBSCURA_LAUNCH_CMD")
    if not raw:
        return None
    try:
        cmd = json.loads(raw)
        return [str(c) for c in cmd] if isinstance(cmd, list) and cmd else None
    except ValueError:
        return None


# ---- folder picker ------------------------------------------------------------------------------

def pick_folder(prompt: str = "Choose a folder", start: str | None = None, timeout: int = 600) -> str | None:
    """Show this computer's own folder chooser and return the chosen path (None if cancelled)."""
    if sys.platform == "darwin":
        script = f'POSIX path of (choose folder with prompt {json.dumps(prompt)}'
        if start and Path(start).is_dir():
            script += f' default location (POSIX file {json.dumps(start)})'
        script += ")"
        cmd = ["osascript", "-e", script]
    elif sys.platform == "win32":
        # owned by an invisible topmost form: a dialog from the windowless server would otherwise open behind the
        # browser. The chosen path is written as UTF-8 so folder names with accents survive.
        ps = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
              "Add-Type -AssemblyName System.Windows.Forms;"
              "$o = New-Object System.Windows.Forms.Form -Property @{TopMost = $true; ShowInTaskbar = $false};"
              "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
              f"$d.Description = {_ps_quote(prompt)}; $d.ShowNewFolderButton = $true;"
              + (f"$d.SelectedPath = {_ps_quote(start)};" if start else "")
              + "if ($d.ShowDialog($o) -eq [System.Windows.Forms.DialogResult]::OK) { $d.SelectedPath }")
        powershell = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "WindowsPowerShell" / "v1.0"
        cmd = [str(powershell / "powershell.exe"), "-NoProfile", "-NonInteractive", "-STA", "-Command", ps]
    else:
        cmd = ["zenity", "--file-selection", "--directory", f"--title={prompt}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        return None
    return out.rstrip("/\\") or out


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# ---- start at login -----------------------------------------------------------------------------

def autostart_path() -> Path | None:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT}.plist"
    if sys.platform.startswith("linux"):
        return Path.home() / ".config" / "autostart" / "obscura.desktop"
    return None  # Windows: registry Run key


def set_autostart(enabled: bool) -> dict:
    """Start Obscura in the background when this user logs in (or stop doing so)."""
    cmd = launch_command()
    if enabled and not cmd:
        return {"ok": False, "reason": "only available in the installed app"}
    bg = (cmd or []) + ["--background"]
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, "Obscura", 0, winreg.REG_SZ, subprocess.list2cmdline(bg))
            else:
                try:
                    winreg.DeleteValue(k, "Obscura")
                except FileNotFoundError:
                    pass
        return {"ok": True}
    p = autostart_path()
    if not enabled:
        if p and p.exists():
            p.unlink()
        return {"ok": True}
    p.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        import plistlib
        p.write_bytes(plistlib.dumps({"Label": LAUNCH_AGENT, "ProgramArguments": bg, "RunAtLoad": True,
                                      "ProcessType": "Interactive"}))
    else:
        p.write_text("[Desktop Entry]\nType=Application\nName=Obscura\n"
                     f"Exec={shlex.join(bg)}\nX-GNOME-Autostart-enabled=true\n")
    return {"ok": True}


def autostart_enabled() -> bool:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                winreg.QueryValueEx(k, "Obscura")
            return True
        except OSError:
            return False
    p = autostart_path()
    return bool(p and p.exists())


# ---- uninstall ----------------------------------------------------------------------------------

def uninstaller() -> Path | None:
    d = appconfig.install_dir()
    if not d:
        return None
    if sys.platform == "win32":
        # Inno Setup puts unins000.exe in the program folder (next to app\ and runtime\). Never look further up:
        # another program's uninstaller there must not be run.
        return next(iter(sorted(d.glob("unins*.exe"))), None)
    p = d / "uninstall.sh"
    return p if p.exists() else None


def uninstall_command(remove_data: bool, data_dir: Path, wait_pid: int | None = None) -> list[str] | None:
    u = uninstaller()
    if not u:
        return None
    if sys.platform == "win32":
        # /WAITPID: the uninstaller lets the launcher quit by itself before it stops whatever is left (obscura.iss)
        return [str(u), "/SILENT", f"/REMOVEDATA={'1' if remove_data else '0'}"] + (
            [f"/WAITPID={wait_pid}"] if wait_pid else [])
    cmd = ["/bin/bash", str(u), "--yes", "--data-dir", str(data_dir), "--config", str(appconfig.config_path())]
    if wait_pid:
        cmd += ["--wait-pid", str(wait_pid)]
    if remove_data:
        cmd.append("--remove-data")
    return cmd


def run_detached(cmd: list[str]) -> None:
    if os.environ.get("OBSCURA_UNINSTALL_DRYRUN") == "1":
        return
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                "close_fds": True}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)
