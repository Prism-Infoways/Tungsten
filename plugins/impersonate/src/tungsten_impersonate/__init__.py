"""Impersonate plugin for Tungsten: an admin logs in as another user to see what they see.

    from tungsten_impersonate import ImpersonatePlugin

    panel.plugin(ImpersonatePlugin())
    panel.create_tables(engine)   # also creates the impersonation log table

Adds a "Log in as" button to your users (and to HR employees and ticket customers that have a
login), a bar on top of every page with "Back to my account", a time limit, and a log of who
logged in as whom, when and why.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Request
from markupsafe import Markup

from tungsten import Notification, Plugin
from tungsten.actions import Action
from tungsten.forms import Textarea
from tungsten.routes import Routes
from tungsten.support.evaluate import call

from .models import ImpersonateBase, ImpersonationLog
from .service import (
    PERMISSION,
    ImpersonationError,
    back_url,
    can_impersonate,
    can_impersonate_user,
    end,
    expired,
    impersonator_id,
    is_impersonating,
    minutes_left,
    refusal,
    start,
    state,
    state_key,
)

__version__ = "0.1.0"

log = logging.getLogger("tungsten.impersonate")

LOG_PERMISSION = "impersonation-log.view_any"


class ImpersonatePlugin(Plugin):
    """``ImpersonatePlugin(can_impersonate=None, can_be_impersonated=None, max_minutes=60, ...)``.

    - ``can_impersonate(user, ctx)``: who may log in as others. Default: everyone when the panel has
      no roles; with roles, super admins and roles with the "Log in as other users" permission.
    - ``can_be_impersonated(user, target, ctx)``: an extra rule per user. Super admins are never
      allowed, and with ``no_more_access`` nobody can become a user with access they don't have.
    - ``max_minutes``: the admin is sent back to their own account after this long (``0``: no limit).
    - ``require_reason``: ask why before logging in (saved in the log). ``ask_reason=False`` leaves the
      optional "Why?" field out.
    - ``can_view_log(user, ctx)``: who sees the impersonation log. Default: whoever may log in as others.
    - ``redirect_to``: page to open as the user (a path or ``fn(user, ctx)``). Default: the panel home.
    - ``users``: add the button to the resource of your user model.
    - ``link_plugins``: also add it to HR employees and help desk tickets when those plugins are installed.
    - ``on_start(db, log, user, target, ctx)`` / ``on_end(db, state, reason, ctx)``: your own hooks.
    """

    id = "impersonate"
    metadata = ImpersonateBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, can_impersonate: Callable | None = None, can_be_impersonated: Callable | None = None,
                 max_minutes: int | None = 60, require_reason: bool = False, no_more_access: bool = True,
                 redirect_to: Any = None, users: bool = True, link_plugins: bool = True, banner: bool = True,
                 log_resource: bool = True, trust_proxy: bool = False, on_start: Callable | None = None,
                 on_end: Callable | None = None, navigation_group: str = "Security",
                 label: str = "Log in as", ask_reason: bool = True, can_view_log: Callable | None = None) -> None:
        self.can_impersonate = can_impersonate
        self.can_be_impersonated = can_be_impersonated
        self.max_minutes = max(0, int(max_minutes or 0))
        self.require_reason = require_reason
        self.ask_reason = ask_reason
        self.can_view_log = can_view_log
        self.no_more_access = no_more_access
        self.redirect_to = redirect_to
        self.users = users
        self.link_plugins = link_plugins
        self.banner = banner
        self.log_resource = log_resource
        self.trust_proxy = trust_proxy
        self.on_start = on_start
        self.on_end = on_end
        self.navigation_group = navigation_group
        self.label = label
        self.panel: Any = None
        #: ``(target, user_of)`` pairs added with :meth:`link`, for other plugins
        self.links: list[tuple[Any, Callable]] = []

    # ------------------------------------------------------------------ hooks for other code
    def link(self, target: Any, user_of: Callable[[Any, Any], Any] | None = None, label: str | None = None) -> None:
        """Put a "Log in as" button on another resource's records.

        ``target`` is a resource class, model or slug; ``user_of(db, record)`` returns the panel user
        behind a record (``None`` hides the button). Without it the record is the user itself.
        Needs a tungsten-admin with ``panel.record_action``; otherwise add :meth:`action` yourself.
        """
        self.links.append((target, user_of))
        if self.panel is not None and hasattr(self.panel, "record_action"):
            self.panel.record_action(target, lambda: self.action(user_of, label=label))

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        if not panel.auth.enabled:
            log.warning("ImpersonatePlugin needs a panel with Auth(User); it does nothing without logins")
            return
        if self.log_resource:
            from .resources import ImpersonationLogResource

            ImpersonationLogResource.navigation_group = self.navigation_group
            panel.resources([ImpersonationLogResource])
        if self.banner:
            panel.render_hook("body.start", self.render_banner)
        panel.routes(self._routes)

    def boot(self, panel: Any) -> None:
        if not panel.auth.enabled:
            return
        self._wrap_auth(panel.auth)
        if self.users and panel.auth.user_model is not None:
            self.link(panel.auth.user_model)
        if self.link_plugins:
            self._link_plugins(panel)

    def permissions(self) -> list[tuple[str, str]]:
        return [(PERMISSION, "Log in as other users")]

    def _link_plugins(self, panel: Any) -> None:
        """Buttons on other plugins' screens. Each plugin is optional; this one works alone."""
        auth = panel.auth
        if panel.get_plugin("hr") is not None:
            try:
                from tungsten_hr.models import Employee

                self.link(Employee, lambda db, record: auth.find_by_id(db, record.user_id) if record.user_id else None)
            except ImportError:  # pragma: no cover - plugin registered under the id without the package
                pass
        if panel.get_plugin("tickets") is not None:
            try:
                from tungsten_tickets.models import Ticket

                def requester(db: Any, record: Any) -> Any:
                    email = (record.requester_email or "").strip()
                    return auth.find_by_email(db, email) if email else None

                # only on the ticket page: looking a user up for every row would slow the list
                if hasattr(panel, "record_action"):
                    panel.record_action(Ticket, lambda: self.action(requester, label="Log in as customer"),
                                        row=False)
            except ImportError:  # pragma: no cover
                pass
        audit = panel.get_plugin("security-audit")
        if audit is not None and hasattr(audit, "checks"):
            from .checks import impersonation_check

            if impersonation_check not in audit.checks:
                audit.checks.append(impersonation_check)

    # ------------------------------------------------------------------ the session
    def _wrap_auth(self, auth: Any) -> None:
        """Check the running impersonation on every request: end it when it ran out or broke."""
        if getattr(auth, "_tungsten_impersonate", None) is not None:
            return
        plugin = self
        original_load, original_logout = auth.load_user, auth.logout

        def load_user(ctx: Any) -> Any:
            current = state(ctx)
            if current is not None:
                plugin._check(ctx, current)
            elif "session" in ctx.request.scope and state_key(ctx.panel) in ctx.session:
                ctx.session.pop(state_key(ctx.panel), None)  # a broken value: drop it
            return original_load(ctx)

        def logout(ctx: Any) -> None:
            if state(ctx) is not None:
                end(plugin, ctx, "logged_out", restore=False)
            return original_logout(ctx)

        auth.load_user = load_user
        auth.logout = logout
        auth._tungsten_impersonate = self

    def _check(self, ctx: Any, current: dict) -> None:
        auth = ctx.panel.auth
        signed_in = ctx.session.get(auth.session_key())
        if signed_in is None or str(signed_in) != str(current["as"]):
            end(self, ctx, "ended", restore=False)  # signed out or in as someone else meanwhile
            return
        if expired(self, current):
            admin = end(self, ctx, "expired")
            if admin is not None:
                Notification("Back to your own account").body(
                    f"Logging in as another user ends after {self.max_minutes} minutes.").warning().send(ctx)

    # ------------------------------------------------------------------ the button
    def action(self, user_of: Callable[[Any, Any], Any] | None = None, name: str = "impersonate",
               label: str | None = None) -> Action:
        """A "Log in as" action for any table or record page.

        ``user_of(db, record)`` returns the panel user behind the record; without it the record is the user.
        """
        plugin = self

        def target_of(ctx: Any, record: Any) -> Any:
            if record is None:
                return None
            cache = ctx.__dict__.setdefault("_tw_impersonate_targets", {})
            key = (name, type(record).__name__, id(record))
            if key not in cache:
                try:
                    cache[key] = call_user_of(ctx, record)
                except Exception:  # a broken lookup hides the button, it never breaks the page
                    log.exception("Could not find the user behind %r", record)
                    cache[key] = None
            return cache[key]

        def call_user_of(ctx: Any, record: Any) -> Any:
            if user_of is None:
                model = ctx.panel.auth.user_model
                return record if model is not None and isinstance(record, model) else None
            return user_of(ctx.db, record)

        def visible(ctx: Any, record: Any = None) -> bool:
            if ctx is None or not can_impersonate(plugin, ctx):
                return False
            target = target_of(ctx, record)
            return target is not None and refusal(plugin, ctx, target) is None

        def run(ctx: Any, record: Any = None, data: dict | None = None) -> None:
            target = target_of(ctx, record)
            try:
                url = start(plugin, ctx, target, (data or {}).get("reason"))
            except ImpersonationError as exc:
                Notification("Can't log in as this user").body(str(exc)).danger().send(ctx)
                return
            ctx.redirect(url)
            return

        def heading(ctx: Any, record: Any = None) -> str:
            target = target_of(ctx, record)
            who = ctx.panel.auth.display_name(target) if target is not None else "this user"
            return f"Log in as {who}?"

        limit = f" It ends by itself after {self.max_minutes} minutes." if self.max_minutes else ""
        action = (
            Action(name).label(label or self.label).icon("venetian-mask").color("gray")
            .visible(visible)
            .requires_confirmation()
            .modal_heading(heading).modal_icon("venetian-mask", "warning")
            .modal_description("You will see the panel exactly as they do. Anything you change is saved as "
                               f"them, and this is written to the impersonation log.{limit}")
            .modal_submit_action_label("Log in as user")
            .action(run)
        )
        if self.require_reason:
            action.form([Textarea("reason").label("Why?").required().max_length(2000).rows(3)
                         .placeholder("e.g. Ticket TCK-00012: customer can't see their invoice")])
        elif self.ask_reason:
            action.form([Textarea("reason").label("Why? (optional)").max_length(2000).rows(2)])
        return action

    @property
    def asks_reason(self) -> bool:
        return self.require_reason or self.ask_reason

    def may_view_log(self, ctx: Any) -> bool:
        """The signed-in user may open the impersonation log."""
        if ctx is None or ctx.user is None:
            return False
        if self.can_view_log is not None:
            return bool(call(self.can_view_log, user=ctx.user, ctx=ctx, panel=ctx.panel))
        from .service import can_impersonate

        return can_impersonate(self, ctx) or (ctx.panel.auth.enabled and ctx.panel.auth.is_super_admin(ctx))

    # ------------------------------------------------------------------ the bar on top
    def render_banner(self, ctx: Any) -> Markup:
        if ctx is None or getattr(ctx, "user", None) is None:
            return Markup("")
        current = state(ctx)
        if current is None:
            return Markup("")
        auth = ctx.panel.auth
        return Markup(ctx.panel.renderer.render(
            "tungsten_impersonate/banner.html", user_name=auth.display_name(ctx.user),
            leave_url=ctx.panel.url("impersonate", "leave"), token=ctx.session.get("tw_csrf", ""),
            minutes_left=minutes_left(self, current)))

    # ------------------------------------------------------------------ routes
    def _routes(self, app: Any, panel: Any) -> None:
        routes = Routes(panel)
        plugin = self

        def leave(ctx: Any, fd: Any) -> Any:
            current = state(ctx)
            if current is None:
                return ctx.go(panel.url())
            back = back_url(ctx, current)
            admin = end(plugin, ctx, "left")
            if admin is None:
                Notification("Signed out").body("Your own account can't open the panel any more.").warning().send(ctx)
                return ctx.go(panel.url("login"))
            Notification(f"Welcome back, {panel.auth.display_name(admin)}").success().send(ctx)
            return ctx.go(back)

        @app.post("/impersonate/leave")
        async def impersonate_leave(request: Request):
            return await routes.run(request, leave, read_form=True)


__all__ = [
    "LOG_PERMISSION",
    "PERMISSION",
    "ImpersonateBase",
    "ImpersonatePlugin",
    "ImpersonationError",
    "ImpersonationLog",
    "__version__",
    "can_impersonate",
    "can_impersonate_user",
    "end",
    "impersonator_id",
    "is_impersonating",
    "refusal",
    "start",
    "state",
]
