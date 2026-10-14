"""Background jobs: run slow work after the response, then tell the user.

Bulk actions (``BulkAction(...).background()``) and exports
(``ExportAction().background()``) use this. Your own code can too::

    def rebuild_index(job):
        for i, product in enumerate(job.db.scalars(select(Product)), 1):
            index(product)
            if i % 100 == 0:
                job.progress(i)
                yield  # let other work run (needed on an async engine)
        Notification("Search index rebuilt").success().send_to_database(job.user, job.db)

    panel.jobs.register("rebuild-index", rebuild_index)
    panel.jobs.dispatch(ctx, "rebuild-index", name="Rebuild search index")

A job gets its own database session, the user who started it and their
tenant. Jobs run in a small thread pool next to the web server (sync engine)
or as tasks on the event loop (async engine), so they need no extra service.

For long or heavy jobs, ``Panel(jobs="worker")`` makes ``dispatch()`` only queue
them, and ``tungsten jobs:work --panel app.admin:panel`` runs them in their own
process (start as many as you like). A running job writes a heartbeat; a job
whose process stopped (deploy, crash) is queued again by ``panel.jobs.recover()``
while it has tries left (``register(..., max_attempts=3, backoff=30)``), else
marked failed. Several processes are safe: a job is claimed by one at a time.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import logging
import os
import socket
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable

from starlette.requests import Request

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .models import Job
    from .panel import Panel

log = logging.getLogger("tungsten")


def _now() -> dt.datetime:
    return dt.datetime.now()


def background_context(panel: "Panel", db: Any, user_id: str | None, tenant_key: str | None = None,
                       query: str = "") -> "Context":
    """A :class:`Context` for code that runs outside a request: the user is loaded by id and the
    tenant is only set when that user still belongs to it."""
    from .context import Context

    session: dict[str, Any] = {}
    if tenant_key and panel.tenancy.enabled:
        session[panel.tenancy.session_key] = tenant_key
    scope = {
        "type": "http", "method": "GET", "path": panel.path or "/", "root_path": "", "query_string": query.encode(),
        "headers": [], "session": session, "scheme": "http", "server": ("localhost", 80),
    }
    db.info["tungsten_panel"] = panel
    ctx = Context(panel, Request(scope), db)
    if user_id is not None and panel.auth.enabled:
        user = panel.auth.find_by_id(db, user_id)
        ctx.user = user if user is not None and panel.auth.is_active(user) else None
    if ctx.user is not None:
        ctx.tenant = panel.tenancy.resolve(ctx)
    return ctx


class JobContext:
    """What a job handler gets: ``db``, ``ctx``, ``user``, ``tenant``, ``payload`` and ``progress()``."""

    def __init__(self, panel: "Panel", db: Any, job: "Job") -> None:
        self.panel = panel
        self.db = db
        self.job = job
        self.payload: dict[str, Any] = dict(job.payload or {})
        self.ctx = background_context(panel, db, job.user_id, job.tenant_key, self.payload.get("query", ""))
        self.user = self.ctx.user
        self.tenant = self.ctx.tenant

    @property
    def id(self) -> int:
        return self.job.id

    def progress(self, processed: int, total: int | None = None, failed: int | None = None) -> None:
        """Save how far the job is (shown in export history). Commits the session."""
        self.job.processed = processed
        if total is not None:
            self.job.total = total
        if failed is not None:
            self.job.failed = failed
        self.db.commit()


class JobRunner:
    """Runs jobs for one panel. ``workers`` threads run at the same time (sync engine).

    ``mode="thread"`` runs jobs in this process as they are dispatched; ``mode="worker"`` only queues them
    for :meth:`work` (``tungsten jobs:work``)."""

    #: seconds between heartbeats of a running job, and after which a silent job counts as stopped
    heartbeat_seconds = 30
    stale_after = 120

    def __init__(self, panel: "Panel", workers: int = 2, mode: str = "thread") -> None:
        self.panel = panel
        self.workers = workers
        self.mode = mode
        self.handlers: dict[str, Callable] = {}
        self.policies: dict[str, tuple[int, Any]] = {}
        #: who holds a running job: host, process and a random part
        self.worker_id = f"{socket.gethostname()[:40]}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._executor: ThreadPoolExecutor | None = None
        self._futures: set[Future] = set()
        self._tasks: set[asyncio.Task] = set()
        self._running: set[int] = set()
        self._submitted: set[int] = set()
        self._heartbeat: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        from .importexport import run_export_job
        from .actions.background import run_bulk_job

        self.register("bulk_action", run_bulk_job)
        self.register("export", run_export_job)

    def register(self, kind: str, handler: Callable, *, max_attempts: int = 1, backoff: Any = 30) -> "JobRunner":
        """``handler(job)`` runs the work. It may be a generator: each ``yield`` lets other work run.
        What it returns (a dict) is saved as the job's result.

        ``max_attempts`` tries a failed (or stopped) job again, waiting ``backoff`` seconds first: a number,
        a list (one per retry, the last repeats) or ``fn(attempt) -> seconds``."""
        self.handlers[kind] = handler
        self.policies[kind] = (max(1, int(max_attempts)), backoff)
        return self

    def backoff_for(self, kind: str, attempt: int) -> float:
        backoff = self.policies.get(kind, (1, 30))[1]
        if callable(backoff):
            return float(backoff(attempt))
        if isinstance(backoff, (list, tuple)):
            return float(backoff[min(attempt, len(backoff)) - 1]) if backoff else 0.0
        return float(backoff)

    # ------------------------------------------------------------------ dispatch
    def dispatch(self, ctx: "Context", kind: str, payload: dict | None = None, *, name: str = "",
                 total: int | None = None) -> "Job":
        """Save a job for the current user and tenant and start it once the session commits.

        Commits ``ctx.db``. Returns the saved :class:`~tungsten.models.Job`."""
        from .models import Job

        if kind not in self.handlers:
            raise KeyError(f"No job handler registered for {kind!r}")
        panel = self.panel
        job = Job(
            kind=kind, name=name[:255], payload=dict(payload or {}), total=total,
            user_id=panel.auth.user_id(ctx.user) if ctx.user is not None else None,
            tenant_key=panel.tenancy.key_of(ctx.tenant) if ctx.tenant is not None and panel.tenancy.enabled else None,
            max_attempts=self.policies.get(kind, (1, 0))[0], attempts=0,
        )
        ctx.db.add(job)
        ctx.db.commit()
        if self.mode == "thread":
            self.start(job.id)
        return job

    def start(self, job_id: int) -> None:
        if self.panel.is_async:
            loop = asyncio.get_running_loop()  # dispatch runs on the event loop with an async engine
            task = loop.create_task(self._run_async(job_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return
        self._submit(job_id)

    def wait(self, timeout: float | None = 30) -> None:
        """Block until queued jobs finish (sync engine; for tests and scripts)."""
        import concurrent.futures
        import time

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                pending = [f for f in self._futures if not f.done()]
            left = None if deadline is None else deadline - time.monotonic()
            if not pending or (left is not None and left <= 0):
                return
            concurrent.futures.wait(pending, timeout=left)

    async def await_all(self) -> None:
        """Wait for running jobs (async engine; for tests and scripts)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ------------------------------------------------------------------ running
    def _begin(self, db: Any, job_id: int) -> "Job | None":
        """Claim a queued job for this process. Only one process wins (a conditional update)."""
        from sqlalchemy import or_, update

        from .models import Job

        db.info["tungsten_panel"] = self.panel
        now = _now()
        claimed = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued", or_(Job.available_at.is_(None), Job.available_at <= now))
            .values(status="running", started_at=now, heartbeat_at=now, locked_by=self.worker_id,
                    attempts=Job.attempts + 1, finished_at=None)
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()
        if claimed != 1:
            return None
        job = db.get(Job, job_id)
        db.refresh(job)
        with self._lock:
            self._running.add(job_id)
        self._start_heartbeat()
        return job

    # ------------------------------------------------------------------ heartbeat and recovery
    def _start_heartbeat(self) -> None:
        if self.panel.is_async:
            return  # async jobs beat on every step instead
        with self._lock:
            if self._heartbeat is not None and self._heartbeat.is_alive():
                return
            self._heartbeat = threading.Thread(target=self._beat, name="tungsten-job-heartbeat", daemon=True)
            self._heartbeat.start()

    def _beat(self) -> None:
        from sqlalchemy import update

        from .models import Job

        while not self._stop.wait(self.heartbeat_seconds):
            with self._lock:
                running = list(self._running)
            if not running:
                return
            try:
                with self.panel.session_factory() as db:
                    db.execute(update(Job).where(Job.id.in_(running), Job.locked_by == self.worker_id)
                               .values(heartbeat_at=_now()))
                    db.commit()
            except Exception:  # try again on the next beat
                log.exception("Job heartbeat failed")

    def _released(self, job_id: int) -> None:
        with self._lock:
            self._running.discard(job_id)

    def recover(self, stale_after: float | None = None) -> dict[str, int]:
        """Jobs whose process stopped (no heartbeat for ``stale_after`` seconds): queue them again when they
        have tries left, else mark them failed. Jobs other live processes run are left alone, so every
        process may call this at startup. In ``thread`` mode, queued jobs waiting here are started too.
        Returns ``{"requeued": n, "failed": n}``."""
        from sqlalchemy import and_, or_, select, update

        from .models import Job

        cutoff = _now() - dt.timedelta(seconds=self.stale_after if stale_after is None else stale_after)

        def run(db: Any) -> dict[str, int]:
            counts = {"requeued": 0, "failed": 0}
            stale = db.scalars(select(Job).where(Job.status == "running", or_(
                Job.heartbeat_at < cutoff, and_(Job.heartbeat_at.is_(None), Job.started_at < cutoff)))).all()
            for job in stale:
                again = (job.attempts or 0) < (job.max_attempts or 1)
                values: dict[str, Any] = {"locked_by": None}
                if again:
                    values.update(status="queued", available_at=_now(),
                                  error="The server stopped before this job finished; trying again.")
                else:
                    values.update(status="failed", finished_at=_now(),
                                  error="The server stopped before this job finished.")
                done = db.execute(update(Job).where(Job.id == job.id, Job.status == "running",
                                                    Job.heartbeat_at == job.heartbeat_at
                                                    if job.heartbeat_at is not None else Job.heartbeat_at.is_(None))
                                  .values(**values).execution_options(synchronize_session=False)).rowcount
                if done == 1:
                    counts["requeued" if again else "failed"] += 1
            db.commit()
            queued = db.scalars(select(Job.id).where(Job.status == "queued")).all() if self.mode == "thread" else []
            return {**counts, "_queued": list(queued)}

        out = self.panel.with_session(run)
        if self.mode == "thread" and not self.panel.is_async:
            for job_id in out.pop("_queued"):
                self.start(job_id)
        out.pop("_queued", None)
        return out

    def fail_unfinished(self) -> int:
        """Older name for :meth:`recover`: handles jobs a stopped server left behind. Returns how many."""
        out = self.recover()
        return out["requeued"] + out["failed"]

    def retry(self, job_id: int) -> bool:
        """Queue a failed job again (one more try). Returns False when it is not a failed job."""
        from sqlalchemy import update

        from .models import Job

        def run(db: Any) -> bool:
            done = db.execute(update(Job).where(Job.id == job_id, Job.status == "failed").values(
                status="queued", error=None, finished_at=None, available_at=None, locked_by=None,
                max_attempts=Job.attempts + 1)).rowcount
            db.commit()
            return done == 1

        ok = self.panel.with_session(run)
        if ok and self.mode == "thread" and not self.panel.is_async:
            self.start(job_id)
        return ok

    # ------------------------------------------------------------------ worker process
    def work(self, *, once: bool = False, sleep: float = 1.0, stop: threading.Event | None = None) -> int:
        """Run queued jobs until stopped (``tungsten jobs:work``). ``once`` returns when nothing is left.
        Returns how many jobs were started."""
        from sqlalchemy import or_, select

        from .models import Job

        if self.panel.is_async:
            raise RuntimeError("The jobs worker needs a sync database engine (use the sync URL for the worker).")
        stop = stop or self._stop
        started = 0
        last_recover = 0.0
        while not stop.is_set():
            if time.monotonic() - last_recover > self.stale_after / 2:
                self.recover()
                last_recover = time.monotonic()
            with self._lock:
                busy = len([f for f in self._futures if not f.done()])
            free = self.workers - busy
            ids: list[int] = []
            if free > 0:
                def ready(db: Any, limit: int = free) -> list[int]:
                    now = _now()
                    return list(db.scalars(select(Job.id).where(
                        Job.status == "queued", or_(Job.available_at.is_(None), Job.available_at <= now))
                        .order_by(Job.id).limit(limit)))

                with self._lock:
                    in_flight = set(self._submitted)
                ids = [i for i in self.panel.with_session(ready) if i not in in_flight]
                for job_id in ids:
                    self._submit(job_id)
                    started += 1
            if once and not ids and busy == 0:
                self.wait(None)
                with self._lock:
                    if not any(not f.done() for f in self._futures):
                        return started
            if not ids:
                stop.wait(sleep)
        return started

    def _submit(self, job_id: int) -> None:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="tungsten-job")
            future = self._executor.submit(self._run_sync, job_id)
            self._futures.add(future)
            self._submitted.add(job_id)

        def done(f: Future) -> None:
            self._futures.discard(f)
            with self._lock:
                self._submitted.discard(job_id)

        future.add_done_callback(done)

    def _finish(self, db: Any, job: "Job", result: Any) -> None:
        job.status = "done"
        job.locked_by = None
        job.finished_at = _now()
        if isinstance(result, dict):
            job.result = {**(job.result or {}), **result}
        db.commit()

    def _fail(self, db: Any, job_id: int, exc: BaseException) -> None:
        from .models import Job

        log.exception("Background job %s failed", job_id, exc_info=exc)
        db.rollback()
        job = db.get(Job, job_id)
        if job is None:
            return
        job.error = (str(exc).splitlines() or [type(exc).__name__])[0][:500] or type(exc).__name__
        job.locked_by = None
        if (job.attempts or 0) < (job.max_attempts or 1):
            delay = self.backoff_for(job.kind, job.attempts or 1)
            job.status = "queued"
            job.available_at = _now() + dt.timedelta(seconds=delay)
            db.commit()
            self._schedule(job_id, delay)
            return
        job.status = "failed"
        job.finished_at = _now()
        db.commit()
        self._notify_failure(db, job)

    def _schedule(self, job_id: int, delay: float) -> None:
        """Start a retry after its backoff (``thread`` mode; a worker picks it up by itself)."""
        if self.mode != "thread":
            return
        if self.panel.is_async:
            loop = asyncio.get_running_loop()
            loop.call_later(delay, self.start, job_id)
            return
        timer = threading.Timer(delay + 0.01, self.start, args=(job_id,))
        timer.daemon = True
        timer.start()

    def _notify_failure(self, db: Any, job: "Job") -> None:
        from .notifications import Notification

        if job.user_id is None or not self.panel.database_notifications:
            return
        try:
            Notification("Background task failed").body(job.name or job.kind).danger().send_to_database(
                job.user_id, db)
        except Exception:  # noqa: BLE001 - the job is already marked failed
            db.rollback()

    def _step_fn(self, job_id: int) -> Callable[[Any], bool]:
        """A function that runs one piece of the job per call and returns True when it is done."""
        state: dict[str, Any] = {}

        def step(sync_db: Any) -> bool:
            if "gen" not in state:
                job = self._begin(sync_db, job_id)
                if job is None:
                    return True
                state["job"] = job
                result = self.handlers[job.kind](JobContext(self.panel, sync_db, job))
                if not inspect.isgenerator(result):
                    self._finish(sync_db, job, result)
                    return True
                state["gen"] = result
            try:
                next(state["gen"])
            except StopIteration as stop:
                self._finish(sync_db, state["job"], stop.value)
                return True
            job = state["job"]
            now = _now()
            if job.heartbeat_at is None or (now - job.heartbeat_at).total_seconds() >= self.heartbeat_seconds:
                job.heartbeat_at = now
                sync_db.commit()
            return False

        step.state = state  # type: ignore[attr-defined]
        return step

    def _run_sync(self, job_id: int) -> None:
        with self.panel.session_factory() as db:
            step = self._step_fn(job_id)
            try:
                while not step(db):
                    pass
            except Exception as exc:  # noqa: BLE001 - recorded on the job
                self._fail(db, job_id, exc)
            finally:
                if "job" in step.state:  # only the run that claimed the job lets go of it
                    self._released(job_id)

    async def _run_async(self, job_id: int) -> None:
        await asyncio.sleep(0)  # after the request that started it has answered
        async with self.panel.session_factory() as adb:
            step = self._step_fn(job_id)
            try:
                while not await adb.run_sync(step):
                    await asyncio.sleep(0)
            except Exception as exc:  # noqa: BLE001 - recorded on the job
                await adb.run_sync(self._fail, job_id, exc)
            finally:
                if "job" in step.state:
                    self._released(job_id)


def chunks(items: list, size: int):
    for i in range(0, len(items), max(1, size)):
        yield items[i:i + size]
