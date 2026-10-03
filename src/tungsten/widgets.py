"""Dashboard widgets: stats cards, charts, tables and progress lists."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

from markupsafe import Markup

from .hosts import Host
from .i18n import translate as __
from .support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .tables.table import Table


def _kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


SPAN = {1: "md:col-span-1", 2: "md:col-span-2", 3: "md:col-span-3", 4: "md:col-span-4", 6: "md:col-span-6",
        "full": "col-span-full"}


class Widget:
    """Base widget. Widgets load lazily on the page (one request each)."""

    sort: ClassVar[int] = 0
    column_span: ClassVar[int | str] = 1
    lazy: ClassVar[bool] = True
    polling_interval: ClassVar[str | None] = None
    heading: ClassVar[str | None] = None
    description: ClassVar[str | None] = None
    #: optional icon shown in a soft colored tile next to the heading
    icon: ClassVar[str | None] = None
    icon_color: ClassVar[str] = "primary"
    template: ClassVar[str] = ""

    @classmethod
    def get_id(cls) -> str:
        return getattr(cls, "id", None) or _kebab(cls.__name__)

    @classmethod
    def can_view(cls, ctx: "Context") -> bool:
        return True

    @classmethod
    def span_class(cls) -> str:
        return SPAN.get(cls.column_span, "")

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        return {}

    @classmethod
    def render(cls, ctx: "Context") -> Markup:
        return ctx.panel.renderer.render(cls.template, w=cls, ctx=ctx, **cls.view_data(ctx))


class Stat:
    """One stats card: ``Stat("Total users", 1248).trend("12%", "up").chart([...]).icon("users")``."""

    def __init__(self, label: str, value: Any) -> None:
        self.label = label
        self.value = value
        self.description: str | None = None
        self.icon_name: str | None = None
        self.color_name = "primary"
        self.trend_value: str | None = None
        self.trend_direction = "up"
        self.trend_color: str | None = None
        self.chart_points: list[float] | None = None
        self.url_value: str | None = None

    @classmethod
    def make(cls, label: str, value: Any) -> "Stat":
        return cls(label, value)

    def describe(self, text: str) -> "Stat":
        self.description = text
        return self

    def icon(self, name: str) -> "Stat":
        self.icon_name = name
        return self

    def color(self, color: str) -> "Stat":
        self.color_name = color
        return self

    def trend(self, value: str, direction: str = "up", color: str | None = None) -> "Stat":
        """``direction`` is ``"up"`` or ``"down"``; color defaults to green/red."""
        self.trend_value = value
        self.trend_direction = direction
        self.trend_color = color
        return self

    def chart(self, points: list[float]) -> "Stat":
        self.chart_points = [float(p) for p in points]
        return self

    def url(self, url: str) -> "Stat":
        self.url_value = url
        return self


class StatsOverviewWidget(Widget):
    template = "tungsten/widgets/stats.html"
    column_span = "full"
    columns: ClassVar[int] = 4

    @classmethod
    def stats(cls, ctx: "Context") -> list[Stat]:
        return []

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        return {"stats": call(cls.stats, ctx=ctx, db=ctx.db, user=ctx.user, filters=ctx.filters)}


class ChartWidget(Widget):
    """``type`` is line, bar, pie, doughnut, radar or polarArea.

    ``data()`` returns ``{"labels": [...], "datasets": [{"label": ..., "data": [...], "color": "primary"}]}``.
    Bar + line combos: give a dataset ``"type": "line"``.
    """

    template = "tungsten/widgets/chart.html"
    type: ClassVar[str] = "line"
    column_span = 2
    max_height: ClassVar[str] = "18rem"
    #: e.g. {"7": "Last 7 days", "30": "Last 30 days"}
    filters: ClassVar[dict[str, str] | None] = None
    default_filter: ClassVar[str | None] = None
    options: ClassVar[dict] = {}
    #: show the legend as a list next to doughnut/pie charts
    side_legend: ClassVar[bool] = False

    @classmethod
    def data(cls, ctx: "Context", filter: str | None = None) -> dict[str, Any]:
        return {"labels": [], "datasets": []}

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        active = ctx.request.query_params.get("filter") or cls.default_filter or (
            next(iter(cls.filters)) if cls.filters else None)
        data = call(cls.data, ctx=ctx, db=ctx.db, user=ctx.user, filter=active, filters=ctx.filters)
        palette = ["primary", "info", "success", "purple", "warning", "teal", "pink", "danger", "gray"]
        for i, ds in enumerate(data.get("datasets", [])):
            if isinstance(ds.get("label"), str):
                ds["label"] = __(ds["label"])
            if "color" not in ds and "colors" not in ds:
                if cls.type in ("pie", "doughnut", "polarArea"):
                    ds["colors"] = [palette[j % len(palette)] for j in range(len(ds.get("data", [])))]
                else:
                    ds["color"] = palette[i % len(palette)]
        legend = []
        if cls.side_legend and data.get("datasets"):
            ds = data["datasets"][0]
            total = sum(float(v or 0) for v in ds.get("data", [])) or 1
            for label, value, color in zip(data.get("labels", []), ds.get("data", []), ds.get("colors", [])):
                legend.append({"label": label, "value": value, "color": color,
                               "percent": round(float(value or 0) / total * 100)})
        return {
            "chart": {"type": cls.type, "data": data, "options": cls.options},
            "filters": cls.filters,
            "active_filter": active,
            "legend": legend,
            "center": data.get("center"),
        }


class ProgressItem:
    def __init__(self, label: str, value: Any, percent: float, icon: str | None = None, color: str = "primary"):
        self.label, self.value, self.percent, self.icon, self.color = label, value, percent, icon, color


class ProgressListWidget(Widget):
    """A list of labelled progress bars (e.g. "Sales by category")."""

    template = "tungsten/widgets/progress.html"
    link: ClassVar[str | None] = None

    @classmethod
    def items(cls, ctx: "Context") -> list[ProgressItem]:
        return []

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        return {"entries": call(cls.items, ctx=ctx, db=ctx.db, user=ctx.user, filters=ctx.filters), "link": cls.link}


class TableWidget(Widget):
    """A table on the dashboard. Define ``model``, ``query()`` and ``table()``."""

    template = "tungsten/widgets/table.html"
    column_span = 2
    model: ClassVar[Any] = None
    link: ClassVar[str | None] = None
    link_label: ClassVar[str] = "View all"

    @classmethod
    def get_link(cls, ctx: "Context") -> str | None:
        """URL for the "View all" link. Defaults to the model's resource list."""
        if cls.link:
            return cls.link
        resource = ctx.panel.resource_for_model(cls.model)
        return resource.get_url(ctx) if resource and resource.can(ctx, "view_any") else None

    @classmethod
    def query(cls, ctx: "Context"):
        from sqlalchemy import select

        return select(cls.model)

    @classmethod
    def table(cls, table: "Table") -> "Table":
        return table

    @classmethod
    def host(cls) -> "WidgetHost":
        return WidgetHost(cls)

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        host = cls.host()
        table = host.get_table(ctx)
        if not table.is_searchable():
            table.toolbar(False)
        table.bind(ctx, host, params=ctx.request.query_params if ctx.request.query_params.get("host") else None)
        return {"table": table, "link": cls.get_link(ctx)}


class WidgetHost(Host):
    def __init__(self, widget: type[TableWidget]) -> None:
        self.widget = widget
        self.model = widget.model
        self.key = f"widget:{widget.get_id()}"

    def base_query(self, ctx: "Context"):
        query = call(self.widget.query, ctx=ctx, db=ctx.db, user=ctx.user, filters=ctx.filters)
        return ctx.panel.tenancy.scope(ctx, self.model, query)

    def get_table(self, ctx: "Context") -> "Table":
        from .tables.table import Table

        table = self.widget.table(Table().paginated([5, 10, 25], 5))
        return table

    def title(self) -> str:
        return self.widget.heading or ""

    def can(self, ctx: "Context", ability: str, record: Any = None) -> bool:
        resource = ctx.panel.resource_for_model(self.model)
        return resource.can(ctx, ability, record) if resource else True

    def edit_url(self, ctx: "Context", record: Any) -> str | None:
        resource = ctx.panel.resource_for_model(self.model)
        return resource.host().edit_url(ctx, record) if resource else None

    def view_url(self, ctx: "Context", record: Any) -> str | None:
        resource = ctx.panel.resource_for_model(self.model)
        return resource.host().view_url(ctx, record) if resource else None


class AccountWidget(Widget):
    """A small "welcome back" card with the user's name."""

    template = "tungsten/widgets/account.html"
    lazy = False
