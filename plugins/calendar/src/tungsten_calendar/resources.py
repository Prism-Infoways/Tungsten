"""The "Events" list and form."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import or_, select

from tungsten import Resource
from tungsten.actions import Action, ActionGroup, DeleteAction, DeleteBulkAction, EditAction
from tungsten.forms import DatePicker, DateTimePicker, Section, Select, Textarea, TextInput, Toggle
from tungsten.importexport import ExportAction, ExportBulkAction
from tungsten.support.colors import COLOR_NAMES
from tungsten.tables import DateFilter, ListTab, SelectFilter, TextColumn

from .models import CalendarEvent
from .service import REPEATS, parse_date, parse_datetime


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("calendar") if ctx is not None else None


def _kinds(ctx: Any) -> dict:
    plugin = _plugin(ctx)
    from . import DEFAULT_KINDS

    return plugin.kinds if plugin is not None else DEFAULT_KINDS


def user_key(ctx: Any) -> str | None:
    """The signed-in user's id as text (None without a user)."""
    if ctx is None or getattr(ctx, "user", None) is None:
        return None
    return str(ctx.panel.auth.user_id(ctx.user))


def _now(ctx: Any) -> dt.datetime:
    plugin = _plugin(ctx)
    return plugin.now() if plugin is not None else dt.datetime.now().replace(microsecond=0)


def _asked_start(request: Any, ctx: Any) -> dt.datetime:
    """``?date=2026-10-12&time=14:00`` from a click on the calendar, else the next full hour."""
    params = request.query_params if request is not None else {}
    day = parse_date(params.get("date"))
    if day is not None:
        when = parse_datetime(f"{day.isoformat()}T{params.get('time')}") if params.get("time") else None
        return when or dt.datetime.combine(day, dt.time(9, 0))
    return (_now(ctx) + dt.timedelta(hours=1)).replace(minute=0, second=0)


def _asked_day(request: Any, ctx: Any) -> dt.date:
    return _asked_start(request, ctx).date()


def _asked_all_day(request: Any) -> bool:
    return bool(request is not None and request.query_params.get("all_day") in ("1", "true"))


def normalize(data: dict, ctx: Any = None) -> dict:
    """Make the form data consistent before it is saved.

    - all-day events take their dates from the date pickers and start at midnight
    - an end before the start is moved to the start; a repeat ends no earlier than the event starts
    """
    data = dict(data)
    start_day, end_day = data.pop("start_date", None), data.pop("end_date", None)
    if "title" in data and isinstance(data["title"], str):
        data["title"] = data["title"].strip()
    if data.get("all_day"):
        start_day = parse_date(start_day) or (data["starts_at"].date() if data.get("starts_at") else None)
        if start_day is not None:
            end_day = parse_date(end_day) or start_day
            data["starts_at"] = dt.datetime.combine(start_day, dt.time.min)
            data["ends_at"] = dt.datetime.combine(max(end_day, start_day), dt.time.min)
    elif data.get("starts_at") is not None and data.get("ends_at") is not None and data["ends_at"] < data["starts_at"]:
        data["ends_at"] = data["starts_at"]
    if "repeat" in data:
        if not data.get("repeat") or data["repeat"] == "none":
            data["repeat"], data["repeat_every"], data["repeat_until"] = "none", 1, None
        else:
            try:
                data["repeat_every"] = min(365, max(1, int(data.get("repeat_every") or 1)))
            except (TypeError, ValueError):
                data["repeat_every"] = 1
            until, starts = data.get("repeat_until"), data.get("starts_at")
            if until is not None and starts is not None and until < starts.date():
                data["repeat_until"] = starts.date()
    if not data.get("color"):
        data["color"] = None
    return data


def _switch_all_day(state: Any, get: Any, set: Any) -> None:
    """Carry the dates over when "All day" is switched, so the newly shown pickers are not empty."""
    on = state in (True, 1, "1", "true", "on")
    if on:
        if not get("start_date") and get("starts_at"):
            set("start_date", str(get("starts_at"))[:10])
        if not get("end_date") and (get("ends_at") or get("starts_at")):
            set("end_date", str(get("ends_at") or get("starts_at"))[:10])
    elif get("start_date"):
        if not get("starts_at"):
            set("starts_at", f"{str(get('start_date'))[:10]}T09:00")
        if not get("ends_at"):
            set("ends_at", f"{str(get('end_date') or get('start_date'))[:10]}T10:00")


def _repeating(get: Any) -> bool:
    return bool(get("repeat")) and get("repeat") != "none"


class CalendarEventResource(Resource):
    model = CalendarEvent
    slug = "calendar-events"
    icon = "calendar-plus"
    navigation_group = "Calendar"
    navigation_sort = 2
    label = "Event"
    navigation_label = "Events"
    description = "Meetings, calls, tasks and reminders. They show on the calendar."
    pages = ("index", "create", "edit")
    global_search_attributes = ["title", "location"]

    @classmethod
    def query(cls, ctx):
        """Everyone sees shared events; private ones only by the person who made them."""
        query = select(CalendarEvent)
        if not ctx.panel.auth.enabled:
            return query
        me = user_key(ctx)
        if me is None:
            return query.where(CalendarEvent.is_private.is_(False))
        return query.where(or_(CalendarEvent.is_private.is_(False), CalendarEvent.user_id == me))

    @classmethod
    def form(cls, form):
        def kind_options(ctx):
            return {k: v[0] for k, v in _kinds(ctx).items()}

        not_all_day = lambda get: not get("all_day")
        return form.columns(2).schema([
            Section("Event").icon("calendar").columns(2).schema([
                TextInput("title").required().max_length(200).autofocus().column_span("full"),
                Select("kind").label("Type").options(kind_options).default(
                    lambda ctx: next(iter(_kinds(ctx)), None)).required().native(),
                Toggle("all_day").label("All day").live().after_state_updated(_switch_all_day)
                .default(lambda request: _asked_all_day(request)),
                DateTimePicker("starts_at").label("Starts").required().visible(not_all_day)
                .default(lambda request, ctx: _asked_start(request, ctx)).live(on_blur=True),
                DateTimePicker("ends_at").label("Ends").visible(not_all_day)
                .default(lambda request, ctx: _asked_start(request, ctx) + dt.timedelta(hours=1))
                .min_date(lambda get: get("starts_at"))
                .helper_text("Leave empty for a reminder at one time."),
                DatePicker("start_date").label("From").required().visible(lambda get: bool(get("all_day")))
                .default(lambda request, ctx: _asked_day(request, ctx)).live(on_blur=True),
                DatePicker("end_date").label("To").visible(lambda get: bool(get("all_day")))
                .default(lambda request, ctx: _asked_day(request, ctx))
                .min_date(lambda get: get("start_date")),
                TextInput("location").max_length(200).placeholder("Office, phone or video link")
                .column_span("full"),
                Textarea("description").label("Notes").rows(3).max_length(5000).column_span("full"),
            ]).column_span("full"),
            Section("Repeat and sharing").icon("repeat").columns(2).collapsible().schema([
                Select("repeat").options(REPEATS).default("none").native().live(),
                TextInput("repeat_every").label("Repeat every").integer().min_value(1).max_value(365).default(1)
                .visible(_repeating).helper_text("1 = every time, 2 = every other..."),
                DatePicker("repeat_until").label("Repeat until").visible(_repeating)
                .helper_text("Leave empty to repeat with no end.")
                .min_date(lambda get: get("start_date") if get("all_day") else get("starts_at")),
                Select("color").label("Color").options({c: c.title() for c in COLOR_NAMES})
                .placeholder("Same as the type").native(),
                Toggle("is_private").label("Only me").helper_text("Others won't see this event."),
            ]).column_span("full"),
        ])

    @classmethod
    def mutate_form_data_before_create(cls, data, ctx):
        return normalize(data, ctx)

    @classmethod
    def before_create(cls, record, ctx):
        record.user_id = user_key(ctx)  # the owner: private events show only to them

    @classmethod
    def mutate_form_data_before_save(cls, data, ctx):
        return normalize(data, ctx)

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        actions = super().header_actions(ctx, page, record)
        calendar = Action("open_calendar").label("Open calendar").icon("calendar-days").color("gray")
        if page in ("index", "list"):
            return [calendar.url(ctx.url("calendar")), *actions]
        if page == "edit" and record is not None and record.starts_at:
            return [calendar.url(ctx.url("calendar", date=record.starts_at.date().isoformat())), *actions]
        return actions

    @classmethod
    def table(cls, table):
        def kind_label(state, ctx):
            return _kinds(ctx).get(state or "", (state or "",))[0]

        def kind_color(record, ctx):
            return record.color or _kinds(ctx).get(record.kind or "", ("", "gray"))[1]

        def when(record):
            if record.starts_at is None:
                return ""
            if record.all_day:
                first, last = record.start_date, record.end_date
                return f"{first:%d %b %Y}" + (f" – {last:%d %b %Y}" if last and last != first else "")
            text = f"{record.starts_at:%d %b %Y, %H:%M}"
            if record.ends_at and record.ends_at > record.starts_at:
                same = record.ends_at.date() == record.starts_at.date()
                text += f" – {record.ends_at:%H:%M}" if same else f" – {record.ends_at:%d %b %Y, %H:%M}"
            return text

        def upcoming(query, model, ctx):
            start = dt.datetime.combine(_now(ctx).date(), dt.time.min)
            return query.where(or_(model.starts_at >= start, model.ends_at >= start,
                                   (model.repeat != "none") & or_(model.repeat_until.is_(None),
                                                                  model.repeat_until >= start.date())))

        def past(query, model, ctx):
            start = dt.datetime.combine(_now(ctx).date(), dt.time.min)
            return query.where(model.starts_at < start, or_(model.ends_at.is_(None), model.ends_at < start),
                               or_(model.repeat == "none", model.repeat_until < start.date()))

        def mine(query, model, ctx):
            me = user_key(ctx)
            return query.where(model.user_id == me) if me is not None else query

        return (
            table.columns([
                TextColumn("title").weight("medium").searchable().sortable()
                .description(lambda record: record.location),
                TextColumn("kind").label("Type").badge().format_state_using(kind_label).color(kind_color),
                TextColumn("starts_at").label("When").state(when).sortable(),
                TextColumn("repeat").format_state_using(lambda state: REPEATS.get(state or "none", state))
                .toggleable(),
                TextColumn("is_private").label("Shared").format_state_using(
                    lambda state: "Only me" if state else "Everyone").toggleable(hidden_by_default=True),
                TextColumn("created_at").label("Added").since().sortable().toggleable(hidden_by_default=True),
            ])
            .filters([
                SelectFilter("kind").label("Type").options(lambda ctx: {k: v[0] for k, v in _kinds(ctx).items()}),
                SelectFilter("repeat").options(REPEATS),
                DateFilter("starts_at").label("Starts"),
            ])
            .tabs([
                ListTab("upcoming").label("Upcoming").query(upcoming),
                ListTab("mine").label("Mine").query(mine),
                ListTab("past").label("Past").query(past),
                ListTab("all").label("All"),
            ])
            .actions([ActionGroup([EditAction(), DeleteAction()])])
            .bulk_actions([ExportBulkAction(), DeleteBulkAction()])
            .header_actions([ExportAction()])
            .record_url(lambda record, ctx: CalendarEventResource.get_url(ctx, "edit", record))
            .default_sort("starts_at", "asc")
            .empty_state("No events yet", "Add meetings, calls and reminders, or click a day on the calendar.",
                         "calendar")
        )
