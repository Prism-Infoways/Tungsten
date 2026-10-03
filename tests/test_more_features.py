"""Tests for the second batch of Filament features."""

from __future__ import annotations

import json
import re
import time

from sqlalchemy import select
from starlette.datastructures import FormData

from examples.shop.models import Brand, Category, Post, User
from tungsten.auth.two_factor import match_step, otpauth_uri, totp
from tungsten.forms import Block, Builder, Form, TextInput, ToggleButtons, ValidationError

from .conftest import PanelClient, db_session
from .test_panel import table


# ---------------------------------------------------------------------- form fields


def make(schema):
    form = Form().schema(schema)
    form.bind(None, operation="create", refresh_url="/refresh")
    form.fill()
    return form


def test_builder_blocks_round_trip():
    builder = Builder("content").blocks([
        Block("heading").schema([TextInput("text").required()]),
        Block("quote").schema([TextInput("text"), TextInput("author")]),
    ])
    form = make([builder])
    assert form.get("content") == []
    form.handle_ui_action("repeater.add:content:quote")
    form.handle_ui_action("repeater.add:content:heading")
    assert [r["__type"] for r in form.get("content")] == ["quote", "heading"]
    html = str(form.render())
    assert 'name="content.0.__type" value="quote"' in html and "Add block" in html
    form.load(FormData([("content.0.__row", "1"), ("content.0.__type", "quote"), ("content.0.text", "Hi"),
                        ("content.0.author", "Ann"), ("content.1.__row", "1"), ("content.1.__type", "heading"),
                        ("content.1.text", "")]))
    try:
        form.validate()
        raise AssertionError("expected errors")
    except ValidationError as exc:
        assert list(exc.errors) == ["content.1.text"]
    form.load(FormData([("content.0.__row", "1"), ("content.0.__type", "heading"), ("content.0.text", "Title")]))
    assert form.validate() == {"content": [{"type": "heading", "data": {"text": "Title"}}]}


def test_toggle_buttons():
    form = make([
        ToggleButtons("status").options({"draft": "Draft", "live": "Live"}).icons({"live": "check"})
        .colors({"live": "success"}).required(),
        ToggleButtons("days").options(["mon", "tue"]).multiple(),
        ToggleButtons("ok").boolean(),
    ])
    html = str(form.render())
    assert "peer-checked:bg-success-600" in html and 'type="checkbox" name="days"' in html
    form.load(FormData([("status", "live"), ("days", "mon"), ("days", "tue"), ("ok", "0")]))
    assert form.validate() == {"status": "live", "days": ["mon", "tue"], "ok": False}


# ---------------------------------------------------------------------- tables


def test_list_tabs_filter_and_count(admin, panel):
    r = table(admin, "resource:users", tab="inactive")
    with db_session(panel) as db:
        inactive = len(db.scalars(select(User).where(User.is_active.is_(False))).all())
    assert f"of <span class=\"font-medium\">{inactive}</span> results" in r.text
    assert re.search(r'aria-current="page">.*?Inactive', r.text, re.S)
    assert r.headers["HX-Replace-Url"].startswith("/admin/users?tab=inactive")


def test_inline_text_column_validates_and_saves(admin, panel):
    r = admin.post("/admin/_tw/column", {"host": "resource:brands", "record": "1", "column": "name", "value": ""})
    assert "Not saved" in r.headers["HX-Trigger"] and "required" in r.headers["HX-Trigger"]
    r = admin.post("/admin/_tw/column", {"host": "resource:brands", "record": "1", "column": "website", "value": "nope"})
    assert "valid URL" in r.headers["HX-Trigger"]
    r = admin.post("/admin/_tw/column", {"host": "resource:brands", "record": "1", "column": "name", "value": "Renamed"})
    assert "Saved" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert db.get(Brand, 1).name == "Renamed"


def test_inline_select_column(admin, panel):
    r = admin.post("/admin/_tw/column", {"host": "resource:posts", "record": "1", "column": "status", "value": "bogus"})
    assert "Not saved" in r.headers["HX-Trigger"]
    admin.post("/admin/_tw/column", {"host": "resource:posts", "record": "1", "column": "status", "value": "review"})
    with db_session(panel) as db:
        assert db.get(Post, 1).status == "review"


def test_reorder_rows(admin, panel):
    r = table(admin, "resource:categories", reordering="1")
    assert "data-tw-sortable" in r.text and "Done reordering" in r.text and "tw-drag-handle" in r.text
    with db_session(panel) as db:
        ids = [c.id for c in db.scalars(select(Category).order_by(Category.sort))]
    new_order = list(reversed(ids))
    r = admin.post("/admin/_tw/reorder", {"host": "resource:categories", "keys": [str(i) for i in new_order]})
    assert "Order saved" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert [c.id for c in db.scalars(select(Category).order_by(Category.sort))] == new_order


# ---------------------------------------------------------------------- infolists, dashboard filters


def test_view_page_uses_infolist(admin):
    html = admin.get("/admin/products/1").text
    assert "Pricing &amp; stock" in html and "tw-infolist" in html
    assert "₹1,299" in html and 'name="price"' not in html  # entries, not inputs


def test_dashboard_filters_reach_widgets(admin):
    html = admin.get("/admin/?period=7").text
    assert 'name="period"' in html and '<option value="7" selected' in html
    r = admin.get("/admin/_tw/widget/shop-stats?period=7", htmx=True)
    assert "In the last 7 days" in r.text
    r = admin.get("/admin/_tw/widget/shop-stats", htmx=True)
    assert "In the last 30 days" in r.text


# ---------------------------------------------------------------------- auth


def test_registration(client, panel):
    client.get("/admin/register")
    r = client.client.post("/admin/register", data={"_token": client.token, "name": "Reg User", "email": "admin@example.com",
                                                    "password": "password123", "password_confirmation": "password123"})
    assert "has already been taken" in r.text
    r = client.client.post("/admin/register", data={"_token": client.token, "name": "Reg User", "email": "reg@x.com",
                                                    "password": "password123", "password_confirmation": "password123"})
    assert "needs to give you access" in r.text  # demo only lets is_admin users in
    with db_session(panel) as db:
        user = db.scalars(select(User).where(User.email == "reg@x.com")).one()
        assert user.password.startswith("pbkdf2_sha256$")


def test_totp_helpers():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # RFC 6238 test key "12345678901234567890"
    assert totp(secret, 59 // 30) == "287082"  # RFC 6238 vector 94287082, last 6 digits
    assert match_step(secret, "287082", now=59) == 1
    assert match_step(secret, "287082", now=59 + 120) is None  # too old
    assert match_step(secret, "abc") is None
    secret = "JBSWY3DPEHPK3PXP"
    assert otpauth_uri(secret, "a@b.co", "Acme").startswith("otpauth://totp/Acme%3Aa%40b.co?secret=")


def test_two_factor_setup_and_login(admin, app_and_panel):
    from fastapi.testclient import TestClient

    r = admin.post("/admin/two-factor", {"_do": "enable"}, htmx=False)
    secret = re.search(r"<code[^>]*>([A-Z2-7]+)</code>", r.text).group(1)
    r = admin.post("/admin/two-factor", {"_do": "confirm", "code": "123456"}, htmx=False)
    assert "not valid" in r.text
    r = admin.post("/admin/two-factor", {"_do": "confirm", "code": totp(secret)}, htmx=False)
    codes = re.findall(r">([0-9a-f]{6}-[0-9a-f]{6})<", r.text)
    assert len(codes) == 8

    fresh = PanelClient(TestClient(app_and_panel[0]))
    r = fresh.login()
    assert r.headers["location"] == "/admin/two-factor/challenge"
    assert fresh.get("/admin/products", follow_redirects=False).status_code == 303  # not signed in yet
    fresh.get("/admin/two-factor/challenge")
    r = fresh.client.post("/admin/two-factor/challenge", data={"_token": fresh.token, "code": totp(secret)},
                          follow_redirects=False)
    assert "not valid" in r.text  # the same code can't be used twice
    r = fresh.client.post("/admin/two-factor/challenge", data={"_token": fresh.token, "code": codes[0]},
                          follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/"
    assert fresh.get("/admin/products").status_code == 200

    # turning it off needs the password
    r = admin.post("/admin/two-factor", {"_do": "disable", "password": "wrong"}, htmx=False)
    assert "password is incorrect" in r.text
    r = admin.post("/admin/two-factor", {"_do": "disable", "password": "password"}, htmx=False)
    assert "is off" in r.text


def test_two_factor_required_forces_setup(app_and_panel, admin):
    _, panel = app_and_panel
    panel.auth.two_factor_required = True
    try:
        r = admin.get("/admin/products", follow_redirects=False)
        assert r.headers["location"] == "/admin/two-factor"
        assert admin.get("/admin/two-factor").status_code == 200
    finally:
        panel.auth.two_factor_required = False


# ---------------------------------------------------------------------- spa, shortcuts, sidebar


def test_layout_options(admin):
    html = admin.get("/admin/posts/1/edit").text
    assert 'hx-boost="true"' in html
    assert 'data-tw-unsaved-alerts="true"' in html and "data-tw-unsaved" in html
    assert 'data-tw-keys="mod+s"' in html
    assert "twToggleSidebar()" in html


def test_post_builder_saves_through_resource(admin, panel):
    r = admin.post("/admin/posts/create", {
        "title": "Blocks", "slug": "blocks", "status": "published",
        "content.0.__row": "1", "content.0.__type": "heading", "content.0.text": "Hello", "content.0.level": "h3",
        "content.1.__row": "1", "content.1.__type": "quote", "content.1.text": "Nice", "content.1.author": "",
    })
    assert r.status_code == 204, r.text
    with db_session(panel) as db:
        post = db.scalars(select(Post).where(Post.slug == "blocks")).one()
        assert post.content == [{"type": "heading", "data": {"text": "Hello", "level": "h3"}},
                                {"type": "quote", "data": {"text": "Nice", "author": None}}]
    html = admin.get(f"/admin/posts/{post.id}/edit").text
    assert 'name="content.1.text"' in html and "Nice" in html
    assert json.loads(json.dumps(post.content))
    assert time.time()
