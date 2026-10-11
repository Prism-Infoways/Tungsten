"""Where calendar items come from: the plugin's own events, and dates kept by other Tungsten plugins.

A source is a function ``fn(ctx, start, end)`` that returns :class:`CalendarItem` objects (or dicts)
for the days ``start`` to ``end`` (both included). Each source only shows what the signed-in user may
see: it asks the other plugin's resource for permission and uses that resource's own query, so its
filters (tenancy, "only my records", soft delete) still apply.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import extract, func, or_

from .models import CalendarEvent
from .service import CalendarItem, add_months, occurrences


@dataclass
class Source:
    key: str
    label: str
    fn: Callable
    color: str = "gray"
    icon: str = "calendar"
    #: shown until the user hides it with the filter chips
    default: bool = True


def window(start: dt.date, end: dt.date) -> tuple[dt.datetime, dt.datetime]:
    """``start`` 00:00 and the midnight after ``end``: for ``column >= a and column < b`` queries."""
    return dt.datetime.combine(start, dt.time.min), dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min)


def visible_resource(ctx: Any, slug: str | None = None, model: Any = None) -> Any:
    """The panel's resource (by slug or model) when this user may list its records, else None."""
    panel = ctx.panel
    resource = panel.resource(slug) if slug else panel.resource_for_model(model) if model is not None else None
    if resource is None:
        return None
    try:
        return resource if resource.can(ctx, "view_any") else None
    except Exception:  # noqa: BLE001  a broken policy hides the source instead of breaking the calendar
        return None


def scoped(ctx: Any, resource: Any):
    """The resource's own query, with its tenancy scope and without soft-deleted rows."""
    return resource.host().scoped_query(ctx, with_trashed=False)


def record_url(ctx: Any, resource: Any, record: Any) -> str | None:
    """Link to the record's view page (or edit page) when the user may open it."""
    try:
        if resource.has_page("view") and resource.can(ctx, "view", record):
            return resource.get_url(ctx, "view", record)
        if resource.has_page("edit") and resource.can(ctx, "update", record):
            return resource.get_url(ctx, "edit", record)
        return resource.get_url(ctx)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------- the plugin's own events
def event_source(ctx: Any, start: dt.date, end: dt.date, plugin: Any) -> list[CalendarItem]:
    resource = visible_resource(ctx, model=CalendarEvent)
    if resource is None:
        return []
    a, b = window(start, end)
    repeating = func.coalesce(CalendarEvent.repeat, "none") != "none"
    query = scoped(ctx, resource).where(
        CalendarEvent.starts_at < b,
        or_(func.coalesce(CalendarEvent.ends_at, CalendarEvent.starts_at) >= a,
            repeating & or_(CalendarEvent.repeat_until.is_(None), CalendarEvent.repeat_until >= start)),
    ).order_by(CalendarEvent.starts_at)
    items: list[CalendarItem] = []
    for event in ctx.db.scalars(query):
        if event.starts_at is None:
            continue
        kind = plugin.kinds.get(event.kind or "") or ("Event", "primary", "calendar")
        color = event.color or kind[1]
        editable = not event.is_repeating and _can(resource, ctx, "update", event)
        url = record_url(ctx, resource, event)
        for s, e in occurrences(event.starts_at, event.ends_at, event.repeat, event.repeat_every,
                                event.repeat_until, start, end, all_day=event.all_day):
            items.append(CalendarItem(
                title=event.title, start=s, end=e, all_day=event.all_day, color=color, url=url, source="events",
                icon=kind[2], description=event.description, location=event.location, id=str(event.id),
                editable=editable, record_id=event.id, repeating=event.is_repeating,
                extra={"kind": kind[0], "private": event.is_private}))
    return items


def _can(resource: Any, ctx: Any, ability: str, record: Any) -> bool:
    try:
        return bool(resource.can(ctx, ability, record))
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------- HR
def hr_leave_source(ctx: Any, start: dt.date, end: dt.date) -> list[CalendarItem]:
    """Approved leave: who is away, day by day."""
    resource = visible_resource(ctx, "leave-requests")
    if resource is None:
        return []
    model = resource.model
    query = scoped(ctx, resource).where(model.status == "approved", model.start_date <= end,
                                        model.end_date >= start).order_by(model.start_date)
    items = []
    for leave in ctx.db.scalars(query):
        employee = getattr(leave, "employee", None)
        who = getattr(employee, "name", None) or "Someone"
        kind = leave.leave_type.name if getattr(leave, "leave_type", None) else "Leave"
        title = f"{who} on leave ({kind}{', half day' if leave.half_day else ''})"
        last = leave.start_date if leave.half_day else max(leave.end_date or leave.start_date, leave.start_date)
        color = getattr(getattr(leave, "leave_type", None), "color", None) or "warning"
        items.append(CalendarItem(title=title, start=leave.start_date, end=last, color=color, icon="plane",
                                  url=record_url(ctx, resource, leave), id=str(leave.id), description=leave.reason))
    return items


def hr_holiday_source(ctx: Any, start: dt.date, end: dt.date) -> list[CalendarItem]:
    resource = visible_resource(ctx, "holidays")
    if resource is None:
        return []
    model = resource.model
    query = scoped(ctx, resource).where(model.date >= start, model.date <= end).order_by(model.date)
    return [CalendarItem(title=f"{h.name}{' (optional)' if getattr(h, 'is_optional', False) else ''}", start=h.date,
                         color="success", icon="party-popper", url=record_url(ctx, resource, h), id=str(h.id))
            for h in ctx.db.scalars(query)]


def birthday_in(birth: dt.date, year: int) -> dt.date:
    """The birthday in ``year``; 29 Feb falls on 28 Feb in other years."""
    try:
        return birth.replace(year=year)
    except ValueError:
        return dt.date(year, 2, 28)


def hr_birthday_source(ctx: Any, start: dt.date, end: dt.date) -> list[CalendarItem]:
    resource = visible_resource(ctx, "employees")
    if resource is None:
        return []
    model = resource.model
    months, cursor = set(), start.replace(day=1)
    while cursor <= end and len(months) < 12:
        months.add(cursor.month)
        cursor = add_months(cursor, 1)
    query = scoped(ctx, resource).where(model.birth_date.is_not(None), model.status != "left")
    if len(months) < 12:
        query = query.where(extract("month", model.birth_date).in_(sorted(months)))
    items = []
    for person in ctx.db.scalars(query):
        for year in range(start.year, end.year + 1):
            day = birthday_in(person.birth_date, year)
            if start <= day <= end:
                items.append(CalendarItem(title=f"Birthday: {person.name}", start=day, color="pink", icon="cake",
                                          url=record_url(ctx, resource, person), id=f"{person.id}-{year}"))
    return items


# ---------------------------------------------------------------------- Leads
#: lead statuses that need no more follow-up
LEAD_CLOSED = ("won", "lost")


def leads_source(ctx: Any, start: dt.date, end: dt.date, plugin: Any = None) -> list[CalendarItem]:
    """Lead follow-ups that are still open."""
    try:
        from tungsten_leads.models import Lead
    except ImportError:
        return []
    resource = visible_resource(ctx, model=Lead)
    if resource is None:
        return []
    a, b = window(start, end)
    query = scoped(ctx, resource).where(Lead.follow_up_at >= a, Lead.follow_up_at < b,
                                        Lead.status.notin_(LEAD_CLOSED)).order_by(Lead.follow_up_at)
    late = plugin.now() if plugin is not None else dt.datetime.now()
    return [CalendarItem(title=f"Follow up: {lead.name}", start=lead.follow_up_at, icon="phone-call",
                         color="danger" if lead.follow_up_at < late else "info",
                         url=record_url(ctx, resource, lead), id=str(lead.id),
                         description=" · ".join(x for x in (lead.company, lead.phone, lead.email) if x) or None)
            for lead in ctx.db.scalars(query)]


# ---------------------------------------------------------------------- Tickets
TICKET_CLOSED = ("resolved", "closed")


def tickets_source(ctx: Any, start: dt.date, end: dt.date, plugin: Any = None) -> list[CalendarItem]:
    """When open tickets are due (their SLA)."""
    resource = visible_resource(ctx, "tickets")
    if resource is None:
        return []
    model = resource.model
    a, b = window(start, end)
    query = scoped(ctx, resource).where(model.due_at >= a, model.due_at < b,
                                        model.status.notin_(TICKET_CLOSED)).order_by(model.due_at)
    late = plugin.now() if plugin is not None else dt.datetime.now()
    return [CalendarItem(title=f"Due: {t.number or '#' + str(t.id)} {t.subject}", start=t.due_at, icon="life-buoy",
                         color="danger" if t.due_at < late else "warning", url=record_url(ctx, resource, t),
                         id=str(t.id))
            for t in ctx.db.scalars(query)]


# ---------------------------------------------------------------------- Finance
#: invoice statuses with nothing left to collect or pay
INVOICE_DONE = ("draft", "paid", "cancelled")


def finance_source(ctx: Any, start: dt.date, end: dt.date, plugin: Any = None) -> list[CalendarItem]:
    """Due dates of unpaid sales invoices and vendor bills."""
    today = plugin.now().date() if plugin is not None else dt.date.today()
    items = []
    for slug, word, icon in (("invoices", "Invoice", "file-text"), ("bills", "Bill", "receipt-text")):
        resource = visible_resource(ctx, slug)
        if resource is None:
            continue
        model = resource.model
        query = scoped(ctx, resource).where(model.due_date >= start, model.due_date <= end,
                                            model.status.notin_(INVOICE_DONE)).order_by(model.due_date)
        for doc in ctx.db.scalars(query):
            contact = getattr(getattr(doc, "contact", None), "name", None)
            title = f"{word} {doc.number or '#' + str(doc.id)} due" + (f" · {contact}" if contact else "")
            items.append(CalendarItem(title=title, start=doc.due_date, icon=icon,
                                      color="danger" if doc.due_date < today else "warning",
                                      url=record_url(ctx, resource, doc), id=f"{slug}-{doc.id}"))
    return items


# ---------------------------------------------------------------------- Blog
def blog_source(ctx: Any, start: dt.date, end: dt.date, plugin: Any = None) -> list[CalendarItem]:
    """Published posts, and posts scheduled for later."""
    try:
        from tungsten_blog.models import BlogPost
    except ImportError:
        return []
    resource = visible_resource(ctx, model=BlogPost)
    if resource is None:
        return []
    a, b = window(start, end)
    query = scoped(ctx, resource).where(BlogPost.status == "published", BlogPost.published_at >= a,
                                        BlogPost.published_at < b).order_by(BlogPost.published_at)
    current = plugin.now() if plugin is not None else dt.datetime.now()
    return [CalendarItem(title=f"{'Scheduled' if p.published_at > current else 'Published'}: {p.title}",
                         start=p.published_at, icon="newspaper", color="purple" if p.published_at > current else "gray",
                         url=record_url(ctx, resource, p), id=str(p.id))
            for p in ctx.db.scalars(query)]


#: (plugin id, key, label, fn, color, icon) of the plugins the calendar links with when they are installed
LINKS: list[tuple[str, str, str, Callable, str, str]] = [
    ("hr", "hr_leave", "Leave", hr_leave_source, "warning", "plane"),
    ("hr", "hr_holidays", "Holidays", hr_holiday_source, "success", "party-popper"),
    ("hr", "hr_birthdays", "Birthdays", hr_birthday_source, "pink", "cake"),
    ("leads", "leads", "Lead follow-ups", leads_source, "info", "phone-call"),
    ("tickets", "tickets", "Ticket due dates", tickets_source, "warning", "life-buoy"),
    ("finance", "finance", "Invoice due dates", finance_source, "danger", "file-text"),
    ("blog", "blog", "Blog posts", blog_source, "purple", "newspaper"),
]
