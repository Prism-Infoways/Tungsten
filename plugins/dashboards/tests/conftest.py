"""A tiny panel with the dashboards plugin, some widgets, an admin and a staff member who log in."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_dashboards import DashboardsPlugin

from tungsten import Auth, ChartWidget, Panel, Resource, Stat, StatsOverviewWidget, hash_password


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
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class UserResource(Resource):
    model = User
    icon = "users"


class SalesStats(StatsOverviewWidget):
    lazy = False

    @classmethod
    def stats(cls, ctx):
        return [Stat("Sales today", "12")]


class OrdersChart(ChartWidget):
    heading = "Orders per day"

    @classmethod
    def data(cls, ctx, filter=None):
        return {"labels": ["Mon", "Tue"], "datasets": [{"label": "Orders", "data": [3, 5]}]}


class SecretStats(StatsOverviewWidget):
    """Only admins see this one."""

    lazy = False

    @classmethod
    def can_view(cls, ctx):
        return bool(ctx.user is not None and ctx.user.is_admin)

    @classmethod
    def stats(cls, ctx):
        return [Stat("Profit", "99")]


class BrokenWidget(StatsOverviewWidget):
    """Breaks every time it is drawn."""

    @classmethod
    def stats(cls, ctx):
        raise RuntimeError("database down")


class OnlyOnDashboards(StatsOverviewWidget):
    lazy = False
    dashboard_label = "Extra numbers"

    @classmethod
    def stats(cls, ctx):
        return [Stat("Extra", "7")]


def gate(user, permission):
    """Admins may do anything; staff may build their own dashboards but not share them."""
    if permission.startswith("dashboards."):
        return bool(user and user.is_admin) or permission == "dashboards.create"
    return None


@pytest.fixture()
def plugin():
    return DashboardsPlugin()


@pytest.fixture()
def panel(tmp_path, plugin):
    engine = create_engine(f"sqlite:///{tmp_path / 'dash.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password"), is_admin=True))
        db.add(User(name="Ravi Staff", email="ravi@example.com", password=hash_password("password")))
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", auth=Auth(User, gate=gate))
    panel.resources([UserResource])
    panel.widgets([SalesStats, OrdersChart, SecretStats, BrokenWidget])
    plugin.add_widgets([OnlyOnDashboards])
    plugin.add_template("Sales", [SalesStats, "orders-chart", "no-such-widget"])
    panel.plugin(plugin)
    panel.create_tables(engine)
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


@pytest.fixture()
def ravi(panel):
    app = FastAPI()
    panel.mount(app)
    c = PanelClient(TestClient(app))
    assert c.login("ravi@example.com").status_code == 303
    c.get("/admin/")
    return c
