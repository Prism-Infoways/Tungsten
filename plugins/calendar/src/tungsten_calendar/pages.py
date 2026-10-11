"""The calendar page: month, week, day and list views."""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar

from markupsafe import Markup

from tungsten import Page
from tungsten.actions import Action, ActionGroup
from tungsten.i18n import translate as __

from .models import CalendarEvent
from .service import by_day, color_css, month_weeks, parse_date, shift, view_range, weekday_names

VIEWS = {"month": "Month", "week": "Week", "day": "Day", "list": "List"}
#: items drawn in one month cell before "+N more"
MONTH_CELL_ITEMS = 3
#: the dates the calendar can be moved to
FIRST_DAY, LAST_DAY = dt.date(1900, 1, 1), dt.date(2999, 12, 31)


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("calendar")


def read_params(ctx: Any, plugin: Any) -> dict:
    """The view, the date and the hidden sources from the address bar (bad values fall back to defaults)."""
    params = ctx.request.query_params
    view = params.get("view") if params.get("view") in VIEWS else plugin.default_view
    day = parse_date(params.get("date"), None) or plugin.today()
    day = min(max(day, FIRST_DAY), LAST_DAY)  # far-off years would overflow the grids
    hidden = {k for k in (params.get("hide") or "").split(",") if k in plugin.sources}
    if params.get("hide") is None:  # first visit: sources that start hidden
        hidden = {k for k, s in plugin.sources.items() if not s.default}
    return {"view": view, "date": day, "hidden": hidden}


def page_url(ctx: Any, view: str, day: dt.date, hidden: set[str], **extra: Any) -> str:
    return ctx.url("calendar", view=view, date=day.isoformat(), hide=",".join(sorted(hidden)), **extra)


def heading(view: str, first: dt.date, last: dt.date, day: dt.date) -> str:
    if view == "month":
        return f"{__(day.strftime('%B'))} {day.year}"
    if view == "day":
        return f"{__(day.strftime('%A'))}, {day.day} {__(day.strftime('%b'))} {day.year}"
    if first.year != last.year:
        return f"{first.day} {__(first.strftime('%b'))} {first.year} – {last.day} {__(last.strftime('%b'))} {last.year}"
    if first.month != last.month:
        return f"{first.day} {__(first.strftime('%b'))} – {last.day} {__(last.strftime('%b'))} {last.year}"
    return f"{first.day} – {last.day} {__(last.strftime('%b'))} {last.year}"


def _event_resource(ctx: Any) -> Any:
    return ctx.panel.resource_for_model(CalendarEvent)


def can_create(ctx: Any) -> bool:
    resource = _event_resource(ctx)
    try:
        return resource is not None and resource.can(ctx, "create")
    except Exception:  # noqa: BLE001
        return False


def calendar_data(ctx: Any, plugin: Any) -> dict:
    """Everything the template needs, worked out once."""
    p = read_params(ctx, plugin)
    view, day, hidden = p["view"], p["date"], p["hidden"]
    first, last = view_range(view, day, plugin.first_weekday, plugin.list_days)
    items, failed = plugin.items(ctx, first, last, hidden)
    days = by_day(items, first, last)
    today = plugin.today()
    creating = can_create(ctx)
    resource = _event_resource(ctx)

    def new_url(d: dt.date, all_day: bool = False) -> str | None:
        if not creating:
            return None
        return resource.get_url(ctx, "create", date=d.isoformat(), **({"all_day": "1"} if all_day else {}))

    def card(item: Any, on: dt.date | None = None) -> dict:
        strong, soft = color_css(item.color, "primary")
        label = __(item.time_label(on))
        # the month grid has little room: just the start time
        short = item.start.strftime("%H:%M") if on is None or item.first_day == on else label
        return {"title": item.title, "time": label, "short": short, "url": item.url, "icon": item.icon,
                "strong": strong, "soft": soft, "all_day": item.all_day or (on is not None and item.first_day < on),
                "continues_before": on is not None and item.first_day < on,
                "continues_after": on is not None and item.last_day > on,
                "move": item.record_id if item.editable else None, "location": item.location,
                "source": plugin.sources[item.source].label if item.source in plugin.sources else item.source,
                "description": item.description}

    def day_cell(d: dt.date) -> dict:
        rows = [card(i, d) for i in days.get(d, [])]
        return {"date": d, "iso": d.isoformat(), "num": d.day, "today": d == today, "weekend": d.weekday() >= 5,
                "outside": view == "month" and d.month != day.month, "rows": rows,
                "shown": rows[:MONTH_CELL_ITEMS] if view == "month" else rows,
                "more": max(0, len(rows) - MONTH_CELL_ITEMS) if view == "month" else 0,
                "day_url": page_url(ctx, "day", d, hidden), "new_url": new_url(d, all_day=view == "month"),
                "label": f"{__(d.strftime('%a'))} {d.day}"}

    weeks = []
    if view == "month":
        weeks = [[day_cell(d) for d in week] for week in month_weeks(day.year, day.month, plugin.first_weekday)]
    columns = [day_cell(first + dt.timedelta(days=i)) for i in range((last - first).days + 1)] \
        if view in ("week", "day") else []
    agenda = [day_cell(d) for d, rows in days.items() if rows] if view == "list" else []

    chips = []
    for key, source in plugin.sources.items():
        toggled = hidden ^ {key}
        chips.append({"key": key, "label": source.label, "hidden": key in hidden, "icon": source.icon,
                      "strong": color_css(source.color)[0], "url": page_url(ctx, view, day, toggled)})
    return {
        "view": view, "views": [{"key": k, "label": v, "url": page_url(ctx, k, day, hidden), "active": k == view}
                                for k, v in VIEWS.items()],
        "heading": heading(view, first, last, day), "first": first, "last": last,
        "prev_url": page_url(ctx, view, shift(view, day, -1, plugin.list_days), hidden),
        "next_url": page_url(ctx, view, shift(view, day, 1, plugin.list_days), hidden),
        "today_url": page_url(ctx, view, today, hidden), "is_today": first <= today <= last,
        "weekdays": [__(n) for n in weekday_names(plugin.first_weekday)], "weeks": weeks, "columns": columns,
        "agenda": agenda, "chips": chips if len(chips) > 1 else [], "failed": failed, "count": len(items),
        "move_url": ctx.url("calendar", "move"), "can_create": creating,
        "new_url": new_url(day if first <= day <= last else first),
    }


class CalendarPage(Page):
    slug = "calendar"
    title = "Calendar"
    icon = "calendar-days"
    navigation_group = "Calendar"
    navigation_sort = 1
    content_template = "tungsten_calendar/calendar.html"
    widget_columns: ClassVar[int] = 1

    @classmethod
    def can_access(cls, ctx: Any) -> bool:
        return _plugin(ctx) is not None and super().can_access(ctx)

    @classmethod
    def header_actions(cls, ctx: Any) -> list:
        plugin = _plugin(ctx)
        p = read_params(ctx, plugin)
        actions: list = []
        if can_create(ctx):
            actions.append(Action("new_event").label("New event").icon("plus")
                           .url(_event_resource(ctx).get_url(ctx, "create", date=p["date"].isoformat())))
        more = [Action("download_ics").label("Download .ics").icon("download")
                .url(ctx.url("calendar", "export.ics", view=p["view"], date=p["date"].isoformat(),
                             hide=",".join(sorted(p["hidden"]))))]
        if plugin.feeds and ctx.user is not None:
            from .feeds import reset_action, subscribe_action

            more = [subscribe_action(), *more, reset_action()]
        actions.append(ActionGroup(more).label("Share").icon("share-2").color("gray").button())
        return actions

    @classmethod
    def content(cls, ctx: Any) -> Any:
        plugin = _plugin(ctx)
        return Markup(ctx.panel.renderer.render(cls.content_template, ctx=ctx, cal=calendar_data(ctx, plugin)))
