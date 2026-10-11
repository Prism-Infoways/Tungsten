"""Tables of the saved views plugin. Users and tenants are stored by id as a string, so any model works."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> dt.datetime:
    return dt.datetime.now()


class SavedViewsBase(DeclarativeBase):
    pass


class SavedView(SavedViewsBase):
    """A named table state (filters, search, sort, tab, columns) of one resource list."""

    __tablename__ = "tungsten_saved_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: who made it ("" when the panel has no login)
    user_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    #: the current team or company, when the panel has tenancy ("" otherwise)
    tenant_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    #: the resource slug, like "leads" or "tickets"
    resource: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(80))
    #: the table's query string: tab, search, sort, filters.* ...
    query: Mapped[str] = mapped_column(Text, default="")
    #: the columns that were hidden when the view was saved (None: leave columns as they are)
    hidden_columns: Mapped[list | None] = mapped_column(JSON, nullable=True)
    icon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    color: Mapped[str] = mapped_column(String(20), default="gray")
    #: everybody who can open the list sees it
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def __str__(self) -> str:
        return self.name


class SavedViewDefault(SavedViewsBase):
    """The view a user's list opens with. ``view_key`` is a view id, or ``preset:<key>`` for a code preset."""

    __tablename__ = "tungsten_saved_view_defaults"
    __table_args__ = (UniqueConstraint("user_id", "tenant_key", "resource", name="uq_saved_view_default"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    tenant_key: Mapped[str] = mapped_column(String(64), default="")
    resource: Mapped[str] = mapped_column(String(100))
    view_key: Mapped[str] = mapped_column(String(80))
