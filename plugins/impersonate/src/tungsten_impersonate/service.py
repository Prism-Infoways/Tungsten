"""Start and stop "log in as": the safety rules, the session switch and the log.

While someone is impersonated, the session keeps the real admin under its own key::

    {"by": "<admin id>", "as": "<user id>", "at": <unix time>, "back": "<page to return to>",
     "log": <log id>, "tenant": <admin's tenant>}

The panel's normal login key holds the user being viewed, so every screen, permission and
record filter works exactly as it does for that user.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any
from urllib.parse import urlsplit

from tungsten import Notification
from tungsten.context import Context
from tungsten.support.evaluate import call

from .models import ImpersonationLog

log = logging.getLogger("tungsten.impersonate")

PERMISSION = "impersonate.start"


class ImpersonationError(Exception):
    """Raised with a message the admin can read when "log in as" is not allowed."""


# ---------------------------------------------------------------------- session state
def state_key(panel: Any) -> str:
    return f"tw_impersonate_{panel.id}"


def state(ctx: Any) -> dict | None:
    """The running impersonation in this browser, or ``None``."""
    if "session" not in ctx.request.scope:
        return None
    value = ctx.session.get(state_key(ctx.panel))
    return value if isinstance(value, dict) and value.get("by") and value.get("as") else None


def is_impersonating(ctx: Any) -> bool:
    return state(ctx) is not None


def impersonator_id(ctx: Any) -> str | None:
    """The id of the real admin behind this request, when someone is impersonated."""
    current = state(ctx)
    return str(current["by"]) if current else None


def _tenant_keys(panel: Any) -> list[str]:
    keys = ["tw_tenant"]
    tenancy = getattr(panel, "tenancy", None)
    if tenancy is not None and getattr(tenancy, "enabled", False) and tenancy.session_key not in keys:
        keys.append(tenancy.session_key)
    return keys


def _context_for(ctx: Any, user: Any) -> Context:
    """A copy of the request context as ``user`` sees it (for their permissions and access)."""
    other = Context(ctx.panel, ctx.request, ctx.db)
    other.user = user
    other.tenant = getattr(ctx, "tenant", None)
    return other


def _client_ip(ctx: Any, trust_proxy: bool) -> str | None:
    request = ctx.request
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else None


def _referer_path(ctx: Any) -> str | None:
    """The page the admin pressed the button on, when it is on this same site."""
    referer = ctx.request.headers.get("referer")
    if not referer:
        return None
    parts = urlsplit(referer)
    if parts.netloc and parts.netloc != ctx.request.url.netloc:
        return None
    return parts.path + (f"?{parts.query}" if parts.query else "")


def safe_back_url(panel: Any, url: Any) -> str:
    """Only a page inside this panel; anything else (another site, ``//evil``) goes home."""
    url = str(url or "")
    base = panel.url()
    if url.startswith("/") and not url.startswith("//") and "\\" not in url \
            and (url.startswith(base) or url == base.rstrip("/")):
        return url
    return base


# ---------------------------------------------------------------------- rules
def can_impersonate(plugin: Any, ctx: Any) -> bool:
    """May the signed-in user log in as others? Never while already impersonating someone."""
    auth = ctx.panel.auth
    if ctx.user is None or not auth.enabled or is_impersonating(ctx):
        return False
    if plugin.can_impersonate is not None:
        return bool(call(plugin.can_impersonate, user=ctx.user, ctx=ctx, panel=ctx.panel))
    if not auth.rbac and auth.gate is None:
        return True  # without roles every panel user can already do everything
    return auth.is_super_admin(ctx) or ctx.can(PERMISSION)


def refusal(plugin: Any, ctx: Any, target: Any) -> str | None:
    """Why the signed-in user may not log in as ``target``, or ``None`` when they may."""
    panel = ctx.panel
    auth = panel.auth
    if is_impersonating(ctx):
        return "Go back to your own account first."
    if not can_impersonate(plugin, ctx):
        return "You are not allowed to log in as other users."
    if target is None:
        return "This user was not found."
    if auth.user_id(target) == auth.user_id(ctx.user):
        return "This is your own account."
    if not auth.is_active(target):
        return "This user is not active."
    other = _context_for(ctx, target)
    if not auth.allowed(other, target):
        return "This user cannot open the panel."
    if auth.rbac or auth.super_admin is not None:
        if auth.is_super_admin(other):
            return "You can't log in as a super admin."
        # never a way to more access: every permission of theirs must be one you have too
        if plugin.no_more_access and not auth.is_super_admin(ctx) \
                and any(not ctx.can(p) for p in auth.permissions(other)):
            return "This user has access you don't have."
    if auth.two_factor_required:
        from tungsten.auth.two_factor import TwoFactor

        if not TwoFactor(other, target).enabled:
            return "This user has not set up two-step login yet."
    if auth.email_verification:
        from tungsten.auth.verification import needs_verification

        if needs_verification(panel, target):
            return "This user has not verified their email yet."
    if plugin.can_be_impersonated is not None and not call(plugin.can_be_impersonated, user=ctx.user,
                                                           target=target, record=target, ctx=ctx, panel=panel):
        return "You can't log in as this user."
    return None


def can_impersonate_user(plugin: Any, ctx: Any, target: Any) -> bool:
    return refusal(plugin, ctx, target) is None


# ---------------------------------------------------------------------- start and stop
def start(plugin: Any, ctx: Any, target: Any, reason: str | None = None, back: str | None = None) -> str:
    """Log in as ``target``. Returns the page to open next. Raises :class:`ImpersonationError`."""
    problem = refusal(plugin, ctx, target)
    if problem:
        raise ImpersonationError(problem)
    reason = (reason or "").strip()[:2000] or None
    if plugin.require_reason and not reason:
        raise ImpersonationError("Write why you are logging in as this user.")
    panel, auth, db = ctx.panel, ctx.panel.auth, ctx.db
    admin = ctx.user
    entry = ImpersonationLog(
        impersonator_id=auth.user_id(admin), impersonator_name=auth.display_name(admin)[:200],
        target_id=auth.user_id(target), target_name=auth.display_name(target)[:200], reason=reason,
        ip=_client_ip(ctx, plugin.trust_proxy),
        user_agent=(ctx.request.headers.get("user-agent") or "")[:300] or None)
    db.add(entry)
    db.commit()
    tenants = {key: ctx.session.pop(key) for key in _tenant_keys(panel) if key in ctx.session}
    ctx.session[state_key(panel)] = {
        "by": auth.user_id(admin), "as": auth.user_id(target), "at": time.time(), "log": entry.id,
        "back": safe_back_url(panel, back or _referer_path(ctx)),
        "tenant": tenants,
    }
    auth.login(ctx, target)
    ctx._permissions = None
    log.info("%s logged in as %s", entry.impersonator_name, entry.target_name)
    if plugin.on_start:
        try:
            call(plugin.on_start, db=db, log=entry, user=admin, target=target, ctx=ctx)
        except Exception:  # a broken hook must not leave the admin half switched
            log.exception("on_start hook failed")
    Notification("You are now logged in as " + (entry.target_name or "this user")).body(
        "Everything you see is what they see. Use the bar at the top to go back.").info().send(ctx)
    url = call(plugin.redirect_to, user=target, target=target, ctx=ctx, panel=panel) \
        if callable(plugin.redirect_to) else plugin.redirect_to
    return safe_back_url(panel, url or panel.url())


def _close_log(db: Any, log_id: Any, reason: str) -> ImpersonationLog | None:
    if not log_id:
        return None
    try:
        entry = db.get(ImpersonationLog, int(log_id))
    except (TypeError, ValueError):
        return None
    if entry is not None and entry.ended_at is None:
        entry.ended_at = dt.datetime.now()
        entry.end_reason = reason
        db.commit()
    return entry


def end(plugin: Any, ctx: Any, reason: str = "left", restore: bool = True) -> Any:
    """Stop impersonating. With ``restore`` the admin is signed back in; returns them (or ``None``)."""
    panel, auth = ctx.panel, ctx.panel.auth
    current = ctx.session.pop(state_key(panel), None)
    if not isinstance(current, dict):
        return None
    try:
        _close_log(ctx.db, current.get("log"), reason)
    except Exception:  # a broken log must never trap anyone in someone else's account
        ctx.db.rollback()
        log.exception("Could not close impersonation log %s", current.get("log"))
    if plugin.on_end:
        try:
            call(plugin.on_end, db=ctx.db, state=current, reason=reason, ctx=ctx)
        except Exception:
            log.exception("on_end hook failed")
    if not restore:
        return None
    for key in _tenant_keys(panel):
        ctx.session.pop(key, None)
    admin = auth.find_by_id(ctx.db, current.get("by")) if auth.enabled else None
    if admin is None or not auth.is_active(admin) or not auth.allowed(_context_for(ctx, admin), admin):
        auth.logout(ctx)  # the admin's own account is gone or blocked: sign out completely
        return None
    for key, value in (current.get("tenant") or {}).items():
        ctx.session[key] = value
    auth.login(ctx, admin)
    ctx._permissions = None
    return admin


def back_url(ctx: Any, current: dict | None) -> str:
    return safe_back_url(ctx.panel, (current or {}).get("back"))


def expired(plugin: Any, current: dict) -> bool:
    if not plugin.max_minutes:
        return False
    try:
        started = float(current.get("at") or 0)
    except (TypeError, ValueError):
        return True
    return time.time() - started > plugin.max_minutes * 60


def minutes_left(plugin: Any, current: dict) -> int | None:
    if not plugin.max_minutes:
        return None
    try:
        started = float(current.get("at") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, int((plugin.max_minutes * 60 - (time.time() - started)) // 60) + 1)
