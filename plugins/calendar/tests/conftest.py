"""A tiny panel with the calendar plugin and two users. ``linked`` adds HR, Leads, Tickets, Finance and Blog."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_calendar import CalendarPlugin

from tungsten import Auth, Panel, hash_password


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


def make_panel(tmp_path, plugins=(), **options):
    engine = create_engine(f"sqlite:///{tmp_path / 'calendar.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.add(User(name="Ravi Staff", email="ravi@example.com", password=hash_password("password")))
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", app_url="https://office.example.com",
                  auth=Auth(User))
    for plugin in plugins:
        panel.plugin(plugin)
    panel.plugin(CalendarPlugin(**{"timezone": "Asia/Kolkata", **options}))
    panel.create_tables(engine)
    panel.db = factory  # type: ignore[attr-defined]
    return panel


@pytest.fixture()
def panel(tmp_path):
    return make_panel(tmp_path)


@pytest.fixture()
def linked(tmp_path):
    from tungsten_blog import BlogPlugin
    from tungsten_finance import FinancePlugin
    from tungsten_hr import HRPlugin
    from tungsten_leads import LeadsPlugin
    from tungsten_tickets import TicketsPlugin

    return make_panel(tmp_path, [HRPlugin(), LeadsPlugin(), TicketsPlugin(), FinancePlugin(), BlogPlugin()])


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
    client.get("/admin/")
    return client
