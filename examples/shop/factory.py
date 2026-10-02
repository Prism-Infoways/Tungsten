"""Builds the shop demo panel and app (used by app.py and the tests)."""

from __future__ import annotations

import os

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


def create_panel(session_factory, storage_dir: str = "storage/tungsten", mailer=None) -> Panel:
    panel = Panel(
        path="/admin",
        session_factory=session_factory,
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        auth=Auth(User, avatar_field="avatar", active_field="is_active",
                  can_access=lambda user: user.is_admin, mailer=mailer,
                  registration=True, two_factor=True),
        dashboard=ShopDashboard,
        spa=True,
        brand_name="Tungsten",
        colors={"primary": "orange"},
        navigation_groups=["Shop", "Catalog", "Marketing", "Settings"],
        storage=LocalStorage(storage_dir),
        activity_log=True,
    )
    panel.resources(ALL_RESOURCES).pages([Reports, SystemSettings]).widgets(DASHBOARD_WIDGETS)
    panel.rbac()
    panel.plugin(DocsPlugin())
    return panel


def create_app(database_url: str = "sqlite:///shop.db", **panel_options) -> tuple[FastAPI, Panel]:
    engine, session_factory = make_engine(database_url)
    Base.metadata.create_all(engine)
    panel = create_panel(session_factory, **panel_options)
    panel.create_tables(engine)

    app = FastAPI(title="Tungsten shop demo")
    panel.mount(app)

    @app.get("/")
    def root():
        return RedirectResponse("/admin/")

    return app, panel
