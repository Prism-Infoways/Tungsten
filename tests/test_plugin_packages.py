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
