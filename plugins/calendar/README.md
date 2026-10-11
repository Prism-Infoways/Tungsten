# tungsten-calendar

A calendar for your [Tungsten](https://tungsten.prisminfoways.com/) admin panel: month, week, day and list views, meetings, calls, tasks and reminders, and the dates from your other Tungsten plugins in one place.

- **Four views**: month, week, day and list, with arrow-key navigation.
- **Events**: all-day, multi-day and timed, with type, color, location and notes.
- **Repeat**: every day, week, month or year, every N times, until a date. Month ends and 29 February are handled.
- **Drag and drop**: drag an event to another day to move it.
- **Private events**: "Only me" events are hidden from everyone else.
- **Phone sync**: a private link for Google Calendar, Outlook or an iPhone, plus .ics download.
- **Linked with your plugins**: approved leave, holidays and birthdays (HR), lead follow-ups (Leads), ticket due times (Help desk), unpaid invoices and bills (Finance) and blog posts (Blog). Each person only sees what they may see.
- **Tags and Quick Create**: with those plugins, events get tags, and "+ New → Event" works from any page.
- **Hooks**: any plugin can add its own dates with `add_source`.
- **Dashboard card**: what is coming up in the next 7 days.

## Install

```bash
pip install tungsten-calendar
```

```python
from tungsten_calendar import CalendarPlugin

panel.plugin(CalendarPlugin(timezone="Asia/Kolkata"))
panel.create_tables(engine)
```

Open **Calendar** in the menu.

## Add your own dates

```python
from tungsten_calendar import CalendarItem

def site_visits(ctx, start, end):
    return [CalendarItem(title=f"Visit: {v.client}", start=v.starts_at, end=v.ends_at, url=ctx.url("visits", v.id))
            for v in visits_between(ctx.db, start, end)]

class VisitsPlugin(Plugin):
    id = "visits"

    def boot(self, panel):
        calendar = panel.get_plugin("calendar")
        if calendar is not None:
            calendar.add_source("visits", "Site visits", site_visits, color="teal", icon="map-pin")
```

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `timezone` | server's | Your team's time zone, like `"Asia/Kolkata"` |
| `first_day` | `"monday"` | First day of the week (`"sunday"` or 0-6 also work) |
| `default_view` | `"month"` | `month`, `week`, `day` or `list` |
| `kinds` | Meeting, Call, Task, Reminder, Other | Event types: key -> (label, color, icon) |
| `links` | `True` | Dates from other plugins: `True`, `False` or a list of keys |
| `feeds` | `True` | Private subscribe links for phone calendars |
| `dashboard_widget` | `True` | The "Coming up" card, for `upcoming_days` days |

Full guide: https://tungsten.prisminfoways.com/docs/calendar

## Try it

```bash
pip install -e . -e plugins/calendar -e plugins/hr -e plugins/leads -e plugins/tickets uvicorn
uvicorn plugins.calendar.example:app --reload
```

Open http://127.0.0.1:8000/admin/calendar and sign in with admin@example.com / password.
