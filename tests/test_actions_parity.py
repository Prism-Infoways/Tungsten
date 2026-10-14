"""Filament parity for actions and exports: nested modals, chaining, wizards, hooks, rate limits,
downloads, chunked and background bulk actions, background exports and export history."""

from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from tungsten import Auth, Notification, Panel, Resource, hash_password
from tungsten.actions import Action, BulkAction, DownloadAction, DownloadBulkAction, Halt
from tungsten.actions.action import rate_limiter
from tungsten.forms import TextInput
from tungsten.forms.layout import Step
from tungsten.importexport import ExportAction, ExportBulkAction
from tungsten.models import DatabaseNotification, Job
from tungsten.tables import TextColumn

from .conftest import PanelClient

ACTION = "/admin/_tw/action"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100))
    password: Mapped[str] = mapped_column(String(200))


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="new")


calls: list = []


def mark(status):
    def run(records, db):
        calls.append([r.name for r in records])
        for r in records:
            r.status = status
        db.commit()
    return run


class ItemResource(Resource):
    model = Item

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])

    @classmethod
    def table(cls, table):
        return (table.columns([TextColumn("name"), TextColumn("status")])
                .header_actions([ExportAction(), ExportAction("bg_export").background()])
                .actions([
                    Action("approve").form([TextInput("note")])
                    .extra_modal_footer_actions([
                        Action("ask").form([TextInput("question").required()])
                        .action(lambda data: calls.append(("ask", data["question"]))),
                        Action("ping").action(lambda record: calls.append(("ping", record.name))),
                        Action("reject").requires_confirmation().cancel_parent_actions()
                        .action(lambda record: calls.append(("reject", record.name))),
                    ])
                    .extra_modal_submit_action("draft", "Save as draft", {"draft": True})
                    .action(lambda record, data, arguments: calls.append(("approve", record.name, data["note"],
                                                                         arguments.get("draft", False)))),
                    Action("publish").action(lambda record: calls.append(("publish", record.name)))
                    .then(Action("share").form([TextInput("to").required()])
                          .action(lambda record, data: calls.append(("share", record.name, data["to"])))),
                    Action("first").action(lambda: "ok").then(lambda result: "second" if result == "ok" else None),
                    Action("second").action(lambda record: calls.append(("second", record.name))),
                    Action("setup").steps([
                        Step("One").schema([TextInput("a").required()]),
                        Step("Two").schema([TextInput("b")]),
                    ]).modal_submit_action_label("Finish").action(lambda data: calls.append(("setup", data))),
                    Action("hooked").before(lambda data: calls.append("before"))
                    .after(lambda result: calls.append(("after", result)))
                    .action(lambda: calls.append("run") or 7),
                    Action("guarded").before(lambda: (_ for _ in ()).throw(Halt())).action(lambda: calls.append("ran")),
                    Action("limited").rate_limit(2, 60).action(lambda: calls.append("limited")),
                    Action("tall").form([TextInput("x")]).sticky_modal_header(False).sticky_modal_footer(False),
                    DownloadAction("card").file(lambda record: f"name,{record.name}\n".encode())
                    .filename(lambda record: f"card-{record.id}.csv"),
                    DownloadAction("big").stream(lambda: (f"{i}\n" for i in range(3))).filename("big.txt"),
                ])
                .bulk_actions([
                    BulkAction("chunked").chunk_selected_records(2).action(mark("chunked")),
                    BulkAction("later").background(chunk_size=2).action(mark("later")),
                    BulkAction("maybe_later").background(lambda keys: len(keys) > 3).action(mark("maybe")),
                    DownloadBulkAction("names").file(lambda records: ",".join(r.name for r in records).encode())
                    .filename("names.txt"),
                    ExportBulkAction("export_selected").background(),
                ]))


@pytest.fixture()
def env(tmp_path):
    calls.clear()
    rate_limiter.clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        db.add_all([User(name="Ann", email="ann@x.com", password=hash_password("password")),
                    User(name="Bob", email="bob@x.com", password=hash_password("password"))])
        db.add_all([Item(name=f"Item {i}") for i in range(1, 6)])
        db.commit()
    from tungsten import LocalStorage

    panel = Panel(session_factory=Session, secret_key="s", auth=Auth(User),
                  storage=LocalStorage(tmp_path / "storage"))
    panel.resources([ItemResource])
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    return app, Session, panel


def client(app, email="ann@x.com"):
    c = PanelClient(TestClient(app))
    assert c.login(email).status_code == 303
    c.get("/admin/items")
    return c


def row(name, record="1", **extra):
    return {"_tw_host": "resource:items", "_tw_scope": "row", "_tw_name": name, "_tw_record": record, **extra}


def query(params):
    from urllib.parse import urlencode

    return ACTION + "?" + urlencode(params, doseq=True)


def events(r):
    return json.loads(r.headers.get("HX-Trigger", "{}"))


# ---------------------------------------------------------------------- nested modals and footers
def test_modal_footer_opens_nested_modal_on_top(env):
    app, _, _ = env
    c = client(app)
    modal = c.get(query(row("approve")), htmx=True).text
    assert '"_tw_name": "approve/ask"' in modal and 'hx-target="#tw-modal-1"' in modal
    assert '"_tw_level": "1"' in modal and "Save as draft" in modal and 'name="_tw_submit" value="draft"' in modal

    nested = c.get(query(row("approve/ask", _tw_level="1")), htmx=True).text
    assert 'hx-target="#tw-modal-1"' in nested and 'name="_tw_level" value="1"' in nested
    assert "z-index: 60" in nested

    r = c.post(ACTION, row("approve/ask", _tw_level="1", question=""))
    assert "required" in r.text.lower()  # stays open with the error
    r = c.post(ACTION, row("approve/ask", _tw_level="1", question="Why?"))
    assert calls == [("ask", "Why?")]
    assert events(r)["tw-close-modal"] == {"from": 1}  # only the nested modal closes


def test_nested_action_without_modal_and_cancel_parents(env):
    app, _, _ = env
    c = client(app)
    r = c.post(ACTION, row("approve/ping", _tw_level="1"))
    assert calls == [("ping", "Item 1")] and events(r)["tw-close-modal"] == {"from": 1}
    r = c.post(ACTION, row("approve/reject", _tw_level="1"))
    assert events(r)["tw-close-modal"] is True  # every modal closes


def test_unknown_nested_action_is_404(env):
    app, _, _ = env
    c = client(app)
    assert "Page not found" in c.post(ACTION, row("approve/nope", _tw_level="1")).headers["HX-Trigger"]


def test_extra_submit_passes_arguments(env):
    app, _, _ = env
    c = client(app)
    c.post(ACTION, row("approve", note="hi"))
    c.post(ACTION, row("approve", note="later", _tw_submit="draft"))
    assert calls == [("approve", "Item 1", "hi", False), ("approve", "Item 1", "later", True)]
    assert "Page not found" in c.post(ACTION, row("approve", note="x", _tw_submit="bogus")).headers["HX-Trigger"]


# ---------------------------------------------------------------------- chaining
def test_then_opens_the_next_actions_modal(env):
    app, _, _ = env
    c = client(app)
    r = c.post(ACTION, row("publish"))
    assert calls == [("publish", "Item 1")]
    assert r.headers["HX-Retarget"] == "#tw-modal" and r.headers["HX-Reswap"] == "innerHTML"
    assert 'value="publish/share"' in r.text
    r = c.post(ACTION, row("publish/share", to="team"))
    assert calls[-1] == ("share", "Item 1", "team")


def test_then_with_a_closure_runs_a_named_action(env):
    app, _, _ = env
    c = client(app)
    c.post(ACTION, row("first", record="2"))
    assert calls == [("second", "Item 2")]


# ---------------------------------------------------------------------- wizard, sticky, hooks, rate limit
def test_modal_wizard(env):
    app, _, _ = env
    c = client(app)
    modal = c.get(query(row("setup")), htmx=True).text
    assert "wizard.next" in modal and "Finish" not in modal.split("tw-modal")[0]
    assert modal.count('type="submit"') == 0  # the wizard shows Next until its last step
    r = c.post("/admin/_tw/form", {"_tw_kind": "action", "_tw_host": "resource:items", "_tw_scope": "row",
                                           "_tw_name": "setup", "_tw_record": "1", "a": "x",
                                           "_tw_ui_action": re.search(r"wizard\.next:[^\"&]+", modal).group(0)})
    assert "Finish" in r.text
    c.post(ACTION, row("setup", a="x", b="y"))
    assert calls == [("setup", {"a": "x", "b": "y"})]


def test_sticky_header_and_footer_can_be_turned_off(env):
    app, _, _ = env
    c = client(app)
    tall = c.get(query(row("tall")), htmx=True).text
    scroller = tall.index('class="flex-1 overflow-y-auto"')
    assert tall.index("<h2") > scroller and tall.index("Cancel") > scroller
    normal = c.get(query(row("approve")), htmx=True).text
    assert normal.index("<h2") < normal.index('class="flex-1 overflow-y-auto"')


def test_before_and_after_hooks(env):
    app, _, _ = env
    c = client(app)
    c.post(ACTION, row("hooked"))
    assert calls == ["before", "run", ("after", 7)]
    calls.clear()
    assert c.post(ACTION, row("guarded")).status_code == 204
    assert calls == []


def test_rate_limit(env):
    app, _, _ = env
    c = client(app)
    for _ in range(2):
        assert "Too many" not in c.post(ACTION, row("limited")).headers.get("HX-Trigger", "")
    r = c.post(ACTION, row("limited"))
    assert "Too many attempts" in r.headers["HX-Trigger"] and "try again in" in r.headers["HX-Trigger"]
    assert calls == ["limited", "limited"]
    other = client(app, "bob@x.com")  # counted per user
    other.post(ACTION, row("limited"))
    assert calls == ["limited"] * 3


# ---------------------------------------------------------------------- downloads
def test_download_action_sends_a_signed_link(env):
    app, _, _ = env
    c = client(app)
    r = c.post(ACTION, row("card", record="3"))
    link = r.headers["HX-Redirect"]
    assert link.startswith("/admin/_tw/download?token=")
    file = c.get(link)
    assert file.status_code == 200 and file.content == b"name,Item 3\n"
    assert 'attachment; filename="card-3.csv"' in file.headers["content-disposition"]
    assert c.get(link.replace("token=", "token=x")).status_code == 404
    assert client(app, "bob@x.com").get(link).status_code == 403  # the link is only for who made it


def test_stream_and_bulk_downloads(env):
    app, _, _ = env
    c = client(app)
    link = c.post(ACTION, row("big")).headers["HX-Redirect"]
    assert c.get(link).text == "0\n1\n2\n"
    link = c.post(ACTION, {"_tw_host": "resource:items", "_tw_scope": "bulk", "_tw_name": "names",
                           "records": ["1", "2"]}).headers["HX-Redirect"]
    assert c.get(link).text == "Item 1,Item 2"


# ---------------------------------------------------------------------- bulk: chunks and background
def bulk(name, keys):
    return {"_tw_host": "resource:items", "_tw_scope": "bulk", "_tw_name": name, "records": keys}


def test_bulk_action_in_chunks(env):
    app, Session, _ = env
    c = client(app)
    c.post(ACTION, bulk("chunked", ["1", "2", "3", "4", "5"]))
    assert calls == [["Item 1", "Item 2"], ["Item 3", "Item 4"], ["Item 5"]]
    with Session() as db:
        assert {i.status for i in db.scalars(select(Item))} == {"chunked"}


def test_bulk_action_in_background_notifies_when_done(env):
    app, Session, panel = env
    c = client(app)
    r = c.post(ACTION, bulk("later", ["1", "2", "3", "999"]))
    assert "Started in the background" in r.headers["HX-Trigger"]
    panel.jobs.wait()
    with Session() as db:
        statuses = {i.name: i.status for i in db.scalars(select(Item))}
        job = db.scalars(select(Job).where(Job.kind == "bulk_action")).one()
        note = db.scalars(select(DatabaseNotification)).one()
    assert statuses == {"Item 1": "later", "Item 2": "later", "Item 3": "later", "Item 4": "new", "Item 5": "new"}
    assert calls == [["Item 1", "Item 2"], ["Item 3"]]
    assert job.status == "done" and job.processed == 4 and job.failed == 1 and job.total == 4
    assert note.data["title"] == "Later finished" and "1 failed" in note.data["body"]


def test_background_condition(env):
    app, _, panel = env
    c = client(app)
    r = c.post(ACTION, bulk("maybe_later", ["1", "2"]))
    assert "Started in the background" not in r.headers.get("HX-Trigger", "") and calls == [["Item 1", "Item 2"]]
    r = c.post(ACTION, bulk("maybe_later", ["1", "2", "3", "4"]))
    assert "Started in the background" in r.headers["HX-Trigger"]
    panel.jobs.wait()
    assert calls[1:] == [["Item 1", "Item 2", "Item 3", "Item 4"]]


def test_failing_job_is_recorded_and_reported(env):
    app, Session, panel = env

    def boom(job):
        raise RuntimeError("disk full")

    panel.jobs.register("boom", boom)
    c = client(app)
    from tungsten.jobs import background_context

    with Session() as db:
        ctx = background_context(panel, db, "1")
        panel.jobs.dispatch(ctx, "boom", name="Nightly")
    panel.jobs.wait()
    with Session() as db:
        job = db.scalars(select(Job)).one()
        note = db.scalars(select(DatabaseNotification)).one()
    assert job.status == "failed" and job.error == "disk full"
    assert note.data["title"] == "Background task failed" and note.data["body"] == "Nightly"
    assert c.get("/admin/items").status_code == 200


# ---------------------------------------------------------------------- exports
def table(name, **data):
    return {"_tw_host": "resource:items", "_tw_scope": "table", "_tw_name": name, **data}


def test_background_export_and_history(env):
    app, Session, panel = env
    c = client(app)
    r = c.post(ACTION, table("bg_export", format="csv", columns=["name"], state="search=Item"))
    assert "Export started" in r.headers["HX-Trigger"]
    panel.jobs.wait()
    with Session() as db:
        job = db.scalars(select(Job).where(Job.kind == "export")).one()
        note = db.scalars(select(DatabaseNotification)).one()
    assert job.status == "done" and job.processed == 5
    assert note.data["title"] == "Your export is ready"
    url = note.data["actions"][0]["url"]
    assert url == f"/admin/_tw/exports/{job.id}/download"
    file = c.get(url)
    assert file.status_code == 200 and sorted(file.text.lstrip("﻿").splitlines()) == [f"Item {i}" for i in range(1, 6)] + ["Name"]
    assert client(app, "bob@x.com").get(url).status_code == 403
    # the stored file is not reachable through the general storage route
    assert c.get("/admin/storage/" + job.result["file"]).status_code == 404

    history = c.get("/admin/_tw/exports").text
    assert "Export history" in history and url in history and "Ready" in history
    assert "No exports yet" in client(app, "bob@x.com").get("/admin/_tw/exports").text


def test_direct_export_is_kept_in_history(env):
    app, Session, _ = env
    c = client(app)
    link = c.post(ACTION, table("export", format="csv", columns=["name", "status"], state="")).headers["HX-Redirect"]
    assert c.get(link).status_code == 200
    with Session() as db:
        job = db.scalars(select(Job)).one()
    assert job.status == "done" and job.processed == 5 and job.payload["rerun"].startswith("/admin/_tw/export?")
    history = c.get("/admin/_tw/exports").text
    assert "Download again" in history


def test_bulk_export_in_background(env):
    app, Session, panel = env
    c = client(app)
    r = c.post(ACTION, bulk("export_selected", ["2", "4"]))
    assert "Export started" in r.headers["HX-Trigger"]
    panel.jobs.wait()
    with Session() as db:
        job = db.scalars(select(Job)).one()
    text = c.get(f"/admin/_tw/exports/{job.id}/download").text.lstrip("﻿")
    assert "Item 2" in text and "Item 4" in text and "Item 1" not in text


def test_old_export_files_are_removed(env, tmp_path):
    import datetime as dt

    from tungsten.importexport import prune_exports

    app, Session, panel = env
    c = client(app)
    c.post(ACTION, table("bg_export", format="xlsx", columns=["name"], state=""))
    panel.jobs.wait()
    with Session() as db:
        job = db.scalars(select(Job)).one()
        path = panel.storage.path(job.result["file"])
        assert path.is_file() and job.result["filename"].endswith(".xlsx")
        job.finished_at = dt.datetime.now() - dt.timedelta(days=30)
        db.commit()
        prune_exports(db, panel.storage)
        assert db.get(Job, job.id).status == "expired"
    assert not path.exists()
    assert c.get(f"/admin/_tw/exports/{job.id}/download").status_code == 404


def test_notification_helper_still_works(env):
    # jobs send through the existing database notifications
    _, Session, _ = env
    with Session() as db:
        Notification("Hi").send_to_database("1", db)
        assert db.scalars(select(DatabaseNotification)).one().data["title"] == "Hi"


def test_background_bulk_action_on_async_engine(tmp_path):
    import time

    from sqlalchemy.ext.asyncio import create_async_engine

    calls.clear()
    url = tmp_path / "db.sqlite"
    sync_engine = create_engine(f"sqlite:///{url}")
    Base.metadata.create_all(sync_engine)
    with sessionmaker(sync_engine)() as db:
        db.add(User(name="Ann", email="ann@x.com", password=hash_password("password")))
        db.add_all([Item(name=f"Item {i}") for i in range(1, 6)])
        db.commit()
    panel = Panel(engine=create_async_engine(f"sqlite+aiosqlite:///{url}"), secret_key="s", auth=Auth(User))
    panel.resources([ItemResource])
    panel.create_tables(sync_engine)
    app = FastAPI()
    panel.mount(app)
    with TestClient(app) as tc:
        c = PanelClient(tc)
        assert c.login("ann@x.com").status_code == 303
        c.get("/admin/items")
        r = c.post(ACTION, bulk("later", ["1", "2", "3"]))
        assert "Started in the background" in r.headers["HX-Trigger"]
        Session = sessionmaker(sync_engine)
        for _ in range(100):
            with Session() as db:
                job = db.scalars(select(Job)).first()
                if job is not None and job.status in ("done", "failed"):
                    break
            time.sleep(0.05)
        assert job.status == "done" and job.processed == 3
        assert calls == [["Item 1", "Item 2"], ["Item 3"]]
