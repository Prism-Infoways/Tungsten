"""A small panel with the security audit plugin, an admin, a staff user and a fake network."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_security_audit import Net, SecurityAuditPlugin
from tungsten_security_audit.net import Page

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.forms import TextInput
from tungsten.models import Role, RoleAssignment

SECURE_HEADERS = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "content-security-policy": "frame-ancestors 'self'; object-src 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "server": "LiteSpeed",
}


class FakeNet(Net):
    """Answers like a well set up site; tests change ``headers``, ``cookies`` and friends."""

    def __init__(self):
        self.headers = dict(SECURE_HEADERS)
        self.cookies = ["tungsten_admin=abc; path=/; Max-Age=1209600; httponly; samesite=lax; secure"]
        self.redirect = "https://shop.example.com/admin/login"
        self.days = 80.0
        self.vulns = {}
        self.calls = []
        self.down = False

    def get(self, url, headers=None):
        self.calls.append(url)
        if self.down:
            raise OSError("connection refused")
        if url.startswith("http://"):
            return Page(301, {"location": self.redirect}, [], url)
        return Page(200, dict(self.headers), list(self.cookies), url)

    def cert_days_left(self, url):
        return self.days

    def osv(self, packages):
        self.calls.append("osv")
        return {p: ids for p, ids in self.vulns.items() if p in packages}


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


# a fast hash keeps the weak-password check quick in tests
FAST = "pbkdf2_sha256$1000$"


def fast_hash(password):
    return hash_password(password, iterations=1000)


@pytest.fixture()
def options():
    return {}


@pytest.fixture()
def panel_options():
    return {}


@pytest.fixture()
def net():
    return FakeNet()


@pytest.fixture()
def panel(tmp_path, options, panel_options, net):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = {"secret_key": "x" * 40, "app_url": "https://shop.example.com", "https_only_cookies": True,
                "activity_log": True, **panel_options}
    auth = settings.pop("auth", None) or Auth(User, rbac=True, two_factor=True, active_field="is_active")
    panel = Panel(path="/admin", session_factory=factory, auth=auth, **settings)
    panel.resources([UserResource])
    panel.plugin(SecurityAuditPlugin(net=net, **options))
    panel.create_tables(engine)
    with factory() as db:
        admin = User(name="Asha Admin", email="admin@example.com", password=fast_hash("Long-Unique-Passw0rd!"))
        staff = User(name="Sam Staff", email="staff@example.com", password=fast_hash("password"))
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
    return panel


@pytest.fixture()
def http(panel):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    panel.mount(app)
    return TestClient(app, base_url="https://shop.example.com")


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

    def login(self, email: str = "admin@example.com", password: str = "Long-Unique-Passw0rd!"):
        self.get("/admin/login")
        return self.client.post("/admin/login", data={"_token": self.token, "email": email, "password": password},
                                follow_redirects=False)


@pytest.fixture()
def client(http):
    return PanelClient(http)


@pytest.fixture()
def admin(http):
    client = PanelClient(http)
    assert client.login().status_code == 303
    client.get("/admin/")
    return client


@pytest.fixture()
def make_client():
    return PanelClient


@pytest.fixture()
def user_model():
    return User
