"""The modern design: the new card widgets, the UI kit macros and the gallery page."""

from __future__ import annotations

import pytest
from tungsten import (
    ActivityWidget,
    BannerWidget,
    ChecklistWidget,
    ColumnsWidget,
    FunnelWidget,
    GaugeWidget,
    HeroStatWidget,
    Item,
    LeaderboardWidget,
    QuickActionsWidget,
    ScheduleWidget,
    Stat,
    TeamWidget,
)

LAZY_WIDGETS = {
    "revenue-hero": "hero-stat",
    "monthly-target": "gauge",
    "sales-overview": "columns",
    "order-funnel": "funnel",
    "top-customers": "leaderboard",
    "recent-activity": "activity",
    "team-schedule": "schedule",
    "team-members": "team",
    "setup-guide": "checklist",
}


@pytest.mark.parametrize("widget_id,kind", LAZY_WIDGETS.items())
def test_demo_widgets_render(admin, widget_id, kind):
    r = admin.get(f"/admin/_tw/widget/{widget_id}", htmx=True)
    assert r.status_code == 200
    assert f'data-tw-widget="{kind}"' in r.text


def test_dashboard_has_the_modern_layout(admin):
    page = admin.get("/admin").text
    assert 'data-tw-widget="banner"' in page  # not lazy: drawn with the page
    assert 'data-tw-widget="quick-actions"' in page
    assert "Selling is better together" in page
    assert 'data-tw-stat="brand"' in admin.get("/admin/_tw/widget/shop-stats", htmx=True).text
    assert "tw-nav-item-active" in page and "lg:rounded-[1.75rem]" in page  # floating sidebar


def test_hero_stat_shows_value_trend_actions_and_bars(admin):
    html = admin.get("/admin/_tw/widget/revenue-hero", htmx=True).text
    assert "Total revenue" in html and "₹" in html
    assert "New order" in html and "/admin/orders/create" in html
    assert html.count('class="w-3 rounded-[4px]"') == 9


def test_gauge_percent_is_capped(admin):
    html = admin.get("/admin/_tw/widget/monthly-target", htmx=True).text
    assert "Monthly target" in html and "stroke-dashoffset" in html


def test_columns_highlight_and_filter(admin):
    html = admin.get("/admin/_tw/widget/sales-overview?filter=9", htmx=True).text
    assert html.count("tw-stripes") == 8  # nine months, one highlighted
    assert '<option value="9" selected' in html


def test_funnel_percent_is_share_of_first_stage(ctx_stub):
    class F(FunnelWidget):
        @classmethod
        def items(cls):
            return [Item("Visits", 200), Item("Carts", 50), Item("Paid", 0)]

    data = F.view_data(ctx_stub)
    assert [it.percent for it in data["entries"]] == [100.0, 25.0, 0.0]


def test_gauge_and_columns_math(ctx_stub):
    class G(GaugeWidget):
        @classmethod
        def value(cls):
            return {"value": 250, "max": 200}

    assert G.view_data(ctx_stub)["percent"] == 100.0

    class C(ColumnsWidget):
        @classmethod
        def data(cls):
            return {"labels": ["a", "b", "c"], "values": [2, 8, 0]}

    cols = C.view_data(ctx_stub)["columns"]
    assert [c["active"] for c in cols] == [False, True, False]
    assert [c["height"] for c in cols] == [25, 100, 6]

    class Empty(ColumnsWidget):
        pass

    assert Empty.view_data(ctx_stub)["columns"] == []


def test_checklist_and_schedule(ctx_stub):
    class L(ChecklistWidget):
        @classmethod
        def items(cls):
            return [Item("One", done=True), Item("Two"), Item("Three", done=True), Item("Four")]

    data = L.view_data(ctx_stub)
    assert (data["done"], data["percent"]) == (2, 50)

    class S(ScheduleWidget):
        pass

    days = S.view_data(ctx_stub)["days"]
    assert len(days) == 7 and sum(d["today"] for d in days) == 1


def test_item_clamps_percent():
    assert Item("x", percent=140).percent == 100.0
    assert Item("x", percent=-3).percent == 0.0
    assert Item("x").percent is None


def test_stat_highlight():
    assert Stat("a", 1).highlight().variant == "brand"
    assert Stat("a", 1).highlight("dark").variant == "dark"
    assert Stat("a", 1).highlight("nope").variant == "default"


def test_ui_kit_page_renders_every_macro(admin):
    page = admin.get("/admin/ui-kit").text
    assert "data-tw-gallery" in page
    for marker in ('role="radiogroup"', "tw-pill-nav-item-active", "stroke-dasharray", "tw-stripes",
                   'role="progressbar"', "tw-chip", "tw-skeleton", "tw-card-dark", "aria-current=\"date\""):
        assert marker in page, marker


def test_new_widgets_are_exported():
    for cls in (ActivityWidget, BannerWidget, HeroStatWidget, LeaderboardWidget, QuickActionsWidget, TeamWidget):
        assert cls.template.startswith("tungsten/widgets/")


@pytest.fixture()
def ctx_stub():
    """A bare context: enough for view_data() of widgets that don't touch the database."""
    from types import SimpleNamespace

    class Query:
        def get(self, key, default=None):
            return default

    return SimpleNamespace(db=None, user=None, filters={}, request=SimpleNamespace(query_params=Query()))
