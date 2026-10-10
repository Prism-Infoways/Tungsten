from __future__ import annotations

import datetime as dt

import pytest
from conftest import mails
from sqlalchemy import select
from tungsten_hr import (
    Attendance,
    Employee,
    Holiday,
    LeaveError,
    LeaveRequest,
    approve_leave,
    check_in,
    check_out,
    count_days,
    leave_balance,
    reject_leave,
    request_leave,
)

from tungsten.models import DatabaseNotification

MONDAY = dt.date(2026, 11, 2)


def session(panel):
    db = panel.db()
    db.info["tungsten_panel"] = panel
    return db


def action(client, host, name, record, scope="page", **data):
    return client.post("/admin/_tw/action", {"_tw_host": f"resource:{host}", "_tw_scope": scope, "_tw_name": name,
                                             "_tw_record": str(record), **data})


def test_pages_load(admin):
    for url in ("/admin/employees", "/admin/employees/create", "/admin/employees/1", "/admin/departments",
                "/admin/attendance", "/admin/attendance/create", "/admin/leave-requests",
                "/admin/leave-requests/create", "/admin/leave-types", "/admin/holidays", "/admin/"):
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[:500])
    page = admin.get("/admin/employees/1").text
    assert "Leave left this year" in page and "Casual" in page and "Attendance this month" in page
    assert "Check in" in admin.get("/admin/attendance").text


def test_create_employee_gets_code(admin, panel):
    admin.get("/admin/employees/create")
    r = admin.post("/admin/employees/create", {"first_name": "Neha", "last_name": "Kapoor", "status": "active",
                                               "employment_type": "full_time", "department_id": "1"})
    assert r.status_code == 204, r.text
    with session(panel) as db:
        neha = db.scalars(select(Employee).where(Employee.first_name == "Neha")).one()
        assert neha.code == "EMP-0003" and neha.department.name == "Sales"


def test_days_skip_weekends_and_holidays(panel):
    with session(panel) as db:
        assert count_days(db, MONDAY, MONDAY + dt.timedelta(days=6)) == 5
        db.add(Holiday(name="Diwali", date=MONDAY + dt.timedelta(days=1)))
        db.add(Holiday(name="Optional", date=MONDAY + dt.timedelta(days=2), is_optional=True))
        db.flush()
        assert count_days(db, MONDAY, MONDAY + dt.timedelta(days=6)) == 4
        assert count_days(db, MONDAY, MONDAY, half_day=True) == 0.5


def test_leave_limits_and_clashes(panel):
    with session(panel) as db:
        ravi = db.get(Employee, 2)
        first = request_leave(db, ravi, 1, MONDAY, MONDAY + dt.timedelta(days=1))
        assert first.days == 2 and first.status == "pending"
        with pytest.raises(LeaveError, match="Only 0 Casual"):
            request_leave(db, ravi, 1, MONDAY + dt.timedelta(days=7))
        with pytest.raises(LeaveError, match="already a leave request"):
            request_leave(db, ravi, 2, MONDAY + dt.timedelta(days=1))
        with pytest.raises(LeaveError, match="weekends or holidays"):
            request_leave(db, ravi, 2, MONDAY - dt.timedelta(days=2), MONDAY - dt.timedelta(days=1))
        unpaid = request_leave(db, ravi, 2, MONDAY + dt.timedelta(days=7), MONDAY + dt.timedelta(days=11))
        assert unpaid.days == 5
        # the manager (head of Sales, user 1) gets a bell note for each request
        bell = db.scalars(select(DatabaseNotification)).all()
        assert [n.user_id for n in bell] == ["1", "1"] and bell[0].data["title"] == "Leave request"


def test_approve_marks_attendance_and_emails(panel):
    with session(panel) as db:
        ravi = db.get(Employee, 2)
        request = request_leave(db, ravi, 1, MONDAY, MONDAY + dt.timedelta(days=1), reason="Wedding")
        assert approve_leave(db, request, user_id="1")
        db.commit()
        days = db.scalars(select(Attendance).where(Attendance.employee_id == 2).order_by(Attendance.date)).all()
        assert [(d.date, d.status) for d in days] == [(MONDAY, "leave"), (MONDAY + dt.timedelta(days=1), "leave")]
        balance = {row["name"]: row for row in leave_balance(db, ravi, MONDAY.year)}
        assert balance["Casual"]["used"] == 2 and balance["Casual"]["left"] == 0
        assert balance["Unpaid"]["left"] is None
        to, subject, body = mails[-1]
        assert to == "ravi@example.com" and "approved" in subject and "2 day(s)" in body
        # cancelling an approved leave clears its attendance days
        from tungsten_hr import decide_leave

        decide_leave(db, request, "cancelled", user_id="1")
        db.commit()
        assert db.scalars(select(Attendance).where(Attendance.employee_id == 2)).all() == []


def test_reject_with_note(panel):
    with session(panel) as db:
        request = request_leave(db, db.get(Employee, 2), 2, MONDAY)
        reject_leave(db, request, user_id="1", note="Month-end closing")
        db.commit()
        assert request.status == "rejected" and request.review_note == "Month-end closing"
        assert "Month-end closing" in mails[-1][2]


def test_check_in_and_out(panel):
    with session(panel) as db:
        ravi = db.get(Employee, 2)
        row = check_in(db, ravi, dt.datetime.combine(MONDAY, dt.time(9, 45)))
        assert row.status == "present" and row.is_late
        row = check_out(db, ravi, dt.datetime.combine(MONDAY, dt.time(12, 15)))
        assert row.hours == 2.5 and row.status == "half_day"
        early = check_in(db, db.get(Employee, 1), dt.datetime.combine(MONDAY, dt.time(9, 0)), remote=True)
        assert early.status == "remote" and not early.is_late


def test_ask_for_leave_in_panel_and_approve(ravi, panel):
    ravi.get("/admin/leave-requests/create")
    page = ravi.get("/admin/leave-requests/create").text
    assert 'value="2" selected' in page or "Ravi Staff (EMP-0002)" in page
    r = ravi.post("/admin/leave-requests/create", {
        "employee_id": "2", "leave_type_id": "1", "start_date": MONDAY.isoformat(),
        "end_date": (MONDAY + dt.timedelta(days=4)).isoformat(), "reason": "Trip"})
    assert r.status_code == 200 and "Only 2 Casual day(s) left" in r.text
    r = ravi.post("/admin/leave-requests/create", {
        "employee_id": "2", "leave_type_id": "1", "start_date": MONDAY.isoformat(),
        "end_date": MONDAY.isoformat(), "reason": "Trip"})
    assert r.status_code == 204, r.text
    with session(panel) as db:
        request = db.scalars(select(LeaveRequest)).one()
        assert request.days == 1 and request.status == "pending"
        assert db.scalars(select(DatabaseNotification)).one().user_id == "1"
    # Ravi can't approve his own leave
    assert "Approve" not in ravi.get(f"/admin/leave-requests/{request.id}").text


def test_manager_approves_from_panel(admin, panel):
    with session(panel) as db:
        request = request_leave(db, db.get(Employee, 2), 1, MONDAY)
        db.commit()
        request_id = request.id
    assert "Approve" in admin.get(f"/admin/leave-requests/{request_id}").text
    r = action(admin, "leave-requests", "approve", request_id)
    assert r.status_code in (200, 204), r.text
    with session(panel) as db:
        assert db.get(LeaveRequest, request_id).status == "approved"
        bell = db.scalars(select(DatabaseNotification).where(DatabaseNotification.user_id == "2")).one()
        assert bell.data["title"] == "Leave approved"


def test_check_in_button_and_bulk_attendance(admin, panel):
    r = action(admin, "attendance", "check_in", "", remote="1")
    assert r.status_code in (200, 204), r.text
    with session(panel) as db:
        row = db.scalars(select(Attendance).where(Attendance.employee_id == 1)).one()
        assert row.date == dt.date.today() and row.status == "remote" and row.source == "self"
    admin.get("/admin/employees")
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:employees", "_tw_scope": "bulk",
                                         "_tw_name": "mark_attendance", "records": ["1", "2"],
                                         "date": MONDAY.isoformat(), "status": "absent"})
    assert r.status_code in (200, 204), r.text
    with session(panel) as db:
        rows = db.scalars(select(Attendance).where(Attendance.date == MONDAY)).all()
        assert sorted((r.employee_id, r.status) for r in rows) == [(1, "absent"), (2, "absent")]


def test_attendance_one_row_per_day(admin, panel):
    with session(panel) as db:
        db.add(Attendance(employee_id=2, date=MONDAY, status="present"))
        db.commit()
    admin.get("/admin/attendance/create")
    r = admin.post("/admin/attendance/create", {"employee_id": "2", "date": MONDAY.isoformat(),
                                                "status": "absent"})
    assert r.status_code == 200 and "already has attendance" in r.text
    r = admin.post("/admin/attendance/create", {"employee_id": "2", "date": (MONDAY + dt.timedelta(days=1))
                                                .isoformat(), "status": "present", "check_in": "10:00",
                                                "check_out": "18:30"})
    assert r.status_code == 204, r.text
    with session(panel) as db:
        row = db.scalars(select(Attendance).where(Attendance.date == MONDAY + dt.timedelta(days=1))).one()
        assert row.hours == 8.5 and row.is_late
