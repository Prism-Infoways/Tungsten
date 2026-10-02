"""The :class:`Panel`: one admin panel mounted into your FastAPI app."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable
from urllib.parse import urlencode

from markupsafe import Markup

from .auth import Auth
from .navigation import NavigationGroup, NavigationItem
from .pages import Dashboard, Page
from .rendering import Renderer
from .resources.resource import Resource
from .storage import LocalStorage, Storage
from .support import colors as color_tools
from .support.evaluate import call, evaluate
from .tenancy import NoTenancy, Tenancy
from .widgets import Widget

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

    from .context import Context
    from .plugins import Plugin

STATIC_DIR = Path(__file__).with_name("static")
VERSION = "0.1.0"


class Panel:
    """An admin panel::

        panel = Panel(
            path="/admin",
            session_factory=SessionLocal,
            secret_key="change-me",
            auth=Auth(User),
            brand_name="Acme",
            colors={"primary": "orange"},
        )
        panel.resources([ProductResource, OrderResource])
        panel.widgets([StatsWidget, RevenueChart])
        panel.mount(app)
    """

    def __init__(
        self,
        *,
        id: str = "admin",
        path: str = "/admin",
        session_factory: Callable | None = None,
        engine: Any = None,
        secret_key: str | None = None,
        auth: Auth | None = None,
        brand_name: str = "Tungsten",
        brand_logo: str | None = None,
        brand_logo_dark: str | None = None,
        brand_tagline: str | None = None,
        favicon: str | None = None,
        colors: dict[str, Any] | None = None,
        font: str | None = "Inter",
        dark_mode: bool = True,
        default_theme: str = "system",
        sidebar_collapsible: bool = True,
        spa: bool = False,
        unsaved_changes_alerts: bool = True,
        tenancy: Tenancy | None = None,
        storage: Storage | None = None,
        global_search: bool = True,
        database_notifications: bool = True,
        notifications_polling: str | None = "30s",
        navigation_groups: list[str | NavigationGroup] | None = None,
        dashboard: type[Page] | None = Dashboard,
        template_dirs: Iterable[str | Path] = (),
        login_hero: dict[str, Any] | None = None,
        sidebar_footer: Any = None,
        https_only_cookies: bool = False,
        activity_log: bool = False,
    ) -> None:
        self.id = id
        self.path = "/" + path.strip("/") if path.strip("/") else ""
        if session_factory is None and engine is not None:
            from sqlalchemy.orm import sessionmaker

            session_factory = sessionmaker(engine, expire_on_commit=False)
        self.session_factory = session_factory
        self.engine = engine
        self.secret_key = secret_key or secrets.token_urlsafe(32)
        self.auth = auth or Auth(None)
        self.auth.panel = self
        self.brand_name = brand_name
        self.brand_logo = brand_logo
        self.brand_logo_dark = brand_logo_dark
        self.brand_tagline = brand_tagline
        self.favicon = favicon
        self.colors = dict(colors or {})
        self.font = font
        self.dark_mode = dark_mode
        self.default_theme = default_theme
        self.sidebar_collapsible = sidebar_collapsible
        self.spa = spa
        self.unsaved_changes_alerts = unsaved_changes_alerts
        self.tenancy = tenancy or NoTenancy()
        self.storage = storage or LocalStorage()
        if getattr(self.storage, "panel", "missing") is None:
            self.storage.panel = self  # type: ignore[attr-defined]
        self.global_search_enabled = global_search
        self.database_notifications = database_notifications
        self.notifications_polling = notifications_polling
        self.dashboard = dashboard
        self.login_hero = login_hero or {
            "heading": "Modern admin panel for Python projects",
            "text": "Build powerful internal tools, fast and beautiful.",
        }
        self.sidebar_footer = sidebar_footer
        self.https_only_cookies = https_only_cookies
        self.activity_log = activity_log
        self.renderer = Renderer(template_dirs)
        self.renderer.env.globals["panel"] = self

        self._resources: list[type[Resource]] = []
        self._pages: list[type[Page]] = []
        self._widgets: list[type[Widget]] = []
        self._nav_groups: list[NavigationGroup] = [
            g if isinstance(g, NavigationGroup) else NavigationGroup(g) for g in (navigation_groups or [])
        ]
        self._nav_items: list[NavigationItem] = []
        self._user_menu_items: list[dict] = []
        self._hooks: dict[str, list[Callable]] = {}
        self._plugins: list[Plugin] = []
        self._extra_routes: list[Callable] = []
        self._app: Any = None
        self._booted = False

    # ------------------------------------------------------------------ registration
    def resources(self, resources: Iterable[type[Resource]]) -> "Panel":
        for r in resources:
            if r not in self._resources:
                self._resources.append(r)
        return self

    def pages(self, pages: Iterable[type[Page]]) -> "Panel":
        for p in pages:
            if p not in self._pages:
                self._pages.append(p)
        return self

    def widgets(self, widgets: Iterable[type[Widget]]) -> "Panel":
        for w in widgets:
            if w not in self._widgets:
                self._widgets.append(w)
        return self

    def navigation_items(self, items: Iterable[NavigationItem]) -> "Panel":
        self._nav_items.extend(items)
        return self

    def navigation_group(self, label: str, icon: str | None = None, collapsed: bool = False) -> "Panel":
        self._nav_groups.append(NavigationGroup(label, icon=icon, collapsed=collapsed))
        return self

    def user_menu_item(self, label: str, url: str, icon: str | None = None) -> "Panel":
        self._user_menu_items.append({"label": label, "url": url, "icon": icon})
        return self

    def render_hook(self, name: str, fn: Callable) -> "Panel":
        """Inject HTML at a named spot, e.g. ``"head.end"``, ``"sidebar.nav.end"``, ``"content.start"``."""
        self._hooks.setdefault(name, []).append(fn)
        return self

    def routes(self, fn: Callable) -> Callable:
        """Decorator to add your own routes to the panel app: ``fn(router, panel)``."""
        self._extra_routes.append(fn)
        return fn

    def plugin(self, plugin: "Plugin") -> "Panel":
        self._plugins.append(plugin)
        plugin.register(self)
        return self

    def rbac(self, roles_resource: bool = True) -> "Panel":
        """Turn on role-based permissions (and the Roles & Permissions resource)."""
        from .auth.rbac import RoleResource

        self.auth.rbac = True
        if roles_resource:
            self.resources([RoleResource])
        return self

    def get_plugin(self, plugin_id: str) -> "Plugin | None":
        return next((p for p in self._plugins if p.id == plugin_id), None)

    # ------------------------------------------------------------------ lookup
    def get_resources(self) -> list[type[Resource]]:
        return list(self._resources)

    def get_pages(self) -> list[type[Page]]:
        return list(self._pages)

    def get_widgets(self) -> list[type[Widget]]:
        return list(self._widgets)

    def resource(self, slug: str) -> type[Resource] | None:
        return next((r for r in self._resources if r.get_slug() == slug), None)

    def page(self, slug: str) -> type[Page] | None:
        if self.dashboard is not None and slug == self.dashboard.get_slug():
            return self.dashboard
        return next((p for p in self._pages if p.get_slug() == slug), None)

    def resource_for_model(self, model: Any) -> type[Resource] | None:
        return next((r for r in self._resources if r.model is model), None)

    def all_widgets(self) -> list[type[Widget]]:
        seen: list[type[Widget]] = []
        sources: list[Iterable] = [self._widgets]
        sources += [r.widgets for r in self._resources]
        sources += [p.widgets for p in self._pages]
        if self.dashboard is not None:
            sources.append(self.dashboard.widgets)
        for group in sources:
            for w in group:
                if w not in seen:
                    seen.append(w)
        return seen

    def widget(self, widget_id: str) -> type[Widget] | None:
        return next((w for w in self.all_widgets() if w.get_id() == widget_id), None)

    # ------------------------------------------------------------------ urls
    def url(self, *parts: Any, **query: Any) -> str:
        path = "/".join(str(p).strip("/") for p in parts if p not in (None, ""))
        url = f"{self.path}/{path}" if path else f"{self.path}/"
        query = {k: v for k, v in query.items() if v is not None}
        if query:
            url += "?" + urlencode(query, doseq=True)
        return url

    def asset(self, name: str) -> str:
        return self.url("assets", name) + f"?v={VERSION}"

    # ------------------------------------------------------------------ permissions
    def permission_options(self) -> list[tuple[str, str]]:
        labels = {
            "view_any": "View list", "view": "View", "create": "Create", "update": "Edit", "delete": "Delete",
            "delete_any": "Bulk delete", "restore": "Restore", "restore_any": "Bulk restore",
            "force_delete": "Force delete", "force_delete_any": "Bulk force delete",
        }
        out: list[tuple[str, str]] = [("*", "Everything (super admin)")]
        for r in self._resources:
            for ability in r.abilities():
                out.append((f"{r.permission_prefix()}.{ability}", labels.get(ability, ability.replace("_", " ").title())))
        for p in self._pages:
            if p.permission:
                out.append((p.permission, f"Open {p.get_title()}"))
        for plugin in self._plugins:
            out.extend(getattr(plugin, "permissions", lambda: [])())
        return out

    def permission_group_labels(self) -> dict[str, str]:
        labels = {r.permission_prefix(): r.get_plural_label() for r in self._resources}
        labels["general"] = "General"
        labels["*"] = "General"
        for p in self._pages:
            if p.permission:
                labels[p.permission.rsplit(".", 1)[0]] = "Pages"
        return labels

    # ------------------------------------------------------------------ navigation
    def build_navigation(self, ctx: "Context") -> list[NavigationGroup]:
        current = ctx.request.url.path
        items: list[NavigationItem] = []

        if self.dashboard is not None and self.dashboard.show_in_navigation and self.dashboard.can_access(ctx):
            items.append(NavigationItem(self.dashboard.get_navigation_label(), self.dashboard.get_url(ctx),
                                        self.dashboard.icon, self.dashboard.navigation_group,
                                        self.dashboard.navigation_sort, active=current.rstrip("/") == (self.path or "")))
        for r in self._resources:
            if not r.show_in_navigation or not r.can(ctx, "view_any"):
                continue
            url = r.get_url(ctx)
            badge = call(r.navigation_badge, ctx=ctx, db=ctx.db, user=ctx.user)
            items.append(NavigationItem(r.get_navigation_label(), url, r.icon, r.navigation_group, r.navigation_sort,
                                        badge=badge, badge_color=r.navigation_badge_color, parent=r.navigation_parent,
                                        active=current == url or current.startswith(url + "/")))
        for p in self._pages:
            if not p.show_in_navigation or not p.can_access(ctx):
                continue
            url = p.get_url(ctx)
            badge = call(p.navigation_badge, ctx=ctx, db=ctx.db, user=ctx.user)
            items.append(NavigationItem(p.get_navigation_label(), url, p.icon, p.navigation_group, p.navigation_sort,
                                        badge=badge, badge_color=p.navigation_badge_color, parent=p.navigation_parent,
                                        active=current == url or current.startswith(url + "/")))
        for item in self._nav_items:
            if not evaluate(item.visible, ctx=ctx, user=ctx.user):
                continue
            prefix = item.active_prefix or item.url
            item.active = bool(prefix) and prefix != "#" and (current == prefix or current.startswith(prefix.rstrip("/") + "/"))
            items.append(item)

        # nest children under their parent (matched by label)
        by_label = {i.label: i for i in items}
        top: list[NavigationItem] = []
        for item in items:
            item.children = [c for c in item.children if c not in items]
        for item in items:
            parent = by_label.get(item.parent) if item.parent else None
            if parent is not None and parent is not item:
                parent.children.append(item)
            else:
                top.append(item)

        groups: dict[str | None, NavigationGroup] = {None: NavigationGroup("")}
        for g in self._nav_groups:
            groups[g.label] = NavigationGroup(g.label, g.icon, g.collapsible, g.collapsed)
        for item in sorted(top, key=lambda i: (i.sort, i.label)):
            if item.group not in groups:
                groups[item.group] = NavigationGroup(item.group or "")
            groups[item.group].items.append(item)
        return [g for g in groups.values() if g.items]

    # ------------------------------------------------------------------ rendering
    def hooks(self, name: str, ctx: "Context") -> Markup:
        out = []
        for fn in self._hooks.get(name, []):
            out.append(str(call(fn, ctx=ctx, panel=self, user=ctx.user) or ""))
        return Markup("".join(out))

    def theme_css(self) -> Markup:
        return Markup(color_tools.css_variables(self.colors))

    def csrf_token(self, ctx: "Context") -> str:
        token = ctx.session.get("tw_csrf")
        if not token:
            token = secrets.token_urlsafe(24)
            ctx.session["tw_csrf"] = token
        return token

    def layout_context(self, ctx: "Context") -> dict[str, Any]:
        tenants = self.tenancy.tenants(ctx) if self.tenancy.enabled else []
        return {
            "panel": self,
            "ctx": ctx,
            "user": ctx.user,
            "user_name": self.auth.display_name(ctx.user),
            "user_avatar": self.auth.avatar_url(ctx.user),
            "user_role": self._user_role_label(ctx),
            "navigation": self.build_navigation(ctx) if ctx.user is not None or not self.auth.enabled else [],
            "flash": ctx.pop_flash(),
            "csrf_token": self.csrf_token(ctx),
            "tenant": ctx.tenant,
            "tenants": tenants,
            "tenant_label": self.tenancy.label(ctx.tenant) if self.tenancy.enabled else "",
            "user_menu_items": self._user_menu_items,
            "version": VERSION,
        }

    def _user_role_label(self, ctx: "Context") -> str:
        if ctx.user is None:
            return ""
        if self.auth.rbac:
            roles = self.auth.roles(ctx)
            if roles:
                return ", ".join(r.name for r in roles[:2])
        return str(getattr(ctx.user, "role", "") or "")

    def render_page(self, ctx: "Context", template: str, **context: Any) -> Markup:
        return self.renderer.render(template, **self.layout_context(ctx), **context)

    # ------------------------------------------------------------------ app
    @property
    def app(self) -> Any:
        if self._app is None:
            from .routes import build_app

            self.boot()
            self._app = build_app(self)
        return self._app

    def boot(self) -> None:
        if self._booted:
            return
        self._booted = True
        for plugin in self._plugins:
            plugin.boot(self)

    def mount(self, app: "FastAPI") -> "Panel":
        """Mount the panel into your FastAPI (or Starlette) app at ``path``."""
        app.mount(self.path or "/", self.app, name=f"tungsten-{self.id}")
        return self

    def create_tables(self, engine: Any = None) -> None:
        """Create Tungsten's own tables (roles, notifications, password resets)."""
        from .models import TungstenBase

        engine = engine or self.engine
        if engine is None and self.session_factory is not None:
            engine = self.session_factory.kw.get("bind")  # type: ignore[union-attr]
        TungstenBase.metadata.create_all(engine)

    def log_activity(self, ctx: "Context", event: str, record: Any, description: str | None = None,
                     properties: dict | None = None) -> None:
        if not self.activity_log:
            return
        from sqlalchemy import inspect as sa_inspect

        from .models import ActivityLog

        pk = sa_inspect(type(record)).primary_key[0]
        ctx.db.add(ActivityLog(
            user_id=self.auth.user_id(ctx.user) if ctx.user is not None else None,
            subject_type=type(record).__name__,
            subject_id=str(getattr(record, pk.key)),
            event=event,
            description=description,
            properties=properties or {},
        ))
