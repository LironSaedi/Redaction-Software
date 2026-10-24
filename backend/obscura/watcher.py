"""Watcher: hands-free redaction of files dropped into a folder.

Every new file that appears in a watched input folder is ingested into the watcher's case, analysed
with its preset, exported, and the redacted file plus its redaction log are written to the output
folder. Nothing leaves the machine.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from .audit import record
from .db import Export, File, Preset, Watcher, tx
from .jobs import run_inline
from .processing import KIND_BY_EXT, analyze_file, export_file, ingest
from .storage import get_storage

log = logging.getLogger("obscura.watcher")


class WatchService:
    def __init__(self, interval: float = 5.0):
        self.interval = interval
        self.seen: dict[int, set[str]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="obscura-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as e:  # noqa: BLE001
                log.error("watcher error: %s", e)
            self._stop.wait(self.interval)

    def scan_once(self) -> int:
        processed = 0
        with tx() as s:
            watchers = [(w.id, w.input_dir, w.output_dir, w.case_id, w.preset_id, dict(w.export_settings or {}))
                        for w in s.query(Watcher).filter_by(enabled=True).all()]
            presets = {p.id: dict(p.settings or {}) for p in s.query(Preset).all()}
        for wid, ind, outd, case_id, preset_id, export_settings in watchers:
            inp, out = Path(ind), Path(outd)
            if not inp.is_dir():
                continue
            out.mkdir(parents=True, exist_ok=True)
            seen = self.seen.setdefault(wid, set(p.name for p in (out / ".processed").glob("*")) if
                                        (out / ".processed").exists() else set())
            for p in sorted(inp.iterdir()):
                if not p.is_file() or p.name.startswith(".") or p.name in seen:
                    continue
                if p.suffix.lower().lstrip(".") not in KIND_BY_EXT:
                    continue
                if not _stable(p):
                    continue
                seen.add(p.name)
                try:
                    self._process(wid, p, out, case_id, presets.get(preset_id, {}), export_settings)
                    processed += 1
                except Exception as e:  # noqa: BLE001
                    log.error("watcher %s failed on %s: %s", wid, p.name, e)
                    record("watcher_failed", None, "watcher", wid, case_id, {"error": str(e)[:300]})
                marker = out / ".processed"
                marker.mkdir(exist_ok=True)
                (marker / p.name).touch()
        return processed

    def _process(self, wid: int, src: Path, out: Path, case_id: int, preset: dict, export_settings: dict) -> None:
        ids = ingest(case_id, src, src.name, None)
        record("watcher_ingested", None, "watcher", wid, case_id, {"files": ids})
        for fid in ids:
            run_inline(lambda ctx: analyze_file(fid, preset, ctx))
            res = run_inline(lambda ctx: export_file(fid, export_settings, None, ctx))
            with tx() as s:
                ex = s.get(Export, res["export_id"])
                f = s.get(File, fid)
                st = get_storage()
                dest = out / ex.name
                with open(dest, "wb") as fh:
                    for chunk in st.stream(ex.blob):
                        fh.write(chunk)
                if ex.log_blob:
                    (out / (Path(ex.name).stem + "_redaction_log.csv")).write_bytes(st.get_bytes(ex.log_blob))
                if not ex.verified:
                    (out / (Path(ex.name).stem + "_VERIFICATION_FAILED.txt")).write_text(
                        "Automatic verification found possible leaks. Review this file in Obscura before release.\n")
                record("watcher_exported", None, "file", fid, f.case_id, {"export": ex.id, "verified": ex.verified})


def _stable(p: Path, wait: float = 1.0) -> bool:
    """Skip files that are still being copied in."""
    try:
        a = p.stat().st_size
        time.sleep(wait)
        return a == p.stat().st_size and a > 0
    except OSError:
        return False


SERVICE = WatchService()
