"""Date math for the calendar: items, month and week grids, repeating events, time zones and .ics files.

Everything here is plain Python so it can be tested without a panel.
"""

from __future__ import annotations

import calendar as _cal
import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover  (Python < 3.9 is not supported anyway)
    ZoneInfo = None  # type: ignore[assignment,misc]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]

REPEATS = {"none": "Does not repeat", "daily": "Every day", "weekly": "Every week", "monthly": "Every month",
           "yearly": "Every year"}
#: the most occurrences of one repeating event drawn in one view (a guard against huge ranges)
MAX_OCCURRENCES = 1000
#: the longest range one request may ask for, in days (about 13 months)
MAX_RANGE_DAYS = 400
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


# ---------------------------------------------------------------------- time zones
def get_zone(name: str | None) -> Any:
    """The ``ZoneInfo`` for ``name``, or None for the server's own time zone. Raises ValueError on a bad name."""
    if not name:
        return None
    if ZoneInfo is None:  # pragma: no cover
        raise ValueError("Time zones need Python 3.9+")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"Unknown time zone {name!r}. Use a name like 'Asia/Kolkata'.") from None


def now(zone: Any = None) -> dt.datetime:
    """The wall-clock time now, in ``zone`` (or the server's zone), without an offset."""
    if zone is None:
        return dt.datetime.now().replace(microsecond=0)
    return dt.datetime.now(zone).replace(tzinfo=None, microsecond=0)


def today(zone: Any = None) -> dt.date:
    return now(zone).date()


def to_wall(value: Any, zone: Any = None) -> Any:
    """Turn a time with an offset into the wall-clock time in ``zone`` (naive). Naive values pass through."""
    if isinstance(value, dt.datetime) and value.tzinfo is not None:
        value = value.astimezone(zone) if zone is not None else value.astimezone()
        return value.replace(tzinfo=None)
    return value


def parse_date(value: Any, default: dt.date | None = None) -> dt.date | None:
    """``"2026-10-11"`` (or a longer ISO string) to a date; ``default`` when it is missing or wrong."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if not value or not isinstance(value, str):
        return default
    try:
        return dt.date.fromisoformat(value.strip()[:10])
    except ValueError:
        return default


def parse_datetime(value: Any, zone: Any = None) -> dt.datetime | None:
    """An ISO date or date-time (with or without an offset, ``Z`` allowed) to a wall-clock time in ``zone``."""
    if isinstance(value, dt.datetime):
        return to_wall(value, zone)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        day = parse_date(text)
        return dt.datetime.combine(day, dt.time.min) if day and len(text) == 10 else None
    return to_wall(parsed, zone)


# ---------------------------------------------------------------------- items
def _as_datetime(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    raise TypeError(f"Expected a date or datetime, got {type(value).__name__}")


@dataclass
class CalendarItem:
    """One thing on the calendar. Plugins return these from their sources.

    - ``start`` / ``end``: dates (all-day) or datetimes. For an all-day item ``end`` is its last day
      (inclusive). For a timed item ``end`` is when it finishes; leave it out for a point in time.
    - ``url``: where a click goes. ``editable`` items can be dragged to another day (calendar events only).
    """

    title: str
    start: Any
    end: Any = None
    all_day: bool = False
    #: a panel color name (primary, success, danger...) or a hex color; empty: the source's color
    color: str | None = None
    url: str | None = None
    source: str = "events"
    icon: str | None = None
    description: str | None = None
    location: str | None = None
    #: a stable id, unique within its source (used for .ics files and drag-and-drop)
    id: str | None = None
    editable: bool = False
    #: the calendar event behind this item (drag-and-drop moves it)
    record_id: int | None = None
    #: for repeating events: this is one of the repeats
    repeating: bool = False
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.start, dt.date) and not isinstance(self.start, dt.datetime):
            self.all_day = True
        self.start = _as_datetime(self.start)
        if self.start is None:
            raise ValueError("A calendar item needs a start")
        self.end = _as_datetime(self.end)
        if self.all_day:
            self.start = self.start.replace(hour=0, minute=0, second=0, microsecond=0)
            if self.end is not None:
                self.end = self.end.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.end is not None and self.end < self.start:
            self.end = self.start  # an end before the start is treated as no length at all
        self.title = str(self.title or "").strip() or "(no title)"

    @classmethod
    def coerce(cls, value: Any, source: str, zone: Any = None) -> CalendarItem:
        """Accept a CalendarItem or a dict with the same keys; move times with an offset into ``zone``."""
        if isinstance(value, CalendarItem):
            item = value
        elif isinstance(value, dict):
            known = {k: v for k, v in value.items() if k in cls.__dataclass_fields__}
            item = cls(**known)
        else:
            raise TypeError(f"A calendar source returned {type(value).__name__}, not a CalendarItem or dict")
        if zone is not None or (item.start and item.start.tzinfo) or (item.end and item.end.tzinfo):
            item.start = to_wall(item.start, zone)
            item.end = to_wall(item.end, zone)
        if item.source == "events":  # the default: name the source it came from
            item.source = source
        return item

    @property
    def first_day(self) -> dt.date:
        return self.start.date()

    @property
    def last_day(self) -> dt.date:
        if self.end is None:
            return self.start.date()
        if self.all_day:
            return max(self.end.date(), self.start.date())
        if self.end <= self.start:
            return self.start.date()
        # a meeting that ends at midnight belongs to the day before
        return (self.end - dt.timedelta(microseconds=1)).date()

    @property
    def is_multi_day(self) -> bool:
        return self.last_day > self.first_day

    def touches(self, first: dt.date, last: dt.date) -> bool:
        """Whether the item is on any day from ``first`` to ``last`` (both included)."""
        return self.first_day <= last and self.last_day >= first

    def time_label(self, day: dt.date | None = None) -> str:
        """``09:30``, ``09:30–10:00``, ``All day``, or ``Until 11:00`` / ``From 22:00`` on the edge days."""
        if self.all_day:
            return "All day"
        starts_today = day is None or self.first_day == day
        ends_today = day is None or self.last_day == day
        start = self.start.strftime("%H:%M")
        end = self.end.strftime("%H:%M") if self.end and self.end > self.start else None
        if starts_today and ends_today:
            return f"{start}–{end}" if end else start
        if starts_today:
            return f"From {start}"
        if ends_today and end:
            return f"Until {end}"
        return "All day"

    def sort_key(self, day: dt.date | None = None) -> tuple:
        # all-day and multi-day items first, then by time, then by title
        on_from_before = day is not None and self.first_day < day
        return (0 if self.all_day or on_from_before else 1, self.start, self.title.lower())


def color_css(color: str | None, fallback: str = "primary") -> tuple[str, str]:
    """CSS for an item's color: the strong color and a soft background."""
    from tungsten.support.colors import COLOR_NAMES

    value = (color or "").strip()
    if HEX.match(value):
        return value, f"color-mix(in srgb, {value} 16%, transparent)"
    name = value if value in COLOR_NAMES else fallback if fallback in COLOR_NAMES else "primary"
    return f"rgb(var(--tw-c-{name}-500))", f"rgb(var(--tw-c-{name}-500) / .14)"


# ---------------------------------------------------------------------- grids
def add_months(day: Any, months: int) -> Any:
    """Move ``day`` (a date or datetime) by whole months, keeping the day of the month when it exists
    (31 Jan + 1 month is 28 or 29 Feb)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    if year < dt.MINYEAR or year > dt.MAXYEAR:
        raise OverflowError("Date out of range")
    return day.replace(year=year, month=month, day=min(day.day, _cal.monthrange(year, month)[1]))


def week_start(day: dt.date, first_weekday: int = 0) -> dt.date:
    """The first day of the week holding ``day``. ``first_weekday``: 0 Monday ... 6 Sunday."""
    return day - dt.timedelta(days=(day.weekday() - first_weekday) % 7)


def month_weeks(year: int, month: int, first_weekday: int = 0) -> list[list[dt.date]]:
    """The weeks shown for a month: full weeks from the one holding the 1st to the one holding the last day."""
    first = dt.date(year, month, 1)
    last = dt.date(year, month, _cal.monthrange(year, month)[1])
    start = week_start(first, first_weekday)
    end = week_start(last, first_weekday) + dt.timedelta(days=6)
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    return [days[i:i + 7] for i in range(0, len(days), 7)]


def weekday_names(first_weekday: int = 0, short: bool = True) -> list[str]:
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] if short else \
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return names[first_weekday:] + names[:first_weekday]


def view_range(view: str, day: dt.date, first_weekday: int = 0, list_days: int = 30) -> tuple[dt.date, dt.date]:
    """First and last day (both included) a view shows."""
    if view == "month":
        weeks = month_weeks(day.year, day.month, first_weekday)
        return weeks[0][0], weeks[-1][-1]
    if view == "week":
        start = week_start(day, first_weekday)
        return start, start + dt.timedelta(days=6)
    if view == "day":
        return day, day
    return day, day + dt.timedelta(days=max(1, list_days) - 1)


def shift(view: str, day: dt.date, steps: int, list_days: int = 30) -> dt.date:
    """The date ``steps`` views before (negative) or after ``day``."""
    try:
        if view == "month":
            return add_months(day.replace(day=1), steps)
        if view == "week":
            return day + dt.timedelta(days=7 * steps)
        if view == "day":
            return day + dt.timedelta(days=steps)
        return day + dt.timedelta(days=max(1, list_days) * steps)
    except (OverflowError, ValueError):
        return day


def by_day(items: Iterable[CalendarItem], first: dt.date, last: dt.date) -> dict[dt.date, list[CalendarItem]]:
    """Each day from ``first`` to ``last`` with the items on it, sorted (multi-day items on every day)."""
    days: dict[dt.date, list[CalendarItem]] = {}
    span = (last - first).days
    for i in range(span + 1):
        days[first + dt.timedelta(days=i)] = []
    for item in items:
        a, b = max(item.first_day, first), min(item.last_day, last)
        while a <= b:
            days[a].append(item)
            a += dt.timedelta(days=1)
    for day, rows in days.items():
        rows.sort(key=lambda it, d=day: it.sort_key(d))
    return days


# ---------------------------------------------------------------------- repeating events
def occurrences(start: dt.datetime, end: dt.datetime | None, repeat: str | None, every: int | None,
                until: dt.date | None, first: dt.date, last: dt.date, all_day: bool = False,
                limit: int = MAX_OCCURRENCES) -> list[tuple[dt.datetime, dt.datetime | None]]:
    """Start and end of each time an event happens between ``first`` and ``last`` (both included).

    Monthly events on the 29th-31st fall on the last day of shorter months; yearly events on 29 Feb
    fall on 28 Feb in other years. ``every`` is "every N days/weeks/months/years".
    """
    every = max(1, int(every or 1))
    length = (end - start) if end is not None and end > start else None

    def last_day(s: dt.datetime) -> dt.date:
        if length is None:
            return s.date()
        e = s + length
        return e.date() if all_day else (e - dt.timedelta(microseconds=1)).date()

    span_days = (last_day(start) - start.date()).days
    repeat = repeat or "none"
    if repeat not in REPEATS or repeat == "none":
        return [(start, start + length if length else end)] if start.date() <= last and last_day(start) >= first \
            else []
    stop = last if until is None else min(last, until)
    if start.date() > stop:
        return []

    if repeat in ("daily", "weekly"):
        step = dt.timedelta(days=every * (7 if repeat == "weekly" else 1))
        gap = (first - start.date()).days - span_days - 1
        k = max(0, gap // step.days)

        def nth(n: int) -> dt.datetime:
            return start + step * n
    else:
        months = every * (12 if repeat == "yearly" else 1)
        gap = (first.year - start.year) * 12 + first.month - start.month - (span_days // 28 + 2)
        k = max(0, gap // months)

        def nth(n: int) -> dt.datetime:
            return add_months(start, months * n)

    out: list[tuple[dt.datetime, dt.datetime | None]] = []
    while len(out) < limit:
        try:
            s = nth(k)
        except (OverflowError, ValueError):
            break
        if s.date() > stop:
            break
        if last_day(s) >= first:
            out.append((s, s + length if length else None))
        k += 1
    return out


# ---------------------------------------------------------------------- .ics files
def _ics_escape(text: Any) -> str:
    return (str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def _fold(line: str) -> str:
    """Split a content line into pieces of at most 75 bytes (RFC 5545), never inside a character."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current, size, limit = [], [], 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            parts.append("".join(current))
            current, size, limit = [], 0, 74  # continuation lines start with a space
        current.append(ch)
        size += n
    parts.append("".join(current))
    return "\r\n ".join(parts)


def _ics_time(value: dt.datetime, zone: Any) -> str:
    if zone is not None:  # a known zone: send UTC so every app shows the right local time
        try:
            aware = value.replace(tzinfo=zone)
            return aware.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        except (OverflowError, ValueError):
            pass
    return value.strftime("%Y%m%dT%H%M%S")  # "floating": the same clock time everywhere


def ics_calendar(items: Iterable[CalendarItem], name: str = "Calendar", zone: Any = None,
                 domain: str = "tungsten", stamp: dt.datetime | None = None) -> str:
    """An iCalendar (.ics) file with one VEVENT per item."""
    stamp = stamp or dt.datetime.now(dt.timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Prism Infoways//Tungsten Calendar//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_escape(name)}"]
    if zone is not None and getattr(zone, "key", None):
        lines.append(f"X-WR-TIMEZONE:{zone.key}")
    for item in items:
        uid = f"{item.source}-{item.id or abs(hash((item.title, item.start)))}-{item.start:%Y%m%d}@{domain}"
        lines += ["BEGIN:VEVENT", f"UID:{_ics_escape(uid)}", f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}"]
        if item.all_day:
            lines.append(f"DTSTART;VALUE=DATE:{item.first_day:%Y%m%d}")
            lines.append(f"DTEND;VALUE=DATE:{item.last_day + dt.timedelta(days=1):%Y%m%d}")
        else:
            lines.append(f"DTSTART:{_ics_time(item.start, zone)}")
            if item.end is not None and item.end > item.start:
                lines.append(f"DTEND:{_ics_time(item.end, zone)}")
        lines.append(f"SUMMARY:{_ics_escape(item.title)}")
        if item.description:
            lines.append(f"DESCRIPTION:{_ics_escape(item.description)}")
        if item.location:
            lines.append(f"LOCATION:{_ics_escape(item.location)}")
        if item.url:
            lines.append(f"URL:{item.url}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
