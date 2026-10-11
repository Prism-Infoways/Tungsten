"""The impersonation log. Users are stored by id as a string (with their name at the time), so any
user model works and the log still reads well after a user is deleted."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> dt.datetime:
    return dt.datetime.now()


class ImpersonateBase(DeclarativeBase):
    pass


class ImpersonationLog(ImpersonateBase):
    """One "log in as" session: who, as whom, why, from where, and when it ended."""

    __tablename__ = "tungsten_impersonation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    impersonator_id: Mapped[str] = mapped_column(String(64), index=True)
    impersonator_name: Mapped[str] = mapped_column(String(200), default="")
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    target_name: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    #: ``left`` (pressed the button), ``expired``, ``logged_out`` or ``ended`` (signed in again, user gone...)
    end_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    @property
    def minutes(self) -> int | None:
        if self.ended_at is None or self.started_at is None:
            return None
        return max(0, int((self.ended_at - self.started_at).total_seconds() // 60))
