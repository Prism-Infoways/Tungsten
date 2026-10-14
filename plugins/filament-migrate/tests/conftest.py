"""Convert the sample Filament shops in ``fixtures/`` and run the result."""

from __future__ import annotations

import importlib
import itertools
import re
import shutil
import sys
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tungsten_filament import build, write

FIXTURES = Path(__file__).with_name("fixtures")
_counter = itertools.count()


def laravel_hash(password: str) -> str:
    return "$2y$" + bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode()[4:]


class Converted:
    def __init__(self, root: Path, out: Path, result) -> None:
        self.root = root
        self.out = out
        self.result = result

    def file(self, rel: str) -> str:
        return (self.out / rel).read_text()

    def import_(self, module: str = ""):
        name = self.out.name + (f".{module}" if module else "")
        return importlib.import_module(name)


def convert(tmp_path: Path, fixture: str, **kw) -> Converted:
    root = tmp_path / "laravel"
    shutil.copytree(FIXTURES / fixture, root)
    out = tmp_path / f"tw_admin_{next(_counter)}"
    result = build(root, out, **kw)
    write(result, out)
    sys.path.insert(0, str(tmp_path))
    return Converted(root, out, result)


@pytest.fixture()
def shop3(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LARAVEL_PATH", raising=False)
    conv = convert(tmp_path, "shop3")
    yield conv
    sys.path.remove(str(tmp_path))


def seed(conv: Converted) -> None:
    """Make the Laravel database the way `php artisan migrate` and a few clicks would."""
    models = conv.import_("models")
    engine = create_engine(f"sqlite:///{conv.root / 'database' / 'database.sqlite'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(models.User(name="Ann", email="ann@acme.test", password=laravel_hash("secret123")))
        customer = models.Customer(name="Bob Buyer", email="bob@example.com")
        category = models.Category(name="Shoes", slug="shoes")
        db.add_all([customer, category])
        db.flush()
        product = models.Product(name="Red shoe", slug="red-shoe", price=10, quantity=3, category=category)
        tag = models.Tag(name="Hot")
        product.tags.append(tag)
        db.add_all([product, tag])
        order = models.Order(customer=customer, number="OR-1001", total=10, status="processing")
        db.add(order)
        db.flush()
        db.add(models.OrderItem(order=order, product=product, qty=1, unit_price=10))
        db.commit()
    engine.dispose()


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

    def login(self, email: str, password: str):
        self.get("/admin/login")
        return self.client.post("/admin/login", data={"_token": self.token, "email": email, "password": password},
                                follow_redirects=False)


@pytest.fixture()
def admin(shop3):
    seed(shop3)
    app = shop3.import_("app")
    client = PanelClient(TestClient(app.app))
    assert client.login("ann@acme.test", "secret123").status_code == 303
    client.get("/admin/")
    client.app_module = app
    return client
