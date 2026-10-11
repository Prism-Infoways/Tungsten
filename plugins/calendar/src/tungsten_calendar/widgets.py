"""Dashboard card: what is coming up in the next few days."""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar

from tungsten import Widget

from .service import by_day, color_css

#: the most rows the card shows
MAX_ROWS = 8


class UpcomingEvents(Widget):
    heading: ClassVar[str | None] = "Coming up"
    icon: ClassVar[str | None] = "calendar-days"
    template: ClassVar[str] = "tungsten_calendar/upcoming.html"
    column_span: ClassVar[Any] = 2
    sort: ClassVar[int] = 40

    @classmethod
    def can_view(cls, ctx: Any) -> bool:
        return ctx.panel.get_plugin("calendar") is not None

    @classmethod
    def view_data(cls, ctx: Any) -> dict[str, Any]:
        plugin = ctx.panel.get_plugin("calendar")
        today = plugin.today()
        last = today + dt.timedelta(days=plugin.upcoming_days - 1)
        hidden = {k for k, s in plugin.sources.items() if not s.default}
        items, failed = plugin.items(ctx, today, last, hidden)
        current = plugin.now()
        rows, total = [], 0
        for day, day_items in by_day(items, today, last).items():
            for item in day_items:
                # on today, skip timed items that are already over
                if day == today and not item.all_day and (item.end or item.start) < current \
                        and item.last_day == today:
                    continue
                total += 1
                if len(rows) < MAX_ROWS:
                    rows.append({"day": "Today" if day == today else "Tomorrow" if day == today + dt.timedelta(days=1)
                                 else day.strftime("%a %d %b"), "time": item.time_label(day), "title": item.title,
                                 "url": item.url, "icon": item.icon, "strong": color_css(item.color)[0]})
        return {"rows": rows, "more": max(0, total - len(rows)), "failed": failed,
                "link": ctx.url("calendar", view="list", date=today.isoformat()),
                "description": f"Next {plugin.upcoming_days} days"}
