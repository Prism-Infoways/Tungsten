"""Calendar plugin for Tungsten.

    from tungsten_calendar import CalendarPlugin

    panel.plugin(CalendarPlugin(timezone="Asia/Kolkata"))
    panel.create_tables(engine)   # also creates the calendar tables

Adds a "Calendar" menu: a month, week, day and list calendar, and an "Events" list for
meetings, calls, tasks and reminders (all-day, multi-day and repeating). Drag an event to
another day to move it, download an .ics file, or subscribe from Google Calendar, Outlook or
a phone with a private link.

When other Tungsten plugins are installed, their dates show up too: approved leave, holidays
and birthdays (HR), lead follow-ups (Leads), ticket due dates (Tickets), invoice and bill due
dates (Finance) and blog posts (Blog). Any plugin can add its own dates with ``add_source``.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tungsten import Plugin
from tungsten.support.evaluate import call

from .models import CalendarBase, CalendarEvent, CalendarFeed
from .service import (
    MAX_RANGE_DAYS,
    CalendarItem,
    get_zone,
    ics_calendar,
    month_weeks,
    now,
    occurrences,
)
from .sources import LINKS, Source, event_source

__version__ = "0.1.0"

log = logging.getLogger("tungsten.calendar")

#: event types: key -> (label, color, icon)
DEFAULT_KINDS: dict[str, tuple[str, str, str]] = {
    "meeting": ("Meeting", "primary", "users"),
    "call": ("Call", "info", "phone"),
    "task": ("Task", "warning", "square-check"),
    "reminder": ("Reminder", "purple", "bell"),
    "other": ("Other", "gray", "calendar"),
}

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}


def _first_weekday(value: Any) -> int:
    if isinstance(value, int) and 0 <= value <= 6:
        return value
    key = str(value or "").strip().lower()
    if key in _WEEKDAYS:
        return _WEEKDAYS[key]
    raise ValueError(f"first_day must be a weekday name like 'monday' or 'sunday', or 0-6; got {value!r}")


class CalendarPlugin(Plugin):
    """``CalendarPlugin(timezone=None, first_day="monday", kinds=None, links=True, feeds=True, ...)``.

    - ``timezone``: the time zone your events are in, like ``"Asia/Kolkata"`` (default: the server's).
      Decides what "today" is and the times sent to phone calendars.
    - ``first_day``: the first column of the week, ``"monday"`` or ``"sunday"`` (or 0-6).
    - ``kinds``: event types, key -> ``(label, color, icon)``.
    - ``links``: show dates from other installed plugins. ``True`` for all, ``False`` for none, or a list
      of source keys: ``hr_leave``, ``hr_holidays``, ``hr_birthdays``, ``leads``, ``tickets``, ``finance``, ``blog``.
    - ``feeds``: let each user subscribe from Google Calendar, Outlook or a phone with a private link.
    - ``default_view``: ``month``, ``week``, ``day`` or ``list``. ``list_days``: how many days the list shows.
    - ``dashboard_widget``: an "Upcoming" card on the dashboard for the next ``upcoming_days`` days.
    """

    id = "calendar"
    metadata = CalendarBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, timezone: str | None = None, first_day: Any = "monday",
                 kinds: dict[str, tuple[str, str, str]] | None = None, links: Any = True, feeds: bool = True,
                 default_view: str = "month", list_days: int = 30, dashboard_widget: bool = True,
                 upcoming_days: int = 7, navigation_group: str = "Calendar") -> None:
        self.timezone = timezone
        self.zone = get_zone(timezone)
        self.first_weekday = _first_weekday(first_day)
        self.kinds = dict(kinds or DEFAULT_KINDS)
        if not self.kinds:
            raise ValueError("kinds needs at least one event type")
        for key, value in self.kinds.items():
            if not (isinstance(value, (tuple, list)) and len(value) == 3):
                raise ValueError(f"kinds[{key!r}] must be (label, color, icon)")
        self.links = links
        self.feeds = feeds
        if default_view not in ("month", "week", "day", "list"):
            raise ValueError("default_view must be month, week, day or list")
        self.default_view = default_view
        self.list_days = max(1, min(int(list_days), MAX_RANGE_DAYS))
        self.dashboard_widget = dashboard_widget
        self.upcoming_days = max(1, min(int(upcoming_days), 60))
        self.navigation_group = navigation_group
        self.panel: Any = None
        self.sources: dict[str, Source] = {}
        self._removed: set[str] = set()
        self.add_source("events", "Events", event_source, color="primary", icon="calendar")

    # ------------------------------------------------------------------ time
    def now(self) -> dt.datetime:
        """The wall-clock time now in the calendar's time zone (no offset)."""
        return now(self.zone)

    def today(self) -> dt.date:
        return self.now().date()

    # ------------------------------------------------------------------ sources (hooks for other plugins)
    def add_source(self, key: str, label: str, fn: Callable, color: str = "gray", icon: str = "calendar",
                   default: bool = True) -> None:
        """Show more dates on the calendar. ``fn(ctx, start, end)`` returns :class:`CalendarItem` objects (or
        dicts with the same keys) for the days ``start`` to ``end``, both included. It may also ask for
        ``db``, ``user`` or ``plugin``. The same ``key`` replaces a source. ``default=False`` starts it hidden.

        Call it from your plugin's ``boot()``, so it works whatever order plugins were added in::

            def boot(self, panel):
                calendar = panel.get_plugin("calendar")
                if calendar is not None:
                    calendar.add_source("visits", "Site visits", visits_on, color="teal", icon="map-pin")
        """
        if not key or not isinstance(key, str) or "," in key:
            raise ValueError("A source key must be text without commas")
        self.sources[key] = Source(key=key, label=label, fn=fn, color=color, icon=icon, default=default)

    def remove_source(self, key: str) -> None:
        """Take a source off the calendar (also stops ``boot()`` from linking it again)."""
        self.sources.pop(key, None)
        self._removed.add(key)

    def items(self, ctx: Any, start: dt.date, end: dt.date, hidden: Any = ()) -> tuple[list[CalendarItem], list[str]]:
        """Everything on the calendar from ``start`` to ``end`` (both included) that this user may see.

        Returns ``(items, failed)``: ``failed`` names the sources that broke (they are logged and skipped,
        so one broken plugin never takes the calendar down).
        """
        if end < start:
            start, end = end, start
        if (end - start).days > MAX_RANGE_DAYS:
            end = start + dt.timedelta(days=MAX_RANGE_DAYS)
        hidden = set(hidden or ())
        out: list[CalendarItem] = []
        failed: list[str] = []
        for key, source in list(self.sources.items()):
            if key in hidden:
                continue
            try:
                got = call(source.fn, ctx=ctx, db=ctx.db, user=getattr(ctx, "user", None), start=start, end=end,
                           plugin=self, panel=ctx.panel)
                for value in got or ():
                    item = CalendarItem.coerce(value, key, self.zone)
                    if not item.touches(start, end):
                        continue
                    item.color = item.color or source.color
                    item.icon = item.icon or source.icon
                    out.append(item)
            except Exception:
                log.exception("Calendar source %r failed", key)
                try:
                    ctx.db.rollback()  # a failed query must not break the next source
                except Exception:  # noqa: BLE001
                    log.debug("Rollback after a failed calendar source failed too", exc_info=True)
                failed.append(source.label)
        out.sort(key=lambda i: (i.start, i.title.lower()))
        return out, failed

    def _link_keys(self) -> set[str] | None:
        if self.links is True:
            return None
        if not self.links:
            return set()
        return set(self.links)

    def pwa_shortcuts(self, panel: Any) -> list[dict[str, str]]:
        """With the PWA plugin: "Calendar" in the menu of the installed app's icon."""
        return [{"name": "Calendar", "url": panel.url("calendar"), "description": "Your events and due dates"}]

    def _attach_tags(self, panel: Any) -> None:
        """With the Tags plugin, events get a tags box, a tags column and a tag filter."""
        from .resources import CalendarEventResource

        tags = panel.get_plugin("tags")
        if tags is None or not getattr(tags, "auto_attach", True) or not hasattr(tags, "attach"):
            return
        try:
            if tags.target_for(CalendarEventResource) is None:
                tags.attach(CalendarEventResource)
        except Exception:  # noqa: BLE001  an older Tags plugin must not stop the panel
            log.exception("Could not add tags to calendar events")

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        from .feeds import add_routes
        from .pages import CalendarPage
        from .resources import CalendarEventResource
        from .widgets import UpcomingEvents

        self.panel = panel
        CalendarPage.navigation_group = self.navigation_group
        CalendarEventResource.navigation_group = self.navigation_group
        panel.pages([CalendarPage])
        panel.resources([CalendarEventResource])
        panel.navigation_group(self.navigation_group, icon="calendar-days")
        if self.dashboard_widget:
            panel.widgets([UpcomingEvents])
        panel.routes(lambda app, panel: add_routes(app, panel, self))

    def boot(self, panel: Any) -> None:
        """Link with the plugins that are installed (all plugins are registered by now)."""
        self._attach_tags(panel)
        wanted = self._link_keys()
        for plugin_id, key, label, fn, color, icon in LINKS:
            if key in self.sources or key in self._removed or panel.get_plugin(plugin_id) is None:
                continue  # already added (maybe replaced by the app), or that plugin isn't installed
            if wanted is not None and key not in wanted:
                continue
            self.add_source(key, label, fn, color=color, icon=icon)


__all__ = [
    "DEFAULT_KINDS", "CalendarBase", "CalendarEvent", "CalendarFeed", "CalendarItem", "CalendarPlugin", "Source",
    "ics_calendar", "month_weeks", "occurrences",
]
