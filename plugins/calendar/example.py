"""Try the Calendar plugin (with HR, Leads and Tickets, to see the dates they add).

    pip install -e . -e plugins/calendar -e plugins/hr -e plugins/leads -e plugins/tickets uvicorn
    uvicorn plugins.calendar.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin/calendar and sign in with admin@example.com / password.
"""

from __future__ import annotations

import datetime as dt

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_calendar import CalendarEvent, CalendarPlugin

from tungsten import Auth, Panel, hash_password


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


engine = create_engine("sqlite:///calendar_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Tungsten Calendar", colors={"primary": "indigo"}, spa=True)

# the other plugins are optional: the calendar links with the ones that are installed
optional = []
try:
    from tungsten_hr import HRPlugin

    optional.append(HRPlugin())
except ImportError:
    pass
try:
    from tungsten_leads import LeadsPlugin

    optional.append(LeadsPlugin())
except ImportError:
    pass
try:
    from tungsten_tickets import TicketsPlugin

    optional.append(TicketsPlugin(portal=False))
except ImportError:
    pass
for plugin in optional:
    panel.plugin(plugin)
panel.plugin(CalendarPlugin(timezone="Asia/Kolkata"))
panel.create_tables(engine)


def seed() -> None:
    with Session() as db:
        if db.scalar(select(User)) is not None:
            return
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        today = panel.get_plugin("calendar").today()

        def at(days: int, hour: int, minute: int = 0) -> dt.datetime:
            return dt.datetime.combine(today + dt.timedelta(days=days), dt.time(hour, minute))

        db.add_all([
            CalendarEvent(title="Weekly sales review", kind="meeting", starts_at=at(-6, 10), ends_at=at(-6, 11),
                          repeat="weekly", location="Board room", user_id="1"),
            CalendarEvent(title="Call with Acme", kind="call", starts_at=at(1, 15), ends_at=at(1, 15, 30),
                          user_id="1"),
            CalendarEvent(title="Send GST returns", kind="task", starts_at=at(3, 0), ends_at=at(3, 0),
                          all_day=True, user_id="1"),
            CalendarEvent(title="Team offsite", kind="meeting", starts_at=at(8, 0), ends_at=at(9, 0), all_day=True,
                          location="Lonavala", user_id="1"),
            CalendarEvent(title="Pay rent", kind="reminder", starts_at=at(-today.day + 1, 9), repeat="monthly",
                          user_id="1"),
            CalendarEvent(title="Dentist", kind="other", starts_at=at(2, 18), ends_at=at(2, 19), is_private=True,
                          user_id="1"),
        ])
        if panel.get_plugin("hr") is not None:
            from tungsten_hr.models import Employee, Holiday, LeaveRequest, LeaveType

            amit = Employee(first_name="Amit", last_name="Sharma", birth_date=dt.date(1992, today.month,
                                                                                      min(today.day + 4, 28)))
            casual = LeaveType(name="Casual leave", color="info")
            db.add_all([amit, casual, Holiday(name="Company day", date=today + dt.timedelta(days=12))])
            db.flush()
            db.add(LeaveRequest(employee_id=amit.id, leave_type_id=casual.id, start_date=today + dt.timedelta(days=5),
                                end_date=today + dt.timedelta(days=6), status="approved", days=2))
        if panel.get_plugin("leads") is not None:
            from tungsten_leads.models import Lead

            db.add(Lead(name="Neha Gupta", company="Gupta Traders", status="contacted", follow_up_at=at(1, 11)))
        if panel.get_plugin("tickets") is not None:
            from tungsten_tickets.models import Ticket

            db.add(Ticket(subject="Printer not working", number="TCK-00001", status="open", due_at=at(0, 17)))
        db.commit()


seed()
app = FastAPI()
panel.mount(app)


@app.get("/")
def root():
    return RedirectResponse("/admin/calendar")
