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
They stop if the server stops. Call ``panel.jobs.fail_unfinished()`` when
your app starts (one server process) to mark such jobs as failed.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import logging
import threading
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
    """Runs jobs for one panel. ``workers`` threads run at the same time (sync engine)."""

    def __init__(self, panel: "Panel", workers: int = 2) -> None:
        self.panel = panel
        self.workers = workers
        self.handlers: dict[str, Callable] = {}
        self._executor: ThreadPoolExecutor | None = None
        self._futures: set[Future] = set()
        self._tasks: set[asyncio.Task] = set()
        self._lock = threading.Lock()
        from .importexport import run_export_job
        from .actions.background import run_bulk_job

        self.register("bulk_action", run_bulk_job)
        self.register("export", run_export_job)

    def register(self, kind: str, handler: Callable) -> "JobRunner":
        """``handler(job)`` runs the work. It may be a generator: each ``yield`` lets other work run.
        What it returns (a dict) is saved as the job's result."""
        self.handlers[kind] = handler
        return self

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
        )
        ctx.db.add(job)
        ctx.db.commit()
        self.start(job.id)
        return job

    def start(self, job_id: int) -> None:
        if self.panel.is_async:
            loop = asyncio.get_running_loop()  # dispatch runs on the event loop with an async engine
            task = loop.create_task(self._run_async(job_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="tungsten-job")
            future = self._executor.submit(self._run_sync, job_id)
            self._futures.add(future)
        future.add_done_callback(self._futures.discard)

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
        from .models import Job

        db.info["tungsten_panel"] = self.panel
        job = db.get(Job, job_id)
        if job is None or job.status != "queued":
            return None
        job.status = "running"
        job.started_at = _now()
        db.commit()
        return job

    def fail_unfinished(self) -> int:
        """Mark jobs left queued or running by a stopped server as failed. Call it at startup when
        only one server process runs jobs. Returns how many were marked."""
        from sqlalchemy import update

        from .models import Job

        def run(db: Any) -> int:
            result = db.execute(update(Job).where(Job.status.in_(("queued", "running")))
                                .values(status="failed", error="The server stopped before this job finished.",
                                        finished_at=_now()))
            db.commit()
            return result.rowcount or 0

        return self.panel.with_session(run)

    def _finish(self, db: Any, job: "Job", result: Any) -> None:
        job.status = "done"
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
        job.status = "failed"
        job.error = (str(exc).splitlines() or [type(exc).__name__])[0][:500] or type(exc).__name__
        job.finished_at = _now()
        db.commit()
        self._notify_failure(db, job)

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
                return False
            except StopIteration as stop:
                self._finish(sync_db, state["job"], stop.value)
                return True

        return step

    def _run_sync(self, job_id: int) -> None:
        with self.panel.session_factory() as db:
            step = self._step_fn(job_id)
            try:
                while not step(db):
                    pass
            except Exception as exc:  # noqa: BLE001 - recorded on the job
                self._fail(db, job_id, exc)

    async def _run_async(self, job_id: int) -> None:
        await asyncio.sleep(0)  # after the request that started it has answered
        async with self.panel.session_factory() as adb:
            step = self._step_fn(job_id)
            try:
                while not await adb.run_sync(step):
                    await asyncio.sleep(0)
            except Exception as exc:  # noqa: BLE001 - recorded on the job
                await adb.run_sync(lambda db: self._fail(db, job_id, exc))


def chunks(items: list, size: int):
    for i in range(0, len(items), max(1, size)):
        yield items[i:i + size]
