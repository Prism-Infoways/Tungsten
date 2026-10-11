"""A tiny panel with the environment indicator plugin and one admin user."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_environment_indicator import ENV_VARS, EnvironmentIndicatorPlugin

from tungsten import Auth, Panel, hash_password


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)


class PanelClient:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.token: str | None = None

    def get(self, url: str, **kw):
        r = self.client.get(url, **kw)
        m = re.search(r'"X-CSRF-Token": "([^"]+)"', r.text) or re.search(r'name="_token" value="([^"]+)"', r.text)
        if m:
            self.token = m.group(1)
        return r

    def login(self, email: str = "admin@example.com", password: str = "password"):
        self.get("/admin/login")
        return self.client.post("/admin/login", data={"_token": self.token, "email": email, "password": password},
                                follow_redirects=False)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_VARS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def make_client(tmp_path):
    """``make_client(plugin, debug=False, base_url=...)`` -> logged-in client."""

    def make(plugin: EnvironmentIndicatorPlugin, *, debug: bool = False, base_url: str = "http://testserver",
             login: bool = True, app_url: str | None = None, **panel_kw):
        engine = create_engine(f"sqlite:///{tmp_path / 'env.db'}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory() as db:
            if not db.query(User).count():
                db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
                db.add(User(name="Ravi Staff", email="staff@example.com", password=hash_password("password"),
                            is_admin=False))
                db.commit()
        panel = Panel(path="/admin", session_factory=factory, secret_key="test", auth=Auth(User),
                      app_url=app_url, **panel_kw)
        panel.plugin(plugin)
        app = FastAPI(debug=debug)
        panel.mount(app)
        client = PanelClient(TestClient(app, base_url=base_url))
        client.panel = panel  # type: ignore[attr-defined]
        if login:
            assert client.login().status_code == 303
        return client

    return make
