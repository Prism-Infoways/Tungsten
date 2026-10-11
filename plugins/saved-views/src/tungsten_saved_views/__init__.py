"""Saved table views for Tungsten: users save their own filters as one-click tabs.

    from tungsten_saved_views import SavedViewsPlugin

    panel.plugin(SavedViewsPlugin())
    panel.create_tables(engine)   # also creates the saved view tables

Every resource list gets a row of views above the table. A user sets filters,
search, sort, tab and columns, clicks "Save view" and gets a tab like
"My leads" or "Pending" next time. Views can be shared with the whole team,
and each user can pick the view their list opens with.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Request
from markupsafe import Markup
from starlette.datastructures import QueryParams

from tungsten import Notification, Plugin
from tungsten.i18n import translate as __
from tungsten.support.evaluate import call

from .models import SavedView, SavedViewDefault, SavedViewsBase
from .service import (
    COLORS,
    Preset,
    ViewError,
    ViewItem,
    clean_name,
    clean_query,
    count_own,
    expand,
    forget_view,
    get_default,
    match_key,
    name_taken,
    set_default,
    views_query,
)

__version__ = "0.1.0"
__all__ = ["Preset", "SavedView", "SavedViewDefault", "SavedViewsPlugin", "ViewError", "ViewItem"]

log = logging.getLogger("tungsten.saved_views")

SHARE_PERMISSION = "saved_views.share"
MANAGE_PERMISSION = "saved_views.manage"


class SavedViewsPlugin(Plugin):
    """``SavedViewsPlugin(resources=None, exclude=(), presets=True, sharing=True, manage_page=True, max_views=30)``.

    - ``resources``: slugs of the lists that get a views bar (``None``: every resource).
    - ``exclude``: slugs that never get one.
    - ``presets``: add ready views for installed plugins, like "My tickets" and "My leads".
    - ``sharing``: let users share a view with everybody (needs the ``saved_views.share``
      permission when the panel uses roles).
    - ``manage_page``: a "Saved views" page in the user menu to rename, recolour, order and delete views.
    - ``max_views``: most views one user may save on one list.
    """

    id = "saved-views"
    metadata = SavedViewsBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, resources: list[str] | None = None, exclude: list[str] | tuple = (), presets: bool = True,
                 sharing: bool = True, manage_page: bool = True, max_views: int = 30,
                 path: str = "_views") -> None:
        self.resources = set(resources) if resources is not None else None
        self.exclude = set(exclude) | {"saved-views"}
        self.builtin_presets = presets
        self.sharing = sharing
        self.manage_page = manage_page
        self.max_views = max(1, int(max_views))
        self.path = path.strip("/") or "_views"
        self.panel: Any = None
        self._presets: dict[str, list[Preset]] = {}
        #: other plugins hook in with on_view_saved / on_view_deleted
        self.saved_listeners: dict[str, Callable] = {}
        self.deleted_listeners: dict[str, Callable] = {}

    # ------------------------------------------------------------------ hooks for other code
    def preset(self, resource: str, name: str, query: str, icon: str | None = None, color: str = "gray",
               key: str | None = None, visible: Callable | None = None) -> SavedViewsPlugin:
        """Add a view everyone sees on ``resource``. ``query`` is the table address, e.g.
        ``"filters.status.values=open&sort=created_at&direction=desc"``. ``{me}`` becomes the
        signed-in user's id and ``{today}`` today's date. ``visible(ctx, user)`` can hide it."""
        key = key or "-".join(name.lower().split())
        items = self._presets.setdefault(resource, [])
        items[:] = [p for p in items if p.key != key]  # the same key replaces the preset
        items.append(Preset(key=key, resource=resource, name=name, query=clean_query(query), icon=_safe_icon(icon),
                            color=color if color in COLORS else "gray", visible=visible))
        return self

    def presets_for(self, resource: str) -> list[Preset]:
        return list(self._presets.get(resource, []))

    def on_view_saved(self, key: str, fn: Callable) -> None:
        """Run ``fn(db, view)`` after a view is saved or changed. The same ``key`` replaces the function."""
        self.saved_listeners[key] = fn

    def on_view_deleted(self, key: str, fn: Callable) -> None:
        """Run ``fn(db, view)`` just before a view is deleted."""
        self.deleted_listeners[key] = fn

    def enabled_for(self, resource: str) -> bool:
        if resource in self.exclude:
            return False
        return self.resources is None or resource in self.resources

    def views_for(self, ctx: Any, resource: Any) -> list[ViewItem]:
        """The views the current user sees on a resource (a slug or a Resource class): presets,
        then shared and own views. Kanban boards, dashboards and other plugins can list these."""
        resource_cls = self._resource(resource)
        if resource_cls is None:
            return []
        slug = resource_cls.get_slug()
        me, tenant = self.user_key(ctx), self.tenant_key(ctx)
        default = get_default(ctx.db, me, tenant, slug)
        default_key = default.view_key if default is not None else None
        base = resource_cls.get_url(ctx)
        out: list[ViewItem] = []
        for p in self.presets_for(slug):
            if p.visible is not None and not call(p.visible, ctx=ctx, user=ctx.user, panel=self.panel):
                continue
            query = expand(p.query, me)
            out.append(ViewItem(key=f"preset:{p.key}", name=__(p.name), query=query, url=_join(base, query),
                                icon=p.icon, color=p.color, preset=True, match=match_key(query),
                                is_default=default_key == f"preset:{p.key}"))
        for v in ctx.db.scalars(views_query(me, tenant, slug)).all():
            query = expand(v.query or "", me)
            out.append(ViewItem(key=str(v.id), id=v.id, name=v.name, query=query, url=_join(base, query),
                                icon=_safe_icon(v.icon), color=v.color if v.color in COLORS else "gray", shared=bool(v.is_shared), mine=v.user_id == me,
                                editable=self.can_edit(ctx, v), match=match_key(query),
                                is_default=default_key == str(v.id), extra={"hidden_columns": v.hidden_columns}))
        return out

    def default_for(self, ctx: Any, resource: Any, items: list[ViewItem] | None = None) -> ViewItem | None:
        """The view the user's list opens with, if they picked one that still exists."""
        items = self.views_for(ctx, resource) if items is None else items
        return next((i for i in items if i.is_default), None)

    # ------------------------------------------------------------------ who may do what
    def user_key(self, ctx: Any) -> str:
        if ctx.user is None or not self.panel.auth.enabled:
            return ""
        return str(self.panel.auth.user_id(ctx.user))[:64]

    def tenant_key(self, ctx: Any) -> str:
        tenancy = self.panel.tenancy
        if not tenancy.enabled or ctx.tenant is None:
            return ""
        key_of = getattr(tenancy, "key_of", None)
        return str(key_of(ctx.tenant) if key_of else getattr(ctx.tenant, "id", ctx.tenant))[:64]

    def can_share(self, ctx: Any) -> bool:
        return self.sharing and ctx.can(SHARE_PERMISSION)

    def can_edit(self, ctx: Any, view: SavedView) -> bool:
        if view.user_id == self.user_key(ctx) and view.tenant_key == self.tenant_key(ctx):
            return True
        return bool(view.is_shared) and view.tenant_key == self.tenant_key(ctx) and self.can_manage(ctx)

    def can_manage(self, ctx: Any) -> bool:
        """May change views other people shared. Without roles or a gate nobody may: only owners."""
        auth = self.panel.auth
        if not auth.enabled or (not auth.rbac and auth.gate is None):
            return False
        return ctx.can(MANAGE_PERMISSION)

    def permissions(self) -> list[tuple[str, str]]:
        return [(SHARE_PERMISSION, __("Share table views with everyone")),
                (MANAGE_PERMISSION, __("Change and delete views other people shared"))]

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        panel.render_hook("resource.list.before-table", self._bar)
        panel.routes(self._routes)
        if self.manage_page:
            from .resources import SavedViewResource

            panel.resources([SavedViewResource])
            panel.user_menu_item(__("Saved views"), panel.url(SavedViewResource.get_slug()), icon="bookmark")

    def boot(self, panel: Any) -> None:
        if self.builtin_presets and panel.auth.enabled:
            self._add_builtin_presets(panel)

    def _add_builtin_presets(self, panel: Any) -> None:
        """Ready views for the official plugins that are installed (each keeps working alone)."""
        mine = {"tickets": ("My tickets", "life-buoy"), "leads": ("My leads", "user-round")}
        for plugin_id, (name, icon) in mine.items():
            plugin = panel.get_plugin(plugin_id)
            resource = panel.resource(plugin_id)
            if plugin is None or resource is None or not self.enabled_for(plugin_id):
                continue
            if any(p.key == "mine" for p in self.presets_for(plugin_id)):
                continue  # the app set its own
            self.preset(plugin_id, name, "filters.assigned_to.value={me}", icon=icon, color="primary", key="mine")

    def _resource(self, resource: Any) -> Any:
        if resource is None:
            return None
        if isinstance(resource, str):
            return self.panel.resource(resource)
        return resource

    # ------------------------------------------------------------------ the bar above the table
    def _bar(self, ctx: Any, resource: Any = None, table: Any = None) -> Markup:
        if resource is None:  # an older Tungsten: find the resource from the address
            resource = self.panel.resource(str(ctx.request.path_params.get("slug", "")))
        if resource is None or not self.enabled_for(resource.get_slug()):
            return Markup("")
        try:
            return self._render_bar(ctx, resource, table)
        except Exception:  # a broken view must never break the list page
            log.exception("Saved views bar failed on %s", resource.get_slug())
            try:
                ctx.db.rollback()
            except Exception:  # pragma: no cover
                pass
            return Markup("")

    def _render_bar(self, ctx: Any, resource: Any, table: Any) -> Markup:
        slug = resource.get_slug()
        items = self.views_for(ctx, resource)
        toggleable = [c.name for c in table._columns if c._toggleable] if table is not None else []
        for item in items:
            hidden = item.extra.get("hidden_columns")
            if hidden is not None and toggleable:
                item.url = _join(item.url, _cols_query(toggleable, hidden))
        default = self.default_for(ctx, resource, items)
        replace_url = redirect_url = None
        params = ctx.request.query_params
        if default is not None and not params:
            if table is not None:  # draw the list with the default view right away
                query = default.query
                hidden = default.extra.get("hidden_columns")
                if hidden is not None and toggleable:
                    query = _join_query(query, _cols_query(toggleable, hidden))
                table.bind(ctx, table.host, params=QueryParams(query), id=table.id)
                replace_url = _join(resource.get_url(ctx), default.query)
            else:
                redirect_url = default.url
        current = match_key(QueryParams(replace_url.partition("?")[2]) if replace_url else params)
        active = next((i for i in items if i.match == current), None)
        all_url = resource.get_url(ctx) + ("?_view=all" if default is not None else "")
        return self.panel.renderer.render(
            "tungsten_saved_views/bar.html",
            panel=self.panel, ctx=ctx, plugin=self, resource=slug, items=items, active=active,
            all_active=active is None and current == match_key(""), all_url=all_url,
            all_match=match_key(""), can_share=self.can_share(ctx), default=default,
            replace_url=replace_url, redirect_url=redirect_url, csrf_token=self.panel.csrf_token(ctx),
            action=lambda *parts: self.panel.url(self.path, *parts),
            full=count_own(ctx.db, self.user_key(ctx), self.tenant_key(ctx), slug) >= self.max_views,
        )

    # ------------------------------------------------------------------ routes
    def _routes(self, app: Any, panel: Any) -> None:
        from tungsten.routes import Routes

        routes = Routes(panel)
        plugin = self
        base = f"/{self.path}"

        @app.post(base + "/save")
        async def save(request: Request):
            return await routes.run(request, plugin._save, read_form=True)

        @app.post(base + "/default")
        async def default(request: Request):
            return await routes.run(request, plugin._default, read_form=True)

        @app.post(base + "/{view_id}/update")
        async def update(request: Request, view_id: str):
            return await routes.run(request, plugin._update, read_form=True, view_id=view_id)

        @app.post(base + "/{view_id}/rename")
        async def rename(request: Request, view_id: str):
            return await routes.run(request, plugin._rename, read_form=True, view_id=view_id)

        @app.post(base + "/{view_id}/delete")
        async def delete(request: Request, view_id: str):
            return await routes.run(request, plugin._delete, read_form=True, view_id=view_id)

    def _list_resource(self, ctx: Any, slug: Any) -> Any:
        from tungsten.routes import Forbidden, NotFound

        resource = self.panel.resource(str(slug or ""))
        if resource is None or not self.enabled_for(resource.get_slug()):
            raise NotFound()
        if not resource.can(ctx, "view_any"):
            raise Forbidden()
        return resource

    def _find(self, ctx: Any, view_id: str) -> SavedView:
        from tungsten.routes import Forbidden, NotFound

        try:
            view = ctx.db.get(SavedView, int(view_id))
        except (TypeError, ValueError):
            view = None
        if view is None:
            raise NotFound()
        if not self.can_edit(ctx, view):
            raise Forbidden()
        resource = self.panel.resource(view.resource)
        if resource is not None and not resource.can(ctx, "view_any"):
            raise Forbidden()
        return view

    def _hidden_columns(self, ctx: Any, resource: Any) -> list[str] | None:
        """The columns this user has hidden on the list right now (None when nothing can be hidden)."""
        try:
            host = resource.host()
            table = host.get_table(ctx)
            if table is None:
                return None
            table.bind(ctx, host, params=QueryParams(""))
            if not any(c._toggleable for c in table._columns):
                return None
            return sorted(table.hidden_columns())
        except Exception:  # columns are a nice extra; never block saving over them
            log.exception("Could not read the hidden columns of %s", resource.get_slug())
            return None

    def _back(self, ctx: Any, resource: Any = None, query: str = "") -> Any:
        if resource is not None:
            return ctx.go(_join(resource.get_url(ctx), query) if query else resource.get_url(ctx) + "?_view=all")
        return ctx.go(ctx.request.headers.get("referer") or self.panel.url())

    def _fail(self, ctx: Any, message: str, resource: Any = None, query: str = "") -> Any:
        Notification(__("View not saved")).body(__(message)).danger().send(ctx)
        return self._back(ctx, resource, query)

    def _fire(self, listeners: dict, db: Any, view: SavedView) -> None:
        for key, fn in list(listeners.items()):
            try:
                call(fn, db=db, view=view, plugin=self)
            except Exception:  # another plugin's bug must not lose the view
                log.exception("Saved view listener %s failed", key)

    def _save(self, ctx: Any, fd: Any) -> Any:
        resource = self._list_resource(ctx, fd.get("resource"))
        slug = resource.get_slug()
        raw_query = str(fd.get("query") or "")
        try:
            query = clean_query(raw_query)
        except ViewError as e:
            return self._fail(ctx, str(e), resource)
        try:
            name = clean_name(fd.get("name"))
            if not query:
                raise ViewError("Nothing to save yet. Pick a filter, search, sort or tab first.")
            me, tenant = self.user_key(ctx), self.tenant_key(ctx)
            if count_own(ctx.db, me, tenant, slug) >= self.max_views:
                raise ViewError(f"You can keep up to {self.max_views} views here. Delete one first.")
            if name_taken(ctx.db, me, tenant, slug, name):
                raise ViewError("You already have a view with this name.")
        except ViewError as e:
            return self._fail(ctx, str(e), resource, query)
        color = str(fd.get("color") or "gray")
        view = SavedView(user_id=me, tenant_key=tenant, resource=slug, name=name, query=query,
                         hidden_columns=self._hidden_columns(ctx, resource),
                         color=color if color in COLORS else "gray",
                         is_shared=bool(fd.get("shared")) and self.can_share(ctx),
                         sort=count_own(ctx.db, me, tenant, slug))
        ctx.db.add(view)
        ctx.db.flush()
        if fd.get("default"):
            set_default(ctx.db, me, tenant, slug, str(view.id))
        self._fire(self.saved_listeners, ctx.db, view)
        ctx.db.commit()
        Notification(__("View saved")).body(__("“:name” is now a tab above the table.", name=name)).success().send(ctx)
        return ctx.go(_join(resource.get_url(ctx), expand(query, me)))

    def _update(self, ctx: Any, fd: Any, view_id: str) -> Any:
        view = self._find(ctx, view_id)
        resource = self._list_resource(ctx, view.resource)
        try:
            query = clean_query(str(fd.get("query") or ""))
        except ViewError as e:
            return self._fail(ctx, str(e), resource)
        if not query:
            return self._fail(ctx, "Nothing to save yet. Pick a filter, search, sort or tab first.", resource)
        view.query = query
        view.hidden_columns = self._hidden_columns(ctx, resource)
        self._fire(self.saved_listeners, ctx.db, view)
        ctx.db.commit()
        Notification(__("View updated")).body(__("“:name” now uses these filters.", name=view.name)).success().send(ctx)
        return ctx.go(_join(resource.get_url(ctx), expand(query, self.user_key(ctx))))

    def _rename(self, ctx: Any, fd: Any, view_id: str) -> Any:
        view = self._find(ctx, view_id)
        resource = self._list_resource(ctx, view.resource)
        try:
            name = clean_name(fd.get("name"))
            if name_taken(ctx.db, view.user_id, view.tenant_key, view.resource, name, skip_id=view.id):
                raise ViewError("You already have a view with this name.")
        except ViewError as e:
            return self._fail(ctx, str(e), resource, expand(view.query, self.user_key(ctx)))
        view.name = name
        if "shared" in fd or fd.get("_sharing"):
            view.is_shared = bool(fd.get("shared")) and self.can_share(ctx)
        self._fire(self.saved_listeners, ctx.db, view)
        ctx.db.commit()
        Notification(__("View renamed")).success().send(ctx)
        return ctx.go(_join(resource.get_url(ctx), expand(view.query, self.user_key(ctx))))

    def _delete(self, ctx: Any, fd: Any, view_id: str) -> Any:
        view = self._find(ctx, view_id)
        resource = self.panel.resource(view.resource)
        name = view.name
        self._fire(self.deleted_listeners, ctx.db, view)
        forget_view(ctx.db, view)
        ctx.db.commit()
        Notification(__("View deleted")).body(__("“:name” was removed.", name=name)).success().send(ctx)
        return self._back(ctx, resource)

    def _default(self, ctx: Any, fd: Any) -> Any:
        resource = self._list_resource(ctx, fd.get("resource"))
        key = str(fd.get("key") or "")
        items = self.views_for(ctx, resource)
        item = next((i for i in items if i.key == key), None) if key else None
        if key and item is None:
            from tungsten.routes import NotFound

            raise NotFound()
        set_default(ctx.db, self.user_key(ctx), self.tenant_key(ctx), resource.get_slug(), key or None)
        ctx.db.commit()
        if item is None:
            Notification(__("The list now opens with all records")).success().send(ctx)
            return self._back(ctx, resource)
        Notification(__("Default view set")).body(__("The list now opens with “:name”.", name=item.name)) \
            .success().send(ctx)
        return ctx.go(item.url)


def _safe_icon(name: Any) -> str | None:
    """Only plain icon names: the icon helper draws raw ``<svg>`` text as given."""
    name = str(name or "").strip().lower()
    return name if name and len(name) <= 40 and all(ch.isalnum() or ch == "-" for ch in name) else None


def _join_query(a: str, b: str) -> str:
    return "&".join(x for x in (a, b) if x)


def _join(url: str, query: str) -> str:
    if not query:
        return url
    return url + ("&" if "?" in url else "?") + query


def _cols_query(toggleable: list[str], hidden: list[str]) -> str:
    from urllib.parse import urlencode

    hidden_set = set(hidden or [])
    return urlencode([("_cols", "1")] + [("cols", name) for name in toggleable if name not in hidden_set])
