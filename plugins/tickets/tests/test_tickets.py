from __future__ import annotations

import datetime as dt
import json
import re

from conftest import mails
from sqlalchemy import select
from tungsten_tickets import (
    SavedReply,
    Ticket,
    TicketCategory,
    TicketReply,
    add_reply,
    create_ticket,
    find_ticket,
)

from tungsten.models import DatabaseNotification


def action(admin, name, record, scope="page", **data):
    return admin.post("/admin/_tw/action", {"_tw_host": "resource:tickets", "_tw_scope": scope, "_tw_name": name,
                                            "_tw_record": str(record), **data})


def make_ticket(panel, **kw):
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        ticket = create_ticket(db, **{"subject": "Can't log in", "description": "It says wrong password",
                                      "requester_name": "Amit", "requester_email": "Amit@Example.com", **kw})
        db.commit()
        return ticket.id, ticket.number, ticket.access_key


def test_pages_load(admin, panel):
    for url in ("/admin/tickets", "/admin/tickets/create", "/admin/ticket-categories", "/admin/saved-replies",
                "/admin/"):
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[:500])
    assert "Help desk" in admin.get("/admin/tickets").text


def test_create_in_panel_assigns_numbers_and_emails(admin, panel):
    with panel.db() as db:
        db.add(TicketCategory(name="Billing", assign_to="2"))
        db.commit()
    admin.get("/admin/tickets/create")
    r = admin.post("/admin/tickets/create", {
        "subject": "Refund please", "description": "I paid twice", "status": "open", "priority": "high",
        "category_id": "1", "requester_name": "Neha", "requester_email": "neha@example.com",
    })
    assert r.status_code == 204, r.text
    with panel.db() as db:
        ticket = db.scalars(select(Ticket)).one()
        assert ticket.number == "TCK-00001" and ticket.assigned_to == "2"
        hours = (ticket.due_at - ticket.created_at).total_seconds() / 3600
        assert 7.9 < hours < 8.1  # the "high" SLA
        bell = db.scalars(select(DatabaseNotification)).all()
        assert [n.user_id for n in bell] == ["2"] and bell[0].data["title"] == "New ticket for you"
        events = [r.body for r in ticket.replies]
        assert events == ["Assigned to Ravi Agent"]
    to, subject, body = mails[-1]
    assert to == "neha@example.com" and "[TCK-00001]" in subject
    assert f"https://desk.example.com/admin/support/TCK-00001/{ticket.access_key}" in body


def test_view_reply_note_and_resolve(admin, panel):
    ticket_id, _, _ = make_ticket(panel)
    with panel.db() as db:
        db.add(SavedReply(title="Reset", body="Use the reset link on the login page."))
        db.commit()
    page = admin.get(f"/admin/tickets/{ticket_id}").text
    assert "It says wrong password" in page and "data-tickets-conversation" in page
    modal = admin.client.get(f"/admin/_tw/action?_tw_host=resource:tickets&_tw_scope=page&_tw_name=reply"
                             f"&_tw_record={ticket_id}", headers={"HX-Request": "true"}).text
    assert "Use a saved reply" in modal and "Reset" in modal
    filled = admin.client.post("/admin/_tw/form", data={
        "_tw_kind": "action", "_tw_host": "resource:tickets", "_tw_scope": "page", "_tw_name": "reply",
        "_tw_record": str(ticket_id), "_tw_form_id": "tw-action-form", "saved_reply": "1", "body": ""},
        headers={"HX-Request": "true", "HX-Trigger-Name": "saved_reply", "X-CSRF-Token": admin.token})
    assert "Use the reset link on the login page." in filled.text

    mails.clear()
    r = action(admin, "reply", ticket_id, body="Please try the reset link.", status="waiting")
    assert r.headers.get("HX-Redirect") == f"/admin/tickets/{ticket_id}", r.text
    r = action(admin, "note", ticket_id, body="He wrote before too.")
    with panel.db() as db:
        ticket = db.get(Ticket, ticket_id)
        kinds = [(r.kind, r.body) for r in ticket.replies]
        assert ("reply", "Please try the reset link.") in kinds and ("note", "He wrote before too.") in kinds
        assert ticket.status == "waiting" and ticket.first_response_at is not None
        reply = next(r for r in ticket.replies if r.kind == "reply")
        assert reply.author_name == "Asha Admin" and reply.user_id == "1"
    assert len(mails) == 1 and "Please try the reset link." in mails[0][2]  # the note is not emailed

    page = admin.get(f"/admin/tickets/{ticket_id}").text
    assert "Internal note" in page and "He wrote before too." in page

    action(admin, "resolve", ticket_id)
    with panel.db() as db:
        ticket = db.get(Ticket, ticket_id)
        assert ticket.status == "resolved" and ticket.resolved_at is not None
    assert "Resolved:" in mails[-1][1]


def test_edit_logs_status_and_agent_changes(admin, panel):
    ticket_id, _, _ = make_ticket(panel)
    admin.get(f"/admin/tickets/{ticket_id}/edit")
    r = admin.post(f"/admin/tickets/{ticket_id}/edit", {"subject": "Can't log in", "status": "in_progress",
                                                        "priority": "normal", "assigned_to": "2", "source": "api"})
    assert r.status_code == 200 and "Saved" in r.headers["HX-Trigger"], r.text
    with panel.db() as db:
        events = [r.body for r in db.get(Ticket, ticket_id).replies if r.kind == "event"]
    assert "Status changed from Open to In progress by Asha Admin" in events
    assert "Assigned to Ravi Agent by Asha Admin" in events


def test_list_tabs_and_bulk_assign(admin, panel):
    a, _, _ = make_ticket(panel)
    b, _, _ = make_ticket(panel, subject="Old one", priority="urgent")
    with panel.db() as db:
        db.get(Ticket, b).due_at = dt.datetime.now() - dt.timedelta(hours=1)
        db.commit()
    overdue = admin.client.get("/admin/tickets?tab=overdue").text
    assert "Old one" in overdue
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:tickets", "_tw_scope": "bulk", "_tw_name": "assign",
                                         "records": [str(a), str(b)], "user": "2"})
    assert "Tickets assigned" in r.headers["HX-Trigger"]
    with panel.db() as db:
        assert {t.assigned_to for t in db.scalars(select(Ticket))} == {"2"}


def test_portal_raise_and_reply(client, panel):
    r = client.get("/admin/support")
    assert r.status_code == 200 and "Raise a ticket" in r.text
    with panel.db() as db:
        db.add(TicketCategory(name="Sales", is_public=True))
        db.add(TicketCategory(name="Secret", is_public=False))
        db.commit()
    page = client.get("/admin/support").text
    assert "Sales" in page and "Secret" not in page
    r = client.client.post("/admin/support", data={"_token": client.token, "name": "Priya", "email": "priya@x.com",
                                                   "subject": "Price list", "description": "Send me prices",
                                                   "category": "1"}, follow_redirects=False)
    assert r.status_code == 303, r.text[:800]
    link = r.headers["location"]
    assert re.match(r"^/admin/support/TCK-00001/[\w-]+$", link)
    page = client.get(link).text
    assert "Send me prices" in page and "Price list" in page

    # the agent answers with an internal note and a reply: the customer sees only the reply
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        ticket = find_ticket(db, "tck-00001")
        assert ticket.source == "portal" and ticket.category_id == 1
        add_reply(db, ticket, "Secret note", internal=True)
        add_reply(db, ticket, "Here are our prices", author_name="Asha", status="waiting")
        db.commit()
    page = client.get(link).text
    assert "Here are our prices" in page and "Secret note" not in page

    r = client.client.post(link, data={"_token": client.token, "message": "Thanks, one more question"},
                           follow_redirects=False)
    assert r.status_code == 303
    with panel.db() as db:
        ticket = db.scalars(select(Ticket)).one()
        assert ticket.status == "open"  # a customer reply opens a waiting ticket again
        assert ticket.replies[-2].kind == "customer" or ticket.replies[-1].kind == "customer"

    assert client.client.get(link[:-3] + "xyz").status_code == 404
    # bots that fill the hidden field get no ticket
    client.client.post("/admin/support", data={"_token": client.token, "name": "Bot", "email": "b@x.com",
                                               "subject": "Spam", "description": "Spam", "website": "x"})
    with panel.db() as db:
        assert db.scalars(select(Ticket).where(Ticket.subject == "Spam")).first() is None


def test_api(client, panel):
    r = client.client.post("/admin/api/tickets", json={"subject": "Hi"}, headers={"X-Tickets-Token": "nope"})
    assert r.status_code == 401
    r = client.client.post("/admin/api/tickets", json={"name": "Web"}, headers={"X-Tickets-Token": "secret-token"})
    assert r.status_code == 422
    post = lambda: client.client.post("/admin/api/tickets", json={
        "subject": "Order late", "message": "Where is order 12?", "email": "c@x.com", "priority": "urgent",
        "external_id": "mail-1"}, headers={"X-Tickets-Token": "secret-token"})
    first, again = post(), post()
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["number"] == "TCK-00001" and again.json()["id"] == body["id"]
    assert body["url"].startswith("https://desk.example.com/admin/support/TCK-00001/")
    with panel.db() as db:
        ticket = db.get(Ticket, body["id"])
        assert ticket.priority == "urgent" and ticket.source == "api" and ticket.description == "Where is order 12?"


def test_hooks(panel):
    plugin = panel.get_plugin("tickets")
    seen = []
    plugin.on_ticket_created("t", lambda db, ticket: seen.append(("created", ticket.number)))
    plugin.on_ticket_replied("t", lambda db, ticket, reply: seen.append(("reply", reply.kind)))
    plugin.on_status_changed("t", lambda db, ticket, old: seen.append(("status", old, ticket.status)))
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        ticket = create_ticket(db, subject="Hook test")
        add_reply(db, ticket, "Done", status="resolved")
        db.commit()
    assert seen == [("created", "TCK-00001"), ("status", "open", "resolved"), ("reply", "reply")]
    assert json.dumps(seen)
    with panel.db() as db:
        assert db.scalars(select(TicketReply)).first() is not None
