"""Security fixes: disabled actions (#85), Select modify_query (#87), stored file access (#95), logout ends the
session (#103), hidden fields (#107) and the page to go back to after signing in (#109)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.datastructures import FormData

from tests.conftest import PanelClient, db_session


def test_a_disabled_action_does_not_run(panel):
    from tungsten.actions import Action
    from tungsten.jobs import background_context
    from tungsten.routes import Routes

    with db_session(panel) as db:
        ctx = background_context(panel, db, "1")
        ran = []
        locked = Action("delete").disabled(lambda record: record == "locked").action(lambda: ran.append(1))
        assert not Routes.action_available(locked, None, ctx, "locked")
        assert Routes.action_available(locked, None, ctx, "open")


def test_select_checks_ids_against_modify_query(panel):
    from examples.shop.models import Category, Product
    from tungsten.forms import Form, Select
    from tungsten.forms.form import ValidationError
    from tungsten.jobs import background_context

    with db_session(panel) as db:
        ctx = background_context(panel, db, "1")
        first, other = db.scalars(select(Category).order_by(Category.id).limit(2)).all()

        def check(value, **opts):
            field = Select("category_id").relationship(
                "category", "name", modify_query=lambda query: query.where(Category.id == first.id))
            if opts.get("searchable"):
                field.searchable().preload(False)
            form = Form().model(Product).schema([field])
            form.bind(ctx, operation="create")
            form.load(FormData([("category_id", str(value))]))
            try:
                form.validate()
                return True
            except ValidationError:
                return False

        for searchable in (False, True):
            assert check(first.id, searchable=searchable)
            assert not check(other.id, searchable=searchable)


def test_file_access_hook(admin, panel, tmp_path):
    (tmp_path / "storage" / "private").mkdir(parents=True, exist_ok=True)
    (tmp_path / "storage" / "private" / "a.txt").write_text("secret")
    (tmp_path / "storage" / "open.txt").write_text("hello")
    assert admin.get("/admin/storage/private/a.txt").status_code == 200
    panel.on_file_access("private", lambda path: not path.startswith("private/") and None)
    assert admin.get("/admin/storage/private/a.txt").status_code == 404
    assert admin.get("/admin/storage/open.txt").text == "hello"


def test_logout_ends_every_copy_of_the_session(app_and_panel):
    app, panel = app_and_panel
    c = PanelClient(TestClient(app))
    c.login()
    assert c.get("/admin/products").status_code == 200
    saved = c.client.cookies.get("tungsten_admin")
    c.get("/admin/")
    c.post("/admin/logout", {"_token": c.token}, htmx=False, follow_redirects=False)
    replay = PanelClient(TestClient(app))
    replay.client.cookies.set("tungsten_admin", saved)
    r = replay.get("/admin/products", follow_redirects=False)
    assert r.status_code == 303 and "/admin/login" in r.headers["location"]


def test_signing_in_again_replaces_the_old_session(app_and_panel):
    from tungsten.models import AuthSession

    app, panel = app_and_panel
    c = PanelClient(TestClient(app))
    c.login()
    c.login()
    with db_session(panel) as db:
        assert len(db.scalars(select(AuthSession)).all()) == 1


def test_sessions_can_be_turned_off(panel):
    from tungsten import Auth

    assert Auth(object(), sessions=False).sessions is None
    assert panel.auth.session_max_age == 14 * 24 * 3600


def test_hidden_field_gives_no_options(admin, monkeypatch):
    from tungsten.forms.fields import Field

    data = {"_tw_kind": "host", "_tw_host": "resource:orders", "_tw_op": "create", "_tw_field": "customer_id", "q": ""}
    r = admin.post("/admin/_tw/form/options", data)
    assert r.status_code == 200 and r.json()
    visible = Field.is_field_visible
    monkeypatch.setattr(Field, "is_field_visible",
                        lambda self, form, base: self.name != "customer_id" and visible(self, form, base))
    r = admin.post("/admin/_tw/form/options", data)
    assert r.status_code != 200 and not r.content  # refused, no options


def test_next_after_login_is_the_page_not_the_fragment(app_and_panel):
    app, _ = app_and_panel
    c = PanelClient(TestClient(app))
    r = c.client.get("/admin/_tw/widget/anything", headers={
        "HX-Request": "true", "HX-Current-URL": "http://testserver/admin/orders?page=2"})
    assert r.headers["HX-Redirect"] == "/admin/login?next=%2Fadmin%2Forders%3Fpage%3D2"
    r = c.client.get("/admin/_tw/widget/anything", headers={
        "HX-Request": "true", "HX-Current-URL": "http://evil.example/admin/orders"})
    assert r.headers["HX-Redirect"] == "/admin/login"
    r = c.client.get("/admin/_tw/widget/anything", headers={"HX-Request": "true"})
    assert r.headers["HX-Redirect"] == "/admin/login"
    r = c.client.get("/admin/orders", follow_redirects=False)
    assert r.headers["location"] == "/admin/login?next=%2Fadmin%2Forders"
