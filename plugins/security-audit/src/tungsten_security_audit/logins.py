"""The login log and the lockout after too many wrong passwords."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import delete, func, or_, select

from .models import LoginAttempt

#: reasons that count towards a lockout
FAILURES = ("wrong_password", "unknown_user", "not_allowed")
#: reasons that start the count again
RESETS = ("success", "unlocked")


def client_ip(request: Any, trust_proxy: bool = False) -> str | None:
    """The visitor's IP. ``X-Forwarded-For`` only when the site runs behind a proxy you trust."""
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()[:64]
    return request.client.host if request.client else None


class LoginGuard:
    """Wraps ``panel.auth.attempt`` so every login try is logged, and locks out repeated failures."""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    def install(self, auth: Any) -> None:
        if getattr(auth, "_tungsten_security_guard", None) is not None:
            return
        original = auth.attempt
        guard = self

        def attempt(ctx: Any, email: str, password: str) -> Any:
            return guard.attempt(original, ctx, email, password)

        auth.attempt = attempt
        auth._tungsten_security_guard = self

    # ------------------------------------------------------------------ the login
    def attempt(self, original: Any, ctx: Any, email: str, password: str) -> Any:
        plugin = self.plugin
        email = (email or "").strip().lower()[:200]
        ip = client_ip(ctx.request, plugin.trust_proxy)
        db = ctx.db
        if plugin.lockout and email:
            until = self.locked_until(db, email, ip)
            if until is not None:
                self.record(ctx, email, ip, "locked")
                minutes = max(1, int((until - dt.datetime.now()).total_seconds() // 60) + 1)
                raise PermissionError(f"Too many failed logins. Please try again in {minutes} minutes.")
        try:
            user = original(ctx, email, password)
        except PermissionError:
            self.record(ctx, email, ip, "throttled")
            raise
        auth = ctx.panel.auth
        if user is not None:
            self.record(ctx, email, ip, "success", user_id=auth.user_id(user))
            return user
        known = auth.find_by_email(db, email) if email else None
        if known is None:
            reason = "unknown_user"
        elif auth.verify(password, getattr(known, auth.password_field, None)):
            reason = "not_allowed"  # right password, but the account is switched off or may not open the panel
        else:
            reason = "wrong_password"
        self.record(ctx, email, ip, reason, user_id=auth.user_id(known) if known is not None else None)
        return None

    def record(self, ctx: Any, email: str, ip: str | None, reason: str, user_id: str | None = None) -> None:
        db = ctx.db
        agent = (ctx.request.headers.get("user-agent") or "")[:300] or None
        row = LoginAttempt(email=email or "(empty)", ip=ip, user_agent=agent, user_id=user_id,
                           success=reason == "success", reason=reason)
        db.add(row)
        db.commit()
        if row.id and row.id % 200 == 0:
            self.prune(db)

    def prune(self, db: Any) -> None:
        days = self.plugin.keep_login_days
        if not days:
            return
        db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < dt.datetime.now() - dt.timedelta(days=days)))
        db.commit()

    # ------------------------------------------------------------------ lockout
    def locked_until(self, db: Any, email: str, ip: str | None, now: dt.datetime | None = None) -> dt.datetime | None:
        """When the lock on this email (from this IP) ends, or None when it isn't locked."""
        plugin = self.plugin
        now = now or dt.datetime.now()
        window = dt.timedelta(minutes=plugin.lockout_minutes)
        same_ip = LoginAttempt.ip.is_(None) if ip is None else LoginAttempt.ip == ip
        last_reset = db.scalar(
            select(func.max(LoginAttempt.created_at)).where(
                LoginAttempt.email == email,
                LoginAttempt.reason.in_(RESETS),
                # an unlock from the log screen clears every IP; a good login clears its own
                or_(same_ip, LoginAttempt.reason == "unlocked"),
            )
        )
        start = now - window
        if last_reset is not None and last_reset > start:
            start = last_reset
        rows = db.scalars(
            select(LoginAttempt.created_at).where(
                LoginAttempt.email == email, same_ip, LoginAttempt.reason.in_(FAILURES),
                LoginAttempt.created_at > start,
            ).order_by(LoginAttempt.created_at.desc()).limit(plugin.max_failures)
        ).all()
        if len(rows) < plugin.max_failures:
            return None
        until = rows[0] + window
        return until if until > now else None

    def is_locked(self, db: Any, email: str, ip: str | None) -> bool:
        return self.locked_until(db, email, ip) is not None

    def unlock(self, db: Any, email: str, user_id: str | None = None) -> None:
        # also forget the panel's own per-minute count for this email
        attempts = getattr(getattr(self.plugin.panel, "auth", None), "_attempts", None)
        if isinstance(attempts, dict):
            for key in [k for k in attempts if str(k).endswith("|" + email)]:
                attempts.pop(key, None)
        db.add(LoginAttempt(email=email, ip=None, user_agent=None, success=False, reason="unlocked", user_id=user_id))
        db.commit()

    def locked_accounts(self, db: Any) -> list[tuple[str, str | None]]:
        """``(email, ip)`` pairs locked right now."""
        since = dt.datetime.now() - dt.timedelta(minutes=self.plugin.lockout_minutes)
        pairs = db.execute(
            select(LoginAttempt.email, LoginAttempt.ip).where(
                LoginAttempt.reason.in_(FAILURES), LoginAttempt.created_at > since,
            ).group_by(LoginAttempt.email, LoginAttempt.ip)
            .having(func.count() >= self.plugin.max_failures)
        ).all()
        return [(email, ip) for email, ip in pairs if self.is_locked(db, email, ip)]
