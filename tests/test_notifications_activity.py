"""Notifications by email and live push; the activity log for deletes, sign-ins, exports and actions."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from examples.shop.models import Product, User
from tungsten import Notification
from tungsten.broadcast import Broadcaster
from tungsten.models import ActivityLog, DatabaseNotification

from .conftest import PanelClient, db_session


def logs(panel, event=None):
    with db_session(panel) as db:
        query = select(ActivityLog).order_by(ActivityLog.id)
        if event:
            query = query.where(ActivityLog.event == event)
        return db.scalars(query).all()


def post_action(admin, host, scope, action, record=None, **fields):
    data = {"_tw_host": host, "_tw_scope": scope, "_tw_name": action, **fields}
    if record is not None:
        data["_tw_record"] = record
    return admin.post("/admin/_tw/action", data)


# ---------------------------------------------------------------------- email
def test_send_to_mail_uses_the_panel_mailer(panel):
    with db_session(panel) as db:
        db.info["tungsten_panel"] = panel
        admin = db.get(User, 1)
        Notification("Invoice paid").body("INV-0042 was paid.").action("Open", "/admin/orders/1") \
            .send_to_mail([admin, "boss@example.com", 999], db)
    mails = panel.test_mails
    assert [m["to"] for m in mails] == [admin.email, "boss@example.com"]  # unknown id 999 is skipped
    assert mails[0]["subject"] == "Invoice paid"
    assert "INV-0042 was paid." in mails[0]["body"] and "Open: /admin/orders/1" in mails[0]["body"]


def test_send_to_mail_gives_html_and_full_links(panel):
    sent = []
    panel.auth.mailer = lambda to, subject, body, html: sent.append(html)
    panel.app_url = "https://admin.example.com"
    with db_session(panel) as db:
        db.info["tungsten_panel"] = panel
        Notification("Hi <you>").action("Open", "/admin/orders/1").send_to_mail("a@example.com", db, subject="S")
    assert "Hi &lt;you&gt;" in sent[0] and 'href="https://admin.example.com/admin/orders/1"' in sent[0]


def test_failing_mailer_does_not_raise(panel, caplog):
    def broken(to, subject, body):
        raise OSError("smtp down")

    panel.auth.mailer = broken
    with db_session(panel) as db:
        db.info["tungsten_panel"] = panel
        Notification("Hello").send_to_mail("a@example.com", db)
    assert "Could not email notification" in caplog.text


# ---------------------------------------------------------------------- live push
def test_broadcaster_delivers_to_subscribers_only():
    import asyncio

    hub = Broadcaster()

    async def go():
        async with hub.subscribe(1) as queue:
            assert hub.connected("1") == 1
            hub.publish("1", {"type": "toast"})
            hub.publish(2, {"type": "other"})
            return await asyncio.wait_for(queue.get(), 1), queue.qsize()

    message, left = asyncio.run(go())
    assert message == {"type": "toast"} and left == 0
    assert hub.connected(1) == 0


def test_live_socket_needs_a_signed_in_user(app_and_panel):
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(app_and_panel[0])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/admin/_tw/live") as ws:
            ws.receive_text()


def test_live_socket_refuses_other_sites(app_and_panel):
    from starlette.websockets import WebSocketDisconnect

    client = PanelClient(TestClient(app_and_panel[0]))
    client.login()
    with pytest.raises(WebSocketDisconnect):
        with client.client.websocket_connect("/admin/_tw/live", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_text()


def test_live_socket_pushes_toasts_and_bell_updates(admin, panel):
    page = admin.get("/admin/").text
    assert 'data-tw-live-url="/admin/_tw/live"' in page
    with admin.client.websocket_connect("/admin/_tw/live") as ws:
        for _ in range(100):  # wait until the socket has subscribed
            if panel.broadcaster.connected(1):
                break
            import time

            time.sleep(0.01)
        with db_session(panel) as db:
            db.info["tungsten_panel"] = panel
            Notification("Export ready").body("orders.csv").success().broadcast(db.get(User, 1), db)
            Notification("Stored").send_to_database(1, db)
        toast = json.loads(ws.receive_text())
        assert toast["type"] == "toast" and toast["toast"]["title"] == "Export ready"
        assert "<svg" in toast["toast"]["icon_svg"]
        assert json.loads(ws.receive_text()) == {"type": "notifications"}
    with db_session(panel) as db:
        assert db.scalars(select(DatabaseNotification)).first().data["title"] == "Stored"


def test_live_push_can_be_turned_off(admin, panel):
    panel.notifications_live = False
    assert "data-tw-live-url" not in admin.get("/admin/").text
    with db_session(panel) as db:
        db.info["tungsten_panel"] = panel
        Notification("Quiet").broadcast(1, db)  # nothing to send to: no error


# ---------------------------------------------------------------------- activity log
def test_sign_ins_are_logged(client, panel):
    client.get("/admin/login")
    client.client.post("/admin/login", data={"_token": client.token, "email": "admin@example.com",
                                             "password": "wrong"})
    failed = logs(panel, "login_failed")
    assert len(failed) == 1 and failed[0].user_id is None
    assert failed[0].properties["email"] == "admin@example.com" and "ip" in failed[0].properties
    client.login()
    login = logs(panel, "login")
    assert len(login) == 1 and login[0].user_id == "1" and login[0].subject_type == "User"
    client.get("/admin/")
    client.post("/admin/logout", {"_token": client.token}, htmx=False)
    assert [r.user_id for r in logs(panel, "logout")] == ["1"]


def test_deletes_restores_and_force_deletes_are_logged(admin, panel):
    post_action(admin, host="resource:products", scope="row", action="delete", record="1")
    post_action(admin, host="resource:products", scope="row", action="restore", record="1")
    post_action(admin, host="resource:products", scope="bulk", action="delete", records=["2", "3"])
    rows = [(r.event, r.subject_type, r.subject_id, r.user_id) for r in logs(panel)
            if r.event in ("deleted", "restored", "action")]
    assert rows == [("deleted", "Product", "1", "1"), ("restored", "Product", "1", "1"),
                    ("deleted", "Product", "2", "1"), ("deleted", "Product", "3", "1")]


def test_custom_actions_are_logged_once_per_record(admin, panel):
    r = post_action(admin, host="resource:users", scope="bulk", action="deactivate", records=["2", "3"])
    assert "Users deactivated" in r.headers["HX-Trigger"]
    rows = logs(panel, "action")
    assert [(r.subject_type, r.subject_id) for r in rows] == [("User", "2"), ("User", "3")]
    assert rows[0].properties["action"] == "deactivate" and rows[0].description.startswith("Ran ")


def test_modal_create_and_edit_are_logged(admin, panel):
    post_action(admin, "resource:categories", "page", "create", name="Kids Wear", slug="kids-wear", is_visible="1")
    post_action(admin, "resource:categories", "row", "edit", record="1", name="Clothes", slug="clothes")
    events = [(r.event, r.subject_type) for r in logs(panel) if r.subject_type == "Category"]
    assert events == [("created", "Category"), ("updated", "Category")]  # no extra "action" rows


def test_same_event_is_logged_once_per_request(admin, panel):
    from tungsten.context import Context

    with db_session(panel) as db:
        product = db.get(Product, 1)
        ctx = Context.__new__(Context)
        ctx.__dict__.update(panel=panel, db=db, user=None)
        panel.log_activity(ctx, "deleted", product)
        panel.log_activity(ctx, "deleted", product)  # e.g. a plugin logs, then host.delete logs again
        db.commit()
    assert len(logs(panel, "deleted")) == 1


def test_export_is_logged(admin, panel):
    r = admin.get("/admin/_tw/export?host=resource:products&format=csv")
    assert r.status_code == 200
    row = logs(panel, "exported")[0]
    assert row.subject_type == "Product" and row.properties["format"] == "csv"


def test_nothing_is_logged_when_off(admin, panel):
    panel.activity_log = False
    post_action(admin, host="resource:products", scope="row", action="delete", record="1")
    assert logs(panel) == [] or all(r.event == "login" for r in logs(panel))
