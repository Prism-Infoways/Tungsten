"""A tiny shop panel with the MCP plugin, an admin, a staff user with fewer rights, and their tokens."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from tungsten_mcp import McpPlugin, McpToken, hash_token

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.forms import Select, TextInput, Toggle
from tungsten.models import Role, RoleAssignment
from tungsten.tables import TextColumn


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    sku: Mapped[str] = mapped_column(String(40), unique=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    supplier_api_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    category: Mapped[Category | None] = relationship()
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class ProductResource(Resource):
    model = Product
    global_search_attributes = ["sku"]

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required().max_length(100),
            TextInput("sku").required().unique(),
            TextInput("price").numeric().default(0),
            Select("status").options({"draft": "Draft", "live": "Live"}).default("draft").required(),
            Toggle("active").default(True),
            Select("category_id").relationship("category", "name"),
        ])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable(), TextColumn("price")])


class CategoryResource(Resource):
    model = Category

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])


class UserResource(Resource):
    model = User

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required(), TextInput("email").email().required()])


def make_token(db, user_id, can_write=True, raw=None):
    raw = raw or f"tgmcp_test_{user_id}_{can_write}"
    db.add(McpToken(name="test", user_id=str(user_id) if user_id is not None else None, token_hash=hash_token(raw),
                    hint=raw[:12], can_write=can_write))
    db.commit()
    return raw


@pytest.fixture()
def options():
    return {}


@pytest.fixture()
def panel(tmp_path, options):
    engine = create_engine(f"sqlite:///{tmp_path / 'shop.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", auth=Auth(User, rbac=True),
                  app_url="https://shop.example.com", activity_log=True)
    panel.resources([ProductResource, CategoryResource, UserResource])
    panel.plugin(McpPlugin(**options))
    panel.create_tables(engine)
    with factory() as db:
        admin = User(name="Asha Admin", email="admin@example.com", password=hash_password("password"))
        staff = User(name="Sam Staff", email="staff@example.com", password=hash_password("password"))
        db.add_all([admin, staff, Category(name="Shoes")])
        db.flush()
        su = Role(name="Super Admin", permissions=["*"])
        viewer = Role(name="Viewer", permissions=["products.view_any", "products.update"])
        db.add_all([su, viewer])
        db.flush()
        db.add_all([RoleAssignment(role_id=su.id, user_id=str(admin.id)),
                    RoleAssignment(role_id=viewer.id, user_id=str(staff.id))])
        db.add_all([
            Product(name="Red shoe", sku="RS-1", price=Decimal("10.50"), status="live", supplier_api_key="k1"),
            Product(name="Blue shoe", sku="BS-1", price=Decimal(12), status="draft"),
            Product(name="Green hat", sku="GH-1", price=Decimal(5), status="live"),
        ])
        db.commit()
    panel.db = factory  # type: ignore[attr-defined]
    return panel


@pytest.fixture()
def http(panel):
    app = FastAPI()
    panel.mount(app)
    return TestClient(app)


class Mcp:
    """Calls the MCP endpoint like an AI app does."""

    def __init__(self, http, token):
        self.http = http
        self.token = token
        self.next_id = 0

    def rpc(self, method, params=None, token=None):
        self.next_id += 1
        headers = {"Authorization": f"Bearer {token or self.token}"}
        r = self.http.post("/admin/mcp", json={"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                               "params": params or {}}, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    def call(self, name, **args):
        data = self.rpc("tools/call", {"name": name, "arguments": args})
        assert "result" in data, data
        return data["result"]


@pytest.fixture()
def admin_mcp(panel, http):
    with panel.db() as db:
        return Mcp(http, make_token(db, 1))


@pytest.fixture()
def staff_mcp(panel, http):
    with panel.db() as db:
        return Mcp(http, make_token(db, 2))


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


@pytest.fixture()
def admin(http):
    client = PanelClient(http)
    assert client.login().status_code == 303
    client.get("/admin/")
    return client
