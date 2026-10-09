"""Tables of the tickets plugin. Users are stored by id as a string, so any user model works."""

from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> dt.datetime:
    return dt.datetime.now()


def new_access_key() -> str:
    return secrets.token_urlsafe(18)


class TicketsBase(DeclarativeBase):
    pass


class TicketCategory(TicketsBase):
    """A kind of ticket (Billing, Bug, Sales...). New tickets can go to its default agent."""

    __tablename__ = "tungsten_ticket_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    color: Mapped[str] = mapped_column(String(20), default="gray")
    #: new tickets of this category go to this user when nobody is picked
    assign_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: shown on the public "raise a ticket" form
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    def __str__(self) -> str:
        return self.name


class Ticket(TicketsBase):
    __tablename__ = "tungsten_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: the number people see and quote, like TCK-00012
    number: Mapped[str | None] = mapped_column(String(30), nullable=True, unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_ticket_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    requester_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    requester_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    requester_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: where the ticket came from: panel, portal, api, email, whatsapp...
    source: Mapped[str] = mapped_column(String(20), default="panel")
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: SLA: the ticket should be resolved by then
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    first_response_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    #: secret part of the customer's link to the ticket
    access_key: Mapped[str] = mapped_column(String(40), default=new_access_key)
    #: id in the system it came from (an email message id...), to skip duplicates
    external_id: Mapped[str | None] = mapped_column(String(150), nullable=True, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    category: Mapped[TicketCategory | None] = relationship(lazy="joined")
    replies: Mapped[list[TicketReply]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketReply.created_at")

    @property
    def is_open(self) -> bool:
        return self.status not in ("resolved", "closed")

    @property
    def is_overdue(self) -> bool:
        return bool(self.is_open and self.due_at and self.due_at < dt.datetime.now())

    def __str__(self) -> str:
        return f"{self.number or '#' + str(self.id)} {self.subject}"


class TicketReply(TicketsBase):
    """One message on a ticket: a reply to the customer, a customer message, an internal note or an event."""

    __tablename__ = "tungsten_ticket_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tungsten_tickets.id", ondelete="CASCADE"), index=True)
    #: reply (agent to customer), customer, note (internal, never shown to the customer) or event
    kind: Mapped[str] = mapped_column(String(20), default="reply")
    body: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    ticket: Mapped[Ticket] = relationship(back_populates="replies")

    @property
    def is_internal(self) -> bool:
        return self.kind in ("note", "event")

    def __str__(self) -> str:
        return f"{self.kind}: {self.body[:40]}"


class SavedReply(TicketsBase):
    """A ready answer agents drop into a reply ("canned response")."""

    __tablename__ = "tungsten_ticket_saved_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    def __str__(self) -> str:
        return self.title
