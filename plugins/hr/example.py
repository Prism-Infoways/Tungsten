"""Try the HR plugin.

    pip install -e . -e plugins/hr uvicorn
    uvicorn plugins.hr.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password
(or rohit@example.com / password to see the employee side: check in and ask for leave).
"""

from __future__ import annotations

import datetime as dt

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_hr import (
    Department,
    Employee,
    Holiday,
    HRPlugin,
    LeaveType,
    approve_leave,
    check_in,
    check_out,
    request_leave,
)

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


engine = create_engine("sqlite:///hr_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Tungsten HR", colors={"primary": "indigo"}, spa=True)
panel.plugin(HRPlugin())
panel.create_tables(engine)


def seed() -> None:
    with Session() as db:
        if db.scalar(select(User)) is not None:
            return
        db.info["tungsten_panel"] = panel
        db.add_all([User(name="Asha Admin", email="admin@example.com", password=hash_password("password")),
                    User(name="Rohit Verma", email="rohit@example.com", password=hash_password("password"))])
        sales, tech, accounts = (Department(name="Sales", code="SAL", color="info"),
                                 Department(name="Technology", code="TEC", color="purple"),
                                 Department(name="Accounts", code="ACC", color="success"))
        db.add_all([sales, tech, accounts])
        db.add_all([LeaveType(name="Casual leave", days_per_year=12, color="info", sort=1),
                    LeaveType(name="Sick leave", days_per_year=8, color="warning", sort=2),
                    LeaveType(name="Earned leave", days_per_year=15, color="success", sort=3),
                    LeaveType(name="Unpaid leave", is_paid=False, color="gray", sort=4)])
        year = dt.date.today().year
        db.add_all([Holiday(name="Republic Day", date=dt.date(year, 1, 26)),
                    Holiday(name="Independence Day", date=dt.date(year, 8, 15)),
                    Holiday(name="Gandhi Jayanti", date=dt.date(year, 10, 2)),
                    Holiday(name="Christmas", date=dt.date(year, 12, 25))])
        people = [("Asha", "Admin", "HR manager", accounts, "1"), ("Rohit", "Verma", "Sales executive", sales, "2"),
                  ("Priya", "Patel", "Sales lead", sales, None), ("Amit", "Sharma", "Developer", tech, None),
                  ("Sneha", "Iyer", "Designer", tech, None), ("Vikram", "Singh", "Accountant", accounts, None)]
        staff = []
        for i, (first, last, job, dept, user_id) in enumerate(people, start=1):
            person = Employee(code=f"EMP-{i:04d}", first_name=first, last_name=last, job_title=job, department=dept,
                              email=f"{first.lower()}@example.com", user_id=user_id,
                              joined_on=dt.date(2024, i, 1), status="probation" if i == 6 else "active")
            db.add(person)
            staff.append(person)
        db.flush()
        sales.head_id, tech.head_id, accounts.head_id = staff[2].id, staff[3].id, staff[0].id
        db.flush()
        now = dt.datetime.now()
        for k, person in enumerate(staff[:5]):
            check_in(db, person, now.replace(hour=9, minute=10 + k * 7, second=0))
        check_out(db, staff[3], now.replace(hour=18, minute=5, second=0))
        start = dt.date.today() + dt.timedelta(days=7)
        while start.weekday() >= 5:
            start += dt.timedelta(days=1)
        request_leave(db, staff[1], 1, start, start + dt.timedelta(days=1), reason="Sister's wedding")
        approved = request_leave(db, staff[4], 2, dt.date.today() - dt.timedelta(days=1), reason="Fever")
        approve_leave(db, approved, user_id="1")
        db.commit()


seed()
app = FastAPI()
panel.mount(app)


@app.get("/")
def root():
    return RedirectResponse("/admin/")
