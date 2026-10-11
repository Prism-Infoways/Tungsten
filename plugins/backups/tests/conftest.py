"""A small panel with the backups plugin, an admin with full access and a staff user."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_backups import BackupsPlugin

from tungsten import Auth, LocalStorage, Panel, Resource, hash_password
from tungsten.forms import TextInput
from tungsten.models import Role, RoleAssignment


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

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required(), TextInput("email").email().required()])


@pytest.fixture()
def options():
    return {}


@pytest.fixture()
def panel_options():
    return {}


@pytest.fixture()
def plugins():
    return []


@pytest.fixture()
def panel(tmp_path, options, panel_options, plugins):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)  # expire_on_commit=True, like most apps
    settings = {"secret_key": "x" * 40, "activity_log": True, "database_notifications": True,
                "storage": LocalStorage(tmp_path / "storage" / "tungsten"), **panel_options}
    auth = settings.pop("auth", None) or Auth(User, rbac=True, active_field="is_active")
    panel = Panel(path="/admin", session_factory=factory, auth=auth, **settings)
    panel.resources([UserResource])
    for plugin in plugins:
        panel.plugin(plugin)
    panel.plugin(BackupsPlugin(**{"folder": tmp_path / "storage" / "backups", "background": False,
                                  "min_free_mb": 0, **options}))
    panel.create_tables(engine)
    with factory() as db:
        admin = User(name="Asha Admin", email="admin@example.com", password=hash_password("secret", iterations=1000))
        staff = User(name="Sam Staff", email="staff@example.com", password=hash_password("secret", iterations=1000))
        db.add_all([admin, staff])
        db.flush()
        su = Role(name="Super Admin", permissions=["*"])
        viewer = Role(name="Viewer", permissions=["users.view_any"])
        db.add_all([su, viewer])
        db.flush()
        db.add_all([RoleAssignment(role_id=su.id, user_id=str(admin.id)),
                    RoleAssignment(role_id=viewer.id, user_id=str(staff.id))])
        db.commit()
    panel.db = factory  # type: ignore[attr-defined]
    panel.engine_ = engine  # type: ignore[attr-defined]
    return panel


@pytest.fixture()
def plugin(panel):
    return panel.get_plugin("backups")


@pytest.fixture()
def http(panel):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    panel.mount(app)
    return TestClient(app)


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

    def login(self, email: str = "admin@example.com", password: str = "secret"):
        self.get("/admin/login")
        return self.client.post("/admin/login", data={"_token": self.token, "email": email, "password": password},
                                follow_redirects=False)


@pytest.fixture()
def admin(http):
    client = PanelClient(http)
    assert client.login().status_code == 303
    client.get("/admin/")
    return client


@pytest.fixture()
def staff(panel):
    app = FastAPI()
    panel.mount(app)
    client = PanelClient(TestClient(app))
    assert client.login("staff@example.com").status_code == 303
    client.get("/admin/")
    return client


@pytest.fixture()
def user_model():
    return User
