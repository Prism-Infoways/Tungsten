"""A tiny panel with the leads and WhatsApp plugins, one admin user, and fake WhatsApp servers."""

from __future__ import annotations

import json
import re
import urllib.parse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten import Auth, Panel, hash_password

from tungsten_leads import LeadsPlugin
from tungsten_whatsapp import WhatsAppPlugin


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


class FakeHTTP:
    """Answers calls from a dict of ``"METHOD url-path": response``; records every call with its JSON body."""

    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.calls: list[tuple[str, str, dict, dict]] = []

    def __call__(self, method: str, url: str, headers: dict, body: bytes | None):
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        if parsed.netloc == "graph.facebook.com":
            path = path.split("/", 2)[2]
        payload = json.loads(body) if body else {}
        self.calls.append((method, path, payload, headers))
        answer = self.routes.get(f"{method} {path}")
        if answer is None:
            return 404, json.dumps({"error": {"message": f"No fake for {method} {path}"}})
        if callable(answer):
            answer = answer(payload)
        if isinstance(answer, tuple):
            return answer[0], json.dumps(answer[1])
        return 200, json.dumps(answer)


@pytest.fixture()
def http():
    return FakeHTTP()


@pytest.fixture()
def panel(tmp_path, http):
    engine = create_engine(f"sqlite:///{tmp_path / 'leads.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", auth=Auth(User),
                  app_url="https://crm.example.com")
    panel.plugin(LeadsPlugin())
    panel.plugin(WhatsAppPlugin(transport=http))
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
