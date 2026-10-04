"""Tables of the Meta lead forms plugin."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> dt.datetime:
    return dt.datetime.now()


class MetaBase(DeclarativeBase):
    pass


class MetaSettings(MetaBase):
    """One row: the Meta app keys and the connected Facebook account."""

    __tablename__ = "tungsten_meta_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    app_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verify_token: Mapped[str] = mapped_column(String(64))
    user_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    connected_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    webhook_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_webhook_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class MetaPage(MetaBase):
    """A Facebook page whose lead forms we read."""

    __tablename__ = "tungsten_meta_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    access_token: Mapped[str] = mapped_column(Text, default="")
    subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    def __str__(self) -> str:
        return self.name


class MetaForm(MetaBase):
    """A lead form on a page, and how its answers map to lead fields."""

    __tablename__ = "tungsten_meta_forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    form_id: Mapped[str] = mapped_column(String(64), unique=True)
    page_id: Mapped[str] = mapped_column(String(64), index=True)
    page_name: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: status and owner given to new leads from this form
    default_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assign_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Meta question key -> lead field ("name", "email", "phone", "company", "notes", a lead field key, or "" to skip)
    field_map: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    questions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    leads_imported: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_lead_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    def __str__(self) -> str:
        return self.name


class MetaLeadLog(MetaBase):
    """Every lead Meta sent us, and what happened to it."""

    __tablename__ = "tungsten_meta_lead_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    leadgen_id: Mapped[str] = mapped_column(String(64), index=True)
    form_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: imported, duplicate, skipped or failed
    status: Mapped[str] = mapped_column(String(20), default="imported")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    via: Mapped[str] = mapped_column(String(20), default="webhook")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
