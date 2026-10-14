"""Tungsten's own tables (roles, notifications, password resets).

They live in their own metadata so they never clash with your models. Users
are referenced by id as a string, so any user model works.
Create them with ``panel.create_tables(engine)``.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> dt.datetime:
    return dt.datetime.now()


class TungstenBase(DeclarativeBase):
    pass


class Role(TungstenBase):
    __tablename__ = "tungsten_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True, default="primary")
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    assignments: Mapped[list["RoleAssignment"]] = relationship(back_populates="role", cascade="all, delete-orphan")

    def __str__(self) -> str:
        return self.name


class RoleAssignment(TungstenBase):
    __tablename__ = "tungsten_role_user"
    __table_args__ = (UniqueConstraint("role_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("tungsten_roles.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(String(64), index=True)

    role: Mapped[Role] = relationship(back_populates="assignments")


class TenantRoleAssignment(TungstenBase):
    """A role a user has inside one tenant only (``RolesField(...).per_tenant()``)."""

    __tablename__ = "tungsten_tenant_role_user"
    __table_args__ = (UniqueConstraint("role_id", "user_id", "tenant_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("tungsten_roles.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)

    role: Mapped[Role] = relationship()


class DatabaseNotification(TungstenBase):
    __tablename__ = "tungsten_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class PasswordReset(TungstenBase):
    __tablename__ = "tungsten_password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class TwoFactorCredential(TungstenBase):
    """A user's TOTP secret and hashed recovery codes."""

    __tablename__ = "tungsten_two_factor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    secret: Mapped[str] = mapped_column(String(64))
    recovery_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class ActivityLog(TungstenBase):
    """Simple audit trail written by resources (create/update/delete)."""

    __tablename__ = "tungsten_activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    subject_type: Mapped[str] = mapped_column(String(100), index=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class TwoFactorEmail(TungstenBase):
    """A user who gets their sign-in codes by email instead of (or as well as) an authenticator app."""

    __tablename__ = "tungsten_two_factor_email"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class EmailChange(TungstenBase):
    """A new email address waiting for its owner to click the link we sent there."""

    __tablename__ = "tungsten_email_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    old_email: Mapped[str] = mapped_column(String(255))
    new_email: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    block_token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class ApiToken(TungstenBase):
    """A personal API token (like Laravel Sanctum). Only a SHA-256 hash of the token is stored."""

    __tablename__ = "tungsten_api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    abilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    def can(self, ability: str) -> bool:
        abilities = self.abilities or []
        return "*" in abilities or ability in abilities


class Job(TungstenBase):
    """Work run in the background: a bulk action or an export (see :mod:`tungsten.jobs`).

    Exports stay here as the user's export history, with their file while it is kept.
    """

    __tablename__ = "tungsten_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tenant_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: queued, running, done, failed or expired (an export whose file was removed)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    #: tries so far, and how many are allowed (see ``JobRunner.register(max_attempts=...)``)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    #: a retry waits until then (backoff)
    available_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    #: the process running it, and when it last said it is still working
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
