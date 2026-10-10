"""HR plugin for Tungsten: employees, departments, attendance, leave and holidays.

    from tungsten_hr import HRPlugin

    panel.plugin(HRPlugin())
    panel.create_tables(engine)   # also creates the HR tables

Adds an "HR" menu: employees with job, manager and documents; departments; attendance with
a "Check in" button; leave requests with balances and approval; leave types and holidays.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from tungsten import Plugin
from tungsten.support.evaluate import call

from .models import Attendance, Department, Employee, Holiday, HRBase, LeaveRequest, LeaveType
from .resources import (
    RESOURCES,
    AttendanceResource,
    DepartmentResource,
    EmployeeResource,
    HolidayResource,
    LeaveRequestResource,
    LeaveTypeResource,
)
from .service import (
    LeaveError,
    approve_leave,
    check_in,
    check_out,
    count_days,
    decide_leave,
    employee_for_user,
    leave_balance,
    mark_attendance,
    month_summary,
    reject_leave,
    request_leave,
    working_days,
)
from .widgets import HRStats

__version__ = "0.1.0"

log = logging.getLogger("tungsten.hr")


class HRPlugin(Plugin):
    """``HRPlugin(weekend=(5, 6), late_after=time(9, 30), half_day_hours=4, code_prefix="EMP-")``.

    - ``weekend``: weekday numbers that are off (Monday is 0). ``(6,)`` for Sunday only.
    - ``late_after``: a check-in after this time is marked late (``None``: never late).
    - ``half_day_hours``: fewer hours than this between check-in and check-out is a half day.
    - ``code_prefix``: new employees get codes like ``EMP-0007``.
    - ``email_employees``: email people when their leave is approved or rejected, through
      ``mailer`` or the panel's ``Auth(mailer=...)``.
    - ``notify``: bell notifications for approvers and employees who log in to the panel.
    """

    id = "hr"
    metadata = HRBase.metadata

    def __init__(self, weekend: tuple[int, ...] = (5, 6), late_after: dt.time | None = dt.time(9, 30),
                 half_day_hours: float | None = 4, code_prefix: str = "EMP-", email_employees: bool = True,
                 notify: bool = True, mailer: Any = None, dashboard_widget: bool = True,
                 navigation_group: str = "HR") -> None:
        self.weekend = tuple(weekend)
        self.late_after = late_after
        self.half_day_hours = half_day_hours
        self.code_prefix = code_prefix
        self.email_employees = email_employees
        self.notify_enabled = notify
        self.mailer = mailer
        self.dashboard_widget = dashboard_widget
        self.navigation_group = navigation_group
        self.panel: Any = None
        #: other plugins (payroll, WhatsApp, Slack...) hook in with the methods below
        self.employee_listeners: dict[str, Any] = {}
        self.requested_listeners: dict[str, Any] = {}
        self.decided_listeners: dict[str, Any] = {}

    # ------------------------------------------------------------------ hooks for other code
    def on_employee_created(self, key: str, fn: Any) -> None:
        """Run ``fn(db, employee)`` after an employee is added in the panel. The same ``key`` replaces it."""
        self.employee_listeners[key] = fn

    def on_leave_requested(self, key: str, fn: Any) -> None:
        """Run ``fn(db, request)`` after someone asks for leave."""
        self.requested_listeners[key] = fn

    def on_leave_decided(self, key: str, fn: Any) -> None:
        """Run ``fn(db, request, old_status)`` after a request is approved, rejected or cancelled."""
        self.decided_listeners[key] = fn

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        for resource in RESOURCES:
            resource.navigation_group = self.navigation_group
        panel.resources(RESOURCES)
        panel.navigation_group(self.navigation_group, icon="users")
        if self.dashboard_widget:
            panel.widgets([HRStats])

    # ------------------------------------------------------------------ messages
    def leave_link(self, request: LeaveRequest) -> str:
        return self.panel.url(LeaveRequestResource.get_slug(), request.id)

    def notify(self, db: Any, user_id: str, title: str, body: str, url: str | None = None, ctx: Any = None) -> None:
        """Put a note in a panel user's bell (not when they did it themselves)."""
        if not self.notify_enabled or not user_id:
            return
        if ctx is not None and getattr(ctx, "user", None) is not None \
                and str(self.panel.auth.user_id(ctx.user)) == str(user_id):
            return
        from tungsten import Notification
        from tungsten.models import DatabaseNotification

        note = Notification(title).body(body).icon("plane").color("info")
        if url:
            note = note.action("Open", url)
        db.add(DatabaseNotification(user_id=str(user_id), data=note.to_dict()))

    def tell_employee(self, db: Any, request: LeaveRequest, ctx: Any = None) -> None:
        """Tell the employee their leave was approved or rejected: bell and email."""
        employee = request.employee
        word = "approved" if request.status == "approved" else "rejected"
        when = f"{request.start_date:%d %b %Y}" + (
            f" to {request.end_date:%d %b %Y}" if request.end_date != request.start_date else "")
        kind = request.leave_type.name if request.leave_type else "Leave"
        if employee.user_id:
            self.notify(db, employee.user_id, f"Leave {word}", f"{kind}, {when}", self.leave_link(request), ctx)
        if not self.email_employees or not employee.email:
            return
        body = f"Hello {employee.first_name},\n\nYour {kind.lower()} for {when} " \
               f"({request.days:g} day(s)) was {word}."
        if request.review_note:
            body += f"\n\nNote: {request.review_note}"
        mailer = self.mailer or self.panel.auth.mailer
        try:
            call(mailer, to=employee.email, subject=f"Leave {word}: {when}", body=body, request=request,
                 kind=f"leave_{word}")
        except Exception:  # a broken mail server must not undo the decision
            log.exception("Could not email %s about leave %s", employee.email, request.id)


__all__ = [
    "Attendance", "AttendanceResource", "Department", "DepartmentResource", "Employee", "EmployeeResource",
    "HRBase", "HRPlugin", "HRStats", "Holiday", "HolidayResource", "LeaveError", "LeaveRequest",
    "LeaveRequestResource", "LeaveType", "LeaveTypeResource", "approve_leave", "check_in", "check_out",
    "count_days", "decide_leave", "employee_for_user", "leave_balance", "mark_attendance", "month_summary",
    "reject_leave", "request_leave", "working_days",
]
