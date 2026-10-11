"""Plugins shipped as their own package: templates, static files, language files and tables."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import String, create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from tungsten import Panel, Plugin


class NotesBase(DeclarativeBase):
    pass


class Note(NotesBase):
    __tablename__ = "plugin_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(String(100))


def make_plugin(tmp_path):
    (tmp_path / "templates" / "notes").mkdir(parents=True)
    (tmp_path / "templates" / "notes" / "hello.html").write_text("Hello {{ who }} from {{ __('Notes') }}")
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "notes.css").write_text(".note{color:red}")
    (tmp_path / "lang").mkdir()
    (tmp_path / "lang" / "hi.json").write_text(json.dumps({"Notes": "नोट्स"}), encoding="utf-8")

    class NotesPlugin(Plugin):
        id = "notes"
        templates = tmp_path / "templates"
        static = tmp_path / "static"
        lang = tmp_path / "lang"
        metadata = NotesBase.metadata

    return NotesPlugin()


def test_plugin_brings_templates_static_lang_and_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    panel = Panel(path="/admin", session_factory=sessionmaker(engine), secret_key="x")
    panel.plugin(make_plugin(tmp_path))

    assert str(panel.renderer.render("notes/hello.html", who="Asha")) == "Hello Asha from Notes"
    assert panel.translator.messages("hi")["Notes"] == "नोट्स"

    panel.create_tables(engine)
    tables = inspect(engine).get_table_names()
    assert "plugin_notes" in tables and "tungsten_roles" in tables

    app = FastAPI()
    panel.mount(app)
    url = panel.plugin_asset("notes", "notes.css")
    assert url == "/admin/plugins/notes/notes.css"
    r = TestClient(app).get(url)
    assert r.status_code == 200 and "color:red" in r.text


def test_app_templates_override_plugin_templates(tmp_path):
    own = tmp_path / "own" / "notes"
    own.mkdir(parents=True)
    (own / "hello.html").write_text("Mine")
    panel = Panel(path="/admin", secret_key="x", template_dirs=[tmp_path / "own"])
    panel.plugin(make_plugin(tmp_path))
    assert str(panel.renderer.render("notes/hello.html", who="x")) == "Mine"


def test_plugin_mount_hook_adds_routes_to_the_main_app():
    class WellKnownPlugin(Plugin):
        id = "well-known"

        def mount(self, app, panel):
            @app.get("/.well-known/hello")
            def hello():
                return {"panel": panel.path}

    for path in ("/admin", ""):
        panel = Panel(path=path, secret_key="t")
        panel.plugin(WellKnownPlugin())
        app = FastAPI()
        panel.mount(app)
        assert TestClient(app).get("/.well-known/hello").json() == {"panel": path}


def test_record_action_adds_buttons_to_another_resource(admin, panel):
    """``panel.record_action`` lets a plugin put a button on rows and record pages it doesn't own."""
    from sqlalchemy import select

    from examples.shop.models import Product
    from tungsten.actions import Action

    pinged = []
    panel.record_action("products", lambda: Action("ping").label("Ping product").action(
        lambda record: pinged.append(record.id)))
    panel.record_action(Product, lambda: Action("page_only").label("Only on the page"), row=False)
    panel.record_action("brands", lambda: Action("elsewhere").label("Not on products"))

    with panel.sync_session_factory() as db:
        product_id = db.scalars(select(Product.id).order_by(Product.id)).first()
    listing = admin.get("/admin/products").text
    assert "Ping product" in listing
    assert "Only on the page" not in listing and "Not on products" not in listing
    edit = admin.get(f"/admin/products/{product_id}/edit").text
    assert "Ping product" in edit and "Only on the page" in edit and "Not on products" not in edit

    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:products", "_tw_scope": "row", "_tw_name": "ping",
                                         "_tw_record": str(product_id)})
    assert r.status_code == 200 and pinged == [product_id]
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:products", "_tw_scope": "page",
                                         "_tw_name": "page_only", "_tw_record": str(product_id)})
    assert r.status_code in (200, 204)
