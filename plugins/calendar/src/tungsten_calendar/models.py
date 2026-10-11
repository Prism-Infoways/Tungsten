"""Calendar tables: events and the private links people use to subscribe from their phone."""

from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> dt.datetime:
    return dt.datetime.now()


class CalendarBase(DeclarativeBase):
    pass


class CalendarEvent(CalendarBase):
    """One event. Times are wall-clock times in the plugin's time zone (no offset is stored).

    An all-day event keeps midnight of its first day in ``starts_at`` and midnight of its
    last day in ``ends_at`` (so a one-day event has both on the same day).
    """

    __tablename__ = "tungsten_calendar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    #: meeting, call, task, reminder, other (the plugin's ``kinds``)
    kind: Mapped[str] = mapped_column(String(30), default="meeting")
    #: a panel color name (primary, success, danger...)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    #: who made it (the panel user id); private events are shown only to them
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    #: none, daily, weekly, monthly or yearly
    repeat: Mapped[str] = mapped_column(String(10), default="none")
    repeat_every: Mapped[int] = mapped_column(Integer, default=1)
    repeat_until: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def __str__(self) -> str:
        return self.title or "Event"

    # the all-day date pickers on the form read these
    @property
    def start_date(self) -> dt.date | None:
        return self.starts_at.date() if self.starts_at else None

    @property
    def end_date(self) -> dt.date | None:
        value = self.ends_at or self.starts_at
        return value.date() if value else None

    @property
    def is_repeating(self) -> bool:
        return bool(self.repeat and self.repeat != "none")


class CalendarFeed(CalendarBase):
    """A secret link that lets one user subscribe to their calendar in Google Calendar, Outlook or a phone."""

    __tablename__ = "tungsten_calendar_feeds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=lambda: secrets.token_urlsafe(24))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
