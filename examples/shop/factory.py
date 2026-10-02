"""Builds the shop demo panel and app (used by app.py and the tests)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from markupsafe import Markup

from tungsten import Auth, LocalStorage, NavigationItem, Panel, Plugin

from .models import Base, User, make_engine
from .pages import Reports, SystemSettings
from .resources import ALL_RESOURCES
from .widgets import DASHBOARD_WIDGETS, ShopDashboard


class DocsPlugin(Plugin):
    """A tiny plugin: adds a navigation link and a note under the login form."""

    id = "docs"

    def register(self, panel):
        panel.navigation_items([
            NavigationItem("Documentation", "https://github.com/prism-infoways/tungsten", icon="book-open",
                           group="Settings", sort=100, new_tab=True),
        ])

    def boot(self, panel):
        panel.render_hook("auth.login.form.after", lambda: Markup(
            '<p class="text-center text-xs text-gray-400">Demo login: admin@example.com / password</p>'))


def create_panel(session_factory=None, storage_dir: str = "storage/tungsten", mailer=None, engine=None) -> Panel:
    panel = Panel(
        path="/admin",
        session_factory=session_factory,
        engine=engine,
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        auth=Auth(User, avatar_field="avatar", active_field="is_active",
                  can_access=lambda user: user.is_admin, mailer=mailer,
                  registration=True, two_factor=True, email_verification=True),
        dashboard=ShopDashboard,
        spa=True,
        brand_name="Tungsten",
        colors={"primary": "orange"},
        navigation_groups=["Shop", "Catalog", "Marketing", "Settings"],
        storage=LocalStorage(storage_dir),
        activity_log=True,
        locales=["en", "hi"],  # English and Hindi; users pick from the user menu or the login page
        lang_dirs=[Path(__file__).with_name("lang")],
    )
    panel.resources(ALL_RESOURCES).pages([Reports, SystemSettings]).widgets(DASHBOARD_WIDGETS)
    panel.rbac()
    panel.plugin(DocsPlugin())
    return panel


def create_app(database_url: str = "sqlite:///shop.db", async_db: bool = False,
               **panel_options) -> tuple[FastAPI, Panel]:
    """Build the demo app. ``async_db=True`` (or an async URL such as
    ``sqlite+aiosqlite:///shop.db``) runs the panel on an async engine."""
    sync_url = database_url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")
    engine, session_factory = make_engine(sync_url)
    Base.metadata.create_all(engine)
    if async_db or database_url != sync_url:
        from sqlalchemy.ext.asyncio import create_async_engine

        async_url = database_url if database_url != sync_url else database_url.replace("sqlite://", "sqlite+aiosqlite://")
        panel = create_panel(engine=create_async_engine(async_url), **panel_options)
    else:
        panel = create_panel(session_factory, **panel_options)
    panel.create_tables(engine)
    panel.sync_session_factory = session_factory  # type: ignore[attr-defined]  # for the seed script and tests

    app = FastAPI(title="Tungsten shop demo")
    panel.mount(app)

    @app.get("/")
    def root():
        return RedirectResponse("/admin/")

    return app, panel
