"""Tables of the leads plugin. Users are stored by id as a string, so any user model works."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> dt.datetime:
    return dt.datetime.now()


class LeadsBase(DeclarativeBase):
    pass


class Lead(LeadsBase):
    __tablename__ = "tungsten_leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    company: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    source: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    value: Mapped[Any] = mapped_column(Numeric(12, 2), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    follow_up_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: values of the fields added on the "Lead fields" screen, by field key
    custom_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #: id of the lead in the system it came from (a Meta lead id...), to skip duplicates
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    activities: Mapped[list["LeadActivity"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="LeadActivity.created_at.desc()")

    def __str__(self) -> str:
        return self.name


class LeadField(LeadsBase):
    """A form field the admin adds to every lead (budget, city, course...)."""

    __tablename__ = "tungsten_lead_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(60), unique=True)
    type: Mapped[str] = mapped_column(String(20), default="text")
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    help_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    def __str__(self) -> str:
        return self.label


class LeadActivity(LeadsBase):
    """A note, call, email or message on a lead's timeline."""

    __tablename__ = "tungsten_lead_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("tungsten_leads.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20), default="note")
    body: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    lead: Mapped[Lead] = relationship(back_populates="activities")

    def __str__(self) -> str:
        return f"{self.type}: {self.body[:40]}"
