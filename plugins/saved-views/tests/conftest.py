"""A tiny panel with a Tasks list (filters, tabs, hideable columns), the saved views plugin and two users."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_saved_views import SavedViewsPlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.forms import TextInput
from tungsten.tables import ListTab, SelectFilter, TextColumn


class PanelClient:
    """TestClient that sends the CSRF token, like the browser does."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.token: str | None = None

    def get(self, url: str, **kw):
        r = self.client.get(url, **kw)
        m = re.search(r'"X-CSRF-Token": "([^"]+)"', r.text) or re.search(r'name="_token" value="([^"]+)"', r.text)
        if m:
            self.token = m.group(1)
        return r

    def post(self, url: str, data=None, **kw):
        kw.setdefault("follow_redirects", False)
        return self.client.post(url, data={"_token": self.token, **(data or {})}, **kw)

    def login(self, email: str = "admin@example.com", password: str = "password"):
        self.get("/admin/login")
        return self.client.post("/admin/login", data={"_token": self.token, "email": email, "password": password},
                                follow_redirects=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="open")
    owner: Mapped[str] = mapped_column(String(20), default="")
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskResource(Resource):
    model = Task
    slug = "tasks"
    soft_delete_column = None

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("title").required()])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("title").searchable().sortable(),
                TextColumn("status").sortable(),
                TextColumn("owner").toggleable(),
            ])
            .filters([
                SelectFilter("status").options({"open": "Open", "pending": "Pending", "closed": "Closed"}),
                SelectFilter("owner").options({"1": "Admin", "2": "Ravi"}),
            ])
            .tabs([ListTab("all"), ListTab("done").query(lambda query, model: query.where(model.is_done.is_(True)))])
        )


def make_panel(tmp_path, plugin=None, **panel_kw):
    engine = create_engine(f"sqlite:///{tmp_path / 'views.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.add(User(name="Ravi Agent", email="ravi@example.com", password=hash_password("password")))
        db.add_all([
            Task(title="Alpha open", status="open", owner="1"),
            Task(title="Beta pending", status="pending", owner="2"),
            Task(title="Gamma closed", status="closed", owner="1", is_done=True),
        ])
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", auth=Auth(User), **panel_kw)
    panel.resources([TaskResource])
    panel.plugin(plugin or SavedViewsPlugin())
    panel.create_tables(engine)
    panel.db = factory  # type: ignore[attr-defined]
    return panel


@pytest.fixture()
def panel(tmp_path):
    return make_panel(tmp_path)


def client_for(panel):
    app = FastAPI()
    panel.mount(app)
    return PanelClient(TestClient(app))


@pytest.fixture()
def client(panel):
    return client_for(panel)


@pytest.fixture()
def admin(client):
    assert client.login().status_code == 303
    client.get("/admin/tasks")
    return client
