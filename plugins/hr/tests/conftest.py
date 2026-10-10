"""A tiny panel with the HR plugin, a manager and an employee who log in."""

from __future__ import annotations

import datetime as dt
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_hr import Department, Employee, HRPlugin, LeaveType

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


#: emails the panel sent, as (to, subject, body)
mails: list[tuple[str, str, str]] = []


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
def panel(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'hr.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.add(User(name="Ravi Staff", email="ravi@example.com", password=hash_password("password")))
        db.commit()
    mails.clear()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", app_url="https://hr.example.com",
                  auth=Auth(User, mailer=lambda to, subject, body: mails.append((to, subject, body))))
    panel.plugin(HRPlugin())
    panel.create_tables(engine)
    with factory() as db:
        db.info["tungsten_panel"] = panel
        sales = Department(name="Sales", color="info")
        db.add(sales)
        boss = Employee(code="EMP-0001", first_name="Asha", last_name="Admin", email="admin@example.com",
                        user_id="1", department=sales, joined_on=dt.date(2024, 1, 1))
        db.add(boss)
        db.flush()
        sales.head_id = boss.id
        db.add(Employee(code="EMP-0002", first_name="Ravi", last_name="Staff", email="ravi@example.com",
                        user_id="2", department=sales, joined_on=dt.date(2025, 4, 1)))
        db.add(LeaveType(name="Casual", days_per_year=2, sort=1))
        db.add(LeaveType(name="Unpaid", days_per_year=None, is_paid=False, sort=2))
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


@pytest.fixture()
def ravi(client):
    assert client.login("ravi@example.com").status_code == 303
    client.get("/admin/")
    return client
