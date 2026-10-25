"""Calendar links: .ics download, the private subscribe link, and drag-and-drop moves."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fastapi import Request
from markupsafe import Markup, escape
from sqlalchemy import select
from starlette.responses import Response

from tungsten import Notification
from tungsten.actions import Action
from tungsten.routes import Routes

from .models import CalendarEvent, CalendarFeed
from .service import ics_calendar, view_range

log = logging.getLogger("tungsten.calendar")

#: the subscribe link covers this many days back and ahead
FEED_PAST_DAYS = 30
FEED_FUTURE_DAYS = 365
#: a drag can move an event at most this many days
MAX_MOVE_DAYS = 3660


def _user_key(ctx: Any) -> str | None:
    return str(ctx.panel.auth.user_id(ctx.user)) if getattr(ctx, "user", None) is not None else None


def feed_for(db: Any, user_id: str, create: bool = True) -> CalendarFeed | None:
    feed = db.scalars(select(CalendarFeed).where(CalendarFeed.user_id == user_id)).first()
    if feed is None and create:
        feed = CalendarFeed(user_id=user_id)
        db.add(feed)
        db.commit()
    return feed


def feed_url(ctx: Any, feed: CalendarFeed) -> str:
    return ctx.panel.absolute_url(ctx, ctx.url("calendar", "feed", f"{feed.token}.ics"))


def _subscribe_content(ctx: Any) -> Markup:
    me = _user_key(ctx)
    if me is None:
        return Markup("")
    url = feed_url(ctx, feed_for(ctx.db, me))
    steps = [
        ("Google Calendar", "Other calendars → + → From URL, and paste the link."),
        ("Outlook", "Add calendar → Subscribe from web, and paste the link."),
        ("iPhone", "Settings → Calendar → Accounts → Add account → Other → Add subscribed calendar."),
    ]
    rows = "".join(f'<li><strong>{escape(a)}:</strong> {escape(b)}</li>' for a, b in steps)
    return Markup(
        '<div class="grid gap-3 text-sm text-gray-600 dark:text-gray-300">'
        '<p>Paste this private link in your calendar app. It shows what you can see here, '
        'from a month back to a year ahead, and updates on its own.</p>'
        f'<input type="text" readonly value="{escape(url)}" onclick="this.select()" data-calendar-feed '
        'class="w-full rounded-xl border-0 bg-gray-50 px-3 py-2 text-sm text-gray-950 ring-1 ring-gray-950/10 '
        'dark:bg-white/5 dark:text-white dark:ring-white/20" style="font-family:monospace">'
        f'<ul class="grid gap-1" style="list-style:disc;padding-left:20px">{rows}</ul>'
        '<p class="text-gray-500 dark:text-gray-400">Keep it secret: anyone with the link can read it. '
        'Use "Reset subscribe link" if it leaks.</p></div>')


def subscribe_action() -> Action:
    return (Action("subscribe").label("Subscribe on phone").icon("smartphone")
            .modal_heading("Subscribe to your calendar").modal_content(lambda ctx: _subscribe_content(ctx))
            .modal_submit_action(False).modal_cancel_action_label("Close"))


def reset_action() -> Action:
    def run(ctx: Any, db: Any) -> None:
        me = _user_key(ctx)
        feed = feed_for(db, me, create=False) if me else None
        if feed is not None:
            db.delete(feed)
            db.commit()

    return (Action("reset_feed").label("Reset subscribe link").icon("rotate-ccw").color("danger")
            .requires_confirmation().modal_description("The old link stops working. Apps that use it must "
                                                       "subscribe again with the new link.")
            .action(run).success_notification_title("Subscribe link reset"))


def _ics_response(text: str, filename: str | None) -> Response:
    headers = {"Cache-Control": "private, max-age=300"}
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(text, media_type="text/calendar; charset=utf-8", headers=headers)


def _domain(ctx: Any) -> str:
    return (ctx.panel.app_url or "").split("://")[-1].split("/")[0] or ctx.request.url.hostname or "tungsten"


def add_routes(app: Any, panel: Any, plugin: Any) -> None:
    routes = Routes(panel)

    def export(ctx: Any, fd: Any):
        from .pages import read_params

        p = read_params(ctx, plugin)
        first, last = view_range(p["view"], p["date"], plugin.first_weekday, plugin.list_days)
        items, _ = plugin.items(ctx, first, last, p["hidden"])
        text = ics_calendar(items, name=f"{panel.brand_name} calendar", zone=plugin.zone, domain=_domain(ctx))
        return _ics_response(text, f"calendar-{first.isoformat()}.ics")

    def feed(ctx: Any, fd: Any, token: str):
        token = token.removesuffix(".ics")
        row = ctx.db.scalars(select(CalendarFeed).where(CalendarFeed.token == token)).first() \
            if plugin.feeds and token else None
        user = panel.auth.find_by_id(ctx.db, row.user_id) if row is not None and panel.auth.enabled else None
        if user is None or not panel.auth.allowed(ctx, user):
            return Response("Not found", status_code=404, media_type="text/plain")
        ctx.user = user
        today = plugin.today()
        items, _ = plugin.items(ctx, today - dt.timedelta(days=FEED_PAST_DAYS),
                                today + dt.timedelta(days=FEED_FUTURE_DAYS))
        text = ics_calendar(items, name=f"{panel.brand_name} calendar", zone=plugin.zone, domain=_domain(ctx))
        return _ics_response(text, None)

    def move(ctx: Any, fd: Any):
        """Drag-and-drop: move an event by whole days, keeping its time and length."""
        resource = ctx.panel.resource_for_model(CalendarEvent)
        try:
            event_id = int(fd.get("id") or "")
            days = int(fd.get("days") or "")
        except (TypeError, ValueError):
            return routes.error(ctx, 422, "Can't move", "Send the event and the number of days.")
        if abs(days) > MAX_MOVE_DAYS:
            return routes.error(ctx, 422, "Can't move", "That is too far.")
        event = resource.host().find_record(ctx, event_id, with_trashed=False) if resource is not None else None
        if event is None:
            return routes.error(ctx, 404, "Event not found", "It may have been deleted. Refresh the page.")
        if not resource.can(ctx, "update", event):
            return routes.error(ctx, 403, "Not allowed", "You can't change this event.")
        if event.is_repeating:
            return routes.error(ctx, 422, "Open the event to move it", "This event repeats; change its dates there.")
        if days:
            step = dt.timedelta(days=days)
            try:
                event.starts_at = event.starts_at + step
                event.ends_at = event.ends_at + step if event.ends_at is not None else None
            except OverflowError:
                ctx.db.rollback()
                return routes.error(ctx, 422, "Can't move", "That date is out of range.")
            ctx.db.commit()
            Notification("Event moved").body(f"{event.title}: {event.starts_at:%d %b %Y}").success().send(ctx)
        return ctx.refresh()

    @app.get("/calendar/export.ics")
    async def calendar_export(request: Request):
        return await routes.run(request, export)

    @app.get("/calendar/feed/{token}")
    async def calendar_feed(request: Request, token: str):
        return await routes.run(request, feed, public=True, token=token)

    @app.post("/calendar/move")
    async def calendar_move(request: Request):
        return await routes.run(request, move, read_form=True)
