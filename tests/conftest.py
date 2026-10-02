"""Shared fixtures: a seeded shop database and a logged-in HTMX-aware client."""

from __future__ import annotations

import os
import re
import warnings

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)

from fastapi.testclient import TestClient  # noqa: E402

from examples.shop import pages as shop_pages  # noqa: E402
from examples.shop.factory import create_app  # noqa: E402
from examples.shop.seed import seed  # noqa: E402


class PanelClient:
    """TestClient wrapper that knows the CSRF token and sends HTMX headers."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.token: str | None = None

    def refresh_token(self, html: str) -> None:
        m = re.search(r'"X-CSRF-Token": "([^"]+)"', html) or re.search(r'name="_token" value="([^"]+)"', html)
        if m:
            self.token = m.group(1)

    def get(self, url: str, htmx: bool = False, **kw):
        headers = kw.pop("headers", {})
        if htmx:
            headers["HX-Request"] = "true"
        r = self.client.get(url, headers=headers, **kw)
        if r.headers.get("content-type", "").startswith("text/html"):
            self.refresh_token(r.text)
        return r

    def post(self, url: str, data=None, htmx: bool = True, trigger: str | None = None, **kw):
        headers = kw.pop("headers", {})
        if htmx:
            headers["HX-Request"] = "true"
        if trigger:
            headers["HX-Trigger-Name"] = trigger
        if self.token:
            headers["X-CSRF-Token"] = self.token
        return self.client.post(url, data=data, headers=headers, **kw)

    def login(self, email: str = "admin@example.com", password: str = "password"):
        self.get("/admin/login")
        return self.client.post("/admin/login", data={"_token": self.token, "email": email, "password": password},
                                follow_redirects=False)


#: ``TUNGSTEN_TEST_ASYNC=1 pytest`` runs the whole suite on an async engine (aiosqlite)
ASYNC_DB = os.environ.get("TUNGSTEN_TEST_ASYNC") == "1"


@pytest.fixture()
def app_and_panel(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'shop.db'}"
    seed(url)
    monkeypatch.setattr(shop_pages, "SETTINGS_FILE", tmp_path / "settings.json")
    mails: list[dict] = []
    app, panel = create_app(url, async_db=ASYNC_DB, storage_dir=str(tmp_path / "storage"),
                            mailer=lambda to, subject, body: mails.append({"to": to, "subject": subject, "body": body}))
    panel.test_mails = mails  # type: ignore[attr-defined]
    return app, panel


@pytest.fixture()
def panel(app_and_panel):
    return app_and_panel[1]


@pytest.fixture()
def client(app_and_panel):
    return PanelClient(TestClient(app_and_panel[0]))


@pytest.fixture()
def admin(client):
    r = client.login()
    assert r.status_code == 303
    client.get("/admin/")
    return client


def db_session(panel):
    return panel.sync_session_factory()
