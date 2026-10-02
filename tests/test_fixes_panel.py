"""Fixes for the panel shell: custom routes, navigation, branding, theme, search, actions, widgets,
page filters, the notification bell and toasts."""

from __future__ import annotations

import html as html_lib
import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from examples.shop.models import Tag, User
from examples.shop.resources import ProductResource
from examples.shop.widgets import UserStats
from tungsten import NavigationGroup, NavigationItem, Notification, Page, Panel
from tungsten.actions import Action
from tungsten.forms import Select
from tungsten.support.icons import icon
from tungsten.widgets import Stat, StatsOverviewWidget

from .conftest import db_session


def group_chunks(page: str) -> dict[str, str]:
    """Sidebar groups by label: the markup from each group's ``x-data`` to the next one."""
    out = {}
    for chunk in page.split('<div x-data="{ open: ')[1:]:
        m = re.search(r'gap-2">(?:<svg.*?</svg>)?([^<]+)</span>', chunk)
        if m:
            out[m.group(1)] = chunk
    return out


# ---------------------------------------------------------------------- 1. custom routes


def test_custom_routes_with_short_paths_win_over_page_routes():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    panel = Panel(engine=engine, secret_key="x")

    @panel.routes
    def extra(router, panel):
        @router.get("/hello")
        def hello():
            return {"hello": "world"}

        @router.get("/api/stats")
        def stats():
            return {"orders": 3}

    app = FastAPI()
    panel.mount(app)
    c = TestClient(app)
    assert c.get("/admin/hello").json() == {"hello": "world"}
    assert c.get("/admin/api/stats").json() == {"orders": 3}
    assert c.get("/admin/nope").status_code == 404  # the page routes still answer other paths


# ---------------------------------------------------------------------- 2. collapsible / collapsed groups


def test_navigation_group_collapsed_and_not_collapsible(admin, panel):
    panel._nav_groups = [
        NavigationGroup("Shop"),
        NavigationGroup("Catalog", collapsed=True),
        NavigationGroup("Marketing", collapsed=True),
        NavigationGroup("Settings", collapsible=False, collapsed=True),
    ]
    groups = group_chunks(admin.get("/admin/").text)
    assert groups["Shop"].startswith("true") and 'open = !open' in groups["Shop"]
    assert groups["Catalog"].startswith("false") and "x-cloak" in groups["Catalog"].split("</ul>")[0]
    # not collapsible: always open, and the label is not a toggle
    assert groups["Settings"].startswith("true") and "open = !open" not in groups["Settings"].split("<ul")[0]
    # a collapsed group opens by itself when it holds the current page
    groups = group_chunks(admin.get("/admin/posts").text)
    assert groups["Marketing"].startswith("true") and groups["Catalog"].startswith("false")


def test_panel_navigation_group_collapsed_option(admin, panel):
    panel._nav_groups = []
    panel.navigation_group("Catalog", collapsed=True).navigation_group("Shop", collapsible=False)
    groups = group_chunks(admin.get("/admin/").text)
    assert groups["Catalog"].startswith("false")
    assert "open = !open" not in groups["Shop"].split("<ul")[0]


# ---------------------------------------------------------------------- 3. dark logo, tagline, active icon


def test_dark_logo_and_tagline(client, panel):
    panel.brand_logo = "/logo-light.svg"
    panel.brand_logo_dark = "/logo-dark.svg"
    panel.brand_tagline = "Run your shop"
    page = client.get("/admin/login").text
    assert 'src="/logo-light.svg"' in page and "dark:hidden" in page
    assert re.search(r'<img src="/logo-dark.svg"[^>]*class="hidden h-8 w-auto dark:block"', page)
    assert "Run your shop" in page
    panel.brand_logo = None  # only a dark logo: used everywhere
    page = client.get("/admin/login").text
    assert 'src="/logo-dark.svg"' in page and "dark:block" not in page


def test_resource_active_icon(admin, monkeypatch):
    monkeypatch.setattr(ProductResource, "active_icon", "package-open")
    active = str(icon("package-open", "h-5 w-5 shrink-0"))
    assert active in admin.get("/admin/products").text
    page = admin.get("/admin/").text
    assert active not in page and str(icon("package", "h-5 w-5 shrink-0")) in page


# ---------------------------------------------------------------------- 4. nested custom items


class HelpArticles(Page):
    navigation_parent = "Help center"
    navigation_group = "Settings"


def test_custom_parent_item_children_do_not_pile_up(admin, panel):
    parent = NavigationItem("Help center", "/admin/help", icon="life-buoy", group="Settings",
                            children=[NavigationItem("FAQ", "/admin/faq")])
    panel.navigation_items([parent])
    panel.pages([HelpArticles])
    for _ in range(3):
        page = admin.get("/admin/").text
        assert page.count('href="/admin/help-articles"') == 1
        assert page.count('href="/admin/faq"') == 1
    assert [c.label for c in parent.children] == ["FAQ"]  # the registered item is left alone
    assert 'aria-current' not in page.split('href="/admin/faq"')[1][:80]
    assert 'tw-nav-item-active' in admin.get("/admin/help-articles").text.split('href="/admin/help-articles"')[1][:80]


# ---------------------------------------------------------------------- 5. theme switcher


def test_theme_data_attributes(admin, panel):
    panel.default_theme = "dark"
    page = admin.get("/admin/").text
    assert 'data-default-theme="dark"' in page and 'data-dark-mode="true"' in page
    panel.dark_mode = False
    page = admin.get("/admin/").text
    assert 'data-dark-mode="false"' in page and "$store.theme.set" not in page
    js = admin.get("/admin/assets/tungsten.js").text
    assert "dataset.defaultTheme" in js and 'dataset.darkMode !== "false"' in js
    assert "if (!this.allowed) return;" in js  # no OS theme listener when dark mode is off


# ---------------------------------------------------------------------- 6. global search off


def test_global_search_off_hides_sidebar_button_and_shortcut(admin, panel):
    page = admin.get("/admin/").text
    assert "Search menu..." in page and "ctrl.k" in page
    panel.global_search_enabled = False
    page = admin.get("/admin/").text
    assert "Search menu..." not in page and "ctrl.k" not in page and "tw-open-search" not in page


# ---------------------------------------------------------------------- 7. failure toast, create another


def _boom():
    raise RuntimeError("boom")


class ActionsPage(Page):
    slug = "actions-page"

    @classmethod
    def header_actions(cls, ctx):
        return [
            Action("refuse").success_notification_title("Done").failure_notification_title("Could not do it")
            .action(lambda: False),
            Action("explode").failure_notification_title("It broke").action(_boom),
            Action("plain_error").action(_boom),
            Action("ping").action(lambda ctx: Notification("Ping").icon("shopping-cart")
                                  .action("Open", "/admin/orders", color="danger").send(ctx)),
        ]


def run(admin, name):
    return admin.post("/admin/_tw/action", {"_tw_host": "page:actions-page", "_tw_scope": "page", "_tw_name": name})


def test_failure_notification(admin, panel):
    panel.pages([ActionsPage])
    r = run(admin, "refuse")
    notes = json.loads(r.headers["HX-Trigger"])["tw-notify"]
    assert [n["title"] for n in notes] == ["Could not do it"] and notes[0]["status"] == "danger"
    assert "HX-Refresh" not in r.headers
    r = run(admin, "explode")
    assert r.status_code == 200 and "It broke" in r.headers["HX-Trigger"]
    with pytest.raises(RuntimeError):  # without a failure title the error is raised as before
        run(admin, "plain_error")


def test_create_another(admin, panel):
    host = "relation:products:1:tags"
    r = admin.get(f"/admin/_tw/action?_tw_host={host}&_tw_scope=table&_tw_name=create", htmx=True)
    assert "Create &amp; create another" in r.text and 'name="_tw_another"' in r.text
    # the plain submit comes first, so pressing Enter creates without "another"
    assert r.text.index('type="submit"') < r.text.index('name="_tw_another"')
    r = admin.post("/admin/_tw/action", {"_tw_host": host, "_tw_scope": "table", "_tw_name": "create",
                                         "name": "another-one", "_tw_another": "1"})
    trig = json.loads(r.headers["HX-Trigger"])
    assert "tw-refresh" in trig and trig["tw-notify"][0]["title"] == "Created" and "tw-close-modal" not in trig
    assert 'name="name"' in r.text and 'value="another-one"' not in r.text  # a fresh, empty form
    with db_session(panel) as db:
        assert db.scalars(select(Tag).where(Tag.name == "another-one")).one()
    # edit modals have no such button
    r = admin.get(f"/admin/_tw/action?_tw_host={host}&_tw_scope=row&_tw_name=edit&_tw_record=1", htmx=True)
    assert "create another" not in r.text


# ---------------------------------------------------------------------- 8. page filters reach page widgets


class RegionStats(StatsOverviewWidget):
    lazy = False

    @classmethod
    def stats(cls, filters):
        return [Stat("Region", f"R-{filters.get('region')}")]


class LazyRegionStats(RegionStats):
    lazy = True


class RegionReport(Page):
    widgets = [RegionStats, LazyRegionStats]

    @classmethod
    def filters_form(cls, form):
        return form.schema([Select("region").options({"north": "North", "south": "South"}).default("north")])


def test_page_widgets_get_the_page_filters(admin, panel):
    panel.pages([RegionReport])
    page = admin.get("/admin/region-report?region=south").text
    assert "R-south" in page
    assert "/admin/_tw/widget/lazy-region-stats?region=south&amp;_tw_page=region-report" in page
    r = admin.get("/admin/_tw/widget/lazy-region-stats?region=south&_tw_page=region-report", htmx=True)
    assert "R-south" in r.text
    assert "R-north" in admin.get("/admin/region-report").text  # the page's default


# ---------------------------------------------------------------------- 11. chart filter keeps page filters


def test_chart_filter_keeps_dashboard_filters(admin):
    r = admin.get("/admin/_tw/widget/revenue-chart?period=7&_tw_page=&filter=6", htmx=True)
    m = re.search(r'name="filter"\s+hx-get="([^"]+)"', r.text)
    url = html_lib.unescape(m.group(1))
    assert url == "/admin/_tw/widget/revenue-chart?period=7&_tw_page="
    assert re.search(r'<option value="6" selected', r.text)


# ---------------------------------------------------------------------- 12. polling without lazy


def test_polling_non_lazy_widget(admin, monkeypatch):
    monkeypatch.setattr(UserStats, "polling_interval", "10s")
    page = admin.get("/admin/users").text
    m = re.search(r'hx-get="(/admin/_tw/widget/user-stats[^"]*)" hx-trigger="every 10s"', page)
    assert m, "non-lazy widget should poll"
    assert "Total users" in page.split(m.group(0))[1][:3000]  # drawn with the page, then refreshed


# ---------------------------------------------------------------------- 9. bell


def test_bell_translates_stored_text(admin, panel):
    with db_session(panel) as db:
        user = db.scalars(select(User).where(User.email == "admin@example.com")).one()
        Notification("Saved").body("Deleted").action("Created", "/admin").send_to_database(user, db)
    assert "Saved" in admin.get("/admin/_tw/notifications", htmx=True).text
    admin.post("/admin/_tw/locale", {"locale": "hi"}, htmx=False)
    text = admin.get("/admin/_tw/notifications", htmx=True).text
    assert "सेव हो गया" in text and "हटा दिया गया" in text and "बन गया" in text


class KeyBase(DeclarativeBase):
    pass


class Account(KeyBase):
    __tablename__ = "accounts"
    account_no: Mapped[str] = mapped_column(String(20), primary_key=True)
    id: Mapped[str] = mapped_column(String(20))  # a plain column called "id" that is not the key


def test_send_to_database_uses_the_primary_key():
    from tungsten.models import DatabaseNotification, TungstenBase

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TungstenBase.metadata.create_all(engine)
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        Notification("Hi").send_to_database([Account(account_no="AC-9", id="other"), 42], db)
        assert [n.user_id for n in db.scalars(select(DatabaseNotification))] == ["AC-9", "42"]


# ---------------------------------------------------------------------- 10. toasts


def test_toasts_carry_any_icon_and_action_color(admin, panel):
    panel.pages([ActionsPage])
    r = run(admin, "ping")
    assert r.headers.get("HX-Refresh") == "true"  # page actions reload; the toast is flashed
    page = admin.get("/admin/").text
    m = re.search(r'\$store\.toasts\.init\(([^)]*)\)', page)
    flash = json.loads(html_lib.unescape(m.group(1)))
    assert flash[0]["icon_svg"] == str(icon("shopping-cart", "h-4 w-4"))
    assert flash[0]["actions"][0]["color"] == "danger"
    assert "t.icon_svg ||" in page and "text-danger-600" in page.split('x-for="a in (t.actions')[1][:2000]
    # toasts sent with an HTMX response bring the icon too
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:products", "_tw_scope": "row", "_tw_name": "delete",
                                         "_tw_record": "1"})
    note = json.loads(r.headers["HX-Trigger"])["tw-notify"][0]
    assert note["icon_svg"] == str(icon("circle-check", "h-4 w-4"))
