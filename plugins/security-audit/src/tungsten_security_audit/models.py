"""Tables of the security audit plugin."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> dt.datetime:
    return dt.datetime.now()


class SecurityBase(DeclarativeBase):
    pass


class SecurityAudit(SecurityBase):
    """One run of the audit: the score and every check's result."""

    __tablename__ = "tungsten_security_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    grade: Mapped[str] = mapped_column(String(2))
    passed: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    #: the address whose headers were checked, if any
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: ``[{"key", "group", "title", "status", "severity", "detail", "fix"}, ...]``
    results: Mapped[list] = mapped_column(JSON, default=list)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)


class LoginAttempt(SecurityBase):
    """One login try on the panel's login page, good or bad."""

    __tablename__ = "tungsten_login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    #: ``success``, ``wrong_password``, ``unknown_user``, ``not_allowed``, ``locked``, ``throttled`` or ``unlocked``
    reason: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
