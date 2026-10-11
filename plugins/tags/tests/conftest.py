"""A panel with the tags plugin next to Leads, Tickets, HR and Finance, plus an app's own resource."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_finance import FinancePlugin
from tungsten_hr import HRPlugin
from tungsten_leads import LeadsPlugin
from tungsten_tags import TagsPlugin
from tungsten_tickets import TicketsPlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.forms import TextInput
from tungsten.tables import TextColumn


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


class Product(Base):
    """An app's own model, tagged with ``attach()``."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class ProductResource(Resource):
    model = Product

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable()])


@pytest.fixture()
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'tags.db'}")


@pytest.fixture()
def panel(engine):
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", app_url="https://crm.example.com",
                  auth=Auth(User, mailer=lambda **kw: None))
    panel.plugin(TagsPlugin())  # first on purpose: it finds the others when the panel boots
    panel.plugin(LeadsPlugin())
    panel.plugin(TicketsPlugin(email_requester=False))
    panel.plugin(HRPlugin())
    panel.plugin(FinancePlugin(state="27"))
    panel.resources([ProductResource])
    panel.create_tables(engine)
    panel.boot()
    panel.get_plugin("tags").attach(ProductResource, type="product")
    panel.db = factory  # type: ignore[attr-defined]
    return panel


@pytest.fixture()
def tags(panel):
    return panel.get_plugin("tags")


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
