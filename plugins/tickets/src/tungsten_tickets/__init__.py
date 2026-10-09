"""Ticketing desk (help desk) plugin for Tungsten.

    from tungsten_tickets import TicketsPlugin

    panel.plugin(TicketsPlugin())
    panel.create_tables(engine)   # also creates the ticket tables

Adds a "Help desk" menu: tickets with status, priority, category, agent and SLA
due times, a conversation with replies and internal notes, saved replies, and a
public "raise a ticket" page where customers also follow and answer their ticket.
"""

from __future__ import annotations

import hmac
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from tungsten import Plugin
from tungsten.support.evaluate import call

from .models import SavedReply, Ticket, TicketCategory, TicketReply, TicketsBase
from .resources import SavedReplyResource, TicketCategoryResource, TicketResource
from .service import (
    DEFAULT_PRIORITIES,
    DEFAULT_SLA_HOURS,
    DEFAULT_STATUSES,
    add_event,
    add_reply,
    create_ticket,
    find_ticket,
    set_status,
)
from .widgets import TicketStats

__version__ = "0.1.0"

log = logging.getLogger("tungsten.tickets")


class TicketsPlugin(Plugin):
    """``TicketsPlugin(statuses=..., priorities=..., sla_hours=..., portal=True, api_token=None)``.

    - ``statuses`` / ``priorities`` map a key to ``(label, color)``. ``resolved`` and ``closed`` count as done.
    - ``sla_hours`` maps a priority to the hours a ticket has to be resolved (``None``: no due time).
    - ``portal`` adds the public pages ``<panel>/support`` (raise a ticket) and the customer's ticket page.
    - ``api_token`` lets websites and apps POST tickets to ``<panel>/api/tickets``
      (send it in the ``X-Tickets-Token`` header).
    - ``email_requester`` emails the customer on new tickets, replies and when resolved, through
      ``mailer`` or the panel's ``Auth(mailer=...)``.
    - ``notify_agents`` puts new tickets and customer replies in the agent's notification bell.
    """

    id = "tickets"
    metadata = TicketsBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, statuses: dict[str, tuple[str, str]] | None = None,
                 priorities: dict[str, tuple[str, str]] | None = None, sla_hours: dict[str, Any] | None = None,
                 number_prefix: str = "TCK-", portal: bool = True, portal_path: str = "support",
                 api_token: str | None = None, email_requester: bool = True, notify_agents: bool = True,
                 mailer: Any = None, dashboard_widget: bool = True, navigation_group: str = "Help desk") -> None:
        self.statuses = dict(statuses or DEFAULT_STATUSES)
        self.priorities = dict(priorities or DEFAULT_PRIORITIES)
        self.sla_hours = dict(DEFAULT_SLA_HOURS if sla_hours is None else sla_hours)
        self.number_prefix = number_prefix
        self.portal = portal
        self.portal_path = portal_path.strip("/")
        self.api_token = api_token
        self.email_requester_enabled = email_requester
        self.notify_agents = notify_agents
        self.mailer = mailer
        self.dashboard_widget = dashboard_widget
        self.navigation_group = navigation_group
        self.panel: Any = None
        #: other plugins (WhatsApp, Slack...) hook in with the three methods below
        self.created_listeners: dict[str, Any] = {}
        self.reply_listeners: dict[str, Any] = {}
        self.status_listeners: dict[str, Any] = {}

    # ------------------------------------------------------------------ hooks for other code
    def on_ticket_created(self, key: str, fn: Any) -> None:
        """Run ``fn(db, ticket)`` after a ticket is opened. The same ``key`` replaces the function."""
        self.created_listeners[key] = fn

    def on_ticket_replied(self, key: str, fn: Any) -> None:
        """Run ``fn(db, ticket, reply)`` after any reply, customer message or internal note."""
        self.reply_listeners[key] = fn

    def on_status_changed(self, key: str, fn: Any) -> None:
        """Run ``fn(db, ticket, old_status)`` after a ticket's status changes."""
        self.status_listeners[key] = fn

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        for resource in (TicketResource, TicketCategoryResource, SavedReplyResource):
            resource.navigation_group = self.navigation_group
        panel.resources([TicketResource, TicketCategoryResource, SavedReplyResource])
        panel.navigation_group(self.navigation_group, icon="life-buoy")
        if self.dashboard_widget:
            panel.widgets([TicketStats])
        panel.routes(self._routes)

    # ------------------------------------------------------------------ links
    def _absolute(self, ctx: Any, path: str) -> str | None:
        if self.panel.app_url:
            return f"{self.panel.app_url}{path}"
        if ctx is not None and getattr(ctx, "request", None) is not None:
            return self.panel.absolute_url(ctx, path)
        return None

    def portal_path_for(self, ticket: Ticket) -> str:
        return self.panel.url(self.portal_path, ticket.number, ticket.access_key)

    def customer_link(self, ticket: Ticket, ctx: Any = None) -> str | None:
        """The customer's private link to their ticket (None without the portal or a known address)."""
        return self._absolute(ctx, self.portal_path_for(ticket)) if self.portal else None

    def agent_link(self, ticket: Ticket) -> str:
        return self.panel.url(TicketResource.get_slug(), ticket.id)

    # ------------------------------------------------------------------ messages
    def notify_agent(self, db: Any, ticket: Ticket, title: str, body: str, ctx: Any = None) -> None:
        """Put a note in the assigned agent's notification bell (not when they did it themselves)."""
        if not self.notify_agents or not ticket.assigned_to:
            return
        if ctx is not None and getattr(ctx, "user", None) is not None \
                and str(self.panel.auth.user_id(ctx.user)) == str(ticket.assigned_to):
            return
        from tungsten import Notification
        from tungsten.models import DatabaseNotification

        data = Notification(title).body(body).icon("life-buoy").color("info") \
            .action("Open ticket", self.agent_link(ticket)).to_dict()
        db.add(DatabaseNotification(user_id=str(ticket.assigned_to), data=data))

    def email_requester(self, db: Any, ticket: Ticket, kind: str, ctx: Any = None,
                        reply: TicketReply | None = None) -> None:
        """Email the customer: ``received``, ``reply`` or ``resolved``. Mail errors are logged, not raised."""
        if not self.email_requester_enabled or not ticket.requester_email:
            return
        link = self.customer_link(ticket, ctx)
        hello = f"Hello {ticket.requester_name or 'there'},"
        see = f"\n\nSee your ticket and reply here:\n{link}" if link else ""
        if kind == "received":
            subject = f"[{ticket.number}] We got your request: {ticket.subject}"
            body = f"{hello}\n\nThanks for writing to us. Your ticket number is {ticket.number}. " \
                   f"We will reply soon.{see}"
        elif kind == "reply" and reply is not None:
            subject = f"[{ticket.number}] {ticket.subject}"
            body = f"{hello}\n\n{reply.body}{see}"
        elif kind == "resolved":
            subject = f"[{ticket.number}] Resolved: {ticket.subject}"
            body = f"{hello}\n\nWe marked your ticket {ticket.number} as resolved. " \
                   f"If you still need help, just reply.{see}"
        else:
            return
        mailer = self.mailer or self.panel.auth.mailer
        try:
            call(mailer, to=ticket.requester_email, subject=subject, body=body, url=link, ticket=ticket,
                 kind=f"ticket_{kind}")
        except Exception:  # a broken mail server must not lose the ticket
            log.exception("Could not email %s about ticket %s", ticket.requester_email, ticket.number)

    # ------------------------------------------------------------------ routes
    def _routes(self, app: Any, panel: Any) -> None:
        if self.portal:
            from .portal import add_portal_routes

            add_portal_routes(app, panel, self)
        if self.api_token:
            self._api_route(app, panel)

    def _api_route(self, app: Any, panel: Any) -> None:
        plugin = self

        @app.post("/api/tickets")
        async def api_create(request: Request):
            token = request.headers.get("x-tickets-token", "")
            if not hmac.compare_digest(token.encode(), (plugin.api_token or "").encode()):
                return JSONResponse({"error": "Wrong token"}, status_code=401)
            if request.headers.get("content-type", "").startswith("application/json"):
                payload = await request.json()
            else:
                payload = dict(await request.form())
            if not isinstance(payload, dict):
                return JSONResponse({"error": "Send a JSON object"}, status_code=422)
            subject = str(payload.get("subject") or "").strip()
            if not subject:
                return JSONResponse({"error": "Send a subject"}, status_code=422)
            priority = str(payload.get("priority") or "normal")
            if priority not in plugin.priorities:
                return JSONResponse({"error": f"Unknown priority {priority}"}, status_code=422)

            link_ctx = SimpleNamespace(request=request, user=None)  # for full links in emails

            def save(db: Any) -> dict:
                category_id = None
                if payload.get("category"):
                    category = db.query(TicketCategory).filter(TicketCategory.name == str(payload["category"])).first()
                    category_id = category.id if category is not None else None
                ticket = create_ticket(
                    db, subject=subject, description=payload.get("description") or payload.get("message"),
                    requester_name=payload.get("name"), requester_email=payload.get("email"),
                    requester_phone=payload.get("phone"), priority=priority, category_id=category_id,
                    source=str(payload.get("source") or "api")[:20], external_id=payload.get("external_id"),
                    ctx=link_ctx)
                db.commit()
                return {"id": ticket.id, "number": ticket.number, "url": plugin.customer_link(ticket, link_ctx)}

            result = await run_in_threadpool(panel.with_session, save)
            return JSONResponse(result, status_code=201)


__all__ = [
    "SavedReply", "SavedReplyResource", "Ticket", "TicketCategory", "TicketCategoryResource", "TicketReply",
    "TicketResource", "TicketStats", "TicketsBase", "TicketsPlugin", "add_event", "add_reply", "create_ticket",
    "find_ticket", "set_status",
]
