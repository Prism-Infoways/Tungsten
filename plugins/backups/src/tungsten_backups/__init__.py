"""Back up your database (and uploaded files) from the panel, and download the zip.

    from tungsten_backups import BackupsPlugin

    panel.plugin(BackupsPlugin(folder="storage/backups"))
    panel.create_tables(engine)
    panel.mount(app)

Open "Backups" in the panel and press Back up now. Backups are saved in a private folder on the
server and are only downloaded by signed-in admins, never from a public link.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request

from tungsten import Plugin

from .engine import BackupError, human_size, read_manifest, verify_backup, write_backup
from .models import DONE, FAILED, RUNNING, Backup, BackupsBase
from .resources import DOWNLOAD_PERMISSION, PERMISSION, BackupResource, can_download
from .service import KINDS, Busy, Scheduler, delete_backup, file_of, latest_good, prune, start_backup, verify

__version__ = "0.1.0"

log = logging.getLogger("tungsten.backups")


class BackupsPlugin(Plugin):
    """``BackupsPlugin(folder="storage/backups", keep=10, ...)``.

    - ``folder``: where backup zips are saved. Keep it outside any folder your web server serves.
    - ``keep``: how many good backups to keep (older ones are deleted). 0 keeps them all.
    - ``keep_days``: also delete backups older than this many days. 0 never does. The newest good one
      always stays.
    - ``every_hours``: make a backup on its own this often while the app runs (e.g. 24). None: only by hand.
    - ``schedule_kind``: ``"database"`` or ``"full"`` for those automatic backups.
    - ``folders``: more folders saved in a full backup, ``{"name": "path"}``. The panel's upload folder is
      always included.
    - ``include_storage``: save the panel's upload folder in a full backup (default True).
    - ``use_tools``: use ``pg_dump`` / ``mysqldump`` when installed. Without them every table is saved as JSON.
    - ``timeout``: seconds a dump tool may run.
    - ``min_free_mb``: disk space to leave free; a backup that would go below this does not start.
    - ``max_age_days``: the dashboard card and the Security audit warn when the newest backup is older.
    - ``allow``: ``fn(ctx) -> bool`` for an extra rule on who may use backups (on top of the permissions).
    - ``allow_without_login``: let downloads work on a panel with no login (off: anyone could take your data).
    - ``dashboard_widget``: show the "Last backup" card on the dashboard.
    - ``background``: run backups in the background so the page doesn't wait.
    - ``prefix``: start of the file names (default ``backup``).
    """

    id = "backups"
    metadata = BackupsBase.metadata

    def __init__(self, *, folder: str | Path = "storage/backups", keep: int = 10, keep_days: int = 0,
                 every_hours: float | None = None, schedule_kind: str = "database",
                 folders: dict[str, str | Path] | None = None, include_storage: bool = True,
                 use_tools: bool = True, timeout: int = 3600, min_free_mb: int = 100, max_age_days: int = 7,
                 allow: Callable[[Any], bool] | None = None, allow_without_login: bool = False,
                 dashboard_widget: bool = True, background: bool = True, prefix: str = "backup") -> None:
        if schedule_kind not in KINDS:
            raise ValueError(f"schedule_kind must be one of {', '.join(KINDS)}")
        if every_hours is not None and every_hours <= 0:
            raise ValueError("every_hours must be more than 0 (or None to turn it off)")
        self.folder = Path(folder).expanduser().resolve()
        self.keep = max(0, int(keep))
        self.keep_days = max(0, int(keep_days))
        self.every_hours = every_hours
        self.schedule_kind = schedule_kind
        self.include_storage = include_storage
        self.use_tools = use_tools
        self.timeout = max(30, int(timeout))
        self.min_free_mb = max(0, int(min_free_mb))
        self.max_age_days = max(1, int(max_age_days))
        self.allow = allow
        self.allow_without_login = allow_without_login
        self.dashboard_widget = dashboard_widget
        self.background = background
        self.prefix = prefix
        self.panel: Any = None
        self.scheduler = Scheduler(self)
        self._folders: dict[str, Path] = {}
        self._on_backup: list[Callable[[Backup, BackupsPlugin], Any]] = []
        for name, path in (folders or {}).items():
            self.add_folder(name, path)

    # ------------------------------------------------------------------ hooks for your app and other plugins
    def add_folder(self, name: str, path: str | Path) -> BackupsPlugin:
        """Save another folder in full backups, under ``files/<name>/`` in the zip."""
        label = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name)).strip("-.") or "folder"
        resolved = Path(path).expanduser().resolve()
        if self._overlaps(resolved):
            raise ValueError(f"Folder {resolved} holds the backups folder (or sits inside it): a backup would "
                             f"copy itself. Pick another folder.")
        self._folders[label] = resolved
        return self

    def on_backup(self, fn: Callable[[Backup, BackupsPlugin], Any]) -> Callable:
        """Call ``fn(backup, plugin)`` after every backup, good or failed (e.g. copy it off the server)."""
        self._on_backup.append(fn)
        return fn

    def folders(self) -> dict[str, Path]:
        """Every folder a full backup saves.

        Other plugins add theirs by having a ``backup_folders()`` method returning ``{"name": path}``."""
        out: dict[str, Path] = {}
        root = getattr(getattr(self.panel, "storage", None), "root", None)
        if self.include_storage and root is not None:
            root = Path(root).resolve()
            if not self._overlaps(root):  # checked in register() too; a later change of storage lands here
                out["storage"] = root
        for plugin in getattr(self.panel, "_plugins", []):
            extra = getattr(plugin, "backup_folders", None)
            if plugin is self or not callable(extra):
                continue
            try:
                for name, path in (extra() or {}).items():
                    label = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{plugin.id}-{name}").strip("-.")
                    resolved = Path(path).resolve()
                    if not self._overlaps(resolved) and resolved not in out.values():
                        out[label] = resolved
            except Exception:
                log.exception("backup_folders() of plugin %s failed", getattr(plugin, "id", plugin))
        for label, path in self._folders.items():
            if path not in out.values():
                out[label] = path
        return out

    def _overlaps(self, path: Path) -> bool:
        return path == self.folder or path in self.folder.parents or self.folder in path.parents

    def engine(self) -> Any:
        return self.panel._engine()

    # ------------------------------------------------------------------ Python API
    def backup(self, kind: str = "database", note: str | None = None, *, background: bool = False) -> Backup:
        """Make a backup from code (waits for it unless ``background=True``)."""
        return start_backup(self, kind=kind, note=note, source="code", background=background)

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        root = getattr(getattr(panel, "storage", None), "root", None)
        if root is not None and self.folder != Path(root).resolve() and Path(root).resolve() in self.folder.parents:
            raise ValueError(f"The backups folder {self.folder} is inside the panel's upload folder {root}, which "
                             f"the panel serves. Pick a folder outside it, e.g. folder='storage/backups'.")
        panel.resources([BackupResource])
        if self.dashboard_widget:
            from .widgets import BackupStats

            panel.widgets([BackupStats])
        panel.routes(self._routes)

    def boot(self, panel: Any) -> None:
        audit = panel.get_plugin("security-audit")
        if audit is not None and isinstance(getattr(audit, "checks", None), list):
            from .checks import backup_check

            audit.checks.append(backup_check(self))
        quick = panel.get_plugin("quick-create")
        if quick is not None and callable(getattr(quick, "add_link", None)):
            from .resources import allowed

            # the "+ New" menu of tungsten-quick-create opens the Backups screen
            quick.add_link("backups", "Backup", lambda ctx: ctx.url("backups"), icon="database-backup",
                           group="Settings", sort=90, visible=lambda ctx: allowed(ctx))
        if self.every_hours and panel.session_factory is not None:
            self.scheduler.start()

    def permissions(self) -> list[tuple[str, str]]:
        return [(DOWNLOAD_PERMISSION, "Download backups")]

    def _routes(self, app: Any, panel: Any) -> None:
        from starlette.responses import FileResponse

        from tungsten.routes import Routes

        routes = Routes(panel)
        plugin = self

        def download(ctx: Any, fd: Any, backup_id: int):
            if not can_download(ctx):
                return routes.error(ctx, 403, "Not allowed", "You can't download backups.")
            row = ctx.db.get(Backup, backup_id)
            path = file_of(plugin, row) if row is not None else None
            if row is None or row.status != DONE or path is None or not path.is_file():
                return routes.error(ctx, 404, "Not found", "This backup file is not on the server any more.")
            panel.log_activity(ctx, "downloaded", row, f"Downloaded backup {row.name}")
            ctx.db.commit()
            return FileResponse(path, media_type="application/zip", filename=row.name,
                                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

        @app.get("/backups-download/{backup_id:int}")
        async def backups_download(request: Request, backup_id: int):
            return await routes.run(request, download, backup_id=backup_id)


__all__ = [
    "DONE",
    "DOWNLOAD_PERMISSION",
    "FAILED",
    "KINDS",
    "PERMISSION",
    "RUNNING",
    "Backup",
    "BackupError",
    "BackupResource",
    "BackupsBase",
    "BackupsPlugin",
    "Busy",
    "__version__",
    "delete_backup",
    "human_size",
    "latest_good",
    "prune",
    "read_manifest",
    "start_backup",
    "verify",
    "verify_backup",
    "write_backup",
]
