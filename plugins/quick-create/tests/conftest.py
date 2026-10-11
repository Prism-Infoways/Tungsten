"""A tiny panel with a few resources and the quick create plugin."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_quick_create import QuickCreatePlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.forms import TextInput
from tungsten.forms.form import ValidationError


class PanelClient:
    """TestClient that sends the CSRF token and HTMX headers, like the browser does."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.token: str | None = None

    def get(self, url: str, htmx: bool = False, **kw):
        headers = {"HX-Request": "true"} if htmx else {}
        r = self.client.get(url, headers=headers, **kw)
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
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    sku: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(200))


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    line: Mapped[str] = mapped_column(String(200))


class AdminsOnly:
    """Only the admin may create; everyone may look."""

    @staticmethod
    def view_any(user):
        return True

    @staticmethod
    def create(user):
        return user is not None and user.email == "admin@example.com"


class ProductResource(Resource):
    model = Product
    icon = "package"
    navigation_group = "Shop"
    policy = AdminsOnly

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required(), TextInput("sku")])

    @classmethod
    def before_create(cls, data):
        if data.get("sku") == "BAD":
            raise ValidationError({"sku": ["This SKU is blocked."]})


class NoteResource(Resource):
    """A modal-only resource: it still has a create form."""

    model = Note
    icon = "sticky-note"
    simple = True

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("text").required()])


class LogResource(Resource):
    """Read-only: no create page, so never in the menu."""

    model = Log
    pages = ("index",)


class HiddenResource(Resource):
    model = Log
    slug = "hidden-logs"
    quick_create = False


@pytest.fixture()
def make_panel(tmp_path):
    def build(**options):
        engine = create_engine(f"sqlite:///{tmp_path / 'qc.db'}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory() as db:
            if db.query(User).count() == 0:
                db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
                db.add(User(name="Ravi Staff", email="ravi@example.com", password=hash_password("password")))
                db.commit()
        panel = Panel(path="/admin", session_factory=factory, secret_key="test", auth=Auth(User))
        panel.resources([ProductResource, NoteResource, LogResource, HiddenResource])
        panel.plugin(QuickCreatePlugin(**options))
        panel.create_tables(engine)
        panel.db = factory  # type: ignore[attr-defined]
        return panel

    return build


@pytest.fixture()
def panel(make_panel):
    return make_panel()


def client_for(panel) -> PanelClient:
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
