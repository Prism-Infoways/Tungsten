"""A tiny panel with users, a Users screen and the impersonate plugin."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_impersonate import ImpersonatePlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.models import Role, RoleAssignment
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
        headers = {"HX-Request": "true", **({"X-CSRF-Token": self.token} if self.token else {}), **kw.pop("headers", {})}
        return self.client.post(url, data=data, headers=headers, **kw)

    def login(self, email: str = "admin@example.com", password: str = "password"):
        self.get("/admin/login")
        r = self.client.post("/admin/login", data={"_token": self.token, "email": email, "password": password},
                             follow_redirects=False)
        self.get("/admin/")
        return r

    def action(self, name: str, record, host: str = "resource:users", scope: str = "row", headers=None, **data):
        return self.post("/admin/_tw/action", {"_tw_host": host, "_tw_scope": scope, "_tw_name": name,
                                               "_tw_record": str(record), **data}, headers=headers or {})

    def login_as(self, user_id, headers=None, **data):
        return self.action("impersonate", user_id, headers=headers, **data)

    def leave(self):
        return self.client.post("/admin/impersonate/leave", data={"_token": self.token}, follow_redirects=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserResource(Resource):
    model = User
    slug = "users"
    record_title_attribute = "name"

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name"), TextColumn("email")])


USERS = [("Asha Admin", "admin@example.com"), ("Ravi Agent", "ravi@example.com"),
         ("Meena Customer", "meena@example.com"), ("Old Staff", "old@example.com")]


def build(tmp_path, rbac: bool = False, plugins=(), auth_kw=None, **plugin_kw):
    engine = create_engine(f"sqlite:///{tmp_path / 'imp.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        for name, email in USERS:
            db.add(User(name=name, email=email, password=hash_password("password"), is_active=email != "old@example.com"))
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test",
                  auth=Auth(User, active_field="is_active", **(auth_kw or {})))
    panel.resources([UserResource])
    if rbac:
        panel.rbac()
    for p in plugins:
        panel.plugin(p)
    plugin = ImpersonatePlugin(**plugin_kw)
    panel.plugin(plugin)
    panel.create_tables(engine)
    panel.db = factory  # type: ignore[attr-defined]
    panel.imp = plugin  # type: ignore[attr-defined]
    return panel


def client_for(panel) -> PanelClient:
    app = FastAPI()
    panel.mount(app)
    return PanelClient(TestClient(app))


def give_role(panel, email: str, name: str, permissions: list[str]) -> None:
    with panel.db() as db:
        role = db.query(Role).filter(Role.name == name).first()
        if role is None:
            role = Role(name=name, permissions=permissions)
            db.add(role)
            db.flush()
        user = db.query(User).filter(User.email == email).one()
        db.add(RoleAssignment(role_id=role.id, user_id=str(user.id)))
        db.commit()


@pytest.fixture()
def panel(tmp_path):
    return build(tmp_path)


@pytest.fixture()
def client(panel):
    return client_for(panel)


@pytest.fixture()
def admin(client):
    assert client.login().status_code == 303
    return client
