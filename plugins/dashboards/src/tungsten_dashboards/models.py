"""Tables of the dashboards plugin. Users are stored by id as a string, so any user model works."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


class DashboardsBase(DeclarativeBase):
    pass


class CustomDashboard(DashboardsBase):
    """A dashboard a person built. Shared ones are seen by everyone in the panel (or in the same team)."""

    __tablename__ = "tungsten_dashboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    icon: Mapped[str] = mapped_column(String(60), default="layout-dashboard")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: panel user who made it ("" when the panel has no login)
    owner_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    #: the team / company it belongs to when the panel uses multi-tenancy
    tenant_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    #: the home page for everyone who did not pick their own (shared dashboards only)
    home_for_all: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    items: Mapped[list[DashboardItem]] = relationship(
        back_populates="dashboard", cascade="all, delete-orphan", order_by="DashboardItem.position")

    def __str__(self) -> str:
        return self.name


class DashboardItem(DashboardsBase):
    """One widget placed on a dashboard."""

    __tablename__ = "tungsten_dashboard_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dashboard_id: Mapped[int] = mapped_column(ForeignKey("tungsten_dashboards.id", ondelete="CASCADE"), index=True)
    #: a panel widget id (``hr-stats``) or a built-in one (``dashboards.note``)
    widget: Mapped[str] = mapped_column(String(150))
    #: heading shown instead of the widget's own (built-in widgets)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: width in quarters of the row: 1 to 4
    span: Mapped[int] = mapped_column(Integer, default=2)
    position: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    dashboard: Mapped[CustomDashboard] = relationship(back_populates="items")


class DashboardHome(DashboardsBase):
    """The dashboard a person picked as their home page."""

    __tablename__ = "tungsten_dashboard_homes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dashboard_id: Mapped[int] = mapped_column(ForeignKey("tungsten_dashboards.id", ondelete="CASCADE"))
