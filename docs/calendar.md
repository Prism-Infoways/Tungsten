---
title: Calendar (events, leave, follow-ups)
description: Add a calendar to your panel with month, week, day and list views, repeating and all-day events, drag and drop, phone sync, and the dates from HR, Leads, Tickets, Finance and Blog in one place.
---

The `tungsten-calendar` plugin adds a **Calendar** menu to your panel: a calendar with month, week, day and list views, and an **Events** list for meetings, calls, tasks and reminders. When other Tungsten plugins are installed, their dates show on the same calendar: who is on leave, holidays, birthdays, lead follow-ups, ticket due times, unpaid invoices and scheduled blog posts.

## Install

```bash
pip install tungsten-calendar
```

```python
from tungsten_calendar import CalendarPlugin

panel.plugin(CalendarPlugin(timezone="Asia/Kolkata"))
panel.create_tables(engine)
```

`create_tables` makes the calendar tables. Set `timezone` to the time zone your team works in: it decides what "today" is and the times sent to phone calendars. Without it the server's time zone is used.

## The calendar

Open **Calendar** in the menu.

- **Month**, **Week**, **Day** and **List** views. Use the arrows, or the left and right arrow keys, to move. Press **T** or **Today** to come back.
- Click a day number to open that day. Click the **+** on a day to add an event on it.
- **Drag** an event to another day to move it. Its time and length stay the same.
- The chips on top show where items come from (**Events**, **Leave**, **Holidays**...). Click one to hide or show it.
- A month cell shows three items and a **+2 more** link to the full day.
- Multi-day items show on every day they cover. A meeting that ends at midnight stays on its own day.

## Events

**Events** is a normal list with search, filters, tabs (Upcoming, Mine, Past, All) and export. An event has:

| Field | What it does |
| --- | --- |
| Title, Type | Meeting, Call, Task, Reminder or Other. The type sets the color and icon. |
| All day | Pick dates instead of times. An all-day event can cover many days. |
| Starts, Ends | Leave **Ends** empty for a reminder at one time. The end can't be before the start. |
| Location, Notes | Shown in the list view and in phone calendars. |
| Repeat | Every day, week, month or year, **every N** times, **until** a date. |
| Color | Overrides the type's color. |
| Only me | A private event: only the person who made it sees it. |

Monthly events on the 29th, 30th or 31st fall on the last day of shorter months. Yearly events on 29 February fall on 28 February in other years. A repeating event is moved from its own page, not by dragging.

## Dates from other plugins

The calendar links with the plugins you have installed. Each item opens its own record, and people only see what they are allowed to see in that plugin.

| Plugin | Shows |
| --- | --- |
| [HR](hr) | Approved leave, holidays and birthdays (not for people who have left) |
| [Leads](leads) | Follow-ups of open leads (not won or lost); late ones in red |
| [Help desk](tickets) | Due times of open tickets; overdue ones in red |
| [Finance](finance) | Due dates of unpaid invoices and vendor bills |
| [Blog](blog) | Published and scheduled posts |

Pick which ones with `links`:

```python
CalendarPlugin(links=["hr_leave", "hr_holidays", "leads"])   # only these
CalendarPlugin(links=False)                                  # only the calendar's own events
```

The keys are `hr_leave`, `hr_holidays`, `hr_birthdays`, `leads`, `tickets`, `finance` and `blog`.

If one plugin fails, the calendar still shows everything else, with a note saying what couldn't load.

Two more plugins work with the calendar:

- [Tags](tags): events get a tags box, a tags column and a tag filter in **Events**.
- [Quick Create](quick-create): **+ New → Event** adds an event from any page, and the calendar updates right away.

## Add your own dates

Any plugin or app can put its dates on the calendar with `add_source`. Return `CalendarItem` objects, or dicts with the same keys, for the days `start` to `end` (both included):

```python
from tungsten_calendar import CalendarItem

def site_visits(ctx, start, end):
    rows = ctx.db.scalars(select(Visit).where(Visit.day >= start, Visit.day <= end))
    return [CalendarItem(title=f"Visit: {v.client}", start=v.starts_at, end=v.ends_at,
                         url=ctx.url("visits", v.id), id=str(v.id)) for v in rows]

class VisitsPlugin(Plugin):
    id = "visits"

    def boot(self, panel):
        calendar = panel.get_plugin("calendar")
        if calendar is not None:
            calendar.add_source("visits", "Site visits", site_visits, color="teal", icon="map-pin")
```

- `start` is a `date` for an all-day item, or a `datetime`. For an all-day item `end` is its last day.
- Times with an offset (like UTC from an API) are moved into the calendar's time zone.
- `color` is a panel color name (`primary`, `success`, `danger`, `teal`...) or a hex color like `#0ea5e9`.
- Add sources in `boot()`, so it works whatever order the plugins were added in. `default=False` starts a source hidden; `remove_source(key)` takes one off.

`calendar.items(ctx, start, end)` returns every item a user can see, if you want the dates somewhere else (a report, an email).

## Phone and other calendars

Open **Share** on the calendar:

- **Subscribe on phone** gives each person a private link. Paste it in Google Calendar (Other calendars, From URL), Outlook (Subscribe from web) or an iPhone (Add subscribed calendar). It shows what that person can see, from a month back to a year ahead, and updates on its own.
- **Reset subscribe link** turns the old link off if it leaks.
- **Download .ics** saves what is on screen as a file you can import anywhere.

Turn the private links off with `CalendarPlugin(feeds=False)`.

## Dashboard

A **Coming up** card on the dashboard lists the next 7 days. Change it with `upcoming_days=14`, or turn it off with `dashboard_widget=False`.

## Options

```python
CalendarPlugin(
    timezone="Asia/Kolkata",       # default: the server's time zone
    first_day="monday",            # or "sunday" (or 0-6)
    default_view="month",          # month, week, day or list
    list_days=30,                  # days in the list view
    kinds={"meeting": ("Meeting", "primary", "users"), "visit": ("Site visit", "teal", "map-pin")},
    links=True,                    # True, False or a list of keys
    feeds=True,                    # private subscribe links
    dashboard_widget=True,
    upcoming_days=7,
    navigation_group="Calendar",
)
```

Wrong values (an unknown time zone or view) stop the app at start-up with a clear message, not later on a page.
