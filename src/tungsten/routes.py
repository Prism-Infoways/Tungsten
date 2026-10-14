"""HTTP routes for a panel. Handlers are plain sync functions with their own
DB session: in a thread pool for a sync engine, or inside
``AsyncSession.run_sync`` for an async engine (see :meth:`Routes.run`)."""

from __future__ import annotations

import logging
import re
import secrets
import time
from typing import TYPE_CHECKING, Any, Callable

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from sqlalchemy import String, cast, func, or_, select, update
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import QueryParams
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from .actions.action import MAX_MODAL_LEVEL, Action, BulkAction, Halt, flatten_actions, modal_target
from .context import Context
from .forms.form import Form, ValidationError
from .hosts import Host, RelationHost
from .i18n import maybe, reset_locale, set_locale
from .i18n import translate as __
from .notifications import Notification
from .panel import STATIC_DIR
from .support.aio import blocking
from .support.evaluate import call, evaluate
from .tables.columns import EditableColumn
from .tenancy import reset_url_slug, set_url_slug

if TYPE_CHECKING:  # pragma: no cover
    from .panel import Panel


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class CachedStaticFiles(StaticFiles):
    """Asset URLs carry a content hash (``?v=``), so browsers may keep them for a year."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class TenantPathMiddleware:
    """For ``Tenancy(url=True)``: ``/admin/{tenant}/products`` routes like ``/admin/products``.

    The tenant's part moves into ``root_path`` (so ``request.url`` keeps it) and into
    ``scope["tw_tenant"]``. Paths whose first part is one of the panel's own routes
    (``login``, ``assets``, ``_tw``...) have no tenant part.
    """

    def __init__(self, app: Any, reserved: Callable[[], set[str]]) -> None:
        self.app = app
        self._reserved = reserved
        self._cache: set[str] | None = None

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            root = scope.get("root_path", "")
            path = scope["path"]
            rest = path[len(root):] if root and path.startswith(root) else path
            first = rest.lstrip("/").split("/", 1)[0]
            if self._cache is None:
                self._cache = self._reserved()
            if first and first not in self._cache:
                scope = dict(scope, root_path=f"{root}/{first}", tw_tenant=first)
        await self.app(scope, receive, send)


def build_app(panel: "Panel") -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, title=panel.brand_name)
    app.add_middleware(
        SessionMiddleware,
        secret_key=panel.secret_key,
        session_cookie=f"tungsten_{panel.id}",
        same_site="lax",
        https_only=panel.https_only_cookies,
    )
    # compress pages, CSS and JS (a list page shrinks from ~130 KB to ~15 KB)
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)  # level 9 is ~2x slower for ~1% smaller pages
    if panel.security_headers is not False or panel.content_security_policy is not False:
        from .security import SecurityHeadersMiddleware

        app.add_middleware(SecurityHeadersMiddleware, headers=panel.security_headers,
                           content_security_policy=panel.content_security_policy,
                           hsts=panel.security_headers is not False)
    app.mount("/assets", CachedStaticFiles(directory=STATIC_DIR / "tungsten"), name="assets")

    @app.get("/theme.css", include_in_schema=False)
    def theme_css() -> Response:  # the custom theme from `tungsten make:theme`, when it is a file
        file = panel.theme_file()
        if file is None or not file.is_file():
            return Response("Not found", status_code=404)
        return FileResponse(file, media_type="text/css",
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    for plugin in panel._plugins:
        if plugin.static:
            app.mount(f"/plugins/{plugin.id}", StaticFiles(directory=str(plugin.static)), name=f"plugin-{plugin.id}")
    if panel.tenancy.in_url:
        def reserved() -> set[str]:
            out = set()
            for route in app.routes:
                first = str(getattr(route, "path", "")).strip("/").split("/", 1)[0]
                if first and not first.startswith("{"):
                    out.add(first)
            return out

        app.add_middleware(TenantPathMiddleware, reserved=reserved)
    routes = Routes(panel)
    routes.register(app)
    return app


class Routes:
    def __init__(self, panel: "Panel") -> None:
        self.panel = panel

    # ------------------------------------------------------------------ plumbing
    async def run(self, request: Request, handler: Callable, *, public: bool = False, read_form: bool = False,
                  **kwargs: Any) -> Response:
        # polling (marked by tungsten.js) doesn't count as activity for ``Auth(idle_timeout=...)``
        request.state.tw_background = request.headers.get("X-TW-Background") == "1"
        formdata = None
        if read_form and request.method == "POST":
            formdata = await request.form(max_files=50, max_fields=10000)
        panel = self.panel
        if panel.session_factory is None:
            raise RuntimeError("Panel needs session_factory= or engine=")
        try:
            if panel.is_async:
                # the same sync handler runs on the event loop; SQLAlchemy drives the async driver underneath
                async with panel.session_factory() as adb:
                    return await adb.run_sync(self._handle, request, handler, public, formdata, kwargs)
            return await run_in_threadpool(self._run_sync, request, handler, public, formdata, kwargs)
        finally:
            if formdata is not None:
                await formdata.close()

    def _run_sync(self, request: Request, handler: Callable, public: bool, formdata: Any, kwargs: dict) -> Response:
        with self.panel.session_factory() as db:
            return self._handle(db, request, handler, public, formdata, kwargs)

    def _handle(self, db: Any, request: Request, handler: Callable, public: bool, formdata: Any,
                kwargs: dict) -> Response:
        panel = self.panel
        db.info["tungsten_panel"] = panel
        ctx = Context(panel, request, db)
        tokens = set_locale(panel.resolve_locale(ctx), panel.translator)
        slug_token = set_url_slug(None)  # _dispatch sets it once the tenant is known
        try:
            return self._dispatch(ctx, db, handler, public, formdata, kwargs)
        finally:
            reset_url_slug(slug_token)
            reset_locale(tokens)

    def _dispatch(self, ctx: Context, db: Any, handler: Callable, public: bool, formdata: Any,
                  kwargs: dict) -> Response:
        panel = self.panel
        request = ctx.request
        if panel.auth.enabled:
            ctx.user = panel.auth.load_user(ctx)
            if ctx.user is not None and not panel.auth.allowed(ctx, ctx.user):
                panel.auth.logout(ctx)
            if not public:
                blocked = self._gate(ctx)
                if blocked is not None:
                    return blocked
        ctx.tenant = panel.tenancy.resolve(ctx)
        if panel.tenancy.enabled:
            blocked = self._tenant_gate(ctx, handler, public)
            if blocked is not None:
                return blocked
        if request.method == "POST" and not self._csrf_ok(ctx, formdata):
            return HTMLResponse(__("Page expired. Please refresh and try again."), status_code=419)
        try:
            return handler(ctx, formdata, **kwargs)
        except NotFound:
            db.rollback()
            return self.error(ctx, 404, __("Page not found"), __("We couldn't find what you were looking for."))
        except (Forbidden, PermissionError):
            db.rollback()
            return self.error(ctx, 403, __("Not allowed"), __("You don't have permission to do that."))
        except Exception:
            db.rollback()
            raise

    def _gate(self, ctx: Context) -> Response | None:
        """Send signed-out users to login, and users who still owe a step (2FA setup) to that step."""
        panel = self.panel
        request = ctx.request
        if ctx.user is None:
            if ctx.session.pop("tw_idle_out", None):
                Notification("You were signed out").body(
                    "You were away for a while, so we signed you out to keep your account safe.").warning().send(ctx)
            return ctx.go(panel.url("login", next=request.url.path if request.method == "GET" else None))
        path = request.url.path.rstrip("/")
        if panel.auth.email_verification and path != panel.url("email-verification", "prompt"):
            from .auth.verification import needs_verification

            if needs_verification(panel, ctx.user):
                return ctx.go(panel.url("email-verification", "prompt"))
        if panel.auth.two_factor_required and path != panel.url("two-factor"):
            from .auth.two_factor import TwoFactor

            if not TwoFactor(ctx, ctx.user).enabled:
                Notification("Two-factor authentication required").body(
                    "Please set up two-factor authentication to continue.").warning().send(ctx)
                return ctx.go(panel.url("two-factor"))
        return None

    def _tenant_gate(self, ctx: Context, handler: Callable, public: bool) -> Response | None:
        """Tenant in the URL: check it, or send the user to a URL that has one; then the subscription check."""
        panel = self.panel
        tenancy = panel.tenancy
        request = ctx.request
        page_handlers = (self.home, self.index, self.create, self.record_page)
        if tenancy.in_url:
            slug = request.scope.get("tw_tenant")
            if slug is not None and ctx.tenant is None:
                if ctx.user is None:
                    return None if public else self.error(ctx, 404, "Page not found",
                                                          "We couldn't find what you were looking for.")
                # an old link without the tenant (``/admin/products``): add the last-used tenant to it
                fallback = None
                if panel.resource(slug) is not None or panel.page(slug) is not None or panel.cluster(slug) is not None:
                    request.scope.pop("tw_tenant", None)
                    fallback = tenancy.resolve(ctx)
                if fallback is None or request.method != "GET":
                    return self.error(ctx, 404, "Page not found", "We couldn't find what you were looking for.")
                return ctx.go(self._in_tenant(ctx, fallback))
            if ctx.tenant is not None:
                set_url_slug(tenancy.slug_of(ctx.tenant))
            if slug is None and not public and ctx.user is not None \
                    and getattr(handler, "__func__", None) in [h.__func__ for h in page_handlers]:
                if ctx.tenant is not None and request.method == "GET":
                    return ctx.go(self._in_tenant(ctx, ctx.tenant))
                if ctx.tenant is None and tenancy.registration is not None:
                    return ctx.go(panel.url("tenant", "new"))
        billing = tenancy.billing
        if (billing is not None and tenancy.require_subscription and not public and ctx.tenant is not None
                and getattr(handler, "__func__", None) not in
                (Routes.tenant_billing, Routes.tenant_profile, Routes.tenant_register, Routes.logout,
                 Routes.profile, Routes.switch_tenant)
                and not billing.is_subscribed(ctx, ctx.tenant)):
            return ctx.go(panel.url("tenant", "billing"))
        return None

    def _in_tenant(self, ctx: Context, tenant: Any) -> str:
        """The current URL, moved inside ``tenant``."""
        panel = self.panel
        rest = ctx.request.url.path[len(panel.path):].lstrip("/")
        url = panel.tenancy.url(ctx, tenant) + rest
        query = ctx.request.url.query
        return f"{url}?{query}" if query else url

    def _csrf_ok(self, ctx: Context, formdata: Any) -> bool:
        expected = ctx.session.get("tw_csrf")
        if not expected:
            return False
        given = ctx.request.headers.get("X-CSRF-Token") or (formdata.get("_token") if formdata is not None else None)
        return bool(given) and secrets.compare_digest(str(given), str(expected))

    def error(self, ctx: Context, status: int, title: str, message: str) -> Response:
        if ctx.is_htmx:
            Notification(title).body(message).danger().send(ctx)
            return ctx.finalize(Response(status_code=204))
        title, message = __(title), __(message)
        html = self.panel.render_page(ctx, "tungsten/pages/error.html", status=status, title=title, message=message)
        return HTMLResponse(str(html), status_code=status)

    # ------------------------------------------------------------------ resolution
    def resolve_host(self, ctx: Context, key: str | None) -> Host:
        panel = self.panel
        if not key:
            raise NotFound()
        kind, _, rest = key.partition(":")
        if kind == "resource":
            resource = panel.resource(rest)
            if resource is None:
                raise NotFound()
            if not resource.can(ctx, "view_any"):
                raise Forbidden()
            return resource.host()
        if kind == "relation":
            try:
                slug, owner_key, name = rest.split(":", 2)
            except ValueError:
                raise NotFound() from None
            resource = panel.resource(slug)
            if resource is None:
                raise NotFound()
            owner = resource.host().find_record(ctx, owner_key)
            if owner is None:
                raise NotFound()
            if not resource.can(ctx, "view", owner):
                raise Forbidden()
            manager = next((m for m in resource.get_relations() if m.get_name() == name), None)
            if manager is None:
                raise NotFound()
            return RelationHost(resource, owner, manager)
        if kind == "widget":
            widget = panel.widget(rest)
            if widget is None or not hasattr(widget, "host"):
                raise NotFound()
            if not widget.can_view(ctx):
                raise Forbidden()
            return widget.host()
        if kind == "page":
            page = panel.page("" if rest == "_dashboard" else rest)
            if page is None:
                raise NotFound()
            if not page.can_access(ctx):
                raise Forbidden()
            return page.host()
        if kind in ("tenant-register", "tenant-profile") and panel.tenancy.enabled:
            from .tenancy import TenantHost

            tenant_host = TenantHost(panel.tenancy, kind.split("-", 1)[1])
            if not tenant_host.can(ctx, "update"):
                raise Forbidden()
            return tenant_host  # type: ignore[return-value]
        if kind == "profile" and panel.auth.enabled:
            from .auth.profile import ProfileHost

            return ProfileHost(panel)
        raise NotFound()

    def find_action(self, ctx: Context, host: Host, scope: str, name: str, record: Any = None,
                    params: Any = None) -> Action:
        """The action ``name`` (``parent/child`` for an action opened from another action's modal)."""
        root_name, *nested = (name or "").split("/")
        action = self._find_root_action(ctx, host, scope, root_name, record, params)
        for part in nested:
            child = action.find_nested(part)
            if child is None:
                raise NotFound()
            child.scope = action.scope
            action = child
        return action

    def _find_root_action(self, ctx: Context, host: Host, scope: str, name: str, record: Any = None,
                          params: Any = None) -> Action:
        if scope == "page":
            getter = getattr(host, "all_page_actions", None) or host.page_actions
            for a in flatten_actions(getter(ctx, record)):
                if a.name == name:
                    a.scope = "page"
                    return a
            raise NotFound()
        if scope == "infolist":  # a button on an infolist entry
            infolist = host.infolist(ctx, record) if record is not None else None
            for a in (infolist.entry_actions() if infolist is not None else []):
                if a.name == name:
                    a.scope = "infolist"
                    return a
            raise NotFound()
        table = host.get_table(ctx)
        if table is None:
            raise NotFound()
        table.bind(ctx, host, params=params if params is not None else QueryParams(""))
        action = table.find_action(scope, name)
        if action is None:
            raise NotFound()
        return action

    @staticmethod
    def action_available(action: Action, host: Host, ctx: Context, record: Any) -> bool:
        """The action and every action whose modal it was opened from may be used."""
        current: Action | None = action
        while current is not None:
            if not current.is_available(host, ctx, record):
                return False
            current = current._parent
        return True

    def host_form(self, ctx: Context, host: Host, operation: str, record: Any) -> Form:
        form = host.form(ctx, operation, record)
        if form is None:
            raise NotFound()
        if form.ctx is None or form.source.get("kind") != "host":
            form.bind(ctx, operation=operation, record=record,
                      source={"kind": "host", "host": host.key, "op": operation,
                              "record": host.record_key(record) if record is not None else ""})
        return form

    def check_operation(self, ctx: Context, host: Host, operation: str, record: Any) -> None:
        ability = {"create": "create", "edit": "update", "view": "view"}.get(operation, "update")
        if not host.can(ctx, ability, record):
            raise Forbidden()

    # ------------------------------------------------------------------ routes
    def register(self, app: FastAPI) -> None:
        r = self
        g, p = app.get, app.post

        @g("/storage/{path:path}")
        async def storage(request: Request, path: str):
            # uploads need a signed-in user, unless the storage is explicitly public
            public = bool(getattr(r.panel.storage, "is_public", lambda p: False)(path))
            return await r.run(request, r.storage_file, public=public, path=path)

        # auth
        @g("/login")
        async def login(request: Request):
            return await r.run(request, r.login, public=True)

        @p("/login")
        async def login_post(request: Request):
            return await r.run(request, r.login, public=True, read_form=True)

        @p("/logout")
        async def logout(request: Request):
            return await r.run(request, r.logout, public=True, read_form=True)

        @g("/register")
        async def register(request: Request):
            return await r.run(request, r.sign_up, public=True)

        @p("/register")
        async def register_post(request: Request):
            return await r.run(request, r.sign_up, public=True, read_form=True)

        @g("/forgot-password")
        async def forgot(request: Request):
            return await r.run(request, r.forgot_password, public=True)

        @p("/forgot-password")
        async def forgot_post(request: Request):
            return await r.run(request, r.forgot_password, public=True, read_form=True)

        @g("/reset-password/{token}")
        async def reset(request: Request, token: str):
            return await r.run(request, r.reset_password, public=True, token=token)

        @p("/reset-password/{token}")
        async def reset_post(request: Request, token: str):
            return await r.run(request, r.reset_password, public=True, read_form=True, token=token)

        @g("/two-factor/challenge")
        async def two_factor_challenge(request: Request):
            return await r.run(request, r.two_factor_challenge, public=True)

        @p("/two-factor/challenge")
        async def two_factor_challenge_post(request: Request):
            return await r.run(request, r.two_factor_challenge, public=True, read_form=True)

        @g("/two-factor")
        async def two_factor(request: Request):
            return await r.run(request, r.two_factor_setup)

        @p("/two-factor")
        async def two_factor_post(request: Request):
            return await r.run(request, r.two_factor_setup, read_form=True)

        @g("/email-change/{token}")
        async def email_change_confirm(request: Request, token: str):
            return await r.run(request, r.email_change_confirm, public=True, token=token)

        @g("/email-change/{token}/block")
        async def email_change_block(request: Request, token: str):
            return await r.run(request, r.email_change_block, public=True, token=token)

        @p("/email-change/cancel")
        async def email_change_cancel(request: Request):
            return await r.run(request, r.email_change_cancel, read_form=True)

        @g("/api-tokens")
        async def api_tokens(request: Request):
            return await r.run(request, r.api_tokens)

        @p("/api-tokens")
        async def api_tokens_post(request: Request):
            return await r.run(request, r.api_tokens, read_form=True)

        @g("/_tw/ping")
        async def ping(request: Request):
            return await r.run(request, lambda ctx, fd: Response(status_code=204))

        @g("/email-verification/prompt")
        async def verification_prompt(request: Request):
            return await r.run(request, r.verification_prompt)

        @p("/email-verification/prompt")
        async def verification_prompt_post(request: Request):
            return await r.run(request, r.verification_prompt, read_form=True)

        @g("/email-verification/verify/{token}")
        async def verify_email(request: Request, token: str):
            return await r.run(request, r.verify_email, public=True, token=token)

        @g("/profile")
        async def profile(request: Request):
            return await r.run(request, r.profile)

        @p("/profile")
        async def profile_post(request: Request):
            return await r.run(request, r.profile, read_form=True)

        # tenants
        @g("/tenant/new")
        async def tenant_register(request: Request):
            return await r.run(request, r.tenant_register)

        @p("/tenant/new")
        async def tenant_register_post(request: Request):
            return await r.run(request, r.tenant_register, read_form=True)

        @g("/tenant/profile")
        async def tenant_profile(request: Request):
            return await r.run(request, r.tenant_profile)

        @p("/tenant/profile")
        async def tenant_profile_post(request: Request):
            return await r.run(request, r.tenant_profile, read_form=True)

        @g("/tenant/billing")
        async def tenant_billing(request: Request):
            return await r.run(request, r.tenant_billing)

        # internal endpoints
        @g("/_tw/table")
        async def table(request: Request):
            return await r.run(request, r.table)

        @p("/_tw/toggle")
        async def toggle(request: Request):
            return await r.run(request, r.column_update, read_form=True)

        @p("/_tw/reorder")
        async def reorder(request: Request):
            return await r.run(request, r.reorder, read_form=True)

        @p("/_tw/column")
        async def column_update(request: Request):
            return await r.run(request, r.column_update, read_form=True)

        @g("/_tw/action")
        async def action_get(request: Request):
            return await r.run(request, r.action)

        @p("/_tw/action")
        async def action_post(request: Request):
            return await r.run(request, r.action, read_form=True)

        @p("/_tw/form")
        async def form_refresh(request: Request):
            return await r.run(request, r.form_refresh, read_form=True)

        @p("/_tw/form/options")
        async def form_options(request: Request):
            return await r.run(request, r.form_options, read_form=True)

        @p("/_tw/form/attachment")
        async def form_attachment(request: Request):
            return await r.run(request, r.form_attachment, read_form=True)

        @g("/_tw/download")
        async def download(request: Request):
            return await r.run(request, r.download)

        @g("/_tw/exports")
        async def exports(request: Request):
            return await r.run(request, r.export_history)

        @g("/_tw/exports/{job_id}/download")
        async def export_file(request: Request, job_id: int):
            return await r.run(request, r.export_file, job_id=job_id)

        @g("/_tw/search")
        async def search(request: Request):
            return await r.run(request, r.search)

        @g("/_tw/notifications")
        async def notifications(request: Request):
            return await r.run(request, r.notifications)

        @p("/_tw/notifications")
        async def notifications_post(request: Request):
            return await r.run(request, r.notifications, read_form=True)

        @app.websocket("/_tw/live")
        async def live(websocket: WebSocket):
            await r.live(websocket)

        @g("/_tw/notifications/badge")
        async def notifications_badge(request: Request):
            return await r.run(request, r.notifications_badge)

        @g("/_tw/widget/{widget_id}")
        async def widget(request: Request, widget_id: str):
            return await r.run(request, r.widget, widget_id=widget_id)

        @g("/_tw/export")
        async def export(request: Request):
            return await r.run(request, r.export)

        @g("/_tw/import-example")
        async def import_example(request: Request):
            return await r.run(request, r.import_example)

        @p("/_tw/tenant")
        async def tenant(request: Request):
            return await r.run(request, r.switch_tenant, read_form=True)

        @p("/_tw/locale")
        async def locale(request: Request):
            return await r.run(request, r.switch_locale, public=True, read_form=True)

        # your own routes (panel.routes) come before the page catch-alls below, so short paths reach them
        for fn in r.panel._extra_routes:
            fn(app, r.panel)

        # pages & resources
        @g("/")
        async def home(request: Request):
            return await r.run(request, r.home)

        @p("/")
        async def home_post(request: Request):
            return await r.run(request, r.home, read_form=True)

        @g("/{slug}")
        async def index(request: Request, slug: str):
            return await r.run(request, r.index, slug=slug)

        @p("/{slug}")
        async def index_post(request: Request, slug: str):
            return await r.run(request, r.index, read_form=True, slug=slug)

        @g("/{slug}/create")
        async def create(request: Request, slug: str):
            return await r.run(request, r.create, slug=slug)

        @p("/{slug}/create")
        async def create_post(request: Request, slug: str):
            return await r.run(request, r.create, read_form=True, slug=slug)

        @g("/{slug}/{key}")
        async def view(request: Request, slug: str, key: str):
            return await r.run(request, r.record_page, slug=slug, key=key, operation="view")

        @g("/{slug}/{key}/edit")
        async def edit(request: Request, slug: str, key: str):
            return await r.run(request, r.record_page, slug=slug, key=key, operation="edit")

        @p("/{slug}/{key}/edit")
        async def edit_post(request: Request, slug: str, key: str):
            return await r.run(request, r.record_page, read_form=True, slug=slug, key=key, operation="edit")

        # a record's related records on their own page, and nested resources under it
        @g("/{slug}/{key}/{relation}")
        async def relation_page(request: Request, slug: str, key: str, relation: str):
            return await r.run(request, r.relation_page, slug=slug, key=key, relation=relation)

        @g("/{slug}/{key}/{relation}/create")
        async def nested_create(request: Request, slug: str, key: str, relation: str):
            return await r.run(request, r.nested_create, slug=slug, key=key, relation=relation)

        @p("/{slug}/{key}/{relation}/create")
        async def nested_create_post(request: Request, slug: str, key: str, relation: str):
            return await r.run(request, r.nested_create, read_form=True, slug=slug, key=key, relation=relation)

        @g("/{slug}/{key}/{relation}/{child}")
        async def nested_view(request: Request, slug: str, key: str, relation: str, child: str):
            return await r.run(request, r.nested_record, slug=slug, key=key, relation=relation, child=child,
                               operation="view")

        @g("/{slug}/{key}/{relation}/{child}/edit")
        async def nested_edit(request: Request, slug: str, key: str, relation: str, child: str):
            return await r.run(request, r.nested_record, slug=slug, key=key, relation=relation, child=child,
                               operation="edit")

        @p("/{slug}/{key}/{relation}/{child}/edit")
        async def nested_edit_post(request: Request, slug: str, key: str, relation: str, child: str):
            return await r.run(request, r.nested_record, read_form=True, slug=slug, key=key, relation=relation,
                               child=child, operation="edit")

    def storage_file(self, ctx: Context, fd: Any, path: str) -> Response:
        storage = self.panel.storage
        if not hasattr(storage, "path"):
            return Response(status_code=404)
        try:
            full = storage.path(path)
            # background export files are only served to their owner (see export_file)
            if full.relative_to(storage.root.resolve()).parts[:1] == ("exports",):
                return Response(status_code=404)
        except (ValueError, AttributeError):
            return Response(status_code=404)
        if not full.is_file():
            return Response(status_code=404)
        return FileResponse(full, headers={"X-Content-Type-Options": "nosniff",
                                           "Content-Security-Policy": "sandbox"})

    # ------------------------------------------------------------------ auth
    def _auth_form(self, ctx: Context, fields: list) -> Form:
        form = Form().schema(fields).columns(1)
        form.bind(ctx, operation="create", refresh_url="", id="tw-auth-form")
        return form

    def login(self, ctx: Context, fd: Any) -> Response:
        from .forms import TextInput

        panel = self.panel
        if not panel.auth.enabled:
            return ctx.go(panel.url())
        if ctx.user is not None:
            return ctx.go(panel.url())
        forgot = None
        if panel.auth.password_reset:
            from markupsafe import Markup

            from .i18n import translate
            from .support import colors

            forgot = Markup('<a href="{}" class="font-medium {}">{}</a>').format(
                panel.url("forgot-password"), colors.LINK["primary"], translate("Forgot password?"))
        form = self._auth_form(ctx, [
            TextInput("email").label("Email address").email().required().placeholder("you@company.com").autofocus()
            .autocomplete("username").prefix_icon("mail"),
            TextInput("password").label("Password").password().revealable().required().autocomplete("current-password")
            .placeholder("Enter your password").prefix_icon("lock").hint(forgot),
        ])
        error = None
        if fd is not None:
            form.load(fd)
            try:
                data = form.validate()
                user = panel.auth.attempt(ctx, data["email"], form.get("password") or "")
                if user is None:
                    panel.log_auth_event(ctx, "login_failed", email=data["email"])
                    form.add_error("email", "These credentials do not match our records.")
                else:
                    nxt = ctx.request.query_params.get("next") or fd.get("next") or ""
                    if not nxt.startswith(panel.path or "/") or nxt.startswith("//"):
                        nxt = panel.url()
                    if panel.auth.two_factor:
                        from .auth.two_factor import TwoFactor

                        if TwoFactor(ctx, user).enabled:
                            ctx.session["tw_2fa_pending"] = {"id": panel.auth.user_id(user), "next": nxt,
                                                             "at": time.time()}
                            return RedirectResponse(panel.url("two-factor", "challenge"), status_code=303)
                    panel.auth.login(ctx, user)
                    panel.log_auth_event(ctx, "login", user)
                    return RedirectResponse(nxt, status_code=303)
            except ValidationError:
                pass
            except PermissionError as exc:
                panel.log_auth_event(ctx, "login_failed", email=form.get("email"), reason="throttled")
                error = str(exc)
        else:
            form.fill()
        return ctx.render("tungsten/auth/login.html", form=form, error=error,
                          next=ctx.request.query_params.get("next", ""))

    def logout(self, ctx: Context, fd: Any) -> Response:
        if ctx.user is not None:
            self.panel.log_auth_event(ctx, "logout", ctx.user)
        self.panel.auth.logout(ctx)
        return RedirectResponse(self.panel.url("login"), status_code=303)

    def two_factor_challenge(self, ctx: Context, fd: Any) -> Response:
        from .auth import two_factor as tfa
        from .forms import TextInput

        panel = self.panel
        pending = ctx.session.get("tw_2fa_pending")
        if not panel.auth.two_factor or not pending or time.time() - pending.get("at", 0) > 600:
            ctx.session.pop("tw_2fa_pending", None)
            return RedirectResponse(panel.url("login"), status_code=303)
        user = panel.auth.find_by_id(ctx.db, pending["id"])
        if user is None:
            ctx.session.pop("tw_2fa_pending", None)
            return RedirectResponse(panel.url("login"), status_code=303)
        tf = tfa.TwoFactor(ctx, user)
        app_on, email_on = tf.app_enabled, tf.email_enabled
        # someone with both turned on may use either; email codes only for users who turned them on
        email_allowed = email_on
        if email_on and not app_on and fd is None and not tfa.email_code_sent(ctx, user):
            tfa.send_email_code(ctx, user)
        using_email = email_allowed and (tfa.email_code_sent(ctx, user) or (email_on and not app_on))
        if using_email:
            helper = __("We emailed a 6-digit code to :email.",
                        email=tfa.mask_email(getattr(user, panel.auth.email_field, "")))
            if app_on:
                helper += " " + __("You can also use your authenticator app or a recovery code.")
        else:
            helper = "Open your authenticator app, or enter one of your recovery codes."
        form = self._auth_form(ctx, [
            TextInput("code").label("Authentication code").required().autofocus().autocomplete("one-time-code")
            .placeholder("123 456").helper_text(helper),
        ])
        error = None
        if fd is not None and fd.get("_do") == "email" and email_allowed:
            if tfa.send_email_code(ctx, user):
                Notification("Code sent").body(__("Check your inbox at :email.", email=tfa.mask_email(
                    getattr(user, panel.auth.email_field, "")))).success().send(ctx)
            else:
                Notification("Please wait a moment").body("You can ask for a new code once a minute.").warning() \
                    .send(ctx)
            return ctx.go(panel.url("two-factor", "challenge"))
        if fd is not None:
            form.load(fd)
            try:
                data = form.validate()
                key = f"2fa|{pending['id']}"
                if panel.auth.throttled(key):
                    raise PermissionError("Too many attempts. Please try again in a minute.")
                ok = (app_on and tf.verify(data["code"])) or \
                    (email_allowed and tfa.check_email_code(ctx, user, data["code"]))
                if ok:
                    ctx.session.pop("tw_2fa_pending", None)
                    tfa.forget_email_code(ctx)
                    panel.auth.login(ctx, user)
                    panel.log_auth_event(ctx, "login", user, two_factor=True)
                    return RedirectResponse(pending.get("next") or panel.url(), status_code=303)
                panel.auth._attempts[key].append(time.monotonic())
                panel.log_auth_event(ctx, "two_factor_failed", user)
                form.add_error("code", "That code is not valid.")
            except ValidationError:
                pass
            except PermissionError as exc:
                error = str(exc)
        else:
            form.fill()
        return ctx.render("tungsten/auth/two-factor-challenge.html", form=form, error=error, using_email=using_email,
                          can_email=email_allowed, app_on=app_on)

    def two_factor_setup(self, ctx: Context, fd: Any) -> Response:
        from .auth import two_factor as tfa
        from .auth.two_factor import TwoFactor, otpauth_uri

        panel = self.panel
        if not panel.auth.two_factor:
            raise NotFound()
        tf = TwoFactor(ctx, ctx.user)
        auth = panel.auth
        step, codes, error = ("enabled" if tf.app_enabled else "off"), None, None
        email_step = "enabled" if tf.email_enabled else ("confirm" if tfa.email_code_sent(ctx, ctx.user, "setup")
                                                         else "off")
        if fd is not None:
            do = fd.get("_do")
            if do == "enable" and not tf.app_enabled and auth.two_factor_app:
                tf.start()
                step = "confirm"
            elif do == "confirm" and not tf.app_enabled and auth.two_factor_app:
                codes = tf.confirm(fd.get("code") or "")
                if codes is None:
                    step, error = "confirm", "That code is not valid. Check your phone's clock and try again."
                else:
                    step = "codes"
                    panel.log_auth_event(ctx, "two_factor_enabled", ctx.user, method="app")
                    Notification("Two-factor authentication is on").success().send(ctx)
            elif do in ("disable", "codes") and tf.app_enabled:
                if not auth.verify(fd.get("password") or "", getattr(ctx.user, auth.password_field, None)):
                    error = "Your password is incorrect."
                elif do == "disable":
                    if auth.two_factor_required and not tf.email_enabled:
                        error = "Two-factor authentication is required for this panel."
                    else:
                        tf.disable()
                        panel.log_auth_event(ctx, "two_factor_disabled", ctx.user, method="app")
                        step = "off"
                        Notification("Two-factor authentication is off").warning().send(ctx)
                else:
                    codes = tf.regenerate_codes()
                    step = "codes"
            elif do == "email_enable" and auth.two_factor_email and not tf.email_enabled:
                if not tfa.send_email_code(ctx, ctx.user, "setup"):
                    error = "You can ask for a new code once a minute."
                email_step = "confirm"
            elif do == "email_confirm" and auth.two_factor_email and not tf.email_enabled:
                key = f"2fa-setup|{tf.user_id}"
                if auth.throttled(key):
                    error = "Too many attempts. Please try again in a minute."
                    email_step = "confirm"
                elif tfa.check_email_code(ctx, ctx.user, fd.get("code") or "", "setup"):
                    tf.enable_email()
                    panel.log_auth_event(ctx, "two_factor_enabled", ctx.user, method="email")
                    email_step = "enabled"
                    Notification("Email codes are on").success().send(ctx)
                else:
                    auth._attempts[key].append(time.monotonic())
                    email_step, error = "confirm", "That code is not valid."
            elif do == "email_disable" and tf.email_enabled:
                if not auth.verify(fd.get("password") or "", getattr(ctx.user, auth.password_field, None)):
                    error = "Your password is incorrect."
                elif auth.two_factor_required and not tf.app_enabled:
                    error = "Two-factor authentication is required for this panel."
                else:
                    tf.disable_email()
                    panel.log_auth_event(ctx, "two_factor_disabled", ctx.user, method="email")
                    email_step = "off"
                    Notification("Email codes are off").warning().send(ctx)
        secret = tf.credential.secret if step == "confirm" and tf.credential else None
        account = str(getattr(ctx.user, auth.email_field, ""))
        return ctx.render(
            "tungsten/auth/two-factor-setup.html",
            title=__("Two-factor authentication"),
            step=step, codes=codes, error=error, secret=secret,
            uri=otpauth_uri(secret, account, panel.brand_name) if secret else None,
            remaining=len(tf.credential.recovery_codes or []) if tf.app_enabled and tf.credential else 0,
            required=auth.two_factor_required,
            app_method=auth.two_factor_app or tf.app_enabled,
            email_method=auth.two_factor_email,
            email_step=email_step,
            masked_email=tfa.mask_email(account),
            other_on={"app": tf.email_enabled, "email": tf.app_enabled},
        )

    def sign_up(self, ctx: Context, fd: Any) -> Response:
        from .forms import TextInput

        panel = self.panel
        auth = panel.auth
        if not auth.enabled or not auth.registration:
            raise NotFound()
        if ctx.user is not None:
            return ctx.go(panel.url())
        form = self._auth_form(ctx, [
            TextInput(auth.name_field).label("Full name").required().max_length(255).autofocus(),
            TextInput(auth.email_field).label("Email").email().required().max_length(255).unique(),
            TextInput("password").label("Password").password().revealable().required().min_length(8),
            TextInput("password_confirmation").label("Confirm password").password().revealable().required()
            .same("password"),
        ])
        form.model(auth.user_model)
        created = False
        if fd is not None:
            form.load(fd)
            try:
                data = form.validate()
                user = auth.user_model()
                setattr(user, auth.name_field, data[auth.name_field])
                setattr(user, auth.email_field, data[auth.email_field])
                setattr(user, auth.password_field, auth.hash(form.get("password")))
                if auth.on_register is not None:
                    call(auth.on_register, user=user, db=ctx.db, ctx=ctx)
                ctx.db.add(user)
                ctx.db.commit()
                if auth.email_verification:
                    from .auth import verification

                    verification.send(ctx, user)
                panel.log_auth_event(ctx, "registered", user)
                if auth.is_active(user) and auth.allowed(ctx, user):
                    auth.login(ctx, user)
                    panel.log_auth_event(ctx, "login", user)
                    Notification("Welcome!").body("Your account was created.").success().send(ctx)
                    ctx.flash()
                    return RedirectResponse(panel.url(), status_code=303)
                created = True
            except ValidationError:
                pass
        else:
            form.fill()
        return ctx.render("tungsten/auth/register.html", form=form, created=created)

    def verification_prompt(self, ctx: Context, fd: Any) -> Response:
        from .auth import verification

        panel = self.panel
        if not panel.auth.email_verification or verification.is_verified(panel, ctx.user):
            return ctx.go(panel.url())
        sent = None
        if fd is not None:
            sent = verification.send(ctx, ctx.user)
            if sent:
                Notification("Verification link sent").body("Check your inbox for a new link.").success().send(ctx)
            else:
                Notification("Please wait a moment").body("You can ask for a new link once a minute.").warning() \
                    .send(ctx)
        return ctx.render("tungsten/auth/verify-email.html", email=getattr(ctx.user, panel.auth.email_field, ""),
                          sent=sent)

    def verify_email(self, ctx: Context, fd: Any, token: str) -> Response:
        from .auth import verification

        panel = self.panel
        auth = panel.auth
        if not auth.enabled or not auth.email_verification:
            raise NotFound()
        data = verification.read_token(panel, token)
        user = auth.find_by_id(ctx.db, data["id"]) if data else None
        if user is None or not verification.token_matches(panel, user, data):
            return ctx.render("tungsten/auth/verify-email.html", invalid=True,
                              email=getattr(ctx.user, auth.email_field, "") if ctx.user is not None else "")
        verification.mark_verified(panel, user)
        ctx.db.commit()
        Notification("Email verified").body("Thanks! Your email address is confirmed.").success().send(ctx)
        ctx.flash()
        if ctx.user is not None:
            return RedirectResponse(panel.url(), status_code=303)
        return RedirectResponse(panel.url("login"), status_code=303)

    def email_change_confirm(self, ctx: Context, fd: Any, token: str) -> Response:
        from .auth import email_change

        panel = self.panel
        if not panel.auth.enabled or not panel.auth.email_change_verification:
            raise NotFound()
        row = email_change.find(ctx, token)
        error = "This link is invalid or has expired." if row is None else None
        if row is not None:
            user, error = email_change.confirm(ctx, row)
        if not error:
            panel.log_auth_event(ctx, "email_changed", user, old=row.old_email, new=row.new_email)
        if error:
            Notification("Email not changed").body(error).danger().persistent().send(ctx)
        else:
            Notification("Email address changed").body(
                __("Your account now uses :email.", email=getattr(user, panel.auth.email_field))).success().send(ctx)
        ctx.flash()
        if ctx.user is not None:
            return RedirectResponse(panel.url("profile"), status_code=303)
        return RedirectResponse(panel.url("login"), status_code=303)

    def email_change_block(self, ctx: Context, fd: Any, token: str) -> Response:
        from .auth import email_change

        panel = self.panel
        if not panel.auth.enabled or not panel.auth.email_change_verification:
            raise NotFound()
        row = email_change.find(ctx, token, block=True)
        if row is not None:
            panel.log_auth_event(ctx, "email_change_blocked", panel.auth.find_by_id(ctx.db, row.user_id),
                                 new=row.new_email)
            email_change.cancel(ctx, row)
            Notification("Email change stopped").body(
                "Your email address stays the same. If you didn't ask for this, change your password now.") \
                .warning().persistent().send(ctx)
        else:
            Notification("Nothing to stop").body("This change was already confirmed, stopped or has expired.") \
                .send(ctx)
        ctx.flash()
        return RedirectResponse(panel.url("profile") if ctx.user is not None else panel.url("login"),
                                status_code=303)

    def email_change_cancel(self, ctx: Context, fd: Any) -> Response:
        from .auth import email_change

        row = email_change.pending(ctx, ctx.user) if self.panel.auth.email_change_verification else None
        if row is not None:
            email_change.cancel(ctx, row)
            Notification("Email change cancelled").send(ctx)
        return ctx.go(self.panel.url("profile"))

    def api_tokens(self, ctx: Context, fd: Any) -> Response:
        import datetime as dt

        from .auth import tokens

        panel = self.panel
        auth = panel.auth
        if not auth.enabled or not auth.api_tokens:
            raise NotFound()
        options = tokens.ability_options(panel)
        plain, error = None, None
        if fd is not None:
            do = fd.get("_do")
            if do == "create":
                name = (fd.get("name") or "").strip()
                chosen = [a for a in fd.getlist("abilities") if a in options] if options else ["*"]
                days = fd.get("expires") or ""
                if not name:
                    error = "Give the token a name."
                elif options and not chosen:
                    error = "Pick at least one thing this token may do."
                else:
                    expires = None
                    if days.isdigit() and int(days) > 0:
                        expires = dt.datetime.now() + dt.timedelta(days=min(int(days), 3650))
                    row, plain = tokens.create(ctx.db, panel, ctx.user, name, chosen, expires)
                    panel.log_auth_event(ctx, "api_token_created", ctx.user, token=row.name, abilities=chosen)
                    Notification("Token created").body("Copy it now. It won't be shown again.").success().send(ctx)
            elif do == "revoke":
                if tokens.revoke(ctx.db, panel, ctx.user, fd.get("id")):
                    panel.log_auth_event(ctx, "api_token_deleted", ctx.user, token_id=fd.get("id"))
                    Notification("Token deleted").body("Apps using it can no longer sign in.").warning().send(ctx)
        return ctx.render("tungsten/auth/api-tokens.html", title=__("API tokens"),
                          tokens=tokens.for_user(ctx.db, panel, ctx.user), options=options, plain=plain,
                          error=error, default_days=auth.api_token_days, now=dt.datetime.now())

    def forgot_password(self, ctx: Context, fd: Any) -> Response:
        from .forms import TextInput

        panel = self.panel
        if not panel.auth.enabled or not panel.auth.password_reset:
            raise NotFound()
        form = self._auth_form(ctx, [TextInput("email").label("Email").email().required().autofocus()])
        sent = False
        if fd is not None:
            form.load(fd)
            try:
                data = form.validate()
                user = panel.auth.find_by_email(ctx.db, data["email"])
                if user is not None:
                    token = panel.auth.create_reset_token(ctx.db, data["email"])
                    url = panel.absolute_url(ctx, panel.url("reset-password", token))
                    call(panel.auth.mailer, to=getattr(user, panel.auth.email_field),
                         subject=__("Reset your :app password", app=panel.brand_name),
                         body=__("Hello,\n\nUse this link to set a new password:\n:url\n\n"
                                 "The link works for :minutes minutes. If you did not ask for this, you can ignore "
                                 "this email.", url=url, minutes=panel.auth.reset_token_minutes),
                         url=url, user=user, kind="password_reset")
                sent = True
            except ValidationError:
                pass
        else:
            form.fill()
        return ctx.render("tungsten/auth/forgot-password.html", form=form, sent=sent)

    def reset_password(self, ctx: Context, fd: Any, token: str) -> Response:
        from .forms import TextInput

        panel = self.panel
        email = panel.auth.email_for_token(ctx.db, token)
        form = self._auth_form(ctx, [
            TextInput("password").label("New password").password().revealable().required().min_length(8).autofocus(),
            TextInput("password_confirmation").label("Confirm password").password().revealable().required()
            .same("password"),
        ])
        if email is None:
            return ctx.render("tungsten/auth/reset-password.html", form=None, invalid=True)
        if fd is not None:
            form.load(fd)
            try:
                form.validate()
                user = panel.auth.find_by_email(ctx.db, email)
                if user is not None:
                    setattr(user, panel.auth.password_field, panel.auth.hash(form.get("password")))
                    ctx.db.commit()
                    panel.log_auth_event(ctx, "password_reset", user)
                panel.auth.consume_token(ctx.db, token)
                Notification("Password updated").body("You can now sign in with your new password.").success().send(ctx)
                ctx.flash()
                return RedirectResponse(panel.url("login"), status_code=303)
            except ValidationError:
                pass
        else:
            form.fill()
        return ctx.render("tungsten/auth/reset-password.html", form=form, invalid=False)

    def profile(self, ctx: Context, fd: Any) -> Response:
        from .auth.profile import ProfileHost

        if not self.panel.auth.enabled or not self.panel.auth.profile:
            raise NotFound()
        host = ProfileHost(self.panel)
        form = host.form(ctx)
        if fd is None:
            form.fill(ctx.user)
            two_factor = None
            if self.panel.auth.two_factor:
                from .auth.two_factor import TwoFactor

                two_factor = TwoFactor(ctx, ctx.user).enabled
            pending_email = None
            if self.panel.auth.email_change_verification:
                from .auth import email_change

                row = email_change.pending(ctx, ctx.user)
                pending_email = row.new_email if row is not None else None
            return ctx.render("tungsten/pages/profile.html", form=form, title=__("My profile"), two_factor=two_factor,
                              pending_email=pending_email, api_tokens=self.panel.auth.api_tokens)
        form.load(fd)
        try:
            data = form.validate()
        except ValidationError:
            return ctx.html(form.render())
        host.update(ctx, ctx.user, data, form)
        Notification("Profile saved").success().send(ctx)
        if ctx.redirect_to:
            return ctx.go(ctx.redirect_to)
        form.fill(ctx.user)
        return ctx.html(form.render())

    # ------------------------------------------------------------------ pages
    def home(self, ctx: Context, fd: Any) -> Response:
        if self.panel.dashboard is None:
            first = next((r for r in self.panel.get_resources() if r.can(ctx, "view_any")), None)
            if first is None:
                raise NotFound()
            return ctx.go(first.get_url(ctx))
        return self.custom_page(ctx, fd, self.panel.dashboard)

    def custom_page(self, ctx: Context, fd: Any, page: Any) -> Response:
        if not page.can_access(ctx):
            raise Forbidden()
        ctx.page = page  # its widgets get this page's filters
        host = page.host()
        form = host.form(ctx, "edit")
        if form is not None:
            form.id = "tw-page-form"
            if fd is None:
                form.fill_from(call(page.mount, ctx=ctx, db=ctx.db, user=ctx.user) or {})
            else:
                form.load(fd)
                try:
                    data = form.validate()
                except ValidationError:
                    return ctx.html(form.render())
                result = host.save(ctx, data)
                if isinstance(result, Response):
                    return result
                Notification("Saved").success().send(ctx)
                if ctx.redirect_to:
                    return ctx.go(ctx.redirect_to)
                return ctx.html(form.render())
        elif fd is not None:
            raise NotFound()
        actions = flatten_actions(host.page_actions(ctx))
        for a in actions:
            a.scope = "page"
        return ctx.render(
            page.template,
            page=page,
            host=host,
            form=form,
            title=page.get_title(),
            subheading=page.get_subheading(ctx),
            content=page.content(ctx),
            widgets=page.get_widgets(ctx),
            header_actions=host.page_actions(ctx),
        )

    def index(self, ctx: Context, fd: Any, slug: str) -> Response:
        resource = self.panel.resource(slug)
        if resource is None:
            page = self.panel.page(slug)
            if page is None:
                cluster = self.panel.cluster(slug)
                if cluster is None or fd is not None:
                    raise NotFound()
                members = self.panel.cluster_navigation(ctx, cluster)
                if not members:
                    raise Forbidden()
                return ctx.go(members[0].url)
            return self.custom_page(ctx, fd, page)
        if fd is not None:
            raise NotFound()
        if resource.parent_resource is not None:  # nested: its records are listed under each parent record
            return ctx.go(resource.parent_resource.get_url(ctx))
        if not resource.can(ctx, "view_any"):
            raise Forbidden()
        host = resource.host()
        table = host.get_table(ctx).bind(ctx, host)
        actions = host.page_actions(ctx, None, "list")
        for a in flatten_actions(actions):
            a.scope = "page"
        return ctx.render(
            "tungsten/resources/list.html",
            resource=resource,
            host=host,
            table=table,
            header_actions=actions,
            widgets=[w for w in resource.header_widgets(ctx, "list") if w.can_view(ctx)],
            title=resource.get_plural_label(),
            breadcrumbs=[(resource.get_plural_label(), resource.get_url(ctx)), (__("List"), None)],
        )

    def create(self, ctx: Context, fd: Any, slug: str) -> Response:
        resource = self.panel.resource(slug)
        if resource is None or not resource.has_page("create"):
            raise NotFound()
        if not resource.can(ctx, "create"):
            raise Forbidden()
        host = resource.host()
        form = host.form(ctx, "create")
        form.id = "tw-record-form"
        if fd is None:
            form.fill()
        else:
            form.load(fd)
            try:
                data = form.validate()
            except ValidationError:
                return ctx.html(form.render())
            record = host.create(ctx, data, form)
            Notification("Created").body(__(":label was created.", label=resource.get_label())).success().send(ctx)
            if fd.get("_another"):
                return ctx.go(resource.get_url(ctx, "create"))
            target = host.edit_url(ctx, record) if resource.can(ctx, "update", record) else None
            return ctx.go(target or host.view_url(ctx, record) or resource.get_url(ctx))
        actions = host.page_actions(ctx, None, "create")
        for a in flatten_actions(actions):
            a.scope = "page"
        return ctx.render(
            "tungsten/resources/record.html",
            resource=resource,
            host=host,
            form=form,
            record=None,
            operation="create",
            header_actions=actions,
            relations=[],
            title=__("Create :label", label=resource.get_label().lower()),
            breadcrumbs=[(resource.get_plural_label(), resource.get_url(ctx)), (__("Create"), None)],
        )

    def record_page(self, ctx: Context, fd: Any, slug: str, key: str, operation: str) -> Response:
        resource = self.panel.resource(slug)
        if resource is None:
            raise NotFound()
        if operation == "view" and not resource.has_page("view"):
            if resource.has_page("edit"):
                return ctx.go(resource.get_url(ctx, "edit", key))
            raise NotFound()
        if operation == "edit" and not resource.has_page("edit"):
            raise NotFound()
        host = resource.host()
        record = host.find_record(ctx, key)
        if record is None:
            raise NotFound()
        if fd is None and resource.parent_resource is not None:  # a nested resource lives under its parent
            nested = resource.get_url(ctx, operation, record)
            if nested and nested != ctx.request.url.path:
                return ctx.go(nested)
        ability = "update" if operation == "edit" else "view"
        if not resource.can(ctx, ability, record):
            raise Forbidden()
        if operation == "edit" and host.is_trashed(record) and fd is not None:
            raise Forbidden()
        form = (host.infolist(ctx, record) if operation == "view" else None) or host.form(ctx, operation, record)
        form.id = form.id if form.id == "tw-infolist" else "tw-record-form"
        if fd is not None:
            form.load(fd)
            try:
                data = form.validate()
            except ValidationError:
                return ctx.html(form.render())
            host.update(ctx, record, data, form)
            Notification("Saved").body("Your changes were saved.").success().send(ctx)
            ctx.db.refresh(record)
            form = host.form(ctx, operation, record)
            form.id = "tw-record-form"
            form.fill(record)
            return ctx.html(form.render())
        form.fill(record)
        actions = host.page_actions(ctx, record, operation)
        for a in flatten_actions(actions):
            a.scope = "page"
        relations = []
        for manager in resource.get_relations():
            if operation == "view" and not manager.show_on_view:
                continue
            if manager.separate_page:
                continue
            rhost = RelationHost(resource, record, manager)
            if not rhost.can(ctx, "view_any"):
                continue
            table = rhost.get_table(ctx).bind(ctx, rhost, params=QueryParams(""))
            relations.append({"manager": manager, "host": rhost, "table": table,
                              "badge": call(manager.badge, ctx=ctx, owner=record)})
        title_record = resource.get_record_title(record)
        return ctx.render(
            "tungsten/resources/record.html",
            resource=resource,
            host=host,
            form=form,
            record=record,
            record_title=title_record,
            operation=operation,
            header_actions=actions,
            relations=relations,
            record_tabs=self.record_tabs(ctx, resource, record, operation),
            trashed=host.is_trashed(record),
            title=(__("Edit :label", label=resource.get_label().lower()) if operation == "edit" else title_record),
            breadcrumbs=[(resource.get_plural_label(), resource.get_url(ctx)),
                         (title_record, None) if operation == "view" else (__("Edit"), None)],
        )

    # ------------------------------------------------------------------ related records
    def record_url(self, ctx: Context, resource: Any, record: Any) -> str | None:
        """The page a record opens on: edit when allowed, else view."""
        host = resource.host()
        if resource.has_page("edit") and resource.can(ctx, "update", record) and not host.is_trashed(record):
            return host.edit_url(ctx, record)
        if resource.has_page("view"):
            return host.view_url(ctx, record)
        return host.edit_url(ctx, record)

    def record_tabs(self, ctx: Context, resource: Any, record: Any, active: str) -> list[dict]:
        """Links to the record's own page and to each relation shown on a separate page."""
        pages = [m for m in resource.get_relations() if m.separate_page]
        if not pages:
            return []
        operation = "edit" if active == "edit" else "view"
        if not resource.has_page(operation):
            operation = "edit" if resource.has_page("edit") else "view"
        main_url = self.record_url(ctx, resource, record)
        tabs = [{"label": __("Edit") if "/edit" in (main_url or "") else __("Details"), "icon": "file-text",
                 "url": main_url, "active": active in ("edit", "view"), "badge": None}]
        for manager in pages:
            rhost = RelationHost(resource, record, manager)
            if not rhost.can(ctx, "view_any"):
                continue
            tabs.append({"label": manager.get_title(), "icon": manager.icon,
                         "url": manager.get_url(ctx, resource, record), "active": active == manager.get_slug(),
                         "badge": call(manager.badge, ctx=ctx, owner=record)})
        return tabs

    def _relation_host(self, ctx: Context, slug: str, key: str, relation: str) -> RelationHost:
        resource = self.panel.resource(slug)
        if resource is None:
            raise NotFound()
        owner = resource.host().find_record(ctx, key)
        if owner is None:
            raise NotFound()
        if not resource.can(ctx, "view", owner):
            raise Forbidden()
        manager = next((m for m in resource.get_relations() if m.get_slug() == relation), None)
        if manager is None:
            raise NotFound()
        host = RelationHost(resource, owner, manager)
        if not host.can(ctx, "view_any"):
            raise Forbidden()
        return host

    def _owner_crumbs(self, ctx: Context, host: RelationHost) -> list:
        resource, owner = host.resource, host.owner
        return [(resource.get_plural_label(), resource.get_url(ctx)),
                (resource.get_record_title(owner), self.record_url(ctx, resource, owner))]

    def relation_page(self, ctx: Context, fd: Any, slug: str, key: str, relation: str) -> Response:
        """A record's related records on their own page (``/customers/1/orders``)."""
        if fd is not None:
            raise NotFound()
        host = self._relation_host(ctx, slug, key, relation)
        table = host.get_table(ctx).bind(ctx, host)
        manager, resource, owner = host.manager, host.resource, host.owner
        title = manager.get_title()
        return ctx.render(
            "tungsten/resources/relation.html",
            resource=resource,
            host=host,
            table=table,
            record=owner,
            manager=manager,
            header_actions=[],
            record_tabs=self.record_tabs(ctx, resource, owner, manager.get_slug()),
            title=title,
            subheading=resource.get_record_title(owner),
            breadcrumbs=[*self._owner_crumbs(ctx, host), (title, None)],
        )

    def _nested_host(self, ctx: Context, slug: str, key: str, relation: str) -> RelationHost:
        host = self._relation_host(ctx, slug, key, relation)
        if host.related_resource is None:
            raise NotFound()
        return host

    def nested_create(self, ctx: Context, fd: Any, slug: str, key: str, relation: str) -> Response:
        """Create a nested record (``/courses/1/lessons/create``): it is linked to the owner."""
        host = self._nested_host(ctx, slug, key, relation)
        child = host.related_resource
        if not child.has_page("create"):
            raise NotFound()
        if not host.can(ctx, "create"):
            raise Forbidden()
        form = self.host_form(ctx, host, "create", None)
        form.id = "tw-record-form"
        back = host.manager.get_url(ctx, host.resource, host.owner) if host.manager.separate_page \
            else self.record_url(ctx, host.resource, host.owner)
        if fd is None:
            form.fill()
        else:
            form.load(fd)
            try:
                data = form.validate()
            except ValidationError:
                return ctx.html(form.render())
            record = host.create(ctx, data, form)
            self.panel.log_activity(ctx, "created", record)
            ctx.db.commit()
            Notification("Created").body(__(":label was created.", label=host.model_label())).success().send(ctx)
            if fd.get("_another"):
                return ctx.go(host.create_url(ctx))
            target = host.edit_url(ctx, record) if host.can(ctx, "update", record) else None
            return ctx.go(target or host.view_url(ctx, record) or back)
        actions = host.page_actions(ctx, None, "create")
        for a in flatten_actions(actions):
            a.scope = "page"
        return ctx.render(
            "tungsten/resources/record.html",
            resource=child,
            host=host,
            form=form,
            record=None,
            operation="create",
            header_actions=actions,
            relations=[],
            cancel_url=back,
            title=__("Create :label", label=host.model_label().lower()),
            breadcrumbs=[*self._owner_crumbs(ctx, host), (host.manager.get_title(), back), (__("Create"), None)],
        )

    def nested_record(self, ctx: Context, fd: Any, slug: str, key: str, relation: str, child: str,
                      operation: str) -> Response:
        """View or edit a nested record (``/courses/1/lessons/5/edit``)."""
        host = self._nested_host(ctx, slug, key, relation)
        resource = host.related_resource
        if operation == "view" and not resource.has_page("view"):
            if resource.has_page("edit"):
                return ctx.go(host.edit_url(ctx, child))
            raise NotFound()
        if operation == "edit" and not resource.has_page("edit"):
            raise NotFound()
        record = host.find_record(ctx, child)  # only records of this owner
        if record is None:
            raise NotFound()
        if not host.can(ctx, "update" if operation == "edit" else "view", record):
            raise Forbidden()
        if operation == "edit" and host.is_trashed(record) and fd is not None:
            raise Forbidden()
        form = (host.infolist(ctx, record) if operation == "view" else None) or self.host_form(ctx, host, operation,
                                                                                            record)
        form.id = form.id if form.id == "tw-infolist" else "tw-record-form"
        if fd is not None:
            form.load(fd)
            try:
                data = form.validate()
            except ValidationError:
                return ctx.html(form.render())
            host.update(ctx, record, data, form)
            self.panel.log_activity(ctx, "updated", record)
            ctx.db.commit()
            Notification("Saved").body("Your changes were saved.").success().send(ctx)
            ctx.db.refresh(record)
            form = self.host_form(ctx, host, operation, record)
            form.id = "tw-record-form"
            form.fill(record)
            return ctx.html(form.render())
        form.fill(record)
        actions = host.page_actions(ctx, record, operation)
        for a in flatten_actions(actions):
            a.scope = "page"
        relations = []
        if self.panel.resource(resource.get_slug()) is resource:  # its own relation managers need it registered
            for manager in resource.get_relations():
                if (operation == "view" and not manager.show_on_view) or manager.separate_page:
                    continue
                rhost = RelationHost(resource, record, manager)
                if not rhost.can(ctx, "view_any"):
                    continue
                relations.append({"manager": manager, "host": rhost,
                                  "table": rhost.get_table(ctx).bind(ctx, rhost, params=QueryParams("")),
                                  "badge": call(manager.badge, ctx=ctx, owner=record)})
        back = host.manager.get_url(ctx, host.resource, host.owner) if host.manager.separate_page \
            else self.record_url(ctx, host.resource, host.owner)
        title_record = host.record_title(record)
        return ctx.render(
            "tungsten/resources/record.html",
            resource=resource,
            host=host,
            form=form,
            record=record,
            record_title=title_record,
            operation=operation,
            header_actions=actions,
            relations=relations,
            cancel_url=back,
            trashed=host.is_trashed(record),
            title=(__("Edit :label", label=host.model_label().lower()) if operation == "edit" else title_record),
            breadcrumbs=[*self._owner_crumbs(ctx, host), (host.manager.get_title(), back),
                         (title_record, None) if operation == "view" else (__("Edit"), None)],
        )

    # ------------------------------------------------------------------ tables
    def table(self, ctx: Context, fd: Any) -> Response:
        params = ctx.request.query_params
        host = self.resolve_host(ctx, params.get("host"))
        table = host.get_table(ctx)
        if table is None:
            raise NotFound()
        table.bind(ctx, host, params=params)
        response = ctx.html(table.render())
        push = table.push_url()
        if push and not params.get("_nopush"):
            response.headers["HX-Replace-Url"] = push
        return response

    def column_update(self, ctx: Context, fd: Any) -> Response:
        """Save one inline-edited table cell (toggle, checkbox, text input, select)."""
        host = self.resolve_host(ctx, fd.get("host"))
        record = host.find_record(ctx, fd.get("record"))
        if record is None:
            raise NotFound()
        if not host.can(ctx, "update", record):
            raise Forbidden()
        table = host.get_table(ctx).bind(ctx, host, params=QueryParams(""))
        column = next((c for c in table._columns if isinstance(c, EditableColumn) and c.name == fd.get("column")), None)
        if column is None:
            raise NotFound()
        if "value" in fd:
            raw = fd.get("value")
        else:  # a bare toggle click flips the value
            raw = "" if getattr(record, column.name) else "1"
        try:
            column.update(table, record, raw)
        except ValueError as exc:
            ctx.db.rollback()
            Notification("Not saved").body(str(exc)).danger().send(ctx)
            return ctx.finalize(Response(status_code=204))
        ctx.db.commit()
        Notification("Saved").success().duration(2000).send(ctx)
        return ctx.finalize(Response(status_code=204))

    def reorder(self, ctx: Context, fd: Any) -> Response:
        """Save a new row order after drag & drop."""
        host = self.resolve_host(ctx, fd.get("host"))
        if not host.can(ctx, "update"):
            raise Forbidden()
        table = host.get_table(ctx).bind(ctx, host, params=QueryParams(""))
        column = table._reorder_column
        if not column:
            raise NotFound()
        table.reorder(fd.getlist("keys"))
        ctx.db.commit()
        Notification("Order saved").success().duration(2000).send(ctx)
        return ctx.finalize(Response(status_code=204))

    # ------------------------------------------------------------------ actions
    def _action_context(self, ctx: Context, src: Any, lazy_records: bool = False) -> tuple:
        host = self.resolve_host(ctx, src.get("_tw_host"))
        scope = src.get("_tw_scope") or "page"
        name = src.get("_tw_name") or ""
        key = src.get("_tw_record") or ""
        record = host.find_record(ctx, key) if key else None
        if key and record is None:
            raise NotFound()
        action = self.find_action(ctx, host, scope, name, record, params=src)
        records = None
        keys: list[str] = []
        if scope == "bulk":
            keys = [k for k in dict.fromkeys(src.getlist("records")) if k]
            if lazy_records and getattr(action, "_chunk_size", None):
                pass  # loaded a chunk at a time when the action runs
            else:
                records = host.find_records(ctx, keys)
                keys = [host.record_key(r) for r in records]
        if not self.action_available(action, host, ctx, record):
            raise Forbidden()
        return host, action, record, records, scope, keys

    def _action_form(self, ctx: Context, host: Host, action: Action, record: Any, records: Any, scope: str,
                     form_id: str | None = None) -> Form | None:
        form = action.build_form(ctx, host, record, records)
        if form is None:
            return None
        operation = getattr(action, "operation", "create")
        form.bind(ctx, operation=operation, record=record, id=form_id or "tw-action-form",
                  source={"kind": "action", "host": host.key, "scope": scope, "name": action.path,
                          "record": host.record_key(record) if record is not None else ""})
        return form

    def _modal(self, ctx: Context, host: Host, action: Action, record: Any, records: Any, scope: str,
               form: Form | None, keys: list | None = None, level: int = 0) -> Response:
        ev = action.ev(ctx, record, records, host=host)
        if keys is None:
            keys = [host.record_key(r) for r in records or []]
        heading = evaluate(action._modal_heading, **ev)
        if heading is None:
            heading = action.get_modal_heading(host) if hasattr(action, "get_modal_heading") else action.get_label(ev)
            if getattr(action, "operation", None) in ("edit", "view") and record is not None:
                heading = f"{action.get_label(ev)} {host.record_title(record)}".strip()
        heading = maybe(heading)
        description = maybe(evaluate(action._modal_description, **ev))
        if description is None and hasattr(action, "get_modal_description"):
            description = action.get_modal_description(host)
        content = evaluate(action._modal_content, **ev)
        confirm_only = form is None and (content is None or bool(action._requires_confirmation))
        if description is None and confirm_only:
            description = __("Are you sure you would like to do this?")
            if scope == "bulk":
                description = __("Are you sure you want to do this to :count selected records?", count=len(keys))
        submit = maybe(evaluate(action._modal_submit_label, **ev)) if action._modal_submit_label is not None else (
            None if getattr(action, "operation", None) == "view" else (__("Confirm") if form is None else __("Submit")))
        if hasattr(action, "operation") and action._modal_submit_label is None:
            submit = {"create": __("Create"), "edit": __("Save changes"), "view": None}.get(action.operation, submit)
        if not action._modal_submit or action._wizard:  # a wizard has its own buttons
            submit = None
        another = form is not None and getattr(action, "_create_another", False)
        color = evaluate(action._color, **ev) or "primary"
        level = max(0, min(level, MAX_MODAL_LEVEL))
        m = {
            "endpoint": ctx.url("_tw", "action"),
            "heading": heading,
            "description": description,
            "icon": evaluate(action._modal_icon, **ev),
            "icon_color": evaluate(action._modal_icon_color, **ev) or color,
            "submit_label": submit,
            "cancel_label": maybe(evaluate(action._modal_cancel_label, **ev)) or __("Cancel"),
            "color": color if color != "gray" else "primary",
            "width": action._modal_width,
            "slide_over": action._slide_over,
            "confirm_only": confirm_only,
            "content": content,
            "multipart": False,
            "create_another_label": __("Create & create another") if another else None,
            "level": level,
            "target": modal_target(level),
            "sticky_header": action._sticky_header,
            "sticky_footer": action._sticky_footer,
            "footer": action.modal_footer_view(ctx, host, record, level, keys),
        }
        hidden = {"_tw_host": host.key, "_tw_scope": scope, "_tw_name": action.path,
                  "_tw_record": host.record_key(record) if record is not None else ""}
        if level:
            hidden["_tw_level"] = str(level)
        html = self.panel.renderer.render("tungsten/actions/modal.html", m=m, form=form, hidden=hidden, records=keys,
                                          ctx=ctx)
        return ctx.html(html)

    def _keep_open(self, ctx: Context, host: Host, action: Action, record: Any, records: Any, scope: str,
                   form: Form | None, keys: list, level: int) -> Response:
        """Draw the modal again (after an error), or answer with nothing when there is no modal."""
        if form is not None or action._modal_content is not None:
            return self._modal(ctx, host, action, record, records, scope, form, keys, level)
        return ctx.finalize(Response(status_code=204))

    def action(self, ctx: Context, fd: Any) -> Response:
        src = fd if fd is not None else ctx.request.query_params
        try:
            level = max(0, min(int(src.get("_tw_level") or 0), MAX_MODAL_LEVEL))
        except ValueError:
            level = 0
        host, action, record, records, scope, keys = self._action_context(ctx, src, lazy_records=fd is not None)
        if scope == "bulk" and not keys:
            Notification("Select some records first").warning().send(ctx)
            return ctx.finalize(Response(status_code=204))
        form = self._action_form(ctx, host, action, record, records, scope)
        if fd is None:  # open the modal
            if form is not None:
                action.fill(form, ctx, record, records)
            return self._modal(ctx, host, action, record, records, scope, form, keys, level)
        pressed = fd.get("_tw_submit")
        if pressed:
            extra = next((s for s in action._extra_submits if s["name"] == pressed), None)
            if extra is None:
                raise NotFound()
            action.arguments = dict(extra["arguments"])
        data: dict = {}
        if form is not None:
            form.load(fd)
            try:
                data = form.validate()
            except ValidationError:
                return self._modal(ctx, host, action, record, records, scope, form, keys, level)
        wait = action.check_rate_limit(ctx, host)
        if wait:
            action.rate_limited_notification(ctx, wait).send(ctx)
            return self._keep_open(ctx, host, action, record, records, scope, form, keys, level)
        if scope == "bulk" and isinstance(action, BulkAction) and action.runs_in_background(ctx, keys):
            return self._bulk_in_background(ctx, fd, host, action, record, scope, keys, level)
        try:
            result = self._execute(ctx, host, action, record, records, keys, data, form)
        except Halt:
            return self._keep_open(ctx, host, action, record, records, scope, form, keys, level)
        except ValidationError as exc:
            if form is not None:
                form.errors = exc.errors
                return self._modal(ctx, host, action, record, records, scope, form, keys, level)
            raise
        except (NotFound, Forbidden, PermissionError):
            raise
        except Exception:
            if action._failure_title is None:
                raise
            # a failure toast is set: show it instead of an error page
            ctx.db.rollback()
            logging.getLogger("tungsten").exception("Action %r failed", action.path)
            result = False
        if result is not False:
            self._log_action(ctx, host, action, record, records, scope)
        if isinstance(result, Response):
            return result
        if result is False:  # the action failed
            note = action.failure_notification(ctx, record, records)
            if note is not None:
                note.send(ctx)
            if form is not None:
                return self._modal(ctx, host, action, record, records, scope, form, keys, level)
            ctx.dispatch("tw-close-modal", {"from": level} if level else None)
            return ctx.html("")
        note = action.success_notification(ctx, record, records)
        if note is not None:
            note.send(ctx)
        if fd.get("_tw_another") and form is not None and getattr(action, "_create_another", False):
            # "Create & create another": refresh the table behind and open an empty form again
            ctx.dispatch("tw-refresh")
            fresh = self._action_form(ctx, host, action, record, records, scope)
            action.fill(fresh, ctx, record, records)
            return self._modal(ctx, host, action, record, records, scope, fresh, keys, level)
        redirect = ctx.redirect_to or evaluate(action._success_redirect, **action.ev(ctx, record, records, result=result))
        if redirect:
            if getattr(action, "_is_download", False):
                ctx.dispatch("tw-close-modal", {"from": level} if level else None)
            return ctx.go(redirect)
        chained = self._chain(ctx, host, action, record, records, scope, keys, level, result)
        if chained is not None:
            return chained
        if scope in ("page", "infolist") and not level:
            return ctx.refresh()
        ctx.dispatch("tw-refresh")
        ctx.dispatch("tw-close-modal", {"from": level} if level and not action._cancel_parents else None)
        if scope == "bulk" and action._deselect_after and (not level or action._cancel_parents):
            ctx.dispatch("tw-deselect")
        return ctx.html("")

    def _log_action(self, ctx: Context, host: Host, action: Action, record: Any, records: Any, scope: str) -> None:
        """Activity log row(s) for an action that ran: one per record, or one for a page/header action."""
        panel = self.panel
        if not panel.activity_log or not action.logs_activity():
            return
        try:
            label = action.get_label(action.ev(ctx, record, records))
        except Exception:  # noqa: BLE001 - a label that needs more than we have
            label = action.name
        props = {"action": action.name, "label": label, "scope": scope}
        description = f"Ran {label}"
        targets = [record] if record is not None else list(records or [])
        for target in targets:
            panel.log_activity(ctx, "action", target, description, dict(props))
        if not targets:
            model = getattr(host, "model", None)
            panel.log_activity(ctx, "action", None, description, props,
                               subject_type=getattr(model, "__name__", None) or getattr(host, "key", ""))
        ctx.db.commit()

    def _execute(self, ctx: Context, host: Host, action: Action, record: Any, records: Any, keys: list,
                 data: dict, form: Form | None) -> Any:
        """Run the action, one chunk of records at a time for ``chunk_selected_records()``."""
        size = getattr(action, "_chunk_size", None)
        if action.scope != "bulk" or not size:
            return action.execute(ctx, host, record, records, data, form)
        from .jobs import chunks

        action.call_hooks("before", ctx, host, record, None, data, form=form)
        result: Any = None
        for chunk in chunks(keys, size):
            part = action.run(ctx, host, record, host.find_records(ctx, chunk), data, form)
            if isinstance(part, Response):
                return part
            if part is False:
                result = False
        if result is not False:
            action.call_hooks("after", ctx, host, record, None, data, form=form, result=result)
        return result

    def _chain(self, ctx: Context, host: Host, action: Action, record: Any, records: Any, scope: str, keys: list,
               level: int, result: Any, depth: int = 0) -> Response | None:
        """Open (or run) the action set with ``then()``, in the same modal. None when there is none."""
        target = action.next_action(ctx, record, records, result)
        if target is None or depth > 5:
            return None
        nxt: Action | None = None
        if isinstance(target, Action):
            nxt = action.find_nested(target.name)  # ``then(Action(...))`` keeps it as a nested action
            if nxt is None:
                target = target.name
            else:
                nxt.scope = action.scope
        if nxt is None:
            nxt = action.find_nested(str(target))
            if nxt is not None:
                nxt.scope = action.scope
            else:
                try:
                    nxt = self._find_root_action(ctx, host, action.scope, str(target), record)
                except NotFound:
                    if action.scope == "page":
                        raise
                    nxt = self._find_root_action(ctx, host, "page", str(target), record)
        if not self.action_available(nxt, host, ctx, record):
            raise Forbidden()
        ctx.dispatch("tw-refresh")
        form = self._action_form(ctx, host, nxt, record, records, nxt.scope)
        if nxt.needs_modal():
            if form is not None:
                nxt.fill(form, ctx, record, records)
            response = self._modal(ctx, host, nxt, record, records, nxt.scope, form, keys, level)
            response.headers["HX-Retarget"] = modal_target(level)
            response.headers["HX-Reswap"] = "innerHTML"
            return response
        outcome = self._execute(ctx, host, nxt, record, records, keys, {}, None)
        if outcome is False:
            note = nxt.failure_notification(ctx, record, records)
            if note is not None:
                note.send(ctx)
            ctx.dispatch("tw-close-modal", {"from": level} if level else None)
            return ctx.html("")
        note = nxt.success_notification(ctx, record, records)
        if note is not None:
            note.send(ctx)
        return self._chain(ctx, host, nxt, record, records, scope, keys, level, outcome, depth + 1)

    def _bulk_in_background(self, ctx: Context, fd: Any, host: Host, action: Action, record: Any, scope: str,
                            keys: list, level: int) -> Response:
        fields = [(k, v) for k, v in fd.multi_items() if isinstance(v, str) and k != "records"]
        payload = {"host": host.key, "scope": scope, "name": action.path, "keys": keys, "fields": fields,
                   "record": host.record_key(record) if record is not None else "", "arguments": action.arguments}
        label = action.get_label(action.ev(ctx, host=host))
        self.panel.jobs.dispatch(ctx, "bulk_action", payload, name=f"{label} ({len(keys)})", total=len(keys))
        Notification("Started in the background").body(
            "You will get a notification when it is done.").info().send(ctx)
        ctx.dispatch("tw-close-modal", {"from": level} if level and not action._cancel_parents else None)
        if action._deselect_after:
            ctx.dispatch("tw-deselect")
        return ctx.html("")

    def download(self, ctx: Context, fd: Any) -> Response:
        """The file of a :class:`~tungsten.actions.DownloadAction` (a signed link made when it ran)."""
        from .actions.download import read_token

        payload = read_token(self.panel, ctx.request.query_params.get("token") or "")
        if payload is None:
            raise NotFound()
        if payload.get("user") != (self.panel.auth.user_id(ctx.user) if ctx.user is not None else None):
            raise Forbidden()
        host = self.resolve_host(ctx, payload.get("host"))
        key = payload.get("record") or ""
        record = host.find_record(ctx, key) if key else None
        if key and record is None:
            raise NotFound()
        action = self.find_action(ctx, host, payload.get("scope") or "page", payload.get("name") or "", record)
        if not getattr(action, "_is_download", False) or not self.action_available(action, host, ctx, record):
            raise Forbidden()
        records = host.find_records(ctx, payload.get("keys") or []) if payload.get("scope") == "bulk" else None
        action.arguments = dict(payload.get("arguments") or {})
        return action.response(ctx, host, record, records, payload.get("data") or {})

    # ------------------------------------------------------------------ live forms
    def _resolve_form(self, ctx: Context, fd: Any) -> Form:
        kind = fd.get("_tw_kind")
        host = self.resolve_host(ctx, fd.get("_tw_host"))
        record_key = fd.get("_tw_record") or ""
        if kind == "host":
            operation = fd.get("_tw_op") or "create"
            record = host.find_record(ctx, record_key) if record_key else (ctx.user if host.key == "profile" else None)
            if record_key and record is None:
                raise NotFound()
            if host.key.startswith(("resource:", "relation:")):
                self.check_operation(ctx, host, operation, record)
            form = self.host_form(ctx, host, operation, record)
        elif kind == "action":
            scope = fd.get("_tw_scope") or "page"
            record = host.find_record(ctx, record_key) if record_key else None
            action = self.find_action(ctx, host, scope, fd.get("_tw_name") or "", record)
            if not action.is_available(host, ctx, record):
                raise Forbidden()
            records = host.find_records(ctx, fd.getlist("records")) if scope == "bulk" else None
            form = self._action_form(ctx, host, action, record, records, scope)
            if form is None:
                raise NotFound()
        else:
            raise NotFound()
        form_id = fd.get("_tw_form_id")
        if form_id and SAFE_ID.match(form_id):
            form.id = form_id
        return form

    def form_refresh(self, ctx: Context, fd: Any) -> Response:
        form = self._resolve_form(ctx, fd)
        form.load(fd)
        for key in list(fd.keys()):
            if not key.endswith(".__upload"):
                continue
            upload = fd.get(key)
            path = key[: -len(".__upload")]
            if not getattr(upload, "filename", None):
                continue
            owner = form.form_for(path)
            found = owner.find(path)
            if found is None or not hasattr(found[0], "accept_upload"):
                continue
            field = found[0]
            if field.is_disabled(owner, found[2]):
                continue
            error = field.check_upload(upload.filename, upload.content_type or "", upload.size or 0)
            if error is None:
                try:
                    stored = blocking(self.panel.storage.save, upload.file, upload.filename, field._directory)
                    if self.panel.upload_listeners:
                        stored = self.panel.uploaded(ctx, stored, upload.filename, upload.content_type or "",
                                                     upload.size or 0, field)
                    field.accept_upload(owner, path, stored)
                except ValueError as exc:
                    error = str(exc)
            if error:
                owner.add_error(path, error)
        ui_action = fd.get("_tw_ui_action")
        if ui_action:
            form.handle_ui_action(ui_action)
            if ui_action.startswith("faction."):
                ctx.db.commit()  # a form action may have saved something (e.g. a new Select option)
        else:
            changed = ctx.request.headers.get("HX-Trigger-Name")
            if changed:
                form.state_updated(changed)
        return ctx.html(form.render())

    def form_options(self, ctx: Context, fd: Any) -> Response:
        form = self._resolve_form(ctx, fd)
        form.load(fd)
        owner = form.form_for(fd.get("_tw_field") or "")
        found = owner.find(fd.get("_tw_field") or "")
        if found is None or not hasattr(found[0], "search_options"):
            raise NotFound()
        options = found[0].search_options(owner, fd.get("q") or "")
        return JSONResponse([{"value": str(k), "text": label} for k, label in options])

    def form_attachment(self, ctx: Context, fd: Any) -> Response:
        """A file dropped into a RichEditor: store it and return its URL."""
        form = self._resolve_form(ctx, fd)
        form.load(fd)
        path = fd.get("_tw_field") or ""
        owner = form.form_for(path)
        found = owner.find(path)
        field = found[0] if found else None
        if field is None or not hasattr(field, "check_attachment") or field.is_disabled(owner, found[2]) \
                or not field.attachments_enabled(owner, found[2]):
            raise NotFound()
        upload = fd.get("file")
        if not getattr(upload, "filename", None):
            return JSONResponse({"error": __("Choose a file.")}, status_code=422)
        error = field.check_attachment(upload.filename, upload.content_type or "", upload.size or 0)
        if error is None:
            try:
                stored = blocking(self.panel.storage.save, upload.file, upload.filename, field._attachments_directory)
                if self.panel.upload_listeners:
                    stored = self.panel.uploaded(ctx, stored, upload.filename, upload.content_type or "",
                                                 upload.size or 0, field)
            except ValueError as exc:
                error = str(exc)
        if error:
            return JSONResponse({"error": error}, status_code=422)
        url = self.panel.storage.url(stored)
        return JSONResponse({"url": url, "href": url, "path": stored})

    # ------------------------------------------------------------------ global search
    def search(self, ctx: Context, fd: Any) -> Response:
        from .tables.table import Table

        q = (ctx.request.query_params.get("q") or "").strip()
        groups = []
        pages = []
        if q:
            ql = q.lower()
            for group in self.panel.build_navigation(ctx):
                for item in group.items + [c for i in group.items for c in i.children]:
                    if ql in item.label.lower():
                        pages.append(item)
            for resource in self.panel.get_resources():
                if not resource.global_search_attributes or not resource.can(ctx, "view_any"):
                    continue
                host = resource.host()
                helper = Table()
                helper.model = resource.model
                conds = []
                for attr in resource.global_search_attributes:
                    try:
                        conds.append(helper._relation_condition(
                            resource.model, attr, lambda c: cast(c, String).ilike(f"%{q}%")))
                    except (KeyError, AttributeError):
                        continue
                if not conds:
                    continue
                query = host.scoped_query(ctx, with_trashed=False).where(or_(*conds)).limit(resource.global_search_limit)
                records = ctx.db.scalars(query).all()
                if not records:
                    continue
                items = []
                for rec in records:
                    url = (host.edit_url(ctx, rec) if resource.can(ctx, "update", rec) else None) or host.view_url(ctx, rec)
                    items.append({
                        "title": resource.global_search_title(rec),
                        "details": resource.global_search_details(rec),
                        "image": resource.global_search_image(rec),
                        "url": url or resource.get_url(ctx),
                    })
                groups.append({"label": resource.get_plural_label(), "icon": resource.icon, "entries": items})
        html = self.panel.renderer.render("tungsten/components/search-results.html", q=q, groups=groups,
                                          pages=pages[:6], ctx=ctx)
        return ctx.html(html)

    # ------------------------------------------------------------------ notifications
    def _notification_query(self, ctx: Context):
        from .models import DatabaseNotification

        uid = self.panel.auth.user_id(ctx.user)
        return select(DatabaseNotification).where(DatabaseNotification.user_id == uid)

    def notifications(self, ctx: Context, fd: Any) -> Response:
        import datetime as dt

        from .models import DatabaseNotification

        if ctx.user is None or not self.panel.database_notifications:
            raise NotFound()
        uid = self.panel.auth.user_id(ctx.user)
        if fd is not None:
            nid = fd.get("id")
            stmt = update(DatabaseNotification).where(DatabaseNotification.user_id == uid,
                                                      DatabaseNotification.read_at.is_(None))
            if fd.get("clear"):
                for n in ctx.db.scalars(self._notification_query(ctx)):
                    ctx.db.delete(n)
            elif nid:
                ctx.db.execute(stmt.where(DatabaseNotification.id == int(nid)).values(read_at=dt.datetime.now()))
            else:
                ctx.db.execute(stmt.values(read_at=dt.datetime.now()))
            ctx.db.commit()
            ctx.dispatch("tw-notifications-changed")
        items = ctx.db.scalars(self._notification_query(ctx).order_by(DatabaseNotification.id.desc()).limit(30)).all()
        unread = sum(1 for n in items if n.read_at is None)
        html = self.panel.renderer.render("tungsten/components/notifications.html", items=items, unread=unread, ctx=ctx)
        return ctx.html(html)

    def notifications_badge(self, ctx: Context, fd: Any) -> Response:
        from .models import DatabaseNotification

        if ctx.user is None or not self.panel.database_notifications:
            return ctx.html("")
        count = ctx.db.scalar(select(func.count()).select_from(
            self._notification_query(ctx).where(DatabaseNotification.read_at.is_(None)).subquery())) or 0
        return ctx.html(self.panel.renderer.render("tungsten/components/notification-badge.html", count=count))

    # ------------------------------------------------------------------ live push
    async def live(self, websocket: WebSocket) -> None:
        """The WebSocket each signed-in tab keeps open: forwards what the broadcaster publishes for its user."""
        import asyncio
        import json
        from urllib.parse import urlsplit

        panel = self.panel
        origin = websocket.headers.get("origin")
        if origin and urlsplit(origin).netloc != websocket.headers.get("host"):
            await websocket.close(code=4403)  # another site trying to listen in with the user's cookie
            return
        user_id = await self._live_user(websocket) if panel.notifications_live else None
        if user_id is None:
            await websocket.close(code=4401)
            return
        await websocket.accept()

        async def reader() -> None:  # notices the tab going away; the browser sends nothing else
            while True:
                if (await websocket.receive()).get("type") == "websocket.disconnect":
                    return

        async with panel.broadcaster.subscribe(user_id) as queue:
            closed = asyncio.ensure_future(reader())
            getter = asyncio.ensure_future(queue.get())
            try:
                while not closed.done():
                    done, _ = await asyncio.wait({getter, closed}, timeout=25,
                                                 return_when=asyncio.FIRST_COMPLETED)
                    if getter in done:
                        await websocket.send_text(json.dumps(getter.result(), default=str))
                        getter = asyncio.ensure_future(queue.get())
                    elif not closed.done():  # keep proxies from dropping a quiet connection
                        await websocket.send_text('{"type": "ping"}')
            except (WebSocketDisconnect, RuntimeError):
                pass
            finally:
                getter.cancel()
                closed.cancel()

    async def _live_user(self, websocket: WebSocket) -> str | None:
        """The id of the signed-in, active user on this socket's session cookie."""
        panel, auth = self.panel, self.panel.auth
        if not auth.enabled:
            return None
        raw = websocket.session.get(auth.session_key())
        if raw is None:
            return None

        def check(db: Any) -> str | None:
            user = auth.find_by_id(db, raw)
            return auth.user_id(user) if user is not None and auth.is_active(user) else None

        if panel.is_async:
            async with panel.session_factory() as adb:
                return await adb.run_sync(check)

        def run() -> str | None:
            with panel.session_factory() as db:
                return check(db)

        return await run_in_threadpool(run)

    # ------------------------------------------------------------------ widgets / tenants
    def widget(self, ctx: Context, fd: Any, widget_id: str) -> Response:
        widget = self.panel.widget(widget_id)
        if widget is None:
            raise NotFound()
        if not widget.can_view(ctx):
            raise Forbidden()
        slug = ctx.request.query_params.get("_tw_page")
        if slug is not None:  # the page the widget sits on: its filters reach the widget
            page = self.panel.page(slug)
            if page is not None and page.can_access(ctx):
                ctx.page = page
        return ctx.html(widget.render(ctx))

    def export(self, ctx: Context, fd: Any) -> Response:
        import io

        from .importexport import (ExportAction, ExportBulkAction, export_name, export_rows, find_offered_action,
                                   record_export, write_file)

        params = ctx.request.query_params
        host = self.resolve_host(ctx, params.get("host"))
        if host.get_table(ctx) is None:
            raise NotFound()
        keys = params.getlist("keys") or None
        fmt = "xlsx" if params.get("format") == "xlsx" else "csv"
        # only export what the table offers: an export action (bulk for selected rows) the user may run
        action = find_offered_action(ctx, host, ExportBulkAction if keys else ExportAction, params.get("action"),
                                     bulk=bool(keys))
        if action is None:
            raise Forbidden()
        rows = export_rows(ctx, host, params, keys, params.getlist("columns") or None, action.export_columns)
        out = io.BytesIO()
        count = write_file(rows, fmt, out)
        media = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx"
                 else "text/csv; charset=utf-8")
        record_export(ctx, host, fmt, count, str(ctx.request.url.path) + "?" + str(ctx.request.url.query))
        if self.panel.activity_log:
            model = getattr(host, "model", None)
            self.panel.log_activity(ctx, "exported", None, f"Exported {fmt.upper()}",
                                    {"format": fmt, "selected": len(keys or [])},
                                    subject_type=getattr(model, "__name__", None) or host.key, commit=True)
        return Response(out.getvalue(), media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{export_name(host)}.{fmt}"'})

    def export_history(self, ctx: Context, fd: Any) -> Response:
        """The signed-in user's exports, newest first, with their files while they are kept."""
        from .importexport import EXPORT_FILE_DAYS
        from .models import Job

        if ctx.user is None:
            raise NotFound()
        query = select(Job).where(Job.kind == "export", Job.user_id == self.panel.auth.user_id(ctx.user))
        if self.panel.tenancy.enabled:
            key = self.panel.tenancy.key_of(ctx.tenant) if ctx.tenant is not None else None
            query = query.where(Job.tenant_key == key)
        jobs = ctx.db.scalars(query.order_by(Job.id.desc()).limit(100)).all()
        items = []
        for job in jobs:
            payload, result = job.payload or {}, job.result or {}
            url = None
            if job.status == "done" and result.get("file"):
                url = self.panel.url("_tw", "exports", job.id, "download")
            elif job.status in ("done", "expired") and payload.get("rerun"):
                url = payload["rerun"]
            items.append({"job": job, "format": (payload.get("format") or result.get("format") or "csv").upper(),
                          "url": url, "fresh": url is not None and not result.get("file"),
                          "background": "rerun" not in payload})
        return ctx.render("tungsten/pages/exports.html", title=__("Export history"), items=items,
                          keep_days=EXPORT_FILE_DAYS)

    def export_file(self, ctx: Context, fd: Any, job_id: int) -> Response:
        from .models import Job

        job = ctx.db.get(Job, job_id)
        if job is None or job.kind != "export" or ctx.user is None:
            raise NotFound()
        if job.user_id != self.panel.auth.user_id(ctx.user):
            raise Forbidden()
        path = (job.result or {}).get("file")
        if job.status != "done" or not path:
            raise NotFound()
        storage = self.panel.storage
        filename = (job.result or {}).get("filename") or path.rsplit("/", 1)[-1]
        if hasattr(storage, "path"):
            try:
                full = storage.path(path)
            except ValueError:
                raise NotFound() from None
            if not full.is_file():
                raise NotFound()
            return FileResponse(full, filename=filename, headers={"Cache-Control": "no-store"})
        return ctx.go(storage.url(path))

    def import_example(self, ctx: Context, fd: Any) -> Response:
        """The sample CSV of an import action (the "Download example CSV" link in its popup)."""
        from .importexport import ImportAction, find_offered_action

        params = ctx.request.query_params
        host = self.resolve_host(ctx, params.get("host"))
        action = find_offered_action(ctx, host, ImportAction, params.get("action"))
        if action is None:
            raise Forbidden()
        name = re.sub(r"[^a-z0-9-]+", "-", (host.title() or "import").lower()).strip("-") or "import"
        return Response(action.importer.example_csv(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}-example.csv"'})

    def switch_locale(self, ctx: Context, fd: Any) -> Response:
        code = (fd.get("locale") if fd is not None else None) or ""
        if code in self.panel.locales:
            ctx.session["tw_locale"] = code
        return ctx.refresh()

    def switch_tenant(self, ctx: Context, fd: Any) -> Response:
        tenancy = self.panel.tenancy
        tenant = tenancy.switch(ctx, fd.get("tenant") or "") if tenancy.enabled else None
        if tenant is None:
            raise NotFound()
        return ctx.go(tenancy.url(ctx, tenant))

    # ------------------------------------------------------------------ tenant pages
    def tenant_register(self, ctx: Context, fd: Any) -> Response:
        tenancy = self.panel.tenancy
        if not tenancy.enabled or tenancy.registration is None or ctx.user is None:
            raise NotFound()
        form = tenancy.build_form(ctx, "register")
        form.id = "tw-tenant-form"
        if fd is None:
            form.fill()
            return ctx.render("tungsten/pages/tenant-form.html", form=form, action_url=self.panel.url("tenant", "new"),
                              title=__("Register :label", label=tenancy.get_label().lower()),
                              subheading=__("Create a new :label to work in.", label=tenancy.get_label().lower()),
                              submit_label=__("Register"), submit_icon="plus")
        form.load(fd)
        try:
            data = form.validate()
        except ValidationError:
            return ctx.html(form.render())
        tenant = tenancy.register(ctx, data, form)
        Notification("Created").body(__(":label was created.", label=tenancy.label(tenant))).success().send(ctx)
        return ctx.go(tenancy.url(ctx, tenant))

    def tenant_profile(self, ctx: Context, fd: Any) -> Response:
        tenancy = self.panel.tenancy
        if not tenancy.enabled or tenancy.profile is None or ctx.tenant is None:
            raise NotFound()
        if not tenancy.can_profile(ctx):
            raise Forbidden()
        form = tenancy.build_form(ctx, "profile", ctx.tenant)
        form.id = "tw-tenant-form"
        if fd is None:
            form.fill(ctx.tenant)
            return ctx.render("tungsten/pages/tenant-form.html", form=form,
                              action_url=self.panel.url("tenant", "profile"),
                              title=__(":label settings", label=tenancy.get_label()),
                              subheading=tenancy.label(ctx.tenant), submit_label=__("Save changes"),
                              submit_icon="save")
        form.load(fd)
        try:
            data = form.validate()
        except ValidationError:
            return ctx.html(form.render())
        old_slug = tenancy.slug_of(ctx.tenant)
        tenancy.update_profile(ctx, data, form)
        Notification("Saved").body("Your changes were saved.").success().send(ctx)
        if tenancy.in_url and tenancy.slug_of(ctx.tenant) != old_slug:
            return ctx.go(tenancy.url(ctx, ctx.tenant, "tenant", "profile"))
        form = tenancy.build_form(ctx, "profile", ctx.tenant)
        form.id = "tw-tenant-form"
        form.fill(ctx.tenant)
        return ctx.html(form.render())

    def tenant_billing(self, ctx: Context, fd: Any) -> Response:
        tenancy = self.panel.tenancy
        if not tenancy.enabled or tenancy.billing is None or ctx.tenant is None:
            raise NotFound()
        if not tenancy.can_billing(ctx):
            raise Forbidden()
        target = tenancy.billing.billing_url(ctx, ctx.tenant)
        if target:
            return ctx.finalize(RedirectResponse(target, status_code=303))
        return ctx.render("tungsten/pages/tenant-billing.html", title=__(tenancy.billing.label),
                          subheading=tenancy.label(ctx.tenant),
                          content=tenancy.billing.content(ctx, ctx.tenant),
                          subscribed=tenancy.billing.is_subscribed(ctx, ctx.tenant))

