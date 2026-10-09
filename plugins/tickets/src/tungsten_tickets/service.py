"""Functions other code (and other plugins) use to open and answer tickets.

    from tungsten_tickets import add_reply, create_ticket

    ticket = create_ticket(db, subject="Can't log in", description="It says wrong password",
                           requester_name="Amit", requester_email="amit@example.com", source="api")
    add_reply(db, ticket, "Please try the reset link.", user_id="1")
    db.commit()
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select

from .models import Ticket, TicketCategory, TicketReply

log = logging.getLogger("tungsten.tickets")

DEFAULT_STATUSES = {
    "open": ("Open", "info"),
    "in_progress": ("In progress", "primary"),
    "waiting": ("Waiting on customer", "warning"),
    "resolved": ("Resolved", "success"),
    "closed": ("Closed", "gray"),
}
DEFAULT_PRIORITIES = {
    "low": ("Low", "gray"),
    "normal": ("Normal", "info"),
    "high": ("High", "warning"),
    "urgent": ("Urgent", "danger"),
}
#: hours to resolve a ticket, by priority (the SLA). None: no due time.
DEFAULT_SLA_HOURS = {"low": 72, "normal": 24, "high": 8, "urgent": 4}
CLOSED_STATUSES = ("resolved", "closed")


def tickets_plugin(db: Any) -> Any:
    """The ``TicketsPlugin`` of the panel this session belongs to (None in plain scripts)."""
    from tungsten import Panel

    panel = Panel.of(db)
    return panel.get_plugin("tickets") if panel is not None else None


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def status_label(plugin: Any, key: str | None) -> str:
    statuses = plugin.statuses if plugin is not None else DEFAULT_STATUSES
    return statuses.get(key or "", (key or "", ""))[0]


def due_time(plugin: Any, priority: str, start: dt.datetime | None = None) -> dt.datetime | None:
    """When a ticket of this priority should be resolved, or None when the priority has no SLA."""
    hours = (plugin.sla_hours if plugin is not None else DEFAULT_SLA_HOURS).get(priority)
    return (start or _now()) + dt.timedelta(hours=hours) if hours else None


def find_ticket(db: Any, number: str | None = None, *, external_id: str | None = None) -> Ticket | None:
    """A ticket by its number (``TCK-00012``) or outside id."""
    if external_id:
        return db.scalars(select(Ticket).where(Ticket.external_id == str(external_id))).first()
    if number:
        return db.scalars(select(Ticket).where(Ticket.number == number.strip().upper())).first()
    return None


def prepare_new(db: Any, ticket: Ticket) -> None:
    """Fill what a new ticket needs: the category's agent and the SLA due time. Call before flush."""
    plugin = tickets_plugin(db)
    if not ticket.status:
        ticket.status = "open"
    if not ticket.priority:
        ticket.priority = "normal"
    if ticket.requester_email:
        ticket.requester_email = ticket.requester_email.strip().lower()
    if not ticket.assigned_to and ticket.category_id:
        category = db.get(TicketCategory, ticket.category_id)
        if category is not None and category.assign_to:
            ticket.assigned_to = category.assign_to
    if ticket.due_at is None:
        ticket.due_at = due_time(plugin, ticket.priority)


def ticket_created(db: Any, ticket: Ticket, ctx: Any = None) -> None:
    """Give a new (flushed) ticket its number, then tell the agent, the customer and the listeners."""
    plugin = tickets_plugin(db)
    if not ticket.number:
        prefix = plugin.number_prefix if plugin is not None else "TCK-"
        ticket.number = f"{prefix}{ticket.id:05d}"
        db.flush()
    if plugin is None:
        return
    if ticket.assigned_to:
        plugin.notify_agent(db, ticket, "New ticket for you", f"{ticket.number}: {ticket.subject}", ctx)
    plugin.email_requester(db, ticket, "received", ctx)
    for fn in list(plugin.created_listeners.values()):
        fn(db, ticket)


def create_ticket(db: Any, *, subject: str, description: str | None = None, requester_name: str | None = None,
                  requester_email: str | None = None, requester_phone: str | None = None,
                  priority: str = "normal", status: str = "open", category_id: int | None = None,
                  assigned_to: str | None = None, source: str = "api", tags: list | None = None,
                  external_id: str | None = None, ctx: Any = None, **extra: Any) -> Ticket:
    """Open a ticket and return it. With an ``external_id`` that is already saved, return that ticket.

    The session is flushed, not committed: call ``db.commit()`` yourself.
    """
    if external_id:
        existing = find_ticket(db, external_id=external_id)
        if existing is not None:
            return existing
    ticket = Ticket(subject=(subject or "").strip()[:200] or "(no subject)", description=description,
                    requester_name=requester_name, requester_email=requester_email,
                    requester_phone=requester_phone, priority=priority, status=status, category_id=category_id,
                    assigned_to=assigned_to, source=source, tags=list(tags or []),
                    external_id=str(external_id) if external_id else None, **extra)
    prepare_new(db, ticket)
    db.add(ticket)
    db.flush()
    ticket_created(db, ticket, ctx)
    return ticket


def add_event(db: Any, ticket: Ticket, body: str, user_id: str | None = None) -> TicketReply:
    """A grey line on the ticket's conversation, like "Status changed to Resolved"."""
    event = TicketReply(ticket_id=ticket.id, kind="event", body=body, user_id=user_id)
    db.add(event)
    db.flush()
    return event


def set_status(db: Any, ticket: Ticket, status: str, user_id: str | None = None, by: str | None = None,
               ctx: Any = None) -> bool:
    """Change the status, stamp resolved/closed times and log it. False when nothing changed."""
    old = ticket.status
    if status == old:
        return False
    ticket.status = status
    status_changed(db, ticket, old, user_id=user_id, by=by, ctx=ctx)
    return True


def status_changed(db: Any, ticket: Ticket, old: str | None, user_id: str | None = None, by: str | None = None,
                   ctx: Any = None, email: bool = True) -> None:
    """Stamp times, log the change and tell listeners. ``ticket.status`` already holds the new status."""
    plugin = tickets_plugin(db)
    now = _now()
    if ticket.status == "resolved":
        ticket.resolved_at = ticket.resolved_at or now
    elif ticket.status == "closed":
        ticket.closed_at = ticket.closed_at or now
        ticket.resolved_at = ticket.resolved_at or now
    else:
        ticket.resolved_at = None
        ticket.closed_at = None
    text = f"Status changed from {status_label(plugin, old)} to {status_label(plugin, ticket.status)}"
    add_event(db, ticket, text + (f" by {by}" if by else ""), user_id=user_id)
    if plugin is None:
        return
    if ticket.status == "resolved" and email:
        plugin.email_requester(db, ticket, "resolved", ctx)
    for fn in list(plugin.status_listeners.values()):
        fn(db, ticket, old)


def add_reply(db: Any, ticket: Ticket, body: str, *, user_id: str | None = None, author_name: str | None = None,
              internal: bool = False, from_customer: bool = False, attachments: list | None = None,
              status: str | None = None, ctx: Any = None) -> TicketReply:
    """Add a message to the ticket and send the emails and alerts it needs.

    - an agent's reply is emailed to the customer and counts as the first response;
    - ``internal=True`` makes a note only agents see;
    - ``from_customer=True`` is the customer writing: it re-opens a waiting or resolved ticket
      and alerts the agent.

    ``status`` changes the status too (agents usually pick "Waiting on customer").
    The session is flushed, not committed.
    """
    plugin = tickets_plugin(db)
    kind = "customer" if from_customer else "note" if internal else "reply"
    reply = TicketReply(ticket_id=ticket.id, kind=kind, body=body or "", user_id=user_id, author_name=author_name,
                        attachments=list(attachments or []) or None)
    db.add(reply)
    ticket.updated_at = _now()
    if kind == "reply" and ticket.first_response_at is None:
        ticket.first_response_at = _now()
    db.flush()
    if from_customer and ticket.status in ("waiting", *CLOSED_STATUSES) and status is None:
        status = "open"
    if status and status != ticket.status:
        old = ticket.status
        ticket.status = status
        # an agent's reply email already tells the customer, so no second "resolved" email
        status_changed(db, ticket, old, user_id=user_id, by=author_name, ctx=ctx, email=kind != "reply")
    if plugin is not None:
        if kind == "reply":
            plugin.email_requester(db, ticket, "reply", ctx, reply=reply)
        elif kind == "customer" and ticket.assigned_to:
            plugin.notify_agent(db, ticket, "Customer replied", f"{ticket.number}: {ticket.subject}", ctx)
        for fn in list(plugin.reply_listeners.values()):
            fn(db, ticket, reply)
    return reply
