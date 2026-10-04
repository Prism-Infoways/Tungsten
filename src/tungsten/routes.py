"""HTTP routes for a panel. Handlers are plain sync functions with their own
DB session: in a thread pool for a sync engine, or inside
``AsyncSession.run_sync`` for an async engine (see :meth:`Routes.run`)."""

from __future__ import annotations

import logging
import re
import secrets
import time
from typing import TYPE_CHECKING, Any, Callable

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import String, cast, func, or_, select, update
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import QueryParams
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from .actions.action import Action, Halt, flatten_actions
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
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.mount("/assets", CachedStaticFiles(directory=STATIC_DIR / "tungsten"), name="assets")
    for plugin in panel._plugins:
        if plugin.static:
            app.mount(f"/plugins/{plugin.id}", StaticFiles(directory=str(plugin.static)), name=f"plugin-{plugin.id}")
    routes = Routes(panel)
    routes.register(app)
    return app


class Routes:
    def __init__(self, panel: "Panel") -> None:
        self.panel = panel

    # ------------------------------------------------------------------ plumbing
    async def run(self, request: Request, handler: Callable, *, public: bool = False, read_form: bool = False,
                  **kwargs: Any) -> Response:
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
        try:
            return self._dispatch(ctx, db, handler, public, formdata, kwargs)
        finally:
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
        if kind == "profile" and panel.auth.enabled:
            from .auth.profile import ProfileHost

            return ProfileHost(panel)
        raise NotFound()

    def find_action(self, ctx: Context, host: Host, scope: str, name: str, record: Any = None,
                    params: Any = None) -> Action:
        if scope == "page":
            getter = getattr(host, "all_page_actions", None) or host.page_actions
            for a in flatten_actions(getter(ctx, record)):
                if a.name == name:
                    a.scope = "page"
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

        @g("/_tw/search")
        async def search(request: Request):
            return await r.run(request, r.search)

        @g("/_tw/notifications")
        async def notifications(request: Request):
            return await r.run(request, r.notifications)

        @p("/_tw/notifications")
        async def notifications_post(request: Request):
            return await r.run(request, r.notifications, read_form=True)

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

    def storage_file(self, ctx: Context, fd: Any, path: str) -> Response:
        storage = self.panel.storage
        if not hasattr(storage, "path"):
            return Response(status_code=404)
        try:
            full = storage.path(path)
        except ValueError:
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
                    return RedirectResponse(nxt, status_code=303)
            except ValidationError:
                pass
            except PermissionError as exc:
                error = str(exc)
        else:
            form.fill()
        return ctx.render("tungsten/auth/login.html", form=form, error=error,
                          next=ctx.request.query_params.get("next", ""))

    def logout(self, ctx: Context, fd: Any) -> Response:
        self.panel.auth.logout(ctx)
        return RedirectResponse(self.panel.url("login"), status_code=303)

    def two_factor_challenge(self, ctx: Context, fd: Any) -> Response:
        from .auth.two_factor import TwoFactor
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
        form = self._auth_form(ctx, [
            TextInput("code").label("Authentication code").required().autofocus().autocomplete("one-time-code")
            .placeholder("123 456").helper_text("Open your authenticator app, or enter one of your recovery codes."),
        ])
        error = None
        if fd is not None:
            form.load(fd)
            try:
                data = form.validate()
                key = f"2fa|{pending['id']}"
                if panel.auth.throttled(key):
                    raise PermissionError("Too many attempts. Please try again in a minute.")
                if TwoFactor(ctx, user).verify(data["code"]):
                    ctx.session.pop("tw_2fa_pending", None)
                    panel.auth.login(ctx, user)
                    return RedirectResponse(pending.get("next") or panel.url(), status_code=303)
                panel.auth._attempts[key].append(time.monotonic())
                form.add_error("code", "That code is not valid.")
            except ValidationError:
                pass
            except PermissionError as exc:
                error = str(exc)
        else:
            form.fill()
        return ctx.render("tungsten/auth/two-factor-challenge.html", form=form, error=error)

    def two_factor_setup(self, ctx: Context, fd: Any) -> Response:
        from .auth.two_factor import TwoFactor, otpauth_uri

        panel = self.panel
        if not panel.auth.two_factor:
            raise NotFound()
        tf = TwoFactor(ctx, ctx.user)
        auth = panel.auth
        step, codes, error = ("enabled" if tf.enabled else "off"), None, None
        if fd is not None:
            do = fd.get("_do")
            if do == "enable" and not tf.enabled:
                tf.start()
                step = "confirm"
            elif do == "confirm" and not tf.enabled:
                codes = tf.confirm(fd.get("code") or "")
                if codes is None:
                    step, error = "confirm", "That code is not valid. Check your phone's clock and try again."
                else:
                    step = "codes"
                    Notification("Two-factor authentication is on").success().send(ctx)
            elif do in ("disable", "codes") and tf.enabled:
                if not auth.verify(fd.get("password") or "", getattr(ctx.user, auth.password_field, None)):
                    error = "Your password is incorrect."
                elif do == "disable":
                    if auth.two_factor_required:
                        error = "Two-factor authentication is required for this panel."
                    else:
                        tf.disable()
                        step = "off"
                        Notification("Two-factor authentication is off").warning().send(ctx)
                else:
                    codes = tf.regenerate_codes()
                    step = "codes"
        secret = tf.credential.secret if step == "confirm" and tf.credential else None
        account = str(getattr(ctx.user, auth.email_field, ""))
        return ctx.render(
            "tungsten/auth/two-factor-setup.html",
            title=__("Two-factor authentication"),
            step=step, codes=codes, error=error, secret=secret,
            uri=otpauth_uri(secret, account, panel.brand_name) if secret else None,
            remaining=len(tf.credential.recovery_codes or []) if tf.enabled and tf.credential else 0,
            required=auth.two_factor_required,
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
                if auth.is_active(user) and auth.allowed(ctx, user):
                    auth.login(ctx, user)
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
            return ctx.render("tungsten/pages/profile.html", form=form, title=__("My profile"), two_factor=two_factor)
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
                raise NotFound()
            return self.custom_page(ctx, fd, page)
        if fd is not None:
            raise NotFound()
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
            self.panel.log_activity(ctx, "created", record)
            ctx.db.commit()
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
            self.panel.log_activity(ctx, "updated", record)
            ctx.db.commit()
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
            trashed=host.is_trashed(record),
            title=(__("Edit :label", label=resource.get_label().lower()) if operation == "edit" else title_record),
            breadcrumbs=[(resource.get_plural_label(), resource.get_url(ctx)),
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
    def _action_context(self, ctx: Context, src: Any) -> tuple:
        host = self.resolve_host(ctx, src.get("_tw_host"))
        scope = src.get("_tw_scope") or "page"
        name = src.get("_tw_name") or ""
        key = src.get("_tw_record") or ""
        record = host.find_record(ctx, key) if key else None
        if key and record is None:
            raise NotFound()
        action = self.find_action(ctx, host, scope, name, record, params=src)
        records = None
        if scope == "bulk":
            keys = list(dict.fromkeys(src.getlist("records")))
            records = host.find_records(ctx, keys)
        if not action.is_available(host, ctx, record):
            raise Forbidden()
        return host, action, record, records, scope

    def _action_form(self, ctx: Context, host: Host, action: Action, record: Any, records: Any, scope: str,
                     form_id: str | None = None) -> Form | None:
        form = action.build_form(ctx, host, record, records)
        if form is None:
            return None
        operation = getattr(action, "operation", "create")
        form.bind(ctx, operation=operation, record=record, id=form_id or "tw-action-form",
                  source={"kind": "action", "host": host.key, "scope": scope, "name": action.name,
                          "record": host.record_key(record) if record is not None else ""})
        return form

    def _modal(self, ctx: Context, host: Host, action: Action, record: Any, records: Any, scope: str,
               form: Form | None) -> Response:
        ev = action.ev(ctx, record, records, host=host)
        heading = evaluate(action._modal_heading, **ev)
        if heading is None:
            heading = action.get_modal_heading(host) if hasattr(action, "get_modal_heading") else action.get_label(ev)
            if getattr(action, "operation", None) in ("edit", "view") and record is not None:
                heading = f"{action.get_label(ev)} {host.record_title(record)}".strip()
        heading = maybe(heading)
        description = maybe(evaluate(action._modal_description, **ev))
        if description is None and hasattr(action, "get_modal_description"):
            description = action.get_modal_description(host)
        confirm_only = form is None
        if description is None and confirm_only:
            description = __("Are you sure you would like to do this?")
            if scope == "bulk":
                description = __("Are you sure you want to do this to :count selected records?", count=len(records or []))
        submit = maybe(evaluate(action._modal_submit_label, **ev)) if action._modal_submit_label is not None else (
            None if getattr(action, "operation", None) == "view" else (__("Confirm") if confirm_only else __("Submit")))
        if hasattr(action, "operation") and action._modal_submit_label is None:
            submit = {"create": __("Create"), "edit": __("Save changes"), "view": None}.get(action.operation, submit)
        another = form is not None and getattr(action, "_create_another", False)
        color = evaluate(action._color, **ev) or "primary"
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
            "content": evaluate(action._modal_content, **ev),
            "multipart": False,
            "create_another_label": __("Create & create another") if another else None,
        }
        hidden = {"_tw_host": host.key, "_tw_scope": scope, "_tw_name": action.name,
                  "_tw_record": host.record_key(record) if record is not None else ""}
        keys = [host.record_key(r) for r in records or []]
        html = self.panel.renderer.render("tungsten/actions/modal.html", m=m, form=form, hidden=hidden, records=keys,
                                          ctx=ctx)
        return ctx.html(html)

    def action(self, ctx: Context, fd: Any) -> Response:
        src = fd if fd is not None else ctx.request.query_params
        host, action, record, records, scope = self._action_context(ctx, src)
        if scope == "bulk" and not records:
            Notification("Select some records first").warning().send(ctx)
            return ctx.finalize(Response(status_code=204))
        form = self._action_form(ctx, host, action, record, records, scope)
        if fd is None:  # open the modal
            if form is not None:
                action.fill(form, ctx, record, records)
            return self._modal(ctx, host, action, record, records, scope, form)
        data: dict = {}
        if form is not None:
            form.load(fd)
            try:
                data = form.validate()
            except ValidationError:
                return self._modal(ctx, host, action, record, records, scope, form)
        try:
            result = action.run(ctx, host, record, records, data, form)
        except Halt:
            if form is not None:
                return self._modal(ctx, host, action, record, records, scope, form)
            return ctx.finalize(Response(status_code=204))
        except ValidationError as exc:
            if form is not None:
                form.errors = exc.errors
                return self._modal(ctx, host, action, record, records, scope, form)
            raise
        except (NotFound, Forbidden, PermissionError):
            raise
        except Exception:
            if action._failure_title is None:
                raise
            # a failure toast is set: show it instead of an error page
            ctx.db.rollback()
            logging.getLogger("tungsten").exception("Action %r failed", action.name)
            result = False
        if isinstance(result, Response):
            return result
        if result is False:  # the action failed
            note = action.failure_notification(ctx, record, records)
            if note is not None:
                note.send(ctx)
            if form is not None:
                return self._modal(ctx, host, action, record, records, scope, form)
            ctx.dispatch("tw-close-modal")
            return ctx.html("")
        note = action.success_notification(ctx, record, records)
        if note is not None:
            note.send(ctx)
        if fd.get("_tw_another") and form is not None and getattr(action, "_create_another", False):
            # "Create & create another": refresh the table behind and open an empty form again
            ctx.dispatch("tw-refresh")
            fresh = self._action_form(ctx, host, action, record, records, scope)
            action.fill(fresh, ctx, record, records)
            return self._modal(ctx, host, action, record, records, scope, fresh)
        redirect = ctx.redirect_to or evaluate(action._success_redirect, **action.ev(ctx, record, records, result=result))
        if redirect:
            return ctx.go(redirect)
        if scope == "page":
            return ctx.refresh()
        ctx.dispatch("tw-refresh")
        ctx.dispatch("tw-close-modal")
        if scope == "bulk" and action._deselect_after:
            ctx.dispatch("tw-deselect")
        return ctx.html("")

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
            found = form.find(path)
            if found is None or not hasattr(found[0], "accept_upload"):
                continue
            field = found[0]
            if field.is_disabled(form, found[2]):
                continue
            error = field.check_upload(upload.filename, upload.content_type or "", upload.size or 0)
            if error is None:
                try:
                    stored = blocking(self.panel.storage.save, upload.file, upload.filename, field._directory)
                    field.accept_upload(form, path, stored)
                except ValueError as exc:
                    error = str(exc)
            if error:
                form.add_error(path, error)
        ui_action = fd.get("_tw_ui_action")
        if ui_action:
            form.handle_ui_action(ui_action)
        else:
            changed = ctx.request.headers.get("HX-Trigger-Name")
            if changed:
                form.state_updated(changed)
        return ctx.html(form.render())

    def form_options(self, ctx: Context, fd: Any) -> Response:
        form = self._resolve_form(ctx, fd)
        form.load(fd)
        found = form.find(fd.get("_tw_field") or "")
        if found is None or not hasattr(found[0], "search_options"):
            raise NotFound()
        options = found[0].search_options(form, fd.get("q") or "")
        return JSONResponse([{"value": str(k), "text": label} for k, label in options])

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
        from .importexport import (ExportAction, ExportBulkAction, export_rows, find_offered_action, write_csv,
                                   write_xlsx)

        params = ctx.request.query_params
        host = self.resolve_host(ctx, params.get("host"))
        if host.get_table(ctx) is None:
            raise NotFound()
        keys = params.getlist("keys") or None
        fmt = params.get("format", "csv")
        # only export what the table offers: an export action (bulk for selected rows) the user may run
        action = find_offered_action(ctx, host, ExportBulkAction if keys else ExportAction, params.get("action"),
                                     bulk=bool(keys))
        if action is None:
            raise Forbidden()
        rows = export_rows(ctx, host, params, keys, params.getlist("columns") or None, action.export_columns)
        name = re.sub(r"[^a-z0-9-]+", "-", (host.title() or "export").lower()).strip("-") or "export"
        if fmt == "xlsx":
            body, media = write_xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            body, media, fmt = write_csv(rows), "text/csv; charset=utf-8", "csv"
        return Response(body, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})

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
        if not self.panel.tenancy.enabled or not self.panel.tenancy.switch(ctx, fd.get("tenant") or ""):
            raise NotFound()
        return ctx.go(self.panel.url())

