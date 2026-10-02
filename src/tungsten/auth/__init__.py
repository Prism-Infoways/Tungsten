"""Authentication (login, password reset) and authorization (roles & permissions)."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy import func, select

from ..support.aio import blocking

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
        email_verification: bool = False,
        verified_field: str = "email_verified_at",
        verification_minutes: int = 60,
        reset_token_minutes: int = 60,
        max_login_attempts: int = 5,
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
        self.two_factor = two_factor or two_factor_required
        self.two_factor_required = two_factor_required
        self.email_verification = email_verification
        self.verified_field = verified_field
        self.verification_minutes = verification_minutes
        self.reset_token_minutes = reset_token_minutes
        self.max_login_attempts = max_login_attempts
        self.panel: Panel | None = None
        self._attempts: dict[str, list[float]] = defaultdict(list)

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
        now = time.monotonic()
        attempts = [t for t in self._attempts[key] if now - t < 60]
        self._attempts[key] = attempts
        return len(attempts) >= self.max_login_attempts

    def attempt(self, ctx: "Context", email: str, password: str) -> Any:
        key = f"{ctx.request.client.host if ctx.request.client else ''}|{email.lower()}"
        if self.throttled(key):
            raise PermissionError("Too many login attempts. Please try again in a minute.")
        user = self.find_by_email(ctx.db, email) if email else None
        if user is None or not self.verify(password, getattr(user, self.password_field, None)):
            self._attempts[key].append(time.monotonic())
            return None
        if not self.is_active(user) or not self.allowed(ctx, user):
            self._attempts[key].append(time.monotonic())
            return None
        self._attempts.pop(key, None)
        return user

    def login(self, ctx: "Context", user: Any) -> None:
        ctx.session[self.session_key()] = self.user_id(user)
        ctx.user = user

    def logout(self, ctx: "Context") -> None:
        ctx.session.pop(self.session_key(), None)
        ctx.session.pop("tw_tenant", None)
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
        from ..models import Role, RoleAssignment

        if ctx.user is None:
            return []
        uid = self.user_id(ctx.user)
        return list(ctx.db.scalars(
            select(Role).join(RoleAssignment).where(RoleAssignment.user_id == uid)
        ).all())

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
                   "force_delete_any": "force_delete", "attach": "update", "detach": "update"}
        if ability in implied and f"{prefix}.{implied[ability]}" in perms:
            return True
        return False

    def sync_roles(self, db: Any, user: Any, role_ids: list) -> None:
        from ..models import RoleAssignment

        uid = self.user_id(user)
        existing = {a.role_id: a for a in db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == uid))}
        wanted = {int(r) for r in role_ids}
        for rid, assignment in existing.items():
            if rid not in wanted:
                db.delete(assignment)
        for rid in wanted - set(existing):
            db.add(RoleAssignment(role_id=rid, user_id=uid))

    def assign_role(self, db: Any, user: Any, role_name: str) -> None:
        """Give a user a role by name (creates nothing; the role must exist)."""
        from ..models import Role, RoleAssignment

        role = db.scalars(select(Role).where(Role.name == role_name)).first()
        if role is None:
            raise ValueError(f"Role {role_name!r} does not exist")
        uid = self.user_id(user)
        if not db.scalars(select(RoleAssignment).where(RoleAssignment.user_id == uid,
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
