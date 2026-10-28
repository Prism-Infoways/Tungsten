"""Who sees what (#96), the Agent list, priority history and attachment names (#99), requester id (#108)."""

from __future__ import annotations

import re

import pytest
from conftest import Base, PanelClient, User
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tungsten_tickets import Ticket, TicketReply, TicketsPlugin, create_ticket

from tungsten import Auth, Panel, hash_password
from tungsten.storage import LocalStorage


@pytest.fixture()
def desk(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'desk.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        for name, email in (("Asha Admin", "admin@example.com"), ("Ravi Agent", "ravi@example.com"),
                            ("Neha Customer", "neha@example.com"), ("Old Customer", "old@example.com")):
            db.add(User(name=name, email=email, password=hash_password("password")))
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", storage=LocalStorage(tmp_path / "files"),
                  auth=Auth(User, mailer=lambda **kw: None))
    panel.plugin(TicketsPlugin(agent=lambda user: user.email.endswith("@example.com") and "customer" not in
                               user.name.lower(),
                               agents=lambda query, model: query.where(model.name.like("% Agent"))))
    panel.create_tables(engine)
    panel.db = factory  # type: ignore[attr-defined]
    app = FastAPI()
    panel.mount(app)

    def login(email):
        c = PanelClient(TestClient(app))
        assert c.login(email).status_code == 303
        c.get("/admin/")
        return c

    return panel, login


def test_requesters_only_see_their_own_tickets(desk):
    panel, login = desk
    neha = login("neha@example.com")
    assert neha.get("/admin/tickets/create").status_code == 200
    r = neha.post("/admin/tickets/create", {"subject": "My invoice", "description": "Wrong total", "priority": "high"})
    assert r.status_code == 204, r.text
    with panel.db() as db:
        mine = db.scalars(select(Ticket)).one()
        assert (mine.requester_id, mine.requester_email, mine.status) == ("3", "neha@example.com", "open")
        db.info["tungsten_panel"] = panel
        other = create_ticket(db, subject="Someone else's", requester_email="neha@example.com", source="api")
        db.commit()
        other_id = other.id
    listing = neha.get("/admin/tickets").text
    assert "My invoice" in listing and "Someone else&#39;s" not in listing  # same address, not hers
    assert neha.get(f"/admin/tickets/{other_id}").status_code in (403, 404)
    assert neha.get(f"/admin/tickets/{mine.id}/edit").status_code == 403
    for url in ("/admin/ticket-categories", "/admin/saved-replies"):
        assert neha.get(url).status_code == 403
    assert neha.get("/admin/_tw/widget/ticket-stats").status_code == 403
    page = neha.get(f"/admin/tickets/{mine.id}").text
    assert "Add a message" in page and "Internal note" not in page

    admin = login("admin@example.com")
    admin.post("/admin/_tw/action", {"_tw_host": "resource:tickets", "_tw_scope": "page", "_tw_name": "note",
                                     "_tw_record": str(mine.id), "body": "VIP customer"})
    assert "VIP customer" not in neha.get(f"/admin/tickets/{mine.id}").text
    assert admin.get("/admin/_tw/widget/ticket-stats").status_code == 200
    assert "Someone else" in admin.get("/admin/tickets?tab=all").text


def test_agent_list_is_narrowed(desk):
    panel, login = desk
    admin = login("admin@example.com")
    form = admin.get("/admin/tickets/create").text
    start = form.index('name="assigned_to"')
    field = form[start:form.index("</select>", start)]
    assert "Ravi Agent" in field and "Neha Customer" not in field and "Asha Admin" not in field


def test_priority_change_is_in_the_history(desk):
    panel, login = desk
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        ticket = create_ticket(db, subject="Slow page", source="api")
        db.commit()
    admin = login("admin@example.com")
    admin.get(f"/admin/tickets/{ticket.id}/edit")
    admin.post(f"/admin/tickets/{ticket.id}/edit", {"subject": "Slow page", "status": "open", "priority": "urgent",
                                                    "source": "api"})
    with panel.db() as db:
        events = [r.body for r in db.scalars(select(TicketReply).where(TicketReply.kind == "event"))]
    assert "Priority changed from Normal to Urgent by Asha Admin" in events


def test_attachments_keep_their_names(desk):
    panel, login = desk
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        ticket = create_ticket(db, subject="Upload", source="api")
        db.commit()
    admin = login("admin@example.com")
    name = "Quarterly sales report for the north region (final version).pdf"
    r = admin.client.post("/admin/_tw/form", data={
        "_tw_kind": "action", "_tw_host": "resource:tickets", "_tw_scope": "page", "_tw_name": "note",
        "_tw_record": str(ticket.id), "_tw_form_id": "tw-action-form", "body": "see file"},
        files={"attachments.__upload": (name, b"%PDF-1.4", "application/pdf")},
        headers={"HX-Request": "true", "X-CSRF-Token": admin.token})
    signed = re.search(r'name="attachments" value="([^"]+)"', r.text).group(1)
    stored = signed.split("|")[0]
    assert stored.startswith("tickets/") and stored.endswith("/" + name)
    admin.post("/admin/_tw/action", {"_tw_host": "resource:tickets", "_tw_scope": "page", "_tw_name": "note",
                                     "_tw_record": str(ticket.id), "body": "see file", "attachments": signed})
    page = admin.get(f"/admin/tickets/{ticket.id}").text
    assert name in page and "overflow-wrap: anywhere" in page
