"""Dashboard widgets: stats cards, charts, tables, progress lists and the modern card widgets."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlencode

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
    def get_url(cls, ctx: "Context", **params: Any) -> str:
        """The endpoint that draws this widget. Keeps the current query string (the page filters) and
        the page the widget sits on; ``params`` replace values, and ``None`` drops one."""
        page = getattr(ctx, "page", None)
        if page is not None:
            params.setdefault("_tw_page", page.get_slug())
        query = [(k, v) for k, v in ctx.request.query_params.multi_items() if k not in params]
        query += [(k, v) for k, v in params.items() if v is not None]
        url = ctx.url("_tw", "widget", cls.get_id())
        return f"{url}?{urlencode(query)}" if query else url

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
        self.variant = "default"

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

    def highlight(self, variant: str = "brand") -> "Stat":
        """Fill the card: ``"brand"`` (the primary color) or ``"dark"`` (near black)."""
        self.variant = variant if variant in ("brand", "dark") else "default"
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


# ---------------------------------------------------------------------------------------------------
# Modern card widgets. Most of them show a list of ``Item`` objects; each widget uses the fields it needs.


class Item:
    """One row for the list widgets: ``Item("Nikhil Verma", "₹12,400", description="12 orders", avatar=url)``.

    ``value`` is shown as given. ``percent`` (0-100) draws a bar, ``done`` ticks a checklist row,
    ``time`` is a short label like "09:30" or "2h ago", and ``url`` makes the row a link.
    """

    def __init__(self, label: str, value: Any = None, *, description: str | None = None, icon: str | None = None,
                 color: str = "primary", avatar: str | None = None, url: str | None = None,
                 percent: float | None = None, time: str | None = None, done: bool = False,
                 badge: str | None = None) -> None:
        self.label, self.value, self.description = label, value, description
        self.icon, self.color, self.avatar, self.url = icon, color, avatar, url
        self.percent = None if percent is None else max(0.0, min(100.0, float(percent)))
        self.time, self.done, self.badge = time, done, badge


def _items(cls: type[Widget], ctx: "Context") -> list[Item]:
    return list(call(cls.items, ctx=ctx, db=ctx.db, user=ctx.user, filters=ctx.filters) or [])


class _ItemsWidget(Widget):
    link: ClassVar[str | None] = None
    link_label: ClassVar[str] = "View all"

    @classmethod
    def items(cls, ctx: "Context") -> list[Item]:
        return []

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        return {"entries": _items(cls, ctx), "link": cls.link}


class HeroStatWidget(Widget):
    """One big number with a trend, a line of text, action buttons and small bars ("Total revenue")."""

    template = "tungsten/widgets/hero-stat.html"
    column_span = 2

    @classmethod
    def stat(cls, ctx: "Context") -> Stat:
        return Stat("", "")

    @classmethod
    def actions(cls, ctx: "Context") -> list[Item]:
        """Buttons under the number: ``Item("Add deal", url=..., icon="plus", color="primary")``."""
        return []

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        kw = {"ctx": ctx, "db": ctx.db, "user": ctx.user, "filters": ctx.filters}
        stat = call(cls.stat, **kw)
        points = stat.chart_points or []
        top = max(points) if points else 0
        bars = [round(p / top * 100) if top else 0 for p in points]
        return {"stat": stat, "actions": list(call(cls.actions, **kw) or []), "bars": bars}


class GaugeWidget(Widget):
    """Progress towards a target, drawn as a half circle (``shape = "arc"``) or a ring (``"ring"``).

    ``value()`` returns ``{"value": 5626, "max": 20000, "display": "₹5,626", "caption": "of ₹20,000"}``.
    """

    template = "tungsten/widgets/gauge.html"
    shape: ClassVar[str] = "arc"
    #: "dark" draws a near-black card, "brand" a primary colored one, "default" a white one
    variant: ClassVar[str] = "dark"
    color: ClassVar[str] = "primary"
    label: ClassVar[str | None] = None

    @classmethod
    def value(cls, ctx: "Context") -> dict[str, Any]:
        return {"value": 0, "max": 100}

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        data = dict(call(cls.value, ctx=ctx, db=ctx.db, user=ctx.user, filters=ctx.filters) or {})
        total = float(data.get("max") or 100) or 100
        percent = max(0.0, min(100.0, float(data.get("value") or 0) / total * 100))
        data.setdefault("display", data.get("value"))
        return {"gauge": data, "percent": round(percent, 1)}


class ColumnsWidget(Widget):
    """Rounded columns with one highlighted (the "Sales overview" look). No chart library needed.

    ``data()`` returns ``{"labels": [...], "values": [...]}``, plus optional ``"display"`` (the text for
    each value) and ``"highlight"`` (the index to highlight; default the biggest value).
    """

    template = "tungsten/widgets/columns.html"
    color: ClassVar[str] = "primary"
    height: ClassVar[str] = "12rem"
    filters: ClassVar[dict[str, str] | None] = None
    default_filter: ClassVar[str | None] = None

    @classmethod
    def data(cls, ctx: "Context", filter: str | None = None) -> dict[str, Any]:
        return {"labels": [], "values": []}

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        active = ctx.request.query_params.get("filter") or cls.default_filter or (
            next(iter(cls.filters)) if cls.filters else None)
        data = call(cls.data, ctx=ctx, db=ctx.db, user=ctx.user, filter=active, filters=ctx.filters) or {}
        values = [float(v or 0) for v in data.get("values", [])]
        labels = list(data.get("labels", []))
        display = list(data.get("display") or [f"{v:,.0f}" for v in values])
        top = max(values) if values else 0
        highlight = data.get("highlight")
        if highlight is None and values:
            highlight = values.index(top)
        columns = [{"label": labels[i] if i < len(labels) else "", "value": v,
                    "display": display[i] if i < len(display) else v,
                    "height": max(6, round(v / top * 100)) if top else 6, "active": i == highlight}
                   for i, v in enumerate(values)]
        return {"columns": columns, "filters": cls.filters, "active_filter": active}


class BannerWidget(Widget):
    """A wide colored card with a heading, a line of text and a button ("Get premium feature")."""

    template = "tungsten/widgets/banner.html"
    column_span = 2
    lazy = False
    eyebrow: ClassVar[str | None] = None
    text: ClassVar[str | None] = None
    button_label: ClassVar[str | None] = None
    button_url: ClassVar[str | None] = None
    button_icon: ClassVar[str | None] = "arrow-up-right"
    #: "brand" (primary gradient), "dark", "soft" (light tint of ``color``) or "purple"-style any color name
    variant: ClassVar[str] = "soft"
    color: ClassVar[str] = "primary"

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        return {"button_url": call(cls.get_button_url, ctx=ctx)}

    @classmethod
    def get_button_url(cls, ctx: "Context") -> str | None:
        return cls.button_url


class ActivityWidget(_ItemsWidget):
    """A timeline of recent events: ``Item("Order #31 paid", time="2h ago", icon="credit-card")``."""

    template = "tungsten/widgets/activity.html"


class LeaderboardWidget(_ItemsWidget):
    """A ranked list of people or things with a value and an optional bar ("Top sales reps")."""

    template = "tungsten/widgets/leaderboard.html"
    #: show 1, 2, 3... before each row
    ranked: ClassVar[bool] = True


class FunnelWidget(_ItemsWidget):
    """Stages with shrinking bars; each bar is the stage's share of the first stage ("Sales funnel")."""

    template = "tungsten/widgets/funnel.html"

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        entries = _items(cls, ctx)
        first = float(entries[0].value or 0) if entries else 0
        for it in entries:
            if it.percent is None:
                it.percent = round(float(it.value or 0) / first * 100, 1) if first else 0.0
        return {"entries": entries, "link": cls.link}


class ScheduleWidget(_ItemsWidget):
    """This week as a strip of days (today highlighted) with a list of events under it ("Meeting schedule")."""

    template = "tungsten/widgets/schedule.html"

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        import datetime as dt

        today = dt.date.today()
        start = today - dt.timedelta(days=today.weekday())
        days = [{"name": __((start + dt.timedelta(days=i)).strftime("%a")), "day": (start + dt.timedelta(days=i)).day,
                 "today": start + dt.timedelta(days=i) == today} for i in range(7)]
        return {"entries": _items(cls, ctx), "link": cls.link, "days": days,
                "month": __(today.strftime("%B")) + today.strftime(" %Y")}


class TeamWidget(_ItemsWidget):
    """People as avatars with their name and role under each ("Members")."""

    template = "tungsten/widgets/team.html"


class QuickActionsWidget(_ItemsWidget):
    """A grid of round icon buttons that link somewhere ("New order", "Add product"...)."""

    template = "tungsten/widgets/quick-actions.html"
    lazy = False
    columns: ClassVar[int] = 4


class ChecklistWidget(_ItemsWidget):
    """A to-do style list with ticks and an overall progress bar ("Setup guide")."""

    template = "tungsten/widgets/checklist.html"

    @classmethod
    def view_data(cls, ctx: "Context") -> dict[str, Any]:
        entries = _items(cls, ctx)
        done = sum(1 for it in entries if it.done)
        return {"entries": entries, "link": cls.link, "done": done,
                "percent": round(done / len(entries) * 100) if entries else 0}
