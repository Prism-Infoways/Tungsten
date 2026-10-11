"""A tiny panel with a task board, plus the leads, tickets and HR plugins and their boards."""

from __future__ import annotations

import datetime as dt
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_hr import Employee, HRPlugin, LeaveType
from tungsten_kanban import Board, KanbanPlugin
from tungsten_leads import LeadsPlugin
from tungsten_quick_create import QuickCreatePlugin
from tungsten_tickets import TicketsPlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.forms import Select, TextInput


class PanelClient:
    """TestClient that sends the CSRF token and HTMX headers, like the browser does."""

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
        headers = {"HX-Request": "true", **({"X-CSRF-Token": self.token} if self.token else {})}
        return self.client.post(url, data=data, headers=headers, **kw)

    def move(self, board: str, record, to, frm=None, order=None, **extra):
        data = {"record": str(record), "to": to, **extra}
        if frm is not None:
            data["from"] = frm
        if order is not None:
            data["order"] = [str(k) for k in order]
        return self.client.post(f"/admin/_kanban/{board}/move", data=data,
                                headers={"X-CSRF-Token": self.token or ""})

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
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), default="todo", nullable=True)
    sort: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(20), nullable=True)


class TaskPolicy:
    @staticmethod
    def update(user, record):
        return record is None or record.title != "Locked task"

    @staticmethod
    def view_any(user, record):
        return True

    @staticmethod
    def view(user, record):
        return True

    @staticmethod
    def create(user, record):
        return True


class TaskResource(Resource):
    model = Task
    icon = "check-square"
    navigation_group = "Work"
    policy = TaskPolicy

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("title").required(), Select("status").options({"todo": "To do"})])


STATUSES = {"todo": ("To do", "gray"), "doing": ("Doing", "primary"), "done": ("Done", "success")}

#: moves the listener saw, as (title, old, new)
moves: list[tuple] = []


def make_board(**kw):
    options = {"column": "status", "columns": STATUSES, "description": "notes", "order_column": "sort",
               "search": ["title", "notes"], "assignee": "owner", "wip_limits": {"doing": 1},
               "transitions": {"done": ["doing"]}, "fields": {"Owner": "owner"}}
    options.update(kw)
    return Board(TaskResource, **options)


@pytest.fixture()
def panel(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'kanban.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.add(User(name="Ravi Staff", email="ravi@example.com", password=hash_password("password")))
        for i, (title, status, owner) in enumerate([
            ("Write brief", "todo", "1"), ("Design page", "todo", None), ("Build form", "doing", "2"),
            ("Ship it", "done", None), ("Locked task", "todo", None), ("Odd one", "archived", None),
        ]):
            db.add(Task(title=title, status=status, sort=i + 1, owner=owner, notes=f"notes {i}"))
        db.commit()
    moves.clear()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", app_url="https://app.example.com",
                  auth=Auth(User, mailer=lambda **kw: None))
    panel.resources([TaskResource])
    kanban = KanbanPlugin(boards=[make_board()])
    kanban.on_card_moved("test", lambda record, old, new: moves.append((getattr(record, "title", None), old, new)))
    kanban.add_card_badges("test", lambda record: ("Mine", "info") if record.__class__ is Task and record.owner == "1"
                           else None)
    panel.plugin(kanban)
    # added after kanban on purpose: their boards are made when the panel starts
    panel.plugin(LeadsPlugin())
    panel.plugin(TicketsPlugin(email_requester=False))
    panel.plugin(HRPlugin())
    panel.plugin(QuickCreatePlugin(exclude=["leave-requests"]))
    panel.create_tables(engine)
    with factory() as db:
        db.info["tungsten_panel"] = panel
        db.add(Employee(code="EMP-1", first_name="Asha", last_name="Admin", email="admin@example.com", user_id="1",
                        joined_on=dt.date(2024, 1, 1)))
        db.add(Employee(code="EMP-2", first_name="Ravi", last_name="Staff", email="ravi@example.com", user_id="2",
                        joined_on=dt.date(2024, 1, 1)))
        db.add(LeaveType(name="Casual", days_per_year=1, sort=1))
        db.commit()
    panel.db = factory  # type: ignore[attr-defined]
    return panel


@pytest.fixture()
def client(panel):
    app = FastAPI()
    panel.mount(app)
    return PanelClient(TestClient(app))


@pytest.fixture()
def admin(client):
    assert client.login().status_code == 303
    client.get("/admin/")
    return client
