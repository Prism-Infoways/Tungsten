"""Authentication (login, password reset) and authorization (roles & permissions)."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy import func, select

from ..support.aio import blocking
from .sessions import DatabaseSessions, SessionStore
from .throttle import MemoryThrottle, ThrottleStore

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..panel import Panel

log = logging.getLogger("tungsten.auth")

ITERATIONS = 390_000


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    """PBKDF2-SHA256 hash in the form ``pbkdf2_sha256$iterations$salt$hash``."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(digest).decode()}"


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed or not password:
        return False
    try:
        algorithm, iterations, salt, expected = hashed.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(base64.b64encode(digest).decode(), expected)


def _console_mailer(to: str, subject: str, body: str) -> None:
    log.warning("Tungsten mail to %s — %s\n%s", to, subject, body)
    print(f"[tungsten] mail to {to}: {subject}\n{body}")  # noqa: T201


class Auth:
    """Auth settings for a panel.

    ``user_model`` needs an id, an email-like login field and a password hash
    field. Field names are configurable.
    """

    def __init__(
        self,
        user_model: Any = None,
        *,
        email_field: str = "email",
        password_field: str = "password",
        name_field: str = "name",
        avatar_field: str | None = None,
        active_field: str | None = None,
        can_access: Callable | None = None,
        gate: Callable | None = None,
        rbac: bool = False,
        super_admin: Callable | None = None,
        mailer: Callable | None = None,
        hasher: Any = None,
        password_reset: bool = True,
        profile: bool = True,
        registration: bool = False,
        on_register: Callable | None = None,
        two_factor: bool = False,
        two_factor_required: bool = False,
        two_factor_app: bool = True,
        two_factor_email: bool = False,
        two_factor_email_minutes: int = 10,
        email_verification: bool = False,
        email_change_verification: bool | None = None,
        idle_timeout: int | None = None,
        api_tokens: bool = False,
        api_abilities: Any = None,
        api_token_days: int | None = None,
        verified_field: str = "email_verified_at",
        verification_minutes: int = 60,
        reset_token_minutes: int = 60,
        max_login_attempts: int = 5,
        throttle: ThrottleStore | None = None,
        sessions: "SessionStore | bool | None" = None,
        session_max_age: int | None = 14 * 24 * 3600,
    ) -> None:
        self.user_model = user_model
        self.email_field = email_field
        self.password_field = password_field
        self.name_field = name_field
        self.avatar_field = avatar_field
        self.active_field = active_field
        self.can_access = can_access
        self.gate = gate
        self.rbac = rbac
        self.super_admin = super_admin
        self.mailer = mailer or _console_mailer
        self.hasher = hasher
        self.password_reset = password_reset
        self.profile = profile
        self.registration = registration
        self.on_register = on_register
        self.two_factor = two_factor or two_factor_required or two_factor_email
        self.two_factor_required = two_factor_required
        #: which second steps users may turn on: a code from an authenticator app, and/or a code sent by email
        self.two_factor_app = two_factor_app
        self.two_factor_email = two_factor_email
        self.two_factor_email_minutes = two_factor_email_minutes
        self.email_verification = email_verification
        #: a new email typed on the profile page only takes effect after its owner clicks the link sent to it
        #: (follows ``email_verification`` unless set)
        self.email_change_verification = (email_verification if email_change_verification is None
                                          else email_change_verification)
        #: sign users out after this many minutes without activity (``None`` keeps them signed in)
        self.idle_timeout = idle_timeout
        #: personal API tokens (like Laravel Sanctum); ``api_abilities`` lists what a token may be allowed to do,
        #: as names or ``{name: label}``
        self.api_tokens = api_tokens
        self.api_abilities = api_abilities
        self.api_token_days = api_token_days
        self.verified_field = verified_field
        self.verification_minutes = verification_minutes
        self.reset_token_minutes = reset_token_minutes
        self.max_login_attempts = max_login_attempts
        self.panel: Panel | None = None
        #: where failed sign-ins are counted (in memory by default); pass a shared store when you run several
        #: server processes so the limit holds across them
        self.throttle: ThrottleStore = throttle if throttle is not None else MemoryThrottle()
        #: sign-ins kept on the server, so signing out ends every copy of the session cookie (``False``: off)
        self.sessions: SessionStore | None = (None if sessions is False
                                              else DatabaseSessions() if sessions in (None, True) else sessions)
        #: how long a sign-in lasts at most, in seconds (the cookie's lifetime too); ``None``: until the browser closes
        self.session_max_age = session_max_age

    @property
    def enabled(self) -> bool:
        return self.user_model is not None

    # ------------------------------------------------------------------ hashing
    def hash(self, password: str) -> str:
        # hashing is slow on purpose; keep it off the event loop in async mode
        return blocking(self.hasher.hash if self.hasher else hash_password, password)

    def verify(self, password: str, hashed: str | None) -> bool:
        return blocking(self.hasher.verify if self.hasher else verify_password, password, hashed)

    # ------------------------------------------------------------------ users
    def session_key(self) -> str:
        return f"tw_auth_{self.panel.id if self.panel else 'default'}"

    def user_id(self, user: Any) -> str:
        from sqlalchemy import inspect as sa_inspect

        pk = sa_inspect(type(user)).primary_key[0]
        return str(getattr(user, pk.key))

    def find_by_email(self, db: Any, email: str) -> Any:
        column = getattr(self.user_model, self.email_field)
        return db.scalars(select(self.user_model).where(func.lower(column) == email.strip().lower())).first()

    def find_by_id(self, db: Any, user_id: Any) -> Any:
        from sqlalchemy import inspect as sa_inspect

        pk = sa_inspect(self.user_model).primary_key[0]
        try:
            key = pk.type.python_type(user_id)
        except (TypeError, ValueError, NotImplementedError):
            key = user_id
        try:
            return db.get(self.user_model, key)
        except Exception:  # noqa: BLE001 - a malformed id is just "not found"
            return None

    def load_user(self, ctx: "Context") -> Any:
        if not self.enabled:
            return None
        user_id = ctx.session.get(self.session_key())
        if user_id is None:
            return None
        token_auth = getattr(ctx.request.state, "tw_token_auth", False)  # an API/MCP token, no browser session
        if not token_auth and not self.session_alive(ctx.db, ctx.session, user_id):
            self.logout(ctx)  # signed out elsewhere (or too old): this copy of the cookie is dead
            return None
        if self.idle_timeout:
            now = time.time()
            seen = ctx.session.get("tw_seen")
            if seen is None:  # a session from before idle_timeout was on: start counting now
                seen = ctx.session["tw_seen"] = now
            if now - seen > self.idle_timeout * 60:
                user = self.find_by_id(ctx.db, user_id)
                self.logout(ctx)
                if self.panel is not None and user is not None:
                    self.panel.log_auth_event(ctx, "logout", user, reason="idle")
                ctx.session["tw_idle_out"] = True
                return None
            if not getattr(ctx.request.state, "tw_background", False) and now - seen >= 30:
                ctx.session["tw_seen"] = now  # written at most every 30s so the cookie isn't re-sent on every click
        user = self.find_by_id(ctx.db, user_id)
        if user is None or not self.is_active(user):
            return None
        return user

    def is_active(self, user: Any) -> bool:
        return not self.active_field or bool(getattr(user, self.active_field, True))

    def allowed(self, ctx: "Context", user: Any) -> bool:
        if self.can_access is None:
            return True
        from ..support.evaluate import call

        return bool(call(self.can_access, user=user, ctx=ctx, panel=self.panel))

    def throttled(self, key: str) -> bool:
        return self.throttle.failures(key, 60) >= self.max_login_attempts

    def failed_attempt(self, key: str) -> None:
        self.throttle.fail(key)

    def reset_attempts(self, email: str) -> None:
        """Forget the failed sign-ins of ``email`` from every address (after an admin unlocks it)."""
        clear_where = getattr(self.throttle, "clear_where", None)
        if clear_where is not None:
            suffix = "|" + email.lower()
            clear_where(lambda key: str(key).lower().endswith(suffix))

    @property
    def _attempts(self) -> Any:
        """The in-memory counts, for code written against the old dict (prefer :meth:`reset_attempts`)."""
        return self.throttle

    def attempt(self, ctx: "Context", email: str, password: str) -> Any:
        key = f"{ctx.request.client.host if ctx.request.client else ''}|{email.lower()}"
        if self.throttled(key):
            raise PermissionError("Too many login attempts. Please try again in a minute.")
        user = self.find_by_email(ctx.db, email) if email else None
        if user is None or not self.verify(password, getattr(user, self.password_field, None)):
            self.failed_attempt(key)
            return None
        if not self.is_active(user) or not self.allowed(ctx, user):
            self.failed_attempt(key)
            return None
        self.throttle.clear(key)
        return user

    SESSION_ID_KEY = "tw_sid"

    def session_alive(self, db: Any, session: Any, user_id: Any) -> bool:
        """False when the server-side sign-in behind this cookie is gone (signed out) or too old."""
        if self.sessions is None:
            return True
        alive = self.sessions.alive(db, str(session.get(self.SESSION_ID_KEY) or ""), str(user_id),
                                    self.session_max_age)
        return alive is not False

    def login(self, ctx: "Context", user: Any) -> None:
        if self.sessions is not None:
            old = ctx.session.pop(self.SESSION_ID_KEY, None)
            if old:
                self.sessions.end(ctx.db, str(old))  # a new sign-in in this browser replaces the old one
            session_id = self.sessions.start(ctx.db, self.user_id(user))
            if session_id:
                ctx.session[self.SESSION_ID_KEY] = session_id
        ctx.session[self.session_key()] = self.user_id(user)
        ctx.session["tw_seen"] = time.time()
        ctx.session.pop("tw_idle_out", None)
        ctx.user = user

    def logout(self, ctx: "Context") -> None:
        session_id = ctx.session.pop(self.SESSION_ID_KEY, None)
        if session_id and self.sessions is not None:
            self.sessions.end(ctx.db, str(session_id))
        ctx.session.pop(self.session_key(), None)
        ctx.session.pop("tw_tenant", None)
        ctx.session.pop("tw_seen", None)
        tenancy = self.panel.tenancy if self.panel else None
        if tenancy is not None and tenancy.enabled:
            ctx.session.pop(tenancy.session_key, None)  # a custom ``Tenancy(session_key=...)``
        ctx.user = None

    def display_name(self, user: Any) -> str:
        if user is None:
            return ""
        return str(getattr(user, self.name_field, None) or getattr(user, self.email_field, ""))

    def avatar_url(self, user: Any) -> str | None:
        if user is None or not self.avatar_field:
            return None
        value = getattr(user, self.avatar_field, None)
        if not value:
            return None
        if str(value).startswith(("http://", "https://", "/")):
            return value
        return self.panel.storage.url(value) if self.panel else value

    # ------------------------------------------------------------------ permissions
    def is_super_admin(self, ctx: "Context") -> bool:
        if ctx.user is None:
            return False
        if self.super_admin is not None:
            from ..support.evaluate import call

            return bool(call(self.super_admin, user=ctx.user, ctx=ctx))
        return "*" in self.permissions(ctx)

    def roles(self, ctx: "Context") -> list:
        """The user's roles: those for the whole panel plus those given inside the current tenant."""
        from ..models import Role, RoleAssignment, TenantRoleAssignment

        if ctx.user is None:
            return []
        uid = self.user_id(ctx.user)
        tenant_key = self._tenant_key(ctx.tenant)
        cached = getattr(ctx, "_roles", None)  # asked for by permission checks and the user menu alike
        if cached is not None and cached[0] == (uid, tenant_key):
            return list(cached[1])
        roles = list(ctx.db.scalars(
            select(Role).join(RoleAssignment).where(RoleAssignment.user_id == uid)
        ).all())
        if tenant_key is not None:
            seen = {r.id for r in roles}
            roles += [r for r in ctx.db.scalars(
                select(Role).join(TenantRoleAssignment, TenantRoleAssignment.role_id == Role.id)
                .where(TenantRoleAssignment.user_id == uid, TenantRoleAssignment.tenant_id == tenant_key)
            ).all() if r.id not in seen]
        ctx._roles = ((uid, tenant_key), roles)
        return list(roles)

    def _tenant_key(self, tenant: Any) -> str | None:
        if tenant is None:
            return None
        tenancy = self.panel.tenancy if self.panel is not None else None
        return tenancy.key_of(tenant) if tenancy is not None and tenancy.enabled else None

    def permissions(self, ctx: "Context") -> set[str]:
        if ctx._permissions is None:
            perms: set[str] = set()
            if self.rbac and ctx.user is not None:
                for role in self.roles(ctx):
                    perms.update(role.permissions or [])
            ctx._permissions = perms
        return ctx._permissions

    def check(self, ctx: "Context", permission: str, record: Any = None) -> bool:
        if self.gate is not None:
            from ..support.evaluate import call

            result = call(self.gate, user=ctx.user, permission=permission, ability=permission.rsplit(".", 1)[-1],
                          record=record, ctx=ctx)
            if result is not None:
                return bool(result)
        if not self.rbac:
            return True
        if ctx.user is None:
            return False
        if self.super_admin is not None and self.is_super_admin(ctx):
            return True
        perms = self.permissions(ctx)
        if "*" in perms or permission in perms:
            return True
        prefix, _, ability = permission.rpartition(".")
        if f"{prefix}.*" in perms:
            return True
        # "view" is implied by "view_any", bulk abilities by their single ability
        implied = {"view": "view_any", "delete_any": "delete", "restore_any": "restore",
                   "force_delete_any": "force_delete", "attach": "update", "detach": "update",
                   "associate": "update", "dissociate": "update"}
        if ability in implied and f"{prefix}.{implied[ability]}" in perms:
            return True
        return False

    def sync_roles(self, db: Any, user: Any, role_ids: list, tenant: Any = None) -> None:
        """Set a user's roles: for the whole panel, or (with ``tenant``) inside that tenant only."""
        from ..models import RoleAssignment, TenantRoleAssignment

        uid = self.user_id(user)
        if tenant is not None:
            tid = self._tenant_key(tenant) or str(tenant)
            query = select(TenantRoleAssignment).where(TenantRoleAssignment.user_id == uid,
                                                       TenantRoleAssignment.tenant_id == tid)
            existing = {a.role_id: a for a in db.scalars(query)}
        else:
            existing = {a.role_id: a for a in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == uid))}
        wanted = {int(r) for r in role_ids}
        for rid, assignment in existing.items():
            if rid not in wanted:
                db.delete(assignment)
        for rid in wanted - set(existing):
            db.add(TenantRoleAssignment(role_id=rid, user_id=uid, tenant_id=tid) if tenant is not None
                   else RoleAssignment(role_id=rid, user_id=uid))

    def assign_role(self, db: Any, user: Any, role_name: str, tenant: Any = None) -> None:
        """Give a user a role by name (creates nothing; the role must exist), optionally inside one tenant."""
        from ..models import Role, RoleAssignment, TenantRoleAssignment

        role = db.scalars(select(Role).where(Role.name == role_name)).first()
        if role is None:
            raise ValueError(f"Role {role_name!r} does not exist")
        uid = self.user_id(user)
        if tenant is not None:
            tid = self._tenant_key(tenant) or str(tenant)
            if not db.scalars(select(TenantRoleAssignment).where(
                    TenantRoleAssignment.user_id == uid, TenantRoleAssignment.role_id == role.id,
                    TenantRoleAssignment.tenant_id == tid)).first():
                db.add(TenantRoleAssignment(role_id=role.id, user_id=uid, tenant_id=tid))
        elif not db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == uid,
                                                         RoleAssignment.role_id == role.id)).first():
            db.add(RoleAssignment(role_id=role.id, user_id=uid))
        db.commit()

    # ------------------------------------------------------------------ password reset
    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_reset_token(self, db: Any, email: str) -> str:
        from ..models import PasswordReset

        for old in db.scalars(select(PasswordReset).where(PasswordReset.email == email.lower())):
            db.delete(old)
        token = secrets.token_urlsafe(32)
        db.add(PasswordReset(email=email.lower(), token_hash=self._token_hash(token)))
        db.commit()
        return token

    def email_for_token(self, db: Any, token: str) -> str | None:
        from ..models import PasswordReset

        row = db.scalars(select(PasswordReset).where(PasswordReset.token_hash == self._token_hash(token))).first()
        if row is None:
            return None
        if row.created_at < dt.datetime.now() - dt.timedelta(minutes=self.reset_token_minutes):
            db.delete(row)
            db.commit()
            return None
        return row.email

    def consume_token(self, db: Any, token: str) -> None:
        from ..models import PasswordReset

        for row in db.scalars(select(PasswordReset).where(PasswordReset.token_hash == self._token_hash(token))):
            db.delete(row)
        db.commit()


__all__ = ["Auth", "hash_password", "verify_password"]
