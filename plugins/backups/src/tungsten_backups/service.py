"""Running backups: one at a time, in the background, with clean failure and old ones pruned."""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .engine import (
    BackupError,
    database_size,
    folder_size,
    free_space,
    human_size,
    sha256_of,
    verify_backup,
    write_backup,
)
from .models import DONE, FAILED, RUNNING, Backup

log = logging.getLogger("tungsten.backups")

KINDS = {"database": "Database", "full": "Database and files"}


class Busy(BackupError):
    """Another backup is running."""


def detach(db: Any, row: Backup | None) -> Backup | None:
    """Load every column and let the row outlive its session (the app's session may expire on commit)."""
    if row is not None:
        db.refresh(row)
        db.expunge(row)
    return row


def with_db(plugin: Any, fn: Any) -> Any:
    """``panel.with_session(fn)``, also from inside a running event loop (async panels run actions there)."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return plugin.panel.with_session(fn)
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = plugin.panel.with_session(fn)
        except BaseException as exc:  # noqa: BLE001 - handed back to the caller below
            box["error"] = exc

    worker = threading.Thread(target=run, name="tungsten-backup-db")
    worker.start()
    worker.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


# ====================================================================== the folder
DENY = "# Backups hold all your data. Never serve this folder.\nRequire all denied\nDeny from all\n"


def prepare_folder(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    try:
        folder.chmod(0o700)
    except OSError:  # pragma: no cover - some file systems ignore it
        pass
    deny = folder / ".htaccess"
    if not deny.exists():
        deny.write_text(DENY)


def file_of(plugin: Any, backup: Backup) -> Path | None:
    """The backup's file, only when it really sits inside the backups folder."""
    name = backup.name or ""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    path = (plugin.folder / name).resolve()
    if path.parent != plugin.folder.resolve():
        return None
    return path


def new_name(plugin: Any, kind: str) -> str:
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    prefix = re.sub(r"[^a-z0-9]+", "-", (plugin.prefix or "backup").lower()).strip("-") or "backup"
    name = f"{prefix}-{stamp}-{kind}.zip"
    while (plugin.folder / name).exists():
        name = f"{prefix}-{stamp}-{kind}-{secrets.token_hex(2)}.zip"
    return name


# ====================================================================== one at a time
class Lock:
    """A lock file in the backups folder, so two workers or servers never back up at once."""

    #: the lock file is touched this often while a backup runs; one untouched for 10 minutes is left over
    HEARTBEAT = 60

    def __init__(self, folder: Path, stale_after: float = 600) -> None:
        self.path = folder / ".lock"
        self.stale_after = stale_after
        self.held = False
        self._stop = threading.Event()
        self._beat: threading.Thread | None = None

    def keep_alive(self) -> None:
        """Touch the lock file while the backup runs, so a long backup is never taken for a crashed one."""
        def beat() -> None:
            while not self._stop.wait(self.HEARTBEAT):
                try:
                    os.utime(self.path)
                except OSError:
                    return

        self._beat = threading.Thread(target=beat, name="tungsten-backup-lock", daemon=True)
        self._beat.start()

    def acquire(self) -> None:
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > self.stale_after:  # left behind by a crash
                    self.path.unlink(missing_ok=True)
                    continue
                raise Busy("A backup is already running. Wait for it to finish.") from None
            with os.fdopen(fd, "w") as fh:
                fh.write(f"{os.getpid()} {dt.datetime.now().isoformat()}\n")
            self.held = True
            return
        raise Busy("A backup is already running. Wait for it to finish.")

    def release(self) -> None:
        self._stop.set()
        if self.held:
            self.path.unlink(missing_ok=True)
            self.held = False


def _clean_leftovers(folder: Path) -> None:
    """Half-written files from a crash. Only called while holding the lock."""
    for item in folder.iterdir():
        if item.name.endswith(".part") or item.name.startswith((".work-", ".verify-")):
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)


# ====================================================================== running one
def start_backup(plugin: Any, *, kind: str = "database", note: str | None = None, user_id: str | None = None,
                 source: str = "panel", background: bool | None = None) -> Backup:
    """Start a backup and return its row. Raises :class:`BackupError` when it can't start.

    With ``background=True`` the row comes back while the backup is still ``running``."""
    if kind not in KINDS:
        raise BackupError(f"Unknown backup kind {kind!r}. Use one of: {', '.join(KINDS)}.")
    if plugin.panel is None or plugin.panel.session_factory is None:
        raise BackupError("The panel has no database to back up.")
    background = plugin.background if background is None else background
    prepare_folder(plugin.folder)
    lock = Lock(plugin.folder)
    lock.acquire()
    try:
        _clean_leftovers(plugin.folder)
        folders = plugin.folders() if kind == "full" else {}
        _check_space(plugin, folders)
        name = new_name(plugin, kind)

        def create(db: Any) -> Backup:
            for stale in db.scalars(select(Backup).where(Backup.status == RUNNING)).all():
                stale.status = FAILED
                stale.error = "Stopped before it finished (the app restarted or crashed)."
                stale.finished_at = dt.datetime.now()
            row = Backup(name=name, kind=kind, status=RUNNING, note=(note or "").strip()[:300] or None,
                         source=source, user_id=user_id, details={})
            db.add(row)
            db.commit()
            return detach(db, row)

        row = with_db(plugin, create)
    except BaseException:
        lock.release()
        raise
    worker = threading.Thread(target=_run, args=(plugin, row.id, name, kind, folders, lock),
                              name=f"tungsten-backup-{row.id}", daemon=True)
    worker.start()
    if not background:
        worker.join()
        return with_db(plugin, lambda db: detach(db, db.get(Backup, row.id)))
    return row


def _check_space(plugin: Any, folders: dict[str, Path]) -> None:
    need = database_size(plugin.engine()) * 2  # the copy, then the zip
    for path in folders.values():
        if path.is_dir():
            need += folder_size(path, skip=[plugin.folder])[0]
    need += plugin.min_free_mb * 1024 * 1024
    free = free_space(plugin.folder)
    if free < need:
        raise BackupError(f"Not enough disk space: {human_size(free)} free, the backup needs about "
                          f"{human_size(need)} (including {plugin.min_free_mb} MB kept free). "
                          f"Delete old backups or free some space.")


def _run(plugin: Any, backup_id: int, name: str, kind: str, folders: dict[str, Path], lock: Lock) -> None:
    started = time.monotonic()
    lock.keep_alive()
    try:
        try:
            manifest = write_backup(plugin.folder / name, plugin.engine(), folders=folders, skip=[plugin.folder],
                                    use_tools=plugin.use_tools, timeout=plugin.timeout,
                                    extra={"kind": kind, "app": plugin.panel.brand_name})
            path = plugin.folder / name
            try:
                path.chmod(0o600)
            except OSError:  # pragma: no cover
                pass
            digest = sha256_of(path)
            size = path.stat().st_size
            error = None
        except BackupError as exc:
            manifest, error = None, str(exc)
        except Exception as exc:
            log.exception("Backup %s failed", name)
            manifest, error = None, f"Unexpected error: {type(exc).__name__}: {exc}"

        def finish(db: Any) -> Backup | None:
            row = db.get(Backup, backup_id)
            if row is None:  # deleted while running: don't leave an orphan file
                (plugin.folder / name).unlink(missing_ok=True)
                return None
            row.finished_at = dt.datetime.now()
            if manifest is None:
                row.status, row.error = FAILED, error
            else:
                tables = manifest["database"]["tables"] or {}
                row.status, row.error = DONE, None
                row.method = manifest["database"]["method"]
                row.size, row.sha256 = size, digest
                row.tables, row.rows = len(tables), sum(tables.values())
                row.files = manifest["files"]["count"]
                row.details = {"note": manifest["database"]["note"], "skipped": manifest["files"]["skipped"][:50],
                               "skipped_count": len(manifest["files"]["skipped"]),
                               "folders": manifest["files"]["folders"],
                               "seconds": round(time.monotonic() - started, 1)}
            db.commit()
            return detach(db, row)

        row = with_db(plugin, finish)
        if row is None:
            return
        if row.status == DONE:
            try:
                with_db(plugin, lambda db: prune(plugin, db))
            except Exception:
                log.exception("Could not delete old backups")
        _notify(plugin, row)
        for fn in list(plugin._on_backup):
            try:
                fn(row, plugin)
            except Exception:
                log.exception("Backup hook %r failed", fn)
    except Exception:
        log.exception("Backup %s could not be saved", name)
    finally:
        lock.release()


def _notify(plugin: Any, row: Backup) -> None:
    panel = plugin.panel
    if not row.user_id or not panel.database_notifications or not panel.auth.enabled:
        return
    from tungsten import Notification

    if row.status == DONE:
        note = Notification("Backup ready").body(f"{row.name} ({human_size(row.size)}) is ready to download.") \
            .success().icon("database-backup")
    else:
        note = Notification("Backup failed").body(row.error or "Unknown error").danger().icon("triangle-alert")
    try:
        with_db(plugin, lambda db: note.send_to_database(row.user_id, db))
    except Exception:
        log.exception("Could not send the backup notification")


# ====================================================================== keeping it tidy
def delete_backup(plugin: Any, db: Any, row: Backup) -> None:
    if row.status == RUNNING:
        raise BackupError("This backup is still running. Wait for it to finish.")
    path = file_of(plugin, row)
    if path is not None:
        path.unlink(missing_ok=True)
    db.delete(row)


def prune(plugin: Any, db: Any) -> int:
    """Delete backups beyond ``keep`` and older than ``keep_days``. The newest good one always stays."""
    done = db.scalars(select(Backup).where(Backup.status == DONE)
                      .order_by(Backup.created_at.desc(), Backup.id.desc())).all()
    remove = []
    if plugin.keep and len(done) > plugin.keep:
        remove += done[plugin.keep:]
    if plugin.keep_days:
        cutoff = dt.datetime.now() - dt.timedelta(days=plugin.keep_days)
        remove += [b for b in done[1:] if b.created_at < cutoff and b not in remove]
    failed = db.scalars(select(Backup).where(Backup.status == FAILED)
                        .order_by(Backup.created_at.desc(), Backup.id.desc())).all()
    remove += failed[20:]  # keep the last few errors to read
    for row in remove:
        delete_backup(plugin, db, row)
    db.commit()
    return len(remove)


def verify(plugin: Any, db: Any, row: Backup) -> list[str]:
    path = file_of(plugin, row)
    problems = verify_backup(path, row.sha256) if path is not None else ["The file name is not valid."]
    if not problems:
        row.verified_at = dt.datetime.now()
        db.commit()
    return problems


def latest_good(db: Any) -> Backup | None:
    return db.scalars(select(Backup).where(Backup.status == DONE)
                      .order_by(Backup.created_at.desc(), Backup.id.desc()).limit(1)).first()


# ====================================================================== on a timer
class Scheduler:
    """Backs up every ``every_hours`` while the app runs. Safe with many workers: the lock file
    lets one of them run it and the rest see the fresh backup and skip."""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="tungsten-backup-schedule", daemon=True)
            self.thread.start()

    def due(self) -> bool:
        now = dt.datetime.now()

        def last(db: Any, *statuses: str) -> dt.datetime | None:
            return db.scalar(select(Backup.created_at).where(Backup.status.in_(statuses))
                             .order_by(Backup.created_at.desc()).limit(1))

        good, failed = with_db(self.plugin, lambda db: (last(db, DONE, RUNNING), last(db, FAILED)))
        if good is not None and now - good < dt.timedelta(hours=self.plugin.every_hours):
            return False
        # after a failure, wait an hour before trying again instead of failing every few minutes
        return failed is None or now - failed >= dt.timedelta(hours=min(1, self.plugin.every_hours))

    def tick(self) -> Backup | None:
        if not self.due():
            return None
        try:
            return start_backup(self.plugin, kind=self.plugin.schedule_kind, source="schedule", background=False)
        except Busy:
            return None

    def _loop(self) -> None:
        self.stop.wait(60)  # let the app finish starting
        while not self.stop.is_set():
            try:
                self.tick()
            except BackupError as exc:
                log.warning("Scheduled backup did not run: %s", exc)
            except Exception:
                log.exception("Scheduled backup failed")
            self.stop.wait(min(900, max(60, self.plugin.every_hours * 3600 / 4)))
