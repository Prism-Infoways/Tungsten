"""Dashboard numbers for HR."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from tungsten import Stat, StatsOverviewWidget

from .models import Attendance, Employee, LeaveRequest
from .service import WORKING


class HRStats(StatsOverviewWidget):
    lazy = False

    @classmethod
    def stats(cls, db, ctx):
        def count(model, *where):
            return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

        today = dt.date.today()
        staff = count(Employee, Employee.status != "left")
        present = count(Attendance, Attendance.date == today, Attendance.status.in_(WORKING))
        on_leave = count(LeaveRequest, LeaveRequest.status == "approved", LeaveRequest.start_date <= today,
                         LeaveRequest.end_date >= today)
        pending = count(LeaveRequest, LeaveRequest.status == "pending")
        return [
            Stat("Employees", f"{staff:,}").icon("users").color("primary"),
            Stat("At work today", f"{present:,}").icon("user-check").color("success").describe(f"of {staff:,}"),
            Stat("On leave today", f"{on_leave:,}").icon("plane").color("info"),
            Stat("Leave to approve", f"{pending:,}").icon("calendar-clock").color("warning" if pending else "gray"),
        ]
