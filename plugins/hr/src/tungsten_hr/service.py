"""Functions other code (and other plugins) use for employees, attendance and leave.

    from tungsten_hr import approve_leave, check_in, leave_balance, request_leave

    check_in(db, employee)
    request = request_leave(db, employee, leave_type, dt.date(2026, 11, 2), dt.date(2026, 11, 4), reason="Wedding")
    approve_leave(db, request, user_id="1")
    db.commit()
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import func, select

from .models import Attendance, Employee, Holiday, LeaveRequest, LeaveType

log = logging.getLogger("tungsten.hr")

EMPLOYEE_STATUSES = {
    "active": ("Active", "success"),
    "probation": ("On probation", "info"),
    "notice": ("On notice", "warning"),
    "left": ("Left", "gray"),
}
EMPLOYMENT_TYPES = {"full_time": "Full time", "part_time": "Part time", "contract": "Contract", "intern": "Intern"}
ATTENDANCE_STATUSES = {
    "present": ("Present", "success"),
    "remote": ("Work from home", "info"),
    "half_day": ("Half day", "warning"),
    "absent": ("Absent", "danger"),
    "leave": ("On leave", "purple"),
    "holiday": ("Holiday", "gray"),
}
LEAVE_STATUSES = {
    "pending": ("Pending", "warning"),
    "approved": ("Approved", "success"),
    "rejected": ("Rejected", "danger"),
    "cancelled": ("Cancelled", "gray"),
}
#: statuses that count as "at work" for the day
WORKING = ("present", "remote", "half_day")


class LeaveError(ValueError):
    """A leave request that can't be saved; the message says why, in plain words."""


def hr_plugin(db: Any) -> Any:
    """The ``HRPlugin`` of the panel this session belongs to (None in plain scripts)."""
    from tungsten import Panel

    panel = Panel.of(db)
    return panel.get_plugin("hr") if panel is not None else None


def _now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def _setting(db: Any, name: str, default: Any) -> Any:
    plugin = hr_plugin(db)
    return getattr(plugin, name, default) if plugin is not None else default


# ---------------------------------------------------------------------- employees
def employee_for_user(db: Any, user_id: Any) -> Employee | None:
    """The employee a panel user logs in as."""
    if user_id is None:
        return None
    return db.scalars(select(Employee).where(Employee.user_id == str(user_id))).first()


def give_code(db: Any, employee: Employee) -> None:
    """Give a new (flushed) employee its code, like EMP-0007."""
    if not employee.code:
        employee.code = f"{_setting(db, 'code_prefix', 'EMP-')}{employee.id:04d}"
        db.flush()


def approver_of(employee: Employee) -> Employee | None:
    """Who approves this employee's leave: their manager, else the head of their department."""
    if employee.manager is not None and employee.manager.id != employee.id:
        return employee.manager
    head = employee.department.head if employee.department is not None else None
    return head if head is not None and head.id != employee.id else None


# ---------------------------------------------------------------------- days
def holidays_between(db: Any, start: dt.date, end: dt.date) -> set[dt.date]:
    rows = db.scalars(select(Holiday.date).where(Holiday.date >= start, Holiday.date <= end,
                                                 Holiday.is_optional.is_(False))).all()
    return set(rows)


def working_days(db: Any, start: dt.date, end: dt.date) -> list[dt.date]:
    """The days from ``start`` to ``end`` that are not weekends or holidays."""
    weekend = _setting(db, "weekend", (5, 6))
    off = holidays_between(db, start, end)
    days, day = [], start
    while day <= end:
        if day.weekday() not in weekend and day not in off:
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def count_days(db: Any, start: dt.date, end: dt.date, half_day: bool = False) -> float:
    """Leave days for a request: working days only; a half day counts 0.5."""
    if end < start:
        return 0
    n = len(working_days(db, start, end))
    return 0.5 if half_day and n else float(n)


# ---------------------------------------------------------------------- leave
def leave_used(db: Any, employee_id: int, leave_type_id: int, year: int, statuses=("approved",),
               exclude_id: int | None = None) -> float:
    where = [LeaveRequest.employee_id == employee_id, LeaveRequest.leave_type_id == leave_type_id,
             LeaveRequest.status.in_(statuses), func.extract("year", LeaveRequest.start_date) == year]
    if exclude_id is not None:
        where.append(LeaveRequest.id != exclude_id)
    return float(db.scalar(select(func.coalesce(func.sum(LeaveRequest.days), 0)).where(*where)) or 0)


def leave_balance(db: Any, employee: Employee, year: int | None = None) -> list[dict]:
    """Per leave type: days allowed, used (approved), waiting (pending) and left, for a year."""
    year = year or dt.date.today().year
    rows = []
    types = db.scalars(select(LeaveType).where(LeaveType.is_active.is_(True))
                       .order_by(LeaveType.sort, LeaveType.name)).all()
    for kind in types:
        used = leave_used(db, employee.id, kind.id, year)
        pending = leave_used(db, employee.id, kind.id, year, statuses=("pending",))
        allowed = kind.days_per_year
        rows.append({"type": kind, "name": kind.name, "color": kind.color, "allowed": allowed, "used": used,
                     "pending": pending, "left": None if allowed is None else allowed - used})
    return rows


def check_leave(db: Any, request: LeaveRequest) -> None:
    """Fill ``days`` and raise :class:`LeaveError` when the request can't be saved."""
    if request.end_date is None:
        request.end_date = request.start_date
    if request.end_date < request.start_date:
        raise LeaveError("The last day can't be before the first day.")
    if request.half_day:
        request.end_date = request.start_date
    request.days = count_days(db, request.start_date, request.end_date, request.half_day)
    if request.days <= 0:
        raise LeaveError("These days are all weekends or holidays, so no leave is needed.")
    if request.status in ("rejected", "cancelled"):
        return
    clash = db.scalars(select(LeaveRequest).where(
        LeaveRequest.employee_id == request.employee_id, LeaveRequest.status.in_(("pending", "approved")),
        LeaveRequest.start_date <= request.end_date, LeaveRequest.end_date >= request.start_date,
        *([LeaveRequest.id != request.id] if request.id else []))).first()
    if clash is not None:
        raise LeaveError(f"There is already a leave request from {clash.start_date:%d %b} "
                         f"to {clash.end_date:%d %b}.")
    kind = db.get(LeaveType, request.leave_type_id) if request.leave_type_id else None
    if kind is not None and kind.days_per_year is not None and not kind.allow_negative:
        taken = leave_used(db, request.employee_id, kind.id, request.start_date.year,
                           statuses=("pending", "approved"), exclude_id=request.id)
        left = kind.days_per_year - taken
        if request.days > left:
            raise LeaveError(f"Only {left:g} {kind.name} day(s) left this year, "
                             f"but this asks for {request.days:g}.")


def leave_requested(db: Any, request: LeaveRequest, ctx: Any = None) -> None:
    """Tell the approver and the listeners about a new (flushed) request."""
    plugin = hr_plugin(db)
    if plugin is None:
        return
    approver = approver_of(request.employee)
    if approver is not None and approver.user_id:
        plugin.notify(db, approver.user_id, "Leave request",
                      f"{request.employee.name} asks for {request.days:g} day(s) from "
                      f"{request.start_date:%d %b}.", plugin.leave_link(request), ctx)
    for fn in list(plugin.requested_listeners.values()):
        fn(db, request)


def request_leave(db: Any, employee: Employee, leave_type: LeaveType | int | None, start: dt.date,
                  end: dt.date | None = None, *, half_day: bool = False, reason: str | None = None,
                  ctx: Any = None) -> LeaveRequest:
    """Ask for leave. Raises :class:`LeaveError` when it can't be given. Flushed, not committed."""
    type_id = leave_type.id if isinstance(leave_type, LeaveType) else leave_type
    request = LeaveRequest(employee_id=employee.id, leave_type_id=type_id, start_date=start, end_date=end or start,
                           half_day=half_day, reason=reason, status="pending")
    check_leave(db, request)
    db.add(request)
    db.flush()
    leave_requested(db, request, ctx)
    return request


def _mark_leave_days(db: Any, request: LeaveRequest) -> None:
    status = "half_day" if request.half_day else "leave"
    for day in working_days(db, request.start_date, request.end_date):
        row = db.scalars(select(Attendance).where(Attendance.employee_id == request.employee_id,
                                                  Attendance.date == day)).first()
        if row is None:
            db.add(Attendance(employee_id=request.employee_id, date=day, status=status, source="leave",
                              note=str(request.leave_type or "Leave")))
        elif row.status in ("absent", "leave") or row.source == "leave":
            row.status, row.source = status, "leave"
    db.flush()


def _clear_leave_days(db: Any, request: LeaveRequest) -> None:
    rows = db.scalars(select(Attendance).where(
        Attendance.employee_id == request.employee_id, Attendance.source == "leave",
        Attendance.date >= request.start_date, Attendance.date <= request.end_date)).all()
    for row in rows:
        db.delete(row)
    db.flush()


def decide_leave(db: Any, request: LeaveRequest, status: str, *, user_id: str | None = None,
                 note: str | None = None, ctx: Any = None) -> bool:
    """Approve, reject or cancel a request. Approved days show as "On leave" in attendance.

    Returns False when nothing changed. Flushed, not committed.
    """
    if status not in LEAVE_STATUSES or status == request.status:
        return False
    old = request.status
    if status == "approved":
        check_leave(db, request)
    request.status = status
    request.reviewed_by = str(user_id) if user_id is not None else request.reviewed_by
    request.reviewed_at = _now()
    if note:
        request.review_note = note[:255]
    if status == "approved":
        _mark_leave_days(db, request)
    elif old == "approved":
        _clear_leave_days(db, request)
    db.flush()
    plugin = hr_plugin(db)
    if plugin is None:
        return True
    if status in ("approved", "rejected"):
        plugin.tell_employee(db, request, ctx)
    for fn in list(plugin.decided_listeners.values()):
        fn(db, request, old)
    return True


def approve_leave(db: Any, request: LeaveRequest, **kw: Any) -> bool:
    return decide_leave(db, request, "approved", **kw)


def reject_leave(db: Any, request: LeaveRequest, **kw: Any) -> bool:
    return decide_leave(db, request, "rejected", **kw)


# ---------------------------------------------------------------------- attendance
def _hours(start: dt.time | None, end: dt.time | None) -> float | None:
    if start is None or end is None:
        return None
    seconds = (dt.datetime.combine(dt.date.min, end) - dt.datetime.combine(dt.date.min, start)).total_seconds()
    return round(seconds / 3600, 2) if seconds > 0 else 0.0


def fill_attendance(db: Any, row: Attendance) -> None:
    """Work out hours, late and half day from the check-in and check-out times."""
    row.hours = _hours(row.check_in, row.check_out)
    late_after = _setting(db, "late_after", dt.time(9, 30))
    row.is_late = bool(row.check_in and late_after and row.check_in > late_after and row.status in WORKING)
    half = _setting(db, "half_day_hours", 4)
    if row.hours is not None and half and row.status == "present" and row.hours < half:
        row.status = "half_day"


def mark_attendance(db: Any, employee: Employee | int, day: dt.date | None = None, status: str = "present", *,
                    check_in: dt.time | None = None, check_out: dt.time | None = None, note: str | None = None,
                    source: str = "panel") -> Attendance:
    """Set one employee's day, adding the row or changing it. Flushed, not committed."""
    employee_id = employee.id if isinstance(employee, Employee) else employee
    day = day or dt.date.today()
    row = db.scalars(select(Attendance).where(Attendance.employee_id == employee_id, Attendance.date == day)).first()
    if row is None:
        row = Attendance(employee_id=employee_id, date=day)
        db.add(row)
    row.status, row.source = status, source
    if check_in is not None:
        row.check_in = check_in
    if check_out is not None:
        row.check_out = check_out
    if note is not None:
        row.note = note
    fill_attendance(db, row)
    db.flush()
    return row


def today_row(db: Any, employee: Employee) -> Attendance | None:
    return db.scalars(select(Attendance).where(Attendance.employee_id == employee.id,
                                               Attendance.date == dt.date.today())).first()


def check_in(db: Any, employee: Employee, at: dt.datetime | None = None, remote: bool = False) -> Attendance:
    """The employee starts their day (the "Check in" button)."""
    at = at or _now()
    row = db.scalars(select(Attendance).where(Attendance.employee_id == employee.id,
                                              Attendance.date == at.date())).first()
    if row is None:
        row = Attendance(employee_id=employee.id, date=at.date())
        db.add(row)
    if row.check_in is None:
        row.check_in = at.time().replace(microsecond=0)
    row.status, row.source = ("remote" if remote else "present"), "self"
    fill_attendance(db, row)
    db.flush()
    return row


def check_out(db: Any, employee: Employee, at: dt.datetime | None = None) -> Attendance:
    """The employee ends their day. Checks in too when they forgot to."""
    at = at or _now()
    row = db.scalars(select(Attendance).where(Attendance.employee_id == employee.id,
                                              Attendance.date == at.date())).first()
    if row is None or row.check_in is None:
        row = check_in(db, employee, at)
    row.check_out = at.time().replace(microsecond=0)
    fill_attendance(db, row)
    db.flush()
    return row


def month_summary(db: Any, employee: Employee, year: int, month: int) -> dict[str, float]:
    """Count of each attendance status in a month, plus total hours."""
    start = dt.date(year, month, 1)
    end = (start + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    rows = db.scalars(select(Attendance).where(Attendance.employee_id == employee.id, Attendance.date >= start,
                                               Attendance.date <= end)).all()
    summary: dict[str, float] = {key: 0 for key in ATTENDANCE_STATUSES}
    for row in rows:
        summary[row.status] = summary.get(row.status, 0) + 1
    summary["late"] = sum(1 for r in rows if r.is_late)
    summary["hours"] = round(sum(r.hours or 0 for r in rows), 2)
    return summary
