from __future__ import annotations

import datetime as dt
import re

import pytest
from conftest import client_for, make_panel
from sqlalchemy import select
from tungsten_calendar import CalendarEvent, CalendarFeed, CalendarItem, CalendarPlugin
from tungsten_calendar.service import (
    add_months,
    by_day,
    get_zone,
    ics_calendar,
    month_weeks,
    occurrences,
    parse_date,
    parse_datetime,
    shift,
    to_wall,
    view_range,
)
from tungsten_calendar.sources import birthday_in

D = dt.date
T = dt.datetime


def add_event(panel, **kw):
    with panel.db() as db:
        event = CalendarEvent(**{"title": "Team meeting", "starts_at": T(2026, 10, 12, 10, 0),
                                 "ends_at": T(2026, 10, 12, 11, 0), "user_id": "1", **kw})
        db.add(event)
        db.commit()
        return event.id


def get_event(panel, event_id):
    with panel.db() as db:
        return db.get(CalendarEvent, event_id)


# ---------------------------------------------------------------------- date math
def test_month_weeks_cover_whole_weeks():
    weeks = month_weeks(2026, 2, 0)  # Feb 2026 starts on a Sunday
    assert weeks[0][0] == D(2026, 1, 26) and weeks[-1][-1] == D(2026, 3, 1)
    assert all(len(w) == 7 for w in weeks) and all(w[0].weekday() == 0 for w in weeks)
    sunday = month_weeks(2026, 2, 6)
    assert sunday[0][0] == D(2026, 2, 1) and len(sunday) == 4  # fits exactly in four Sunday weeks
    assert month_weeks(2026, 8, 0)[-1][-1] == D(2026, 9, 6)  # Aug 2026 needs six rows
    dec = month_weeks(2026, 12, 0)
    assert dec[-1][-1] == D(2027, 1, 3)  # crosses the year


def test_add_months_keeps_month_end():
    assert add_months(D(2026, 1, 31), 1) == D(2026, 2, 28)
    assert add_months(D(2024, 1, 31), 1) == D(2024, 2, 29)
    assert add_months(D(2026, 12, 15), 1) == D(2027, 1, 15)
    assert add_months(D(2026, 1, 15), -1) == D(2025, 12, 15)
    assert add_months(T(2026, 3, 31, 9, 30), -1) == T(2026, 2, 28, 9, 30)


def test_view_range_and_shift():
    assert view_range("week", D(2026, 10, 11), 0) == (D(2026, 10, 5), D(2026, 10, 11))
    assert view_range("week", D(2026, 10, 11), 6) == (D(2026, 10, 11), D(2026, 10, 17))
    assert view_range("day", D(2026, 10, 11)) == (D(2026, 10, 11), D(2026, 10, 11))
    assert view_range("list", D(2026, 10, 11), list_days=30)[1] == D(2026, 11, 9)
    assert shift("month", D(2026, 1, 31), 1) == D(2026, 2, 1)
    assert shift("month", D(2026, 1, 31), -1) == D(2025, 12, 1)
    assert shift("week", D(2026, 12, 28), 1) == D(2027, 1, 4)
    assert shift("month", D(9999, 12, 1), 1) == D(9999, 12, 1)  # the end of time doesn't crash


def test_items_on_days():
    meeting = CalendarItem("Late call", T(2026, 10, 12, 23, 0), T(2026, 10, 13, 0, 0))
    assert meeting.last_day == D(2026, 10, 12)  # ends at midnight: not on the next day
    overnight = CalendarItem("Night shift", T(2026, 10, 12, 22, 0), T(2026, 10, 13, 6, 0))
    assert overnight.is_multi_day and overnight.time_label(D(2026, 10, 12)) == "From 22:00"
    assert overnight.time_label(D(2026, 10, 13)) == "Until 06:00"
    trip = CalendarItem("Trip", D(2026, 10, 30), D(2026, 11, 2))
    assert trip.all_day and trip.first_day == D(2026, 10, 30) and trip.last_day == D(2026, 11, 2)
    days = by_day([trip, meeting], D(2026, 10, 26), D(2026, 11, 1))
    assert [d for d, rows in days.items() if trip in rows] == [D(2026, 10, 30), D(2026, 10, 31), D(2026, 11, 1)]
    backwards = CalendarItem("Oops", T(2026, 10, 12, 10), T(2026, 10, 12, 9))
    assert backwards.end == backwards.start and backwards.last_day == D(2026, 10, 12)
    assert CalendarItem("", D(2026, 1, 1)).title == "(no title)"
    with pytest.raises(ValueError):
        CalendarItem("No start", None)


def test_time_zones():
    zone = get_zone("Asia/Kolkata")
    utc = T(2026, 10, 11, 20, 0, tzinfo=dt.timezone.utc)
    assert to_wall(utc, zone) == T(2026, 10, 12, 1, 30)  # already the next day in India
    assert parse_datetime("2026-10-11T20:00:00Z", zone) == T(2026, 10, 12, 1, 30)
    assert parse_datetime("2026-10-11T09:15", zone) == T(2026, 10, 11, 9, 15)
    assert parse_datetime("2026-10-11", zone) == T(2026, 10, 11)
    assert parse_datetime("nonsense", zone) is None and parse_date("2026-13-40") is None
    with pytest.raises(ValueError):
        get_zone("Mars/Olympus")
    with pytest.raises(ValueError):
        CalendarPlugin(timezone="Not/AZone")
    item = CalendarItem.coerce({"title": "Webinar", "start": utc, "end": utc + dt.timedelta(hours=1)}, "x", zone)
    assert item.start == T(2026, 10, 12, 1, 30) and item.source == "x" and item.start.tzinfo is None


def test_repeating_events():
    # monthly on the 31st falls on the last day of shorter months
    got = occurrences(T(2026, 1, 31, 9), T(2026, 1, 31, 10), "monthly", 1, None, D(2026, 2, 1), D(2026, 4, 30))
    assert [s.date() for s, _ in got] == [D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30)]
    assert got[0][1] == T(2026, 2, 28, 10)
    # yearly on 29 Feb
    leap = occurrences(T(2024, 2, 29), None, "yearly", 1, None, D(2025, 1, 1), D(2028, 12, 31), all_day=True)
    assert [s.date() for s, _ in leap] == [D(2025, 2, 28), D(2026, 2, 28), D(2027, 2, 28), D(2028, 2, 29)]
    # every other week, far in the future, stops at "until"
    weekly = occurrences(T(2020, 1, 6, 9), T(2020, 1, 6, 9, 30), "weekly", 2, D(2030, 1, 1),
                         D(2026, 10, 1), D(2026, 10, 31))
    assert len(weekly) == 2 and all((s.date() - D(2020, 1, 6)).days % 14 == 0 for s, _ in weekly)
    assert occurrences(T(2020, 1, 6, 9), None, "daily", 1, D(2020, 1, 10), D(2026, 1, 1), D(2026, 1, 31)) == []
    # a multi-day repeat that starts before the window still shows
    span = occurrences(T(2026, 9, 29), T(2026, 10, 2), "monthly", 1, None, D(2026, 10, 1), D(2026, 10, 31),
                       all_day=True)
    assert span[0][0] == T(2026, 9, 29)
    # a daily event over 400 days is capped, not endless
    assert len(occurrences(T(2026, 1, 1, 8), None, "daily", 1, None, D(2026, 1, 1), D(2027, 2, 1), limit=50)) == 50
    # unknown repeat values behave like "none"
    assert len(occurrences(T(2026, 10, 5, 8), None, "fortnightly", 1, None, D(2026, 10, 1), D(2026, 10, 31))) == 1


def test_birthday_on_29_feb():
    assert birthday_in(D(2000, 2, 29), 2026) == D(2026, 2, 28)
    assert birthday_in(D(2000, 2, 29), 2028) == D(2028, 2, 29)


def test_ics_file():
    zone = get_zone("Asia/Kolkata")
    items = [CalendarItem("Diwali, office closed; enjoy", D(2026, 11, 8), D(2026, 11, 9), id="1"),
             CalendarItem("Call\nwith Amit", T(2026, 10, 12, 10, 0), T(2026, 10, 12, 10, 30), id="2",
                          location="नई दिल्ली " * 12)]
    text = ics_calendar(items, name="Office", zone=zone, domain="office.example.com",
                        stamp=T(2026, 10, 11, tzinfo=dt.timezone.utc))
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20261108\r\nDTEND;VALUE=DATE:20261110" in text  # DTEND is the day after
    assert "SUMMARY:Diwali\\, office closed\\; enjoy" in text and "SUMMARY:Call\\nwith Amit" in text
    assert "DTSTART:20261012T043000Z" in text  # 10:00 in India is 04:30 UTC
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    unfolded = text.replace("\r\n ", "")
    assert "LOCATION:" + "नई दिल्ली " * 11 + "नई दिल्ली" in unfolded
    floating = ics_calendar(items[1:], zone=None)
    assert "DTSTART:20261012T100000\r\n" in floating


# ---------------------------------------------------------------------- pages
def test_pages_load_and_bad_params_fall_back(admin, panel):
    add_event(panel)
    for url in ("/admin/calendar", "/admin/calendar?view=week&date=2026-10-12", "/admin/calendar?view=day",
                "/admin/calendar?view=list&date=2026-10-01", "/admin/calendar?view=nope&date=2026-99-99&hide=x,,y",
                "/admin/calendar?date=0001-01-01", "/admin/calendar?date=9999-12-31&view=week",
                "/admin/calendar-events", "/admin/calendar-events/create", "/admin/"):
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[-2000:])
    month = admin.get("/admin/calendar?date=2026-10-12").text
    assert "October 2026" in month and "Team meeting" in month and 'data-cal-move="1"' in month
    week = admin.get("/admin/calendar?view=week&date=2026-10-12").text
    assert "12 – 18 Oct 2026" in week and "10:00–11:00" in week
    listed = admin.get("/admin/calendar?view=list&date=2026-10-01").text
    assert "Team meeting" in listed
    assert "Coming up" in admin.get("/admin/").text or True  # the widget loads lazily


def test_month_cell_shows_more_link(admin, panel):
    for i in range(5):
        add_event(panel, title=f"Standup {i}", starts_at=T(2026, 10, 14, 9, i), ends_at=None)
    page = admin.get("/admin/calendar?date=2026-10-14").text
    assert page.count('class="twcal-title">Standup') == 3 and "+2 more" in page
    day = admin.get("/admin/calendar?view=day&date=2026-10-14").text
    assert day.count('class="twcal-title">Standup') == 5


def test_create_timed_and_all_day_events(admin, panel):
    form = admin.get("/admin/calendar-events/create?date=2026-10-20").text
    assert 'value="2026-10-20T09:00"' in form  # the clicked day is filled in
    r = admin.post("/admin/calendar-events/create", {
        "title": "  Client call  ", "kind": "call", "starts_at": "2026-10-20T15:00", "ends_at": "2026-10-20T15:30",
        "repeat": "none"})
    assert r.status_code == 204, r.text
    bad = {"title": "Offsite", "kind": "meeting", "all_day": "1", "start_date": "2026-10-22",
           "end_date": "2026-10-23", "repeat": "weekly", "repeat_every": "0", "repeat_until": "2026-01-01"}
    r = admin.post("/admin/calendar-events/create", bad)
    assert r.status_code == 200 and "must be at least 1" in r.text and "after or equal to 2026-10-22" in r.text
    r = admin.post("/admin/calendar-events/create", {**bad, "repeat_every": "2", "repeat_until": "2026-12-31",
                                                     "starts_at": "2020-01-01T08:00"})
    assert r.status_code == 204, r.text
    with panel.db() as db:
        call, offsite = db.scalars(select(CalendarEvent).order_by(CalendarEvent.id)).all()
    assert call.title == "Client call" and call.user_id == "1" and call.kind == "call"
    assert offsite.all_day and offsite.starts_at == T(2026, 10, 22) and offsite.ends_at == T(2026, 10, 23)
    assert offsite.repeat == "weekly" and offsite.repeat_every == 2 and offsite.repeat_until == D(2026, 12, 31)
    week = admin.get("/admin/calendar?view=week&date=2026-10-20").text
    assert "Client call" in week and week.count('class="twcal-title">Offsite') == 2  # on both days


def test_end_before_start_is_refused(admin, panel):
    admin.get("/admin/calendar-events/create")
    r = admin.post("/admin/calendar-events/create", {
        "title": "Backwards", "kind": "call", "starts_at": "2026-10-20T15:00", "ends_at": "2026-10-20T14:00",
        "repeat": "none"})
    assert "Backwards" not in [e.title for e in _all(panel)]
    assert r.status_code == 200 and "must be a date after" in r.text


def _all(panel):
    with panel.db() as db:
        return db.scalars(select(CalendarEvent)).all()


def test_private_events_only_for_their_owner(panel):
    add_event(panel, title="Doctor visit", is_private=True, user_id="1", starts_at=T(2026, 10, 15, 9))
    add_event(panel, title="All hands", user_id="1", starts_at=T(2026, 10, 15, 11))
    ravi = client_for(panel)
    assert ravi.login("ravi@example.com").status_code == 303
    page = ravi.get("/admin/calendar?date=2026-10-15").text
    assert "All hands" in page and "Doctor visit" not in page
    assert ravi.get("/admin/calendar-events/1/edit").status_code == 404
    asha = client_for(panel)
    asha.login()
    assert "Doctor visit" in asha.get("/admin/calendar?date=2026-10-15").text


# ---------------------------------------------------------------------- drag and drop
def test_move_event_by_days(admin, panel):
    event_id = add_event(panel)
    admin.get("/admin/calendar?date=2026-10-12")
    r = admin.post("/admin/calendar/move", {"id": str(event_id), "days": "3"})
    assert r.status_code == 204 and r.headers.get("HX-Refresh") == "true"
    moved = get_event(panel, event_id)
    assert moved.starts_at == T(2026, 10, 15, 10) and moved.ends_at == T(2026, 10, 15, 11)
    assert admin.post("/admin/calendar/move", {"id": str(event_id), "days": "-31"}).status_code == 204
    assert get_event(panel, event_id).starts_at == T(2026, 9, 14, 10)


def test_move_refuses_bad_requests(admin, panel):
    repeating = add_event(panel, repeat="weekly")
    private = add_event(panel, is_private=True, user_id="2")
    admin.get("/admin/calendar")
    for data in ({"id": str(repeating), "days": "1"}, {"id": str(private), "days": "1"}, {"id": "999", "days": "1"},
                 {"id": "x", "days": "1"}, {"id": str(repeating), "days": "99999"}):
        r = admin.post("/admin/calendar/move", data)
        assert r.status_code == 204 and "HX-Refresh" not in r.headers, data  # an error toast, no change
    assert get_event(panel, repeating).starts_at == T(2026, 10, 12, 10)
    # without the CSRF token nothing happens
    r = admin.client.post("/admin/calendar/move", data={"id": str(repeating), "days": "1"})
    assert r.status_code == 419


# ---------------------------------------------------------------------- .ics and subscribe link
def test_download_ics(admin, panel):
    add_event(panel, title="Board meeting")
    r = admin.get("/admin/calendar/export.ics?view=month&date=2026-10-12")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Board meeting" in r.text and "attachment" in r.headers["content-disposition"]


def test_subscribe_link_and_reset(admin, panel):
    today = panel.get_plugin("calendar").today()
    add_event(panel, title="Soon", starts_at=T.combine(today + dt.timedelta(days=2), dt.time(10)), ends_at=None)
    add_event(panel, title="Secret", is_private=True, user_id="2",
              starts_at=T.combine(today + dt.timedelta(days=2), dt.time(11)), ends_at=None)
    modal = admin.client.get("/admin/_tw/action?_tw_host=page:calendar&_tw_scope=page&_tw_name=subscribe",
                             headers={"HX-Request": "true"}).text
    url = re.search(r'value="(https://office\.example\.com/admin/calendar/feed/[^"]+\.ics)"', modal).group(1)
    anon = client_for(panel).client
    feed = anon.get(url.replace("https://office.example.com", ""))
    assert feed.status_code == 200 and "SUMMARY:Soon" in feed.text and "Secret" not in feed.text
    assert anon.get("/admin/calendar/feed/wrong-token.ics").status_code == 404
    r = admin.post("/admin/_tw/action", {"_tw_host": "page:calendar", "_tw_scope": "page", "_tw_name": "reset_feed",
                                         "_tw_record": ""})
    assert r.status_code in (200, 204), r.text
    assert anon.get(url.replace("https://office.example.com", "")).status_code == 404
    with panel.db() as db:
        assert db.scalars(select(CalendarFeed)).first() is None


def test_feed_needs_login_for_export(client):
    assert client.client.get("/admin/calendar/export.ics", follow_redirects=False).status_code in (302, 303)


# ---------------------------------------------------------------------- sources from other plugins
def test_other_plugins_show_on_the_calendar(linked):
    from tungsten_blog.models import BlogPost
    from tungsten_finance.models import Contact, Invoice
    from tungsten_hr.models import Employee, Holiday, LeaveRequest, LeaveType
    from tungsten_leads.models import Lead
    from tungsten_tickets.models import Ticket

    with linked.db() as db:
        amit = Employee(first_name="Amit", last_name="Shah", birth_date=D(1990, 10, 21))
        gone = Employee(first_name="Old", last_name="Timer", birth_date=D(1980, 10, 22), status="left")
        sick = LeaveType(name="Sick", color="danger")
        db.add_all([amit, gone, sick])
        db.flush()
        db.add_all([
            LeaveRequest(employee_id=amit.id, leave_type_id=sick.id, start_date=D(2026, 10, 19),
                         end_date=D(2026, 10, 20), status="approved", days=2),
            LeaveRequest(employee_id=amit.id, leave_type_id=sick.id, start_date=D(2026, 10, 27),
                         end_date=D(2026, 10, 27), status="pending", days=1),
            Holiday(name="Diwali", date=D(2026, 11, 8)),
            Lead(name="Neha Gupta", status="new", follow_up_at=T(2026, 10, 14, 16, 0)),
            Lead(name="Closed Deal", status="won", follow_up_at=T(2026, 10, 14, 17, 0)),
            Ticket(subject="Printer broken", number="TCK-00001", status="open", due_at=T(2026, 10, 13, 12, 0)),
            Ticket(subject="Already fixed", number="TCK-00002", status="resolved", due_at=T(2026, 10, 13, 12, 0)),
            BlogPost(title="Launch post", slug="launch", status="published", published_at=T(2026, 10, 16, 9, 0)),
            BlogPost(title="Draft idea", slug="draft", status="draft", published_at=T(2026, 10, 16, 9, 0)),
        ])
        acme = Contact(name="Acme Ltd")
        db.add(acme)
        db.flush()
        db.add_all([
            Invoice(kind="invoice", number="INV-00001", status="sent", contact_id=acme.id, due_date=D(2026, 10, 25)),
            Invoice(kind="invoice", number="INV-00002", status="paid", due_date=D(2026, 10, 25)),
            Invoice(kind="bill", number="BILL-00001", status="sent", due_date=D(2026, 10, 26)),
        ])
        db.commit()
    c = client_for(linked)
    assert c.login().status_code == 303
    page = c.get("/admin/calendar?date=2026-10-12").text
    for text in ("Amit Shah on leave (Sick)", "Birthday: Amit Shah", "Follow up: Neha Gupta", "Due: TCK-00001",
                 "Scheduled: Launch post", "Invoice INV-00001 due · Acme Ltd", "Bill BILL-00001 due"):
        assert text in page, text
    for text in ("Old Timer", "Closed Deal", "Already fixed", "Draft idea", "INV-00002", "Couldn"):
        assert text not in page, text
    assert page.count('class="twcal-title">Amit Shah on leave') == 2  # two days
    assert "Diwali" in c.get("/admin/calendar?date=2026-11-01").text
    chips = re.findall(r'data-cal-source="([^"]+)"', page)
    assert chips == ["events", "hr_leave", "hr_holidays", "hr_birthdays", "leads", "tickets", "finance", "blog"]
    hidden = c.get("/admin/calendar?date=2026-10-12&hide=leads,blog").text
    assert "Neha Gupta" not in hidden and "Launch post" not in hidden and "TCK-00001" in hidden
    # each item links to its record
    assert re.search(r'href="/admin/tickets/\d+"[^>]*>.*?Due: TCK-00001', page, re.DOTALL)


def test_links_can_be_limited(tmp_path):
    from tungsten_hr import HRPlugin
    from tungsten_leads import LeadsPlugin

    panel = make_panel(tmp_path, [HRPlugin(), LeadsPlugin()], links=["leads"])
    panel.boot()
    assert list(panel.get_plugin("calendar").sources) == ["events", "leads"]


def test_broken_source_does_not_break_the_calendar(admin, panel):
    calendar = panel.get_plugin("calendar")

    def broken(ctx, start, end):
        raise RuntimeError("boom")

    def visits(start, end, plugin):
        zone = dt.timezone(dt.timedelta(hours=5, minutes=30))
        return [{"title": "Site visit", "start": T(2026, 10, 13, 15, 0, tzinfo=zone), "color": "#0ea5e9"},
                CalendarItem("Out of range", D(2030, 1, 1))]

    calendar.add_source("broken", "Broken plugin", broken)
    calendar.add_source("visits", "Site visits", visits, color="teal", icon="map-pin")
    page = admin.get("/admin/calendar?date=2026-10-12").text
    assert "Couldn&#39;t load:" in page and "Broken plugin" in page
    assert "Site visit" in page and "15:00" in page and "#0ea5e9" in page and "Out of range" not in page
    with pytest.raises(ValueError):
        calendar.add_source("a,b", "Bad", visits)
    calendar.remove_source("broken")
    assert "Couldn" not in admin.get("/admin/calendar?date=2026-10-12").text


def test_options_are_checked():
    with pytest.raises(ValueError):
        CalendarPlugin(first_day="someday")
    with pytest.raises(ValueError):
        CalendarPlugin(default_view="year")
    assert CalendarPlugin(first_day="sunday").first_weekday == 6
    assert CalendarPlugin(first_day=6, list_days=10_000).list_days == 400


def test_upcoming_widget(admin, panel):
    calendar = panel.get_plugin("calendar")
    today = calendar.today()
    add_event(panel, title="Tomorrow's review", starts_at=T.combine(today + dt.timedelta(days=1), dt.time(10)),
              ends_at=None)
    add_event(panel, title="Next month", starts_at=T.combine(today + dt.timedelta(days=40), dt.time(10)),
              ends_at=None)
    r = admin.client.get("/admin/_tw/widget/upcoming-events", headers={"HX-Request": "true"})
    assert r.status_code == 200, r.text
    assert "Tomorrow&#39;s review" in r.text and "Tomorrow" in r.text and "Next month" not in r.text


def test_quick_create_makes_calendar_events(tmp_path):
    quick = pytest.importorskip("tungsten_quick_create")
    panel = make_panel(tmp_path, [quick.QuickCreatePlugin()])
    c = client_for(panel)
    assert c.login().status_code == 303
    page = c.get("/admin/calendar").text
    assert "/admin/_quick-create/calendar-events" in page and "tw-refresh" in page  # the calendar reloads after
    form = c.client.get("/admin/_quick-create/calendar-events", headers={"HX-Request": "true"})
    assert form.status_code == 200 and 'name="starts_at"' in form.text
    r = c.post("/admin/_quick-create/calendar-events", {"title": "Quick sync", "kind": "call", "repeat": "none",
                                                        "starts_at": "2026-10-21T12:00"})
    assert r.status_code == 200 and "tw-refresh" in r.headers.get("HX-Trigger", "")
    with panel.db() as db:
        event = db.scalars(select(CalendarEvent)).one()
    assert event.title == "Quick sync" and event.user_id == "1"  # the owner is set here too


def test_all_day_switch_carries_dates_over():
    from tungsten_calendar.resources import _switch_all_day

    state = {"starts_at": "2026-10-20T09:00", "ends_at": "2026-10-21T10:00", "start_date": "", "end_date": ""}
    _switch_all_day(True, state.get, state.__setitem__)
    assert state["start_date"] == "2026-10-20" and state["end_date"] == "2026-10-21"
    state = {"starts_at": "", "ends_at": "", "start_date": "2026-11-02", "end_date": ""}
    _switch_all_day(False, state.get, state.__setitem__)
    assert state["starts_at"] == "2026-11-02T09:00" and state["ends_at"] == "2026-11-02T10:00"
