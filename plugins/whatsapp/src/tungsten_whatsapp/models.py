"""Tables of the WhatsApp plugin."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> dt.datetime:
    return dt.datetime.now()


class WhatsAppBase(DeclarativeBase):
    pass


class WhatsAppSettings(WhatsAppBase):
    """One row: which way we send (Cloud API or WhatsApp Web) and its keys."""

    __tablename__ = "tungsten_whatsapp_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: "cloud" (official API), "web" (linked phone through a WAHA gateway) or None (only click-to-chat links)
    channel: Mapped[str | None] = mapped_column(String(10), nullable=True)
    country_code: Mapped[str] = mapped_column(String(4), default="91")

    # Cloud API
    phone_number_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verify_token: Mapped[str] = mapped_column(String(64))

    # WhatsApp Web (WAHA gateway)
    gateway_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gateway_api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gateway_session: Mapped[str] = mapped_column(String(60), default="default")
    web_webhook_token: Mapped[str] = mapped_column(String(64))
    web_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    web_phone: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # automation
    create_leads: Mapped[bool] = mapped_column(Boolean, default=True)
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    welcome_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_template: Mapped[str | None] = mapped_column(String(120), nullable=True)
    welcome_language: Mapped[str] = mapped_column(String(10), default="en")


class WhatsAppMessage(WhatsAppBase):
    """One message, sent or received."""

    __tablename__ = "tungsten_whatsapp_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    phone: Mapped[str] = mapped_column(String(40), index=True)
    #: "in" or "out"
    direction: Mapped[str] = mapped_column(String(3), default="out")
    channel: Mapped[str] = mapped_column(String(10), default="cloud")
    body: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: sent, delivered, read, failed or received
    status: Mapped[str] = mapped_column(String(20), default="sent")
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)


class WhatsAppTemplate(WhatsAppBase):
    """A message template approved by Meta (Cloud API only)."""

    __tablename__ = "tungsten_whatsapp_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    #: how many {{1}}, {{2}}... the body has
    params: Mapped[int] = mapped_column(Integer, default=0)

    def __str__(self) -> str:
        return f"{self.name} ({self.language})"
