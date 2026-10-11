"""Media library plugin for Tungsten: every image and file in one place, uploaded once and reused anywhere.

    from tungsten_media_library import MediaLibraryPlugin

    panel.plugin(MediaLibraryPlugin())
    panel.create_tables(engine)   # also creates the media table

Adds a "Media library" screen (upload, search, folders, alt text, where a file is used) and a
"Choose from library" button on every file field of the panel, so a Blog cover, a ticket
attachment or an HR document can reuse a file that is already uploaded.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import Request
from markupsafe import Markup
from sqlalchemy import String, Text, or_, select

from tungsten import Plugin
from tungsten.support.aio import blocking
from tungsten.support.evaluate import call

from .models import MediaBase, MediaItem
from .resources import MediaResource
from .service import (
    KINDS,
    check_files,
    contains,
    duplicate_of,
    file_facts,
    find_item,
    human_size,
    image_size,
    kind_of,
    record_file,
    search_items,
)

__version__ = "0.1.0"

log = logging.getLogger("tungsten.media")

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SAFE_FIELD = re.compile(r"^[A-Za-z0-9_.\-]{1,200}$")
SAFE_URL = re.compile(r"^/[A-Za-z0-9_./\-?=&%]{0,500}$")


class MediaLibraryPlugin(Plugin):
    """``MediaLibraryPlugin(capture_uploads=True, picker=True, dedupe=True, max_size=20480, ...)``.

    - ``capture_uploads`` adds files uploaded through any file field of the panel to the library,
      except those in ``private_directories`` (ticket attachments, HR documents, imports stay private).
    - ``picker`` adds "Choose from library" to every file field.
    - ``dedupe`` reuses the library copy when the same file is uploaded again (saves disk space).
    - ``max_size`` (kilobytes), ``max_files`` and ``accepted_file_types`` limit the library's own upload.
    - ``protect_used`` refuses to delete a file that a blog post, ticket or employee still uses.
    """

    id = "media"
    metadata = MediaBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, capture_uploads: bool = True, picker: bool = True, dedupe: bool = True,
                 private_directories: tuple[str, ...] | list[str] = ("imports", "tickets", "hr"),
                 directory: str = "media", max_size: int = 20480, max_files: int = 20,
                 accepted_file_types: list[str] | None = None, protect_used: bool = True,
                 navigation_group: str | None = "Content", navigation_sort: int = 0, per_page: int = 24) -> None:
        self.capture_uploads = capture_uploads
        self.picker = picker
        self.dedupe = dedupe
        self.private_directories = tuple(d.strip("/").lower() for d in private_directories)
        self.directory = directory.strip("/") or "media"
        self.max_size = max_size
        self.max_files = max_files
        self.accepted_file_types = accepted_file_types
        self.protect_used = protect_used
        self.navigation_group = navigation_group
        self.navigation_sort = navigation_sort
        self.per_page = max(6, min(per_page, 100))
        self.panel: Any = None
        #: other plugins hook in with the methods below
        self.added_listeners: dict[str, Any] = {}
        self.deleted_listeners: dict[str, Any] = {}
        self.usage_finders: dict[str, Any] = {}
        self.tracked: dict[str, dict] = {}

    # ------------------------------------------------------------------ hooks for other code
    def on_media_added(self, key: str, fn: Any) -> None:
        """Run ``fn(db, item)`` after a file joins the library. The same ``key`` replaces the function."""
        self.added_listeners[key] = fn

    def on_media_deleted(self, key: str, fn: Any) -> None:
        """Run ``fn(db, item)`` after a file is deleted from the library (and from storage)."""
        self.deleted_listeners[key] = fn

    def add_usage_finder(self, key: str, fn: Any) -> None:
        """``fn(db, item, ctx)`` returns where a file is used: a list of ``{"label", "title", "url"}``."""
        self.usage_finders[key] = fn

    def track(self, key: str, model: Any, *columns: str, label: str, title: Any = None, url: Any = None,
              resource: Any = None) -> None:
        """Say that ``model.column`` holds file paths, so "Used in" and delete protection see it.

        ``title(record)`` and ``url(record, ctx)`` name and link a record; by default the record's text and
        the edit page of ``resource`` (or of the panel resource for ``model``).
        """
        self.tracked[key] = {"model": model, "columns": columns, "label": label, "title": title, "url": url,
                             "resource": resource}

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        MediaResource.navigation_group = self.navigation_group
        MediaResource.navigation_sort = self.navigation_sort
        panel.resources([MediaResource])
        if self.navigation_group:
            panel.navigation_group(self.navigation_group, icon="images")
        panel.on_upload("media", self._on_upload)
        panel.on_file_pick("media", self._can_pick)
        panel.on_file_names("media", self._names)
        if self.picker:
            panel.render_hook("forms.file-upload.after", self._picker_button)
        panel.routes(self._routes)

    def boot(self, panel: Any) -> None:
        self._track_known_plugins(panel)

    def _track_known_plugins(self, panel: Any) -> None:
        """Blog covers, ticket attachments and HR files count as "used" when those plugins are installed."""
        if panel.get_plugin("blog") is not None:
            try:
                from tungsten_blog.models import BlogAuthor, BlogPost

                self.tracked.setdefault("blog.posts", {
                    "model": BlogPost, "columns": ("cover_image", "og_image", "content"), "label": "Blog post",
                    "title": None, "url": None, "resource": None})
                self.tracked.setdefault("blog.authors", {
                    "model": BlogAuthor, "columns": ("avatar",), "label": "Blog author", "title": None, "url": None,
                    "resource": None})
            except ImportError:  # pragma: no cover
                pass
        if panel.get_plugin("tickets") is not None:
            try:
                from tungsten_tickets.models import Ticket, TicketReply

                self.tracked.setdefault("tickets.replies", {
                    "model": TicketReply, "columns": ("attachments",), "label": "Ticket",
                    "title": lambda record: str(record.ticket) if record.ticket else f"Reply #{record.id}",
                    "url": lambda record, ctx: _resource_url(ctx, Ticket, record.ticket_id, "view"),
                    "resource": None})
            except ImportError:  # pragma: no cover
                pass
        if panel.get_plugin("hr") is not None:
            try:
                from tungsten_hr.models import Employee

                self.tracked.setdefault("hr.employees", {
                    "model": Employee, "columns": ("photo", "documents"), "label": "Employee",
                    "title": lambda record: record.name, "url": None, "resource": None})
            except ImportError:  # pragma: no cover
                pass

    # ------------------------------------------------------------------ library
    def is_private(self, path: str, field: Any = None) -> bool:
        directory = str(getattr(field, "_directory", "") or "").strip("/").lower()
        first = str(path or "").strip("/").split("/", 1)[0].lower()
        return any(d and (first == d or directory == d or directory.startswith(d + "/"))
                   for d in self.private_directories)

    def url(self, item_or_path: Any) -> str:
        """Link to a library file (or any stored path)."""
        path = item_or_path.path if isinstance(item_or_path, MediaItem) else str(item_or_path or "")
        return self.panel.storage.url(path) if path else ""

    def find(self, db: Any, path: str) -> MediaItem | None:
        return find_item(db, path)

    def alt_for(self, db: Any, path: str) -> str | None:
        """The alt text the library has for ``path`` (for public pages that show the image)."""
        item = find_item(db, path)
        return (item.alt or item.title) if item is not None else None

    def add_file(self, db: Any, path: str, name: str | None = None, content_type: str = "", size: int = 0,
                 folder: str | None = None, user_id: Any = None) -> MediaItem:
        """Add an already stored file to the library (idempotent)."""
        existing = find_item(db, path)
        item = record_file(db, self.panel.storage, path, name, content_type, size, folder, user_id)
        if existing is None:
            self._fire(self.added_listeners, db, item)
        return item

    def delete(self, db: Any, item: MediaItem) -> None:
        """Delete the row and its file. Files still used elsewhere are kept on disk."""
        path = item.path
        db.delete(item)
        db.flush()
        self.forget_file(db, item, path)

    def forget_file(self, db: Any, item: MediaItem, path: str) -> None:
        if not self.usages(db, item):
            try:
                self.panel.storage.delete(path)
            except Exception:  # a storage error must not stop the delete
                log.warning("Could not delete file %s", path, exc_info=True)
        self._fire(self.deleted_listeners, db, item)

    def usages(self, db: Any, item: MediaItem, ctx: Any = None, limit: int = 20) -> list[dict]:
        """Where ``item`` is used: ``[{"label": "Blog post", "title": "...", "url": "..."}]``."""
        found: list[dict] = []
        for key, spec in list(self.tracked.items()):
            model = spec["model"]
            conditions = []
            for name in spec["columns"]:
                column = getattr(model, name, None)
                if column is None:
                    continue
                column_type = getattr(column, "type", None)
                if isinstance(column_type, String) and not isinstance(column_type, Text):
                    conditions.append(column == item.path)  # a single path
                else:
                    conditions.append(contains(column, item.path))  # a JSON list or text that mentions it
            if not conditions:
                continue
            try:
                rows = db.scalars(select(model).where(or_(*conditions)).limit(limit)).all()
            except Exception:
                log.warning("Could not look up %s for %s", key, item.path, exc_info=True)
                continue
            for record in rows:
                title = call(spec["title"], record=record) if spec["title"] else str(record)
                if spec["url"]:
                    link = call(spec["url"], record=record, ctx=ctx)
                else:
                    link = _resource_url(ctx, model, record, "edit", spec["resource"])
                found.append({"label": spec["label"], "title": title, "url": link})
        for key, fn in list(self.usage_finders.items()):
            try:
                found.extend(call(fn, db=db, item=item, ctx=ctx) or [])
            except Exception:
                log.warning("Usage finder %r failed", key, exc_info=True)
        return found[:limit]

    def _fire(self, listeners: dict, db: Any, item: MediaItem) -> None:
        for key, fn in list(listeners.items()):
            try:
                call(fn, db=db, item=item, plugin=self)
            except Exception:
                log.exception("Media listener %r failed", key)

    # ------------------------------------------------------------------ panel hooks
    def _on_upload(self, ctx: Any, path: str, filename: str, content_type: str, size: int, field: Any) -> str | None:
        """Every upload of the panel joins the library (unless private). Returns the copy we already have."""
        own = getattr(field, "_media_library_upload", False)
        if not own and (not self.capture_uploads or self.is_private(path, field)):
            return None
        db = ctx.db
        storage = self.panel.storage
        facts = blocking(file_facts, storage, path)  # reads the file: off the event loop on async panels
        try:
            if self.dedupe and facts.get("checksum"):
                twin = duplicate_of(db, storage, facts["checksum"], facts.get("size", 0), path)
                if twin is not None and not self.is_private(twin.path):
                    storage.delete(path)
                    return twin.path
            user_id = ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None
            existing = find_item(db, path)
            item = record_file(db, storage, path, filename, content_type, size, None, user_id, facts)
            if existing is None:
                self._fire(self.added_listeners, db, item)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return None

    def _can_pick(self, ctx: Any, path: str, field: Any) -> bool:
        if ctx is None or ctx.user is None or not MediaResource.can(ctx, "view_any"):
            return False
        item = find_item(ctx.db, path)
        return item is not None and not item.missing

    def _names(self, ctx: Any, paths: list[str]) -> dict[str, str]:
        paths = [str(p) for p in paths if p][:200]
        if not paths:
            return {}
        rows = ctx.db.execute(select(MediaItem.path, MediaItem.name).where(MediaItem.path.in_(paths))).all()
        return {path: name for path, name in rows if name}

    def _picker_button(self, ctx: Any, field: Any, v: dict, form: Any) -> Markup:
        if getattr(field, "_media_library_upload", False):
            return Markup("")
        if not self.picker or ctx is None or ctx.user is None or not form.refresh_url or not form.id:
            return Markup("")
        if not MediaResource.can(ctx, "view_any"):
            return Markup("")
        if not (SAFE_ID.match(str(form.id)) and SAFE_FIELD.match(str(v.get("path") or ""))):
            return Markup("")
        accepted = list(getattr(field, "_accepted", None) or [])
        url = self.panel.url("media-library", "picker", field=v["path"], form=form.id, refresh=form.refresh_url,
                             accept=",".join(accepted) or None, many="1" if v.get("multiple") else None)
        pid = "tw-media-" + re.sub(r"[^A-Za-z0-9_-]", "-", f"{form.id}-{v['path']}")
        return Markup(self.panel.renderer.render("tungsten_media_library/button.html", url=url, v=v, pid=pid,
                                                 image=bool(v.get("image"))))

    # ------------------------------------------------------------------ routes
    def _routes(self, app: Any, panel: Any) -> None:
        from tungsten.routes import Routes

        routes = Routes(panel)
        plugin = self

        def picker(ctx: Any, fd: Any):
            params = ctx.request.query_params
            if not MediaResource.can(ctx, "view_any"):
                return routes.error(ctx, 403, "Not allowed", "You can't open the media library.")
            field, form_id, refresh = params.get("field", ""), params.get("form", ""), params.get("refresh", "")
            if not (SAFE_FIELD.match(field) and SAFE_ID.match(form_id) and SAFE_URL.match(refresh)
                    and refresh.startswith(panel.path.rstrip("/") + "/")):
                return ctx.html('<p class="text-sm text-danger-600">This picker link is broken.</p>',
                                status_code=400)
            accepted = [a for a in params.get("accept", "").split(",") if a.strip()][:20]
            try:
                page = max(1, min(int(params.get("page") or 1), 10000))
            except ValueError:
                page = 1
            q = params.get("mq", "")[:100]
            items, more = search_items(ctx.db, q, accepted, page=page, per_page=plugin.per_page)
            next_url = None
            if more:
                next_url = panel.url("media-library", "picker", field=field, form=form_id, refresh=refresh,
                                     accept=params.get("accept") or None, many=params.get("many") or None,
                                     mq=q or None, page=page + 1)
            return ctx.html(panel.renderer.render(
                "tungsten_media_library/picker.html", items=[_card(plugin, i) for i in items], field=field,
                form_id=form_id, refresh=refresh, next_url=next_url, page=page, q=q,
                library_url=MediaResource.get_url(ctx)))

        @app.get("/media-library/picker")
        async def media_picker(request: Request):
            return await routes.run(request, picker)


def _card(plugin: MediaLibraryPlugin, item: MediaItem) -> dict:
    return {"path": item.path, "name": str(item), "url": plugin.url(item), "kind": item.kind,
            "icon": KINDS.get(item.kind, KINDS["other"])[2], "alt": item.alt or "", "size": human_size(item.size),
            "dims": item.dimensions}


def _resource_url(ctx: Any, model: Any, record: Any, page: str = "edit", resource: Any = None) -> str | None:
    if ctx is None or record is None:
        return None
    if resource is None:
        resource = next((r for r in ctx.panel.get_resources() if r.model is model), None)
    if resource is None:
        return None
    if not resource.has_page(page):
        page = "view" if resource.has_page("view") else "edit"
        if not resource.has_page(page):
            return resource.get_url(ctx)
    return resource.get_url(ctx, page, record)


__all__ = [
    "KINDS", "MediaBase", "MediaItem", "MediaLibraryPlugin", "MediaResource", "check_files", "find_item",
    "human_size", "image_size", "kind_of", "record_file", "search_items",
]
