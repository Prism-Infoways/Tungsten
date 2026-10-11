"""Custom dashboards for Tungsten: people build their own dashboards by drag and drop.

    from tungsten_dashboards import DashboardsPlugin

    panel.plugin(DashboardsPlugin())
    panel.create_tables(engine)   # also creates the dashboard tables

Adds a "Dashboards" page. Anyone can make dashboards, pick widgets from every installed plugin
(HR, Finance, Tickets, Leads...), drag them around and make them wider or narrower. Dashboards can
be private or shared with everyone, and a person can make one their home page.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tungsten import Plugin

from . import service
from .models import CustomDashboard, DashboardHome, DashboardItem, DashboardsBase
from .service import DashboardError, catalog
from .views import DashboardsPage, add_routes, home_page

__version__ = "0.1.0"


class DashboardsPlugin(Plugin):
    """``DashboardsPlugin(home=True, builtin_widgets=True, navigation_group=None)``.

    - ``home``: a person can make one of their dashboards the panel's home page (and people allowed
      to share can make one the home page for everyone). The normal home page stays until then.
    - ``builtin_widgets``: offer the plugin's own widgets: record counts, quick links and notes.
    - ``navigation_group`` / ``navigation_sort``: where "Dashboards" sits in the menu.
    - ``hide``: widgets (classes or ids) that must not be offered on dashboards.
    """

    id = "dashboards"
    metadata = DashboardsBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, home: bool = True, builtin_widgets: bool = True, navigation_group: str | None = None,
                 navigation_sort: int = -90, hide: Iterable[Any] = ()) -> None:
        self.home = home
        self.builtin_widgets = builtin_widgets
        self.navigation_group = navigation_group
        self.navigation_sort = navigation_sort
        self.hidden_widgets: list[Any] = list(hide)
        #: widgets offered only on dashboards (see :meth:`add_widgets`)
        self.extra_widgets: list[Any] = []
        #: starting points for new dashboards (see :meth:`add_template`)
        self.templates_by_name: dict[str, list[Any]] = {}
        self.panel: Any = None
        self.page: type[DashboardsPage] = type("DashboardsPage", (DashboardsPage,), {"plugin": self, "widgets": []})

    # ------------------------------------------------------------------ hooks for other plugins
    def add_widgets(self, widgets: Iterable[Any]) -> DashboardsPlugin:
        """Offer widgets on custom dashboards without putting them on the normal home page::

            dashboards.add_widgets([OverdueTasksChart, TasksByStatus])
        """
        for widget in widgets:
            if widget not in self.extra_widgets:
                self.extra_widgets.append(widget)
                self.page.widgets.append(widget)  # so the panel can find it for refreshes and filters
        return self

    def add_template(self, name: str, widgets: Iterable[Any]) -> DashboardsPlugin:
        """A ready-made starting point in the "New dashboard" form::

            dashboards.add_template("Sales", [LeadStats, InvoicesChart, "latest-orders"])
        """
        self.templates_by_name[name] = list(widgets)
        return self

    def hide(self, *widgets: Any) -> DashboardsPlugin:
        """Never offer these widgets (classes or ids) on dashboards."""
        self.hidden_widgets.extend(widgets)
        return self

    def url(self, ctx: Any, *parts: Any, **query: Any) -> str:
        return ctx.url(self.page.get_slug(), *parts, **query)

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        self.page.navigation_group = self.navigation_group
        self.page.navigation_sort = self.navigation_sort
        panel.pages([self.page])
        panel.routes(lambda app, panel: add_routes(app, panel, self))

    def boot(self, panel: Any) -> None:
        if self.home and panel.dashboard is not None and not getattr(panel.dashboard, "_tw_custom_home", False):
            panel.dashboard = home_page(panel.dashboard, self)
            panel.dashboard._tw_custom_home = True
        self._link_quick_create(panel)

    def _link_quick_create(self, panel: Any) -> None:
        """With the Quick Create plugin, its + New menu gets a "Dashboard" entry."""
        quick = panel.get_plugin("quick-create")
        if quick is None or not hasattr(quick, "add_link"):
            return
        quick.add_link("dashboards.new", "Dashboard", lambda ctx: self.url(ctx, new=1), icon="layout-grid",
                       group="Dashboards", visible=lambda ctx: service.can_create(ctx))

    def permissions(self) -> list[tuple[str, str]]:
        return [(service.CREATE, "Make own dashboards"),
                (service.SHARE, "Share dashboards with everyone and set the home page for all")]


__all__ = [
    "CustomDashboard",
    "DashboardError",
    "DashboardHome",
    "DashboardItem",
    "DashboardsBase",
    "DashboardsPage",
    "DashboardsPlugin",
    "add_routes",
    "catalog",
    "home_page",
    "service",
]
