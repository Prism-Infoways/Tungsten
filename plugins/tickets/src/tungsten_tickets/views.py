"""Turn a ticket's messages into what the conversation template shows."""

from __future__ import annotations

import os
from typing import Any

from markupsafe import Markup

from .models import Ticket


def when(value: Any) -> str:
    return value.strftime("%d %b %Y, %H:%M") if value else ""


def user_name(panel: Any, db: Any, user_id: str | None, cache: dict) -> str | None:
    if not user_id or panel.auth.user_model is None:
        return None
    if user_id not in cache:
        user = panel.auth.find_by_id(db, user_id)
        cache[user_id] = panel.auth.display_name(user) if user is not None else None
    return cache[user_id]


def _file(panel: Any, path: str, public: bool) -> dict:
    """An attachment: its name, and a link when this viewer may open it."""
    name = os.path.basename(str(path))
    storage = panel.storage
    allowed = not public or (hasattr(storage, "is_public") and storage.is_public(path))
    try:
        url = storage.url(path) if allowed else None
    except Exception:  # storage without links
        url = None
    return {"name": name, "url": url}


def conversation_items(panel: Any, db: Any, ticket: Ticket, public: bool = False) -> list[dict]:
    """The description first, then every reply. ``public`` leaves out internal notes and events."""
    cache: dict = {}
    customer = ticket.requester_name or ticket.requester_email or "Customer"
    items = []
    if ticket.description:
        items.append({"kind": "customer", "author": customer, "body": ticket.description,
                      "when": when(ticket.created_at), "attachments": []})
    for reply in ticket.replies:
        if public and reply.is_internal:
            continue
        if reply.kind == "customer":
            author = reply.author_name or customer
        else:
            author = reply.author_name or user_name(panel, db, reply.user_id, cache) or "Support team"
        items.append({"kind": reply.kind, "author": author, "body": reply.body, "when": when(reply.created_at),
                      "attachments": [_file(panel, p, public) for p in reply.attachments or []]})
    return items


def render_conversation(ctx: Any, ticket: Ticket | None) -> Markup:
    if ticket is None:
        return Markup("")
    items = conversation_items(ctx.panel, ctx.db, ticket)
    return Markup(ctx.panel.renderer.render("tungsten_tickets/conversation.html", items=items, show_tags=True))
