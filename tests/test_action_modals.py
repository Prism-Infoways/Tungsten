"""Actions whose modal only shows something: ``modal_content()`` alone opens a modal."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import Markup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tungsten import Notification, Page, Panel
from tungsten.actions import Action, Halt

from .conftest import PanelClient

ACTION = "/admin/_tw/action"


def not_yet(ctx):
    Notification("Not linked yet").warning().send(ctx)
    raise Halt


class HelpPage(Page):
    slug = "help"
    title = "Help"

    @classmethod
    def header_actions(cls, ctx):
        return [
            Action("guide").label("Setup guide").slide_over().modal_width("2xl")
            .modal_content(Markup("<p>Step one</p>")).modal_submit_action(False).modal_cancel_action_label("Close"),
            Action("link").label("Link phone").modal_description("Scan this code.")
            .modal_content(lambda ctx: Markup("<img alt='QR code'>")).modal_submit_action_label("I have scanned it")
            .action(not_yet),
            Action("publish").requires_confirmation().modal_content(Markup("<p>3 people get an email</p>"))
            .action(lambda: None),
        ]


def make_client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    panel = Panel(path="/admin", session_factory=sessionmaker(engine), secret_key="x")
    panel.pages([HelpPage])
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    client = PanelClient(TestClient(app))
    page = client.get("/admin/help")
    assert page.status_code == 200
    return client, page.text


def test_modal_content_alone_opens_a_modal(tmp_path):
    client, html = make_client(tmp_path)
    for name in ("guide", "link"):
        button = html[html.index(f'"_tw_name": "{name}"') - 400:html.index(f'"_tw_name": "{name}"')]
        assert 'hx-get="/admin/_tw/action"' in button and "hx-post" not in button

    guide = client.get(f"{ACTION}?_tw_host=page:help&_tw_scope=page&_tw_name=guide", htmx=True).text
    assert "Step one" in guide and "justify-end" in guide and "max-w-2xl" in guide
    assert 'type="submit"' not in guide and "Close" in guide and "Are you sure" not in guide

    link = client.get(f"{ACTION}?_tw_host=page:help&_tw_scope=page&_tw_name=link", htmx=True).text
    assert "QR code" in link and "Scan this code." in link and "I have scanned it" in link


def test_halt_keeps_a_content_modal_open(tmp_path):
    client, _ = make_client(tmp_path)
    r = client.post(ACTION, {"_tw_host": "page:help", "_tw_scope": "page", "_tw_name": "link"})
    assert r.status_code == 200 and "QR code" in r.text and "Not linked yet" in r.headers["HX-Trigger"]


def test_confirmation_with_content_still_asks(tmp_path):
    client, _ = make_client(tmp_path)
    modal = client.get(f"{ACTION}?_tw_host=page:help&_tw_scope=page&_tw_name=publish", htmx=True).text
    assert "3 people get an email" in modal and "Are you sure" in modal and "Confirm" in modal
