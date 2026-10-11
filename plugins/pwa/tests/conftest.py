"""A tiny panel with the PWA plugin."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_pwa import PWAPlugin

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


@pytest.fixture()
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pwa.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.commit()
    factory.engine = engine  # type: ignore[attr-defined]
    return factory


@pytest.fixture()
def make(factory):
    """make(plugin=PWAPlugin(...), path="/admin", **panel_options) -> (panel, client)"""

    def build(plugin: PWAPlugin | None = None, path: str = "/admin", **options):
        options.setdefault("brand_name", "Acme Admin")
        panel = Panel(path=path, session_factory=factory, secret_key="test", auth=Auth(User), **options)
        panel.plugin(plugin or PWAPlugin())
        panel.create_tables(factory.engine)
        app = FastAPI()
        panel.mount(app)
        return panel, TestClient(app)

    return build


def login(client: TestClient, path: str = "/admin") -> None:
    page = client.get(f"{path}/login")
    token = re.search(r'name="_token" value="([^"]+)"', page.text).group(1)
    r = client.post(f"{path}/login", data={"_token": token, "email": "admin@example.com", "password": "password"},
                    follow_redirects=False)
    assert r.status_code == 303
