"""Start Obscura (Windows Start-menu shortcut / start-at-login entry): pythonw.exe obscura_launch.pyw [--background]"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
os.chdir(here)
from obscura import appconfig  # noqa: E402

if sys.stderr is None:  # pythonw has no console: keep errors (a failed start, a traceback) in a log file instead
    try:
        _log = appconfig.app_home() / "launcher.log"
        _log.parent.mkdir(parents=True, exist_ok=True)
        if _log.exists() and _log.stat().st_size > 1_000_000:
            _log.replace(_log.with_suffix(".log.1"))
        sys.stdout = sys.stderr = open(_log, "a", encoding="utf-8", buffering=1)
    except OSError:
        pass

from obscura.launcher import main  # noqa: E402

raise SystemExit(main(sys.argv[1:]))
