"""Desktop launcher for installed copies of Obscura.

Starts the local server, opens Obscura in the browser and keeps a small control window open (Open · Stop · Uninstall).
Nothing here talks to the internet: the browser connects to this computer only.

    Obscura                    normal start (control window)
    Obscura --background       start-at-login mode: no window, no browser
    Obscura --uninstall        show the uninstall dialog (Start menu "Uninstall Obscura")
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import appconfig, desktop

EXIT_RESTART, EXIT_UNINSTALL = 3, 4
APP_DIR = Path(__file__).resolve().parent.parent           # …/app (holds obscura/, frontend/, scripts/)


# ---- install layout -----------------------------------------------------------------------------

def layout(install_dir: Path | None = None) -> dict:
    """Paths of the installed program. ``install_dir`` holds runtime/, app/, models/ (optional) and tesseract/."""
    inst = install_dir or Path(os.environ.get("OBSCURA_INSTALL_DIR") or APP_DIR.parent)
    win = sys.platform == "win32"
    rt = inst / "runtime"
    py = rt / ("pythonw.exe" if win else "bin/python3")
    # Windows: the server runs as console python.exe in a hidden console (CREATE_NO_WINDOW), so the console tools it
    # starts (ffmpeg, tesseract, the transcription worker) share that console instead of each flashing a window
    server_py = rt / "python.exe" if win else py
    tess_root = inst / "tesseract"
    tess = tess_root / ("tesseract.exe" if win else "bin/tesseract")
    tessdata = next((p for p in (tess_root / "tessdata", tess_root / "share" / "tessdata") if p.is_dir()), None)
    return {"install_dir": inst, "python": py if py.exists() else Path(sys.executable),
            "server_python": server_py if server_py.exists() else None, "app_dir": inst / "app"
            if (inst / "app" / "obscura").is_dir() else APP_DIR, "frontend": next(
                (p for p in (inst / "app" / "frontend", APP_DIR / "frontend", APP_DIR.parent / "frontend" / "dist")
                 if (p / "index.html").exists()), None),
            "models": inst / "models" if (inst / "models").is_dir() else None,
            "tesseract": tess if tess.exists() else None, "tessdata": tessdata,
            "uninstaller": inst / "uninstall.sh"}


def ensure_config() -> dict:
    p = appconfig.config_path()
    cfg = appconfig.load()
    if not p.exists():
        appconfig.save(cfg)
    return cfg


def server_env(cfg: dict, lay: dict, base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    models = cfg.get("models_dir") or (str(lay["models"]) if lay["models"] else str(appconfig.app_home() / "models"))
    env.update({
        "OBSCURA_INSTALLED": "1",
        "OBSCURA_INSTALL_DIR": str(lay["install_dir"]),
        "OBSCURA_CONFIG": str(appconfig.config_path()),
        "OBSCURA_MODELS": models,
        "OBSCURA_BLOCK_NET": env.get("OBSCURA_BLOCK_NET", "1"),  # privacy: the server never connects out
        "OBSCURA_LAUNCHER_PID": str(os.getpid()),
        "OBSCURA_LAUNCH_CMD": json.dumps(launch_cmd(lay)),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    if lay["frontend"]:
        env["OBSCURA_FRONTEND"] = str(lay["frontend"])
    if lay["tesseract"]:
        env["OBSCURA_TESSERACT"] = str(lay["tesseract"])
    if lay["tessdata"]:
        env["TESSDATA_PREFIX"] = str(lay["tessdata"])
    # never inherit settings meant for a developer checkout
    for k in ("OBSCURA_DATA", "OBSCURA_HOST", "OBSCURA_PORT", "OBSCURA_REQUIRE_LOGIN"):
        env.pop(k, None)
    return env


def launch_cmd(lay: dict) -> list[str]:
    """The command that starts this launcher (used for start-at-login)."""
    exe = os.environ.get("OBSCURA_LAUNCHER_EXE")
    if exe:
        return [exe]
    script = Path(lay["app_dir"]) / "obscura_launch.pyw"
    if script.exists():  # works from any working directory (Windows Run key, shortcuts)
        return [str(lay["python"]), str(script)]
    return [str(lay["python"]), "-m", "obscura.launcher"]


def running_file() -> Path:
    """Process ids of a running Obscura, for the uninstaller (it must stop Obscura before deleting files)."""
    return appconfig.app_home() / "running.json"


def _write_running(server_pid: int | None, port: int) -> None:
    try:
        running_file().parent.mkdir(parents=True, exist_ok=True)
        running_file().write_text(json.dumps({"launcher_pid": os.getpid(), "server_pid": server_pid, "port": port}))
    except OSError:
        pass


def _clear_running() -> None:
    try:
        running_file().unlink()
    except OSError:
        pass


# ---- server process -----------------------------------------------------------------------------

def health(port: int, timeout: float = 1.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            data = json.loads(r.read().decode())
            return data if data.get("ok") else None
    except (OSError, ValueError):
        return None


def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if sys.platform != "win32":  # on Windows SO_REUSEADDR lets a bind succeed even while another program listens
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def choose_port(preferred: int) -> int:
    for p in [preferred] + list(range(preferred + 1, preferred + 40)):
        if port_free(p):
            return p
    raise RuntimeError("no free port for Obscura")


def log_file(cfg: dict) -> Path:
    d = Path(cfg.get("data_dir") or appconfig.app_home() / "data") / "logs"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "server.log"
    if f.exists() and f.stat().st_size > 5_000_000:
        f.replace(d / "server.log.1")
    return f


class Server:
    """Runs ``python -m obscura.main`` and restarts it when it asks to (new settings)."""

    def __init__(self, lay: dict, on_state=None):
        self.lay = lay
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.on_state = on_state or (lambda state, detail="": None)
        self.stopping = False
        self.exit_code: int | None = None
        self._log = None

    def start(self) -> None:
        cfg = ensure_config()
        preferred = int(cfg.get("port") or appconfig.DEFAULT_PORT)
        self.port = choose_port(preferred)
        if self.port != preferred:
            appconfig.update(port=self.port)
            cfg["port"] = self.port
        host = cfg.get("host") or "127.0.0.1"
        env = server_env(cfg, self.lay)
        self._log = open(log_file(cfg), "a", encoding="utf-8")
        flags = 0
        if sys.platform == "win32":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        py = self.lay.get("server_python") or self.lay["python"]
        self.proc = subprocess.Popen([str(py), "-m", "obscura.main", "--host", host, "--port",
                                      str(self.port)], cwd=str(self.lay["app_dir"]), env=env, stdout=self._log,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)
        _write_running(self.proc.pid, self.port)
        self.on_state("starting")

    def wait_ready(self, timeout: float = 180) -> bool:
        t = time.time()
        while time.time() - t < timeout:
            if self.proc and self.proc.poll() is not None:
                return False
            if health(self.port):
                self.on_state("running")
                return True
            time.sleep(0.4)
        return False

    def stop(self, timeout: float = 15) -> None:
        self.stopping = True
        p = self.proc
        if p and p.poll() is None:
            try:
                if sys.platform == "win32":
                    # the windowless launcher shares no console with the server, so Ctrl+Break cannot reach it; end
                    # the server together with the processes it started (transcription worker, ffmpeg, tesseract)
                    taskkill = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "taskkill.exe"
                    subprocess.run([str(taskkill), "/PID", str(p.pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                                   capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    p.terminate()
                p.wait(timeout)
            except (OSError, subprocess.SubprocessError):
                p.kill()
        if self._log:
            self._log.close()
            self._log = None
        _clear_running()

    def supervise(self) -> int:
        """Keep the server running. Returns the reason it finally stopped (0, EXIT_UNINSTALL or an error code)."""
        try:
            return self._supervise()
        finally:
            _clear_running()

    def _supervise(self) -> int:
        crashes: list[float] = []
        while True:
            if not self.proc:
                self.start()
                if not self.wait_ready():
                    if self.proc.poll() is None:
                        self.on_state("error", "Obscura did not start in time — see the log file")
            code = self.proc.wait()
            self.proc = None
            if self._log:
                self._log.close()
                self._log = None
            if self.stopping:
                return 0
            if code == EXIT_RESTART:
                self.on_state("restarting")
                continue
            if code == EXIT_UNINSTALL:
                self.on_state("uninstalling")
                return EXIT_UNINSTALL
            crashes = [t for t in crashes if time.time() - t < 300] + [time.time()]
            if len(crashes) > 3:
                self.on_state("error", f"Obscura stopped unexpectedly (code {code}) — see the log file")
                return code or 1
            self.on_state("restarting", "recovering from an unexpected stop")


def install_stop_handlers(server: "Server", on_stop=None) -> None:
    """Quit cleanly on SIGTERM / SIGINT / SIGHUP (logout, `kill`, Ctrl-C): stop the server too, never orphan it.
    The handler only flags and signals; the supervising loop sees the server exit and returns."""
    import signal

    def handler(signum, frame):
        server.stopping = True
        p = server.proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass
        if on_stop:
            on_stop()
    for name in ("SIGTERM", "SIGINT", "SIGHUP", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError):
                pass


# ---- uninstall ----------------------------------------------------------------------------------

def run_uninstall(remove_data: bool, wait_pid: int | None = None) -> bool:
    cfg = appconfig.load()
    cmd = desktop.uninstall_command(remove_data, Path(cfg.get("data_dir") or appconfig.app_home() / "data"),
                                    wait_pid=wait_pid)
    if not cmd:
        return False
    desktop.run_detached(cmd)
    return True


# ---- control window -----------------------------------------------------------------------------

def _gui(server: Server, open_browser: bool, uninstall_only: bool = False) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Obscura.RedactionStudio")
        except Exception:
            pass
    root = tk.Tk()
    root.title("Obscura Redaction Studio")
    root.resizable(False, False)
    ico = server.lay["install_dir"] / "obscura.ico"
    if sys.platform == "win32" and ico.exists():
        root.iconbitmap(str(ico))
    style = ttk.Style(root)
    for theme in ("aqua", "vista", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break
    BG, INK, MUTED, ACCENT = "#0f172a", "#f8fafc", "#94a3b8", "#6366f1"
    root.configure(bg=BG)
    frame = tk.Frame(root, bg=BG, padx=28, pady=22)
    frame.pack(fill="both", expand=True)
    head = tk.Frame(frame, bg=BG)
    head.pack(fill="x")
    logo = tk.Canvas(head, width=44, height=44, bg=BG, highlightthickness=0)
    logo.create_oval(2, 2, 42, 42, fill=ACCENT, outline="")
    logo.create_rectangle(12, 18, 32, 26, fill=INK, outline="")
    logo.pack(side="left")
    titles = tk.Frame(head, bg=BG, padx=12)
    titles.pack(side="left")
    tk.Label(titles, text="Obscura", font=("Helvetica", 18, "bold"), fg=INK, bg=BG).pack(anchor="w")
    tk.Label(titles, text="Redaction Studio · runs on this computer", font=("Helvetica", 11), fg=MUTED,
             bg=BG).pack(anchor="w")
    status = tk.StringVar(value="Starting…")
    detail = tk.StringVar(value="Loading — the first start can take a minute.")
    tk.Label(frame, textvariable=status, font=("Helvetica", 13, "bold"), fg=INK, bg=BG, pady=4).pack(anchor="w",
                                                                                                     pady=(18, 0))
    tk.Label(frame, textvariable=detail, font=("Helvetica", 11), fg=MUTED, bg=BG, wraplength=380,
             justify="left").pack(anchor="w")
    buttons = tk.Frame(frame, bg=BG, pady=16)
    buttons.pack(fill="x")
    url = lambda: f"http://127.0.0.1:{server.port}/"  # noqa: E731
    open_btn = ttk.Button(buttons, text="Open Obscura", command=lambda: webbrowser.open(url()), state="disabled")
    open_btn.pack(side="left")
    links = tk.Frame(frame, bg=BG)
    links.pack(fill="x")

    def link(text, cmd):
        lab = tk.Label(links, text=text, fg="#a5b4fc", bg=BG, cursor="hand2", font=("Helvetica", 11, "underline"))
        lab.bind("<Button-1>", lambda e: cmd())
        lab.pack(side="left", padx=(0, 16))

    def show_data():
        d = Path(appconfig.load().get("data_dir") or appconfig.app_home() / "data")
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(d)])
        elif sys.platform == "win32":
            os.startfile(str(d))  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(d)])

    def uninstall_dialog():
        win = tk.Toplevel(root)
        win.title("Uninstall Obscura")
        win.configure(bg=BG)
        win.resizable(False, False)
        body = tk.Frame(win, bg=BG, padx=24, pady=20)
        body.pack()
        tk.Label(body, text="Remove Obscura from this computer?", font=("Helvetica", 14, "bold"), fg=INK,
                 bg=BG).pack(anchor="w")
        tk.Label(body, text="The program and its AI models are removed. Your case files are kept unless you tick "
                            "the box below.", wraplength=360, justify="left", fg=MUTED, bg=BG,
                 font=("Helvetica", 11)).pack(anchor="w", pady=(6, 10))
        wipe = tk.BooleanVar(value=False)
        tk.Checkbutton(body, text="Also permanently delete all case files, exports and settings", variable=wipe,
                       fg=INK, bg=BG, selectcolor=BG, activebackground=BG, activeforeground=INK).pack(anchor="w")
        row = tk.Frame(body, bg=BG, pady=14)
        row.pack(fill="x")

        def go():
            if wipe.get() and not messagebox.askyesno(
                    "Delete case files?", "All case files, exports, the audit log and the encryption keys will be "
                                          "deleted. This cannot be undone. Continue?", parent=win, icon="warning"):
                return
            status.set("Uninstalling…")
            server.stop()
            if not run_uninstall(wipe.get(), wait_pid=os.getpid()):
                messagebox.showerror("Uninstall", "This copy of Obscura was not installed with the installer — "
                                                  "delete its folder to remove it.", parent=win)
                return
            root.after(200, root.destroy)
        ttk.Button(row, text="Uninstall", command=go).pack(side="right")
        ttk.Button(row, text="Cancel", command=win.destroy).pack(side="right", padx=8)
        win.transient(root)
        win.grab_set()

    def quit_app():
        if server.proc and messagebox.askokcancel(
                "Stop Obscura", "Stop Obscura? Anyone using it in a browser will be disconnected.", parent=root):
            status.set("Stopping…")
            root.update()
            server.stop()
            root.destroy()
        elif not server.proc:
            root.destroy()

    ttk.Button(buttons, text="Stop and quit", command=quit_app).pack(side="left", padx=10)
    link("Open data folder", show_data)
    link("Uninstall…", uninstall_dialog)
    root.protocol("WM_DELETE_WINDOW", quit_app)
    if sys.platform == "darwin":
        root.createcommand("::tk::mac::Quit", quit_app)  # Obscura › Quit / ⌘Q asks the same way
    install_stop_handlers(server, on_stop=lambda: root.after(0, root.destroy))  # logout / kill: close quietly

    state_text = {"starting": ("Starting…", "Loading — the first start can take a minute."),
                  "running": ("Obscura is running", "Your files never leave this computer. Keep this window "
                                                    "open while you work; close it to stop Obscura."),
                  "restarting": ("Restarting…", "Applying new settings."),
                  "uninstalling": ("Uninstalling…", "Obscura is being removed."),
                  "error": ("Obscura stopped", "")}
    first_run = {"opened": False}

    def on_state(state, extra=""):
        def apply():
            title, text = state_text.get(state, (state, ""))
            status.set(title)
            detail.set(extra or text)
            open_btn.configure(state="normal" if state == "running" else "disabled")
            if state == "running" and open_browser and not first_run["opened"]:
                first_run["opened"] = True
                webbrowser.open(url())
            if state == "uninstalling":
                root.after(500, root.destroy)
        root.after(0, apply)
    server.on_state = on_state
    if uninstall_only:
        root.after(100, uninstall_dialog)
    else:
        threading.Thread(target=server.supervise, daemon=True).start()
    root.mainloop()
    server.stop()
    return 0


# ---- entry point --------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="Obscura")
    ap.add_argument("--background", action="store_true", help="no window, no browser (start at login)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--uninstall", action="store_true", help="show the uninstall dialog")
    ap.add_argument("--headless", action="store_true", help="no window even when one could be shown")
    args, _ = ap.parse_known_args(argv)
    lay = layout()
    os.environ.setdefault("OBSCURA_INSTALL_DIR", str(lay["install_dir"]))  # the uninstaller is found from here
    cfg = ensure_config()
    port = int(cfg.get("port") or appconfig.DEFAULT_PORT)
    if args.uninstall:
        return _gui(Server(lay), open_browser=False, uninstall_only=True)
    running = health(port)
    if running:  # already running (start at login, or a second click on the icon): just show it
        if not (args.background or args.no_browser):
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return 0
    server = Server(lay)
    if args.background or args.headless:
        if not args.background and not args.no_browser:
            server.on_state = lambda s, d="": webbrowser.open(f"http://127.0.0.1:{server.port}/") if s == "running" \
                else None
        install_stop_handlers(server)
        try:
            code = server.supervise()
        except KeyboardInterrupt:
            server.stop()
            code = 0
        server.stop()
        return 0 if code == EXIT_UNINSTALL else code
    try:
        return _gui(server, open_browser=not args.no_browser)
    except ImportError:  # no Tk on this system: run without a window
        return main((argv or []) + ["--headless"])


if __name__ == "__main__":
    raise SystemExit(main())
