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
