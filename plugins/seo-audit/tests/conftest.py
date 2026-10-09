"""A tiny panel with the SEO audit plugin, one admin user, and a fake website."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten import Auth, Panel, hash_password

from tungsten_seo_audit import SeoAuditPlugin


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


GOOD_HEAD = """
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="https://site.test{path}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:image" content="https://site.test/og.png">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{{"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": []}}</script>
"""
WORDS = " ".join(["Tungsten makes admin panels for FastAPI apps quickly and simply."] * 40)


def page(path: str, title: str, description: str, body: str) -> str:
    head = GOOD_HEAD.format(title=title, description=description, path=path)
    return f"<!doctype html><html lang=\"en\"><head>{head}</head><body>{body}</body></html>"


class FakeSite:
    """``{url: (status, headers, body)}``; anything else is a 404. Records each request."""

    def __init__(self) -> None:
        self.pages: dict[str, tuple[int, dict, str]] = {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, headers: dict):
        self.calls.append((method, url))
        status, hdrs, body = self.pages.get(url, (404, {"content-type": "text/html"}, "<h1>Not found</h1>"))
        return status, {"content-type": "text/html; charset=utf-8", **hdrs}, body.encode()

    def add(self, url: str, body: str, status: int = 200, **headers: str) -> None:
        self.pages[url] = (status, headers, body)

    def redirect(self, url: str, to: str, status: int = 301) -> None:
        self.pages[url] = (status, {"location": to}, "")


@pytest.fixture()
def site():
    s = FakeSite()
    s.add("https://site.test/robots.txt", "User-agent: *\nDisallow: /private/\nSitemap: https://site.test/sitemap.xml\n",
          **{"content-type": "text/plain"})
    s.add("https://site.test/sitemap.xml", '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/'
          'sitemap/0.9"><url><loc>https://site.test/</loc></url><url><loc>https://site.test/about</loc></url>'
          '</urlset>', **{"content-type": "application/xml"})
    s.add("https://site.test/llms.txt", "# Site", **{"content-type": "text/plain"})
    s.redirect("http://site.test/", "https://site.test/")
    s.add("https://site.test/", page("/", "Tungsten admin panels for FastAPI apps",
                                     "Build a beautiful admin panel for your FastAPI app in minutes, with forms, tables "
                                     "and charts.",
                                     f"<h1>Home</h1><p>{WORDS}</p><a href=\"/about\">About</a>"
                                     "<a href=\"/old\">Old</a><a href=\"/gone\">Gone</a>"
                                     "<a href=\"https://other.test/x\">Other</a>"
                                     "<a href=\"http://127.0.0.1:8000/admin\">Local</a><a href=\"/private/x\">Private</a><a href=\"mailto:a@b.c\">Mail</a>"
                                     "<img src=\"/a.png\" alt=\"A\" width=\"1\" height=\"1\">"))
    s.add("https://site.test/about", page("/about", "About", "Short",
                                          "<h1>About</h1><h1>Again</h1><h3>Skip</h3><p>Few words.</p>"
                                          "<img src=\"/b.png\"><img src=\"http://cdn.test/c.png\" alt=\"\">"))
    s.redirect("https://site.test/old", "https://site.test/about")
    s.add("https://other.test/x", "ok")
    return s


@pytest.fixture()
def panel(tmp_path, site):
    engine = create_engine(f"sqlite:///{tmp_path / 'seo.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.commit()
    panel = Panel(path="/admin", session_factory=factory, secret_key="test", auth=Auth(User),
                  app_url="https://site.test")
    panel.plugin(SeoAuditPlugin(background=False, transport=site))
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
