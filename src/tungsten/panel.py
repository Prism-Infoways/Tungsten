"""The :class:`Panel`: one admin panel mounted into your FastAPI app."""

from __future__ import annotations

import hashlib
import logging
import secrets
import weakref
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable
from urllib.parse import quote, urlencode

from markupsafe import Markup

from .auth import Auth
from .i18n import LANGUAGE_NAMES, Translator
from .i18n import translate as __
from .navigation import Cluster, NavigationGroup, NavigationItem
from .notifications import with_icon_svg
from .pages import Dashboard, Page
from .rendering import Renderer
from .resources.resource import Resource
from .storage import LocalStorage, Storage
from .support import colors as color_tools
from .support.aio import is_async_engine
from .support.evaluate import call, evaluate
from .tenancy import NoTenancy, Tenancy, current_url_slug
from .widgets import Widget

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

    from .context import Context
    from .plugins import Plugin

STATIC_DIR = Path(__file__).with_name("static")


@lru_cache(maxsize=None)
def asset_version(name: str) -> str:
    """Short hash of a built-in asset, so browsers can cache it forever and still get new versions."""
    try:
        return hashlib.sha1((STATIC_DIR / "tungsten" / name).read_bytes()).hexdigest()[:10]
    except OSError:
        return VERSION


#: paths that never carry the tenant in the URL (signing in happens before a tenant is known)
UNTENANTED_PATHS = ("assets", "plugins", "storage", "login", "logout", "register", "forgot-password",
                    "reset-password", "two-factor", "email-verification", "email-change", "tenant/new")

VERSION = "0.1.12"
VENDOR_FILES = ("chart.umd.min.js", "trix.umd.min.js", "trix.css", "tom-select.complete.min.js", "tom-select.css",
                "sortable.min.js", "qrcode.js")


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

    #: every panel built in this process (so a plain DB session in a script can still find its panel)
    _instances: "weakref.WeakSet[Panel]" = weakref.WeakSet()

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
        top_navigation: bool = False,
        spa: bool = False,
        unsaved_changes_alerts: bool = True,
        tenancy: Tenancy | None = None,
        storage: Storage | None = None,
        global_search: bool = True,
        database_notifications: bool = True,
        notifications_polling: str | None = "30s",
        notifications_live: bool = True,
        broadcaster: Any = None,
        jobs: str = "thread",
        navigation_groups: list[str | NavigationGroup] | None = None,
        dashboard: type[Page] | None = Dashboard,
        template_dirs: Iterable[str | Path] = (),
        login_hero: dict[str, Any] | None = None,
        sidebar_footer: Any = None,
        https_only_cookies: bool = False,
        security_headers: Any = True,
        content_security_policy: Any = True,
        app_url: str | None = None,
        activity_log: bool = False,
        locale: str = "en",
        locales: Iterable[str] | None = None,
        lang_dirs: Iterable[str | Path] = (),
        theme_stylesheet: str | Path | None = None,
    ) -> None:
        Panel._instances.add(self)
        self.id = id
        self.path = "/" + path.strip("/") if path.strip("/") else ""
        if session_factory is None and engine is not None:
            if is_async_engine(engine):
                from sqlalchemy.ext.asyncio import async_sessionmaker

                session_factory = async_sessionmaker(engine, expire_on_commit=False)
            else:
                from sqlalchemy.orm import sessionmaker

                session_factory = sessionmaker(engine, expire_on_commit=False)
        self.session_factory = session_factory
        self.engine = engine
        #: True for ``create_async_engine(...)`` / ``async_sessionmaker``: handlers then run on the event loop
        self.is_async = is_async_engine(session_factory)
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
        #: menu in a bar along the top instead of the sidebar (the sidebar stays as the phone menu)
        self.top_navigation = top_navigation
        self.spa = spa
        self.unsaved_changes_alerts = unsaved_changes_alerts
        self.tenancy = tenancy or NoTenancy()
        self.storage = storage or LocalStorage()
        if getattr(self.storage, "panel", "missing") is None:
            self.storage.panel = self  # type: ignore[attr-defined]
        self.global_search_enabled = global_search
        self.database_notifications = database_notifications
        self.notifications_polling = notifications_polling
        #: push notifications to open tabs over a WebSocket (``/_tw/live``); polling stays as the fallback
        self.notifications_live = notifications_live
        if broadcaster is None:
            from .broadcast import Broadcaster

            broadcaster = Broadcaster()
        self.broadcaster = broadcaster
        if jobs not in ("thread", "worker"):
            raise ValueError('jobs must be "thread" (run in the web process) or "worker" (tungsten jobs:work)')
        #: "thread": background jobs run in the web process; "worker": they only queue, and
        #: ``tungsten jobs:work`` runs them in their own process
        self.jobs_mode = jobs
        self.dashboard = dashboard
        #: the dark panel beside the login form. ``highlight`` is the part of the heading shown in the brand color;
        #: ``features`` is a list of ``{"icon": ..., "label": ...}`` tiles (an empty list hides them).
        self.login_hero = {
            "eyebrow": "Element 74 • Built for FastAPI",
            "heading": "Modern admin panel for Python projects",
            "highlight": "Python projects",
            "text": "The metal that glows in a bulb, now lighting up your data.",
            "features": [
                {"icon": "zap", "label": "Fast development"},
                {"icon": "box", "label": "Beautiful UI components"},
                {"icon": "shield-check", "label": "Secure & role based"},
                {"icon": "chart-column", "label": "Scalable architecture"},
            ],
            **(login_hero or {}),
        }
        self.sidebar_footer = sidebar_footer
        self.https_only_cookies = https_only_cookies
        #: HSTS, X-Frame-Options, nosniff... on every response; a dict adds or replaces headers, False turns off
        self.security_headers = security_headers
        #: True for Tungsten's default CSP, a string to replace it, a dict to add sources, False for none
        self.content_security_policy = content_security_policy
        #: public address of the site (``https://admin.acme.example``) for links in emails
        self.app_url = app_url.rstrip("/") if app_url else None
        self.activity_log = activity_log
        #: default language, and the languages users can pick from (switcher shows when more than one)
        self.locale = locale
        self.locales = list(locales or [locale])
        if locale not in self.locales:
            self.locales.insert(0, locale)
        self.translator = Translator(locale, lang_dirs)
        #: a custom theme's built CSS (``tungsten make:theme``): a file path, or a URL; replaces tungsten.css
        self.theme_stylesheet = theme_stylesheet
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
        self._record_actions: list[dict] = []
        self._plugins: list[Plugin] = []
        self._extra_routes: list[Callable] = []
        #: ``fn(ctx, path, filename, content_type, size, field)`` after a form upload is stored (see on_upload)
        self.upload_listeners: dict[str, Callable] = {}
        #: ``fn(ctx, path, field)`` that lets file fields take an already stored file (see on_file_pick)
        self.file_pick_checks: dict[str, Callable] = {}
        #: ``fn(ctx, paths) -> {path: name}``: the names file fields show for stored files (see on_file_names)
        self.file_name_lookups: dict[str, Callable] = {}
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

    def navigation_group(self, label: str, icon: str | None = None, collapsed: bool = False,
                         collapsible: bool = True) -> "Panel":
        self._nav_groups.append(NavigationGroup(label, icon=icon, collapsible=collapsible, collapsed=collapsed))
        return self

    def user_menu_item(self, label: str, url: str, icon: str | None = None) -> "Panel":
        self._user_menu_items.append({"label": label, "url": url, "icon": icon})
        return self

    def render_hook(self, name: str, fn: Callable) -> "Panel":
        """Inject HTML at a named spot, e.g. ``"head.end"``, ``"sidebar.nav.end"``, ``"content.start"``."""
        self._hooks.setdefault(name, []).append(fn)
        return self

    def record_action(self, target: Any, factory: Callable[[], Any], row: bool = True,
                      pages: Iterable[str] = ("view", "edit")) -> "Panel":
        """Add a button to another resource's rows and record pages, without touching its code.

        Plugins use this to link into each other: ``target`` is a resource class, its model or its
        slug, and ``factory()`` returns a fresh :class:`Action` (hide it with ``.visible(...)``)::

            panel.record_action(User, lambda: Action("login_as").action(...))
        """
        self._record_actions.append({"target": target, "factory": factory, "row": row, "pages": tuple(pages)})
        return self

    def record_actions_for(self, resource: type[Resource], where: str) -> list:
        """Fresh actions added with :meth:`record_action` for ``resource``: ``"row"`` or a page name."""
        out = []
        for item in self._record_actions:
            target = item["target"]
            if target is not resource and target is not resource.model and target != resource.get_slug():
                continue
            if (item["row"] if where == "row" else where in item["pages"]):
                out.append(item["factory"]())
        return out

    def on_upload(self, key: str, fn: Callable) -> "Panel":
        """Run ``fn(ctx, path, filename, content_type, size, field)`` after a form upload is stored.

        Return another stored path to use it instead (a media library can swap a duplicate for the
        file it already has). Errors are logged; they never lose the upload. The same ``key`` replaces ``fn``.
        """
        self.upload_listeners[key] = fn
        return self

    def on_file_pick(self, key: str, fn: Callable) -> "Panel":
        """Let ``FileUpload`` fields take an already stored file: ``fn(ctx, path, field)`` returns True to allow it.

        A media library plugin uses this for its "Choose from library" button. With no check, picks are refused.
        """
        self.file_pick_checks[key] = fn
        return self

    def on_file_names(self, key: str, fn: Callable) -> "Panel":
        """Show friendly names in file fields: ``fn(ctx, paths)`` returns ``{path: "Team photo.png"}``.

        Without one, a field shows the stored file name (a random id).
        """
        self.file_name_lookups[key] = fn
        return self

    def file_names(self, ctx: "Context | None", paths: list[str]) -> dict[str, str]:
        names: dict[str, str] = {}
        if ctx is None or not paths:
            return names
        for key, fn in list(self.file_name_lookups.items()):
            try:
                names.update(call(fn, ctx=ctx, paths=list(paths), panel=self) or {})
            except Exception:
                logging.getLogger("tungsten").exception("File name lookup %r failed", key)
        return names

    def uploaded(self, ctx: "Context", path: str, filename: str, content_type: str, size: int, field: Any) -> str:
        """Tell the upload listeners about a stored upload; returns the path to keep."""
        for key, fn in list(self.upload_listeners.items()):
            try:
                result = call(fn, ctx=ctx, path=path, filename=filename, content_type=content_type, size=size,
                              field=field, panel=self)
            except Exception:  # a listener must never lose the user's upload
                logging.getLogger("tungsten").exception("Upload listener %r failed", key)
                continue
            if isinstance(result, str) and result:
                path = result
        return path

    def can_pick_file(self, ctx: "Context", path: str, field: Any) -> bool:
        """True when a pick check allows ``path`` for ``field``."""
        for key, fn in list(self.file_pick_checks.items()):
            try:
                if call(fn, ctx=ctx, path=path, field=field, panel=self):
                    return True
            except Exception:
                logging.getLogger("tungsten").exception("File pick check %r failed", key)
        return False

    def routes(self, fn: Callable) -> Callable:
        """Decorator to add your own routes to the panel app: ``fn(router, panel)``."""
        self._extra_routes.append(fn)
        return fn

    def plugin(self, plugin: "Plugin") -> "Panel":
        self._plugins.append(plugin)
        if plugin.templates:
            self.renderer.add_dir(plugin.templates)
        if plugin.lang:
            self.translator.add_dir(plugin.lang)
        plugin.register(self)
        return self

    def plugin_asset(self, plugin_id: str, name: str) -> str:
        """URL of a file in a plugin's ``static`` folder."""
        return self.url("plugins", plugin_id, name)

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

    def get_clusters(self) -> list[type[Cluster]]:
        """Clusters used by the panel's resources and pages, in registration order."""
        out: list[type[Cluster]] = []
        for member in [*self._resources, *self._pages]:
            cluster = getattr(member, "cluster", None)
            if cluster is not None and cluster not in out:
                out.append(cluster)
        return out

    def cluster(self, slug: str) -> type[Cluster] | None:
        return next((c for c in self.get_clusters() if c.get_slug() == slug), None)

    def cluster_navigation(self, ctx: "Context", cluster: type[Cluster]) -> list[NavigationItem]:
        """The cluster's sub-menu: its resources and pages the user may open, sorted."""
        current = ctx.request.url.path
        items = []
        for r in self._resources:
            if r.cluster is cluster and r.show_in_navigation and r.can(ctx, "view_any"):
                url = r.get_url(ctx)
                items.append(NavigationItem(r.get_navigation_label(), url, r.icon, sort=r.navigation_sort,
                                            group=r.navigation_group,
                                            badge=call(r.navigation_badge, ctx=ctx, db=ctx.db, user=ctx.user),
                                            badge_color=r.navigation_badge_color, active_icon=r.active_icon,
                                            active=current == url or current.startswith(url + "/")))
        for p in self._pages:
            if p.cluster is cluster and p.show_in_navigation and p.can_access(ctx):
                url = p.get_url(ctx)
                items.append(NavigationItem(p.get_navigation_label(), url, p.icon, sort=p.navigation_sort,
                                            group=p.navigation_group,
                                            badge=call(p.navigation_badge, ctx=ctx, db=ctx.db, user=ctx.user),
                                            badge_color=p.navigation_badge_color,
                                            active=current == url or current.startswith(url + "/")))
        return sorted(items, key=lambda i: (i.sort, i.label))

    def sub_navigation(self, ctx: "Context", resource: Any = None, record: Any = None,
                       page: Any = None) -> dict | None:
        """The sub-menu for the current page: the record's own, else its cluster's. None when there is none."""
        current = ctx.request.url.path
        if resource is not None and record is not None:
            items = list(resource.get_record_sub_navigation(ctx, record) or [])
            if items:
                # the deepest link that holds the current page is active (``/teams/1`` vs ``/teams/1/projects``)
                def holds(url: str) -> bool:
                    path = url.split("?", 1)[0].rstrip("/")
                    return current.rstrip("/") == path or current.startswith(path + "/")

                best = max((i for i in items if holds(i.url)), key=lambda i: len(i.url), default=None)
                for item in items:
                    item.active = item is best
                position = resource.sub_navigation_position or ("start" if resource.record_sub_navigation else "top")
                return {"items": items, "position": position,
                        "heading": resource.get_record_title(record), "description": None}
        owner = resource if resource is not None else page
        cluster = getattr(owner, "cluster", None)
        if cluster is None:
            return None
        items = self.cluster_navigation(ctx, cluster)
        if not items:
            return None
        return {"items": items, "position": cluster.sub_navigation_position, "heading": cluster.get_label(),
                "description": cluster.description}

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
        slug = current_url_slug()
        if slug and not any(path == p or path.startswith(p + "/") for p in UNTENANTED_PATHS):
            path = f"{quote(slug, safe='')}/{path}"
        url = f"{self.path}/{path}" if path else f"{self.path}/"
        query = {k: v for k, v in query.items() if v is not None}
        if query:
            url += "?" + urlencode(query, doseq=True)
        return url

    def absolute_url(self, ctx: "Context", path: str) -> str:
        """A full link to ``path`` (from :meth:`url`) for emails.

        Uses ``app_url`` when set. Otherwise it falls back to the request's
        scheme and ``Host`` header, which a client can forge: set ``app_url``
        in production.
        """
        if self.app_url:
            return f"{self.app_url}{path}"
        url = ctx.request.url
        return f"{url.scheme}://{url.netloc}{path}"

    def asset(self, name: str) -> str:
        return self.url("assets", name) + f"?v={asset_version(name)}"

    def theme_file(self) -> Path | None:
        """The custom theme's CSS file, when ``theme_stylesheet`` is a file path (not a URL)."""
        value = self.theme_stylesheet
        if value is None:
            return None
        if isinstance(value, str) and (value.startswith(("http://", "https://", "//"))
                                       or (value.startswith("/") and not Path(value).is_file())):
            return None
        return Path(value)

    def stylesheet(self) -> str:
        """URL of the panel's CSS: the custom theme when set, else Tungsten's built-in tungsten.css."""
        if self.theme_stylesheet is None:
            return self.asset("tungsten.css")
        file = self.theme_file()
        if file is None:
            return str(self.theme_stylesheet)
        try:
            stat = file.stat()
        except OSError:
            if not getattr(self, "_theme_missing_logged", False):
                self._theme_missing_logged = True
                logging.getLogger("tungsten").warning(
                    "Theme stylesheet %s not found; using the built-in CSS. Run `tungsten theme:build`.", file)
            return self.asset("tungsten.css")
        key = (stat.st_mtime_ns, stat.st_size)
        cached = getattr(self, "_theme_version", None)
        if cached is None or cached[0] != key:  # rebuilt themes get a new ?v=, so browsers fetch them again
            cached = self._theme_version = (key, hashlib.sha1(file.read_bytes()).hexdigest()[:10])
        return self.url("theme.css") + f"?v={cached[1]}"

    def vendor_assets(self) -> dict[str, str]:
        """Big libraries that ``tungsten.js`` loads only when a page needs them."""
        return {name: self.asset(f"vendor/{name}") for name in VENDOR_FILES}

    # ------------------------------------------------------------------ languages
    def resolve_locale(self, ctx: "Context") -> str:
        """The user's pick, else the browser's language (when allowed), else the default."""
        chosen = ctx.session.get("tw_locale") if "session" in ctx.request.scope else None
        if chosen in self.locales:
            return chosen
        if len(self.locales) > 1:
            found = self.translator.negotiate(ctx.request.headers.get("accept-language"), self.locales)
            if found:
                return found
        return self.locale

    def language_options(self) -> list[dict[str, str]]:
        return [{"code": code, "label": LANGUAGE_NAMES.get(code.split("_")[0], code)} for code in self.locales]

    # ------------------------------------------------------------------ permissions
    def permission_options(self) -> list[tuple[str, str]]:
        labels = {
            "view_any": "View list", "view": "View", "create": "Create", "update": "Edit", "delete": "Delete",
            "delete_any": "Bulk delete", "restore": "Restore", "restore_any": "Bulk restore",
            "force_delete": "Force delete", "force_delete_any": "Bulk force delete",
        }
        out: list[tuple[str, str]] = [("*", __("Everything (super admin)"))]
        for r in self._resources:
            for ability in r.abilities():
                out.append((f"{r.permission_prefix()}.{ability}",
                            __(labels.get(ability, ability.replace("_", " ").title()))))
        for p in self._pages:
            if p.permission:
                out.append((p.permission, __("Open :page", page=p.get_title())))
        for plugin in self._plugins:
            out.extend(getattr(plugin, "permissions", lambda: [])())
        return out

    def permission_group_labels(self) -> dict[str, str]:
        labels = {r.permission_prefix(): r.get_plural_label() for r in self._resources}
        labels["general"] = __("General")
        labels["*"] = __("General")
        for p in self._pages:
            if p.permission:
                labels[p.permission.rsplit(".", 1)[0]] = __("Pages")
        return labels

    # ------------------------------------------------------------------ navigation
    def build_navigation(self, ctx: "Context") -> list[NavigationGroup]:
        current = ctx.request.url.path
        items: list[NavigationItem] = []

        if self.dashboard is not None and self.dashboard.show_in_navigation and self.dashboard.can_access(ctx):
            items.append(NavigationItem(self.dashboard.get_navigation_label(), self.dashboard.get_url(ctx),
                                        self.dashboard.icon, self.dashboard.navigation_group,
                                        self.dashboard.navigation_sort, active=current.rstrip("/") == self.url().rstrip("/")))
        for r in self._resources:
            if r.cluster is not None or not r.show_in_navigation or r.parent_resource is not None \
                    or not r.can(ctx, "view_any"):
                continue
            url = r.get_url(ctx)
            badge = call(r.navigation_badge, ctx=ctx, db=ctx.db, user=ctx.user)
            items.append(NavigationItem(r.get_navigation_label(), url, r.icon, r.navigation_group, r.navigation_sort,
                                        badge=badge, badge_color=r.navigation_badge_color, parent=r.navigation_parent,
                                        active=current == url or current.startswith(url + "/"),
                                        active_icon=r.active_icon))
        for p in self._pages:
            if p.cluster is not None or not p.show_in_navigation or not p.can_access(ctx):
                continue
            url = p.get_url(ctx)
            badge = call(p.navigation_badge, ctx=ctx, db=ctx.db, user=ctx.user)
            items.append(NavigationItem(p.get_navigation_label(), url, p.icon, p.navigation_group, p.navigation_sort,
                                        badge=badge, badge_color=p.navigation_badge_color, parent=p.navigation_parent,
                                        active=current == url or current.startswith(url + "/"),
                                        active_icon=getattr(p, "active_icon", None)))
        for cluster in self.get_clusters():
            members = self.cluster_navigation(ctx, cluster)
            if members:
                items.append(NavigationItem(cluster.get_navigation_label(), self.url(cluster.get_slug()), cluster.icon,
                                            cluster.navigation_group, cluster.navigation_sort,
                                            active=any(m.active for m in members), active_icon=cluster.active_icon))
        for item in self._nav_items:
            if evaluate(item.visible, ctx=ctx, user=ctx.user):
                items.append(self._custom_nav_item(ctx, item, current))

        # nest children under their parent (matched by label)
        by_label = {i.label: i for i in items}
        top: list[NavigationItem] = []
        for item in items:
            # parents are named in English in code; labels may be translated
            parent = (by_label.get(__(item.parent)) or by_label.get(item.parent)) if item.parent else None
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

    def _custom_nav_item(self, ctx: "Context", item: NavigationItem, current: str) -> NavigationItem:
        """A per-request copy of a custom item: the registered one is shared between requests, so never changed."""
        prefix = item.active_prefix or item.url
        active = bool(prefix) and prefix != "#" and (current == prefix or current.startswith(prefix.rstrip("/") + "/"))
        children = [self._custom_nav_item(ctx, c, current) for c in item.children
                    if evaluate(c.visible, ctx=ctx, user=ctx.user)]
        return replace(item, active=active, children=children)

    # ------------------------------------------------------------------ rendering
    def hooks(self, name: str, ctx: "Context", **extra: Any) -> Markup:
        """HTML of the hooks at ``name``. ``extra`` (like ``resource`` and ``table``) goes to hooks that ask for it."""
        out = []
        for fn in self._hooks.get(name, []):
            out.append(str(call(fn, ctx=ctx, panel=self, user=ctx.user, **extra) or ""))
        return Markup("".join(out))

    def theme_css(self) -> Markup:
        key = repr(sorted(self.colors.items()))  # colors can change after setup, so cache by value
        cached = getattr(self, "_theme_css", None)
        if cached is None or cached[0] != key:
            cached = self._theme_css = (key, Markup(color_tools.css_variables(self.colors)))
        return cached[1]

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
            "flash": [with_icon_svg(n) for n in ctx.pop_flash()],
            "csrf_token": self.csrf_token(ctx),
            "tenant": ctx.tenant,
            "tenants": tenants,
            "tenant_label": self.tenancy.label(ctx.tenant) if self.tenancy.enabled else "",
            "tenant_menu": self._tenant_menu(ctx),
            "tenant_register_url": self.url("tenant", "new")
            if self.tenancy.enabled and self.tenancy.registration is not None and ctx.user is not None else None,
            "user_menu_items": self._user_menu_items,
            "version": VERSION,
        }

    def _tenant_menu(self, ctx: "Context") -> list[dict]:
        """Links at the top of the tenant switcher: settings and billing of the current tenant."""
        tenancy = self.tenancy
        if not tenancy.enabled or ctx.tenant is None or ctx.user is None:
            return []
        out = []
        if tenancy.can_profile(ctx):
            out.append({"label": __(":label settings", label=tenancy.get_label()), "icon": "settings",
                        "url": self.url("tenant", "profile")})
        if tenancy.can_billing(ctx):
            out.append({"label": __(tenancy.billing.label), "icon": tenancy.billing.icon,
                        "url": self.url("tenant", "billing")})
        return out

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

    def api_user(self, *abilities: str) -> Callable:
        """FastAPI dependency: the user of the ``Authorization: Bearer`` API token (needs ``Auth(api_tokens=True)``).

        ``Depends(panel.api_user("orders:read"))`` also checks the token was given those abilities.
        """
        from .auth.tokens import dependency

        return dependency(self, abilities)

    def boot(self) -> None:
        if self._booted:
            return
        self._booted = True
        for plugin in self._plugins:
            plugin.boot(self)

    def mount(self, app: "FastAPI") -> "Panel":
        """Mount the panel into your FastAPI (or Starlette) app at ``path``."""
        for plugin in self._plugins:
            plugin.mount(app, self)  # first, so a panel at "/" doesn't hide the plugin's routes
        app.mount(self.path or "/", self.app, name=f"tungsten-{self.id}")
        return self

    def _engine(self, engine: Any = None) -> Any:
        engine = engine or self.engine
        if engine is None and self.session_factory is not None:
            engine = self.session_factory.kw.get("bind")  # type: ignore[union-attr]
        return engine

    def create_tables(self, engine: Any = None) -> None:
        """Create Tungsten's own tables (roles, notifications, password resets).

        With an async engine, call this outside a running event loop or use
        ``await panel.acreate_tables()``.
        """
        engine = self._engine(engine)
        if is_async_engine(engine):
            import asyncio

            asyncio.run(self.acreate_tables(engine))
            return
        with engine.begin() as conn:
            self._create_tables(conn)

    def _create_tables(self, conn: Any) -> None:
        from .support.schema import add_missing_columns

        for metadata in self._all_metadata():
            metadata.create_all(conn)
            add_missing_columns(conn, metadata)  # columns added to Tungsten's tables by an upgrade

    async def acreate_tables(self, engine: Any = None) -> None:
        """Async version of :meth:`create_tables` for an async engine."""
        engine = self._engine(engine)
        async with engine.begin() as conn:
            await conn.run_sync(self._create_tables)

    def _all_metadata(self) -> list[Any]:
        from .models import TungstenBase

        out = [TungstenBase.metadata]
        for plugin in self._plugins:
            if plugin.metadata is not None and plugin.metadata not in out:
                out.append(plugin.metadata)
        return out

    def with_session(self, fn: Callable[[Any], Any]) -> Any:
        """Run ``fn(db)`` with a sync DB session, for scripts and the CLI (async engines too).

        With an async engine this starts a private event loop, so call it
        from sync code only.
        """
        def run(db: Any) -> Any:
            db.info["tungsten_panel"] = self
            return fn(db)

        if not self.is_async:
            with self.session_factory() as db:
                return run(db)
        import asyncio

        async def go() -> Any:
            async with self.session_factory() as adb:
                return await adb.run_sync(run)

        return asyncio.run(go())

    @property
    def jobs(self) -> Any:
        """The panel's :class:`~tungsten.jobs.JobRunner` (background bulk actions, exports, your own jobs)."""
        runner = self.__dict__.get("_jobs")
        if runner is None:
            from .jobs import JobRunner

            runner = self.__dict__["_jobs"] = JobRunner(self, mode=self.jobs_mode)
        return runner

    @staticmethod
    def of(db: Any) -> "Panel | None":
        """The panel a DB session belongs to, inside a panel request or :meth:`with_session` (plugins use this)."""
        return getattr(db, "info", {}).get("tungsten_panel")

    @staticmethod
    def only() -> "Panel | None":
        """The app's panel when it has exactly one (the usual case), else ``None``."""
        panels = list(Panel._instances)
        return panels[0] if len(panels) == 1 else None

    def log_activity(self, ctx: "Context", event: str, record: Any = None, description: str | None = None,
                     properties: dict | None = None, *, subject_type: str | None = None,
                     subject_id: Any = None, user: Any = None, commit: bool = False) -> None:
        """Add a row to the activity log (when ``activity_log=True``).

        ``record`` is what the event is about; leave it out and pass ``subject_type`` / ``subject_id`` for
        events without a record. ``user`` is who did it (the signed-in user by default). The same event on the
        same record is written once per request, so a plugin that logs a delete itself is not counted twice.
        """
        if not self.activity_log:
            return
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.exc import NoInspectionAvailable

        from .models import ActivityLog

        if record is not None:
            try:
                pk = sa_inspect(type(record)).primary_key[0]
                subject_id = getattr(record, pk.key) if subject_id is None else subject_id
            except (NoInspectionAvailable, IndexError):
                pass
            subject_type = subject_type or type(record).__name__
        subject_type = (subject_type or "")[:100]
        subject_id = "" if subject_id is None else str(subject_id)[:64]
        seen = ctx.__dict__.setdefault("_tw_activity_logged", set())
        key = (event, subject_type, subject_id)
        if record is not None and key in seen:
            return
        seen.add(key)
        user = ctx.user if user is None else user
        ctx.db.add(ActivityLog(
            user_id=self.auth.user_id(user) if user is not None and self.auth.enabled else None,
            subject_type=subject_type,
            subject_id=subject_id,
            event=event[:50],
            description=description,
            properties=properties or {},
        ))
        if commit:
            ctx.db.commit()

    def log_auth_event(self, ctx: "Context", event: str, user: Any = None, description: str | None = None,
                       **properties: Any) -> None:
        """Log a sign-in event (``login``, ``logout``, ``login_failed`` ...) with the visitor's IP and browser."""
        if not self.activity_log:
            return
        request = ctx.request
        props = {
            "ip": request.client.host if request.client else None,
            "user_agent": (request.headers.get("user-agent") or "")[:255],
            **{k: v for k, v in properties.items() if v is not None},
        }
        model = self.auth.user_model
        self.log_activity(ctx, event, user, description, props, user=user,
                          subject_type=None if user is not None else getattr(model, "__name__", "User"),
                          commit=True)
