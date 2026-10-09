"""Public help desk pages: raise a ticket, then follow and answer it from a private link.

    GET/POST <panel>/support                     the "raise a ticket" form
    GET/POST <panel>/support/<number>/<key>      the customer's ticket and reply box
"""

from __future__ import annotations

import hmac
import time
from typing import Any

from fastapi import Request
from sqlalchemy import select

from tungsten import Notification
from tungsten.forms import Select, Textarea, TextInput
from tungsten.forms.form import Form, ValidationError
from tungsten.routes import Routes

from .models import TicketCategory
from .service import add_reply, create_ticket, find_ticket
from .views import conversation_items, when

#: tickets one browser may raise per hour, to keep bots and floods out
MAX_TICKETS_PER_HOUR = 5


def _form(ctx: Any, fields: list) -> Form:
    form = Form().schema(fields).columns(2)
    form.bind(ctx, operation="create", refresh_url="", id="tw-ticket-form")
    return form


def _category_options(db: Any) -> dict[str, str]:
    rows = db.scalars(select(TicketCategory).where(TicketCategory.is_public.is_(True))
                      .order_by(TicketCategory.sort, TicketCategory.name)).all()
    return {str(c.id): c.name for c in rows}


def add_portal_routes(app: Any, panel: Any, plugin: Any) -> None:
    routes = Routes(panel)
    base = f"/{plugin.portal_path}"

    def page(ctx: Any, template: str, **context: Any):
        return ctx.render(template, portal_home=panel.url(plugin.portal_path), **context)

    def new_ticket(ctx: Any, fd: Any):
        categories = _category_options(ctx.db)
        fields = [
            TextInput("name").label("Your name").required().max_length(150).autofocus(),
            TextInput("email").label("Email").email().required().max_length(255),
            TextInput("phone").label("Phone").tel().max_length(40),
            *([Select("category").label("Topic").options(categories).native()] if categories else []),
            TextInput("subject").required().max_length(200).column_span("full"),
            Textarea("description").label("How can we help?").rows(6).required().max_length(10000)
            .column_span("full"),
        ]
        form = _form(ctx, fields)
        if fd is None:
            form.fill()
            return page(ctx, "tungsten_tickets/portal-new.html", form=form)
        form.load(fd)
        try:
            data = form.validate()
        except ValidationError:
            return page(ctx, "tungsten_tickets/portal-new.html", form=form)
        if fd.get("website"):  # the hidden field only bots fill in: act as if it worked
            return ctx.go(panel.url(plugin.portal_path))
        now = time.time()
        recent = [t for t in ctx.session.get("tw_tickets_sent", []) if now - t < 3600]
        if len(recent) >= MAX_TICKETS_PER_HOUR:
            return page(ctx, "tungsten_tickets/portal-new.html", form=form,
                        error="You sent many tickets in the last hour. Please wait a little and try again.")
        category = data.get("category")
        ticket = create_ticket(ctx.db, subject=data["subject"], description=data["description"],
                               requester_name=data["name"], requester_email=data["email"],
                               requester_phone=data.get("phone"), source="portal",
                               category_id=int(category) if category and str(category) in categories else None,
                               ctx=ctx)
        ctx.db.commit()
        ctx.session["tw_tickets_sent"] = [*recent, now]
        Notification("Ticket sent").body(f"Your ticket number is {ticket.number}. Keep this page's link to "
                                         "follow it.").success().send(ctx)
        return ctx.go(plugin.portal_path_for(ticket))

    def show_ticket(ctx: Any, fd: Any, number: str, key: str):
        ticket = find_ticket(ctx.db, number)
        if ticket is None or not hmac.compare_digest(ticket.access_key.encode(), key.encode()):
            return routes.error(ctx, 404, "Ticket not found", "Check the link in your email.")
        closed = ticket.status == "closed"
        error = None
        message = ""
        if fd is not None and not closed:
            message = str(fd.get("message") or "").strip()
            if not message:
                error = "Write a message first."
            elif len(message) > 10000:
                error = "The message is too long."
            else:
                add_reply(ctx.db, ticket, message, from_customer=True,
                          author_name=ticket.requester_name or ticket.requester_email, ctx=ctx)
                ctx.db.commit()
                Notification("Reply sent").success().send(ctx)
                return ctx.go(plugin.portal_path_for(ticket))
        label, color = plugin.statuses.get(ticket.status, (ticket.status, "gray"))
        return page(ctx, "tungsten_tickets/portal-ticket.html", ticket=ticket, closed=closed,
                    items=conversation_items(panel, ctx.db, ticket, public=True),
                    status_label=label, status_color=color, opened=when(ticket.created_at), error=error,
                    message=message)

    @app.get(base)
    async def portal_new(request: Request):
        return await routes.run(request, new_ticket, public=True)

    @app.post(base)
    async def portal_new_post(request: Request):
        return await routes.run(request, new_ticket, public=True, read_form=True)

    @app.get(base + "/{number}/{key}")
    async def portal_ticket(request: Request, number: str, key: str):
        return await routes.run(request, show_ticket, public=True, number=number, key=key)

    @app.post(base + "/{number}/{key}")
    async def portal_ticket_post(request: Request, number: str, key: str):
        return await routes.run(request, show_ticket, public=True, read_form=True, number=number, key=key)
