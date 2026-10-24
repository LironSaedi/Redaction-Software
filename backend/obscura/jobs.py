"""Background job runner (thread pool) with progress persisted in the database."""
from __future__ import annotations

import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .config import settings
from .db import Job, tx, utcnow

log = logging.getLogger("obscura.jobs")
_pool: ThreadPoolExecutor | None = None
_cancel: set[int] = set()
_lock = threading.Lock()


def pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=max(1, settings.workers), thread_name_prefix="obscura-job")
    return _pool


class JobContext:
    def __init__(self, job_id: int):
        self.job_id = job_id
        self._last = 0.0

    def progress(self, frac: float, message: str | None = None) -> None:
        if self.job_id in _cancel:
            raise JobCancelled()
        frac = max(0.0, min(1.0, frac))
        if frac - self._last < 0.01 and message is None:
            return
        self._last = frac
        with tx() as s:
            j = s.get(Job, self.job_id)
            if j:
                j.progress = frac
                if message is not None:
                    j.message = message

    def stage(self, lo: float, hi: float, message: str | None = None):
        """Progress callback mapping (done, total) into [lo, hi] of the overall job."""
        if message:
            self.progress(lo, message)

        def cb(done, total):
            self.progress(lo + (hi - lo) * (done / total if total else 1.0))
        return cb


class JobCancelled(Exception):
    pass


def submit(kind: str, fn: Callable[[JobContext], dict], file_id: int | None = None, case_id: int | None = None,
           params: dict | None = None, user_id: int | None = None) -> int:
    with tx() as s:
        j = Job(kind=kind, file_id=file_id, case_id=case_id, params=params or {}, created_by=user_id)
        s.add(j)
        s.flush()
        jid = j.id

    def run():
        with tx() as s:
            j = s.get(Job, jid)
            j.status, j.started_at = "running", utcnow()
        ctx = JobContext(jid)
        try:
            result = fn(ctx) or {}
            with tx() as s:
                j = s.get(Job, jid)
                j.status, j.progress, j.result, j.finished_at = "done", 1.0, result, utcnow()
                j.message = j.message or "done"
        except JobCancelled:
            with tx() as s:
                j = s.get(Job, jid)
                j.status, j.finished_at, j.message = "cancelled", utcnow(), "cancelled"
        except Exception as e:  # noqa: BLE001
            log.error("job %s failed: %s\n%s", jid, e, traceback.format_exc())
            with tx() as s:
                j = s.get(Job, jid)
                j.status, j.finished_at, j.message = "error", utcnow(), f"{type(e).__name__}: {e}"[:2000]
        finally:
            _cancel.discard(jid)

    pool().submit(run)
    return jid


def cancel(job_id: int) -> None:
    _cancel.add(job_id)


def run_inline(fn: Callable[[JobContext], dict]) -> dict:
    """Run a job body synchronously (tests, watcher)."""
    class _Ctx(JobContext):
        def __init__(self):
            super().__init__(-1)

        def progress(self, frac, message=None):
            pass
    return fn(_Ctx())


def recover_interrupted() -> int:
    """After a restart (or a crash) no job from the previous process is still running: mark them failed and put
    their files back in a usable state, so nothing shows as "analyzing" forever."""
    from .db import File
    n = 0
    with tx() as s:
        for j in s.query(Job).filter(Job.status.in_(("queued", "running"))).all():
            j.status, j.error, j.finished_at = "error", "interrupted by a server restart — run it again", utcnow()
            n += 1
        for f in s.query(File).filter(File.status.in_(("analyzing", "exporting", "queued"))).all():
            f.status = "ready" if f.detections_blob else "uploaded"
    if n:
        log.warning("marked %d interrupted job(s) as failed", n)
    return n
