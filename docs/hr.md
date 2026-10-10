---
title: HR (employees, attendance, leave)
description: Add HR to your panel with employees, departments, attendance with a check-in button, leave requests with balances and approval, and holidays.
---

The `tungsten-hr` plugin adds an **HR** menu to your panel: employees, departments, attendance, leave requests, leave types and holidays. People who log in to the panel can check in, check out and ask for leave. Managers approve it in one click.

## Install

```bash
pip install tungsten-hr
```

```python
from tungsten_hr import HRPlugin

panel = Panel(..., auth=Auth(User, mailer=send_mail))
panel.plugin(HRPlugin())
panel.create_tables(engine)
```

`create_tables` makes the HR tables. `mailer` sends the leave emails; without it they are printed to the console.

## Employees

Each employee has a code (like `EMP-0007`, made for you when left empty), job title, department, manager, type, status, joining date, birthday, salary, contact details, a photo, documents and **Other details** for anything else (bank account, PAN, Aadhaar, blood group...).

Pick the panel login in **Logs in as** so that person can check in and ask for leave as themselves.

The employee page shows their **leave left this year** and **attendance this month**, with tables of their attendance and leave below.

## Departments

A department has a name, a code, a color and a **head**. When an employee has no manager, the head approves their leave.

## Attendance

There is one row per person per day: present, work from home, half day, absent, on leave or holiday, with check-in and check-out times.

- **Check in** and **Check out** buttons sit on top of the Attendance page for each person with a linked login.
- Hours are worked out from the two times. A check-in after `late_after` (9:30 by default) is marked late, in red. Fewer hours than `half_day_hours` (4) makes it a half day.
- Select people on the Employees list and use **Mark attendance** to fill a day for many people at once.
- Tabs: Today, This week, Late, Absent, All.

## Leave

1. Add **leave types** like Casual (12 days a year), Sick (8) or Unpaid (no limit).
2. Add **holidays**. Leave days skip weekends and holidays. Optional holidays still count.
3. People ask for leave from **Leave requests**. The form shows how many working days it is, and stops clashing requests and requests over the balance with a clear message.
4. The manager gets a bell note and presses **Approve** or **Reject** (with a reason). Many can be approved at once.
5. The employee gets a bell note and an email. Approved days show as "On leave" in attendance. Cancelling an approved leave clears those days again.

Nobody can approve their own leave.

## Options

```python
HRPlugin(
    weekend=(5, 6),               # days off: Monday is 0. (6,) for Sunday only
    late_after=time(9, 30),       # later check-ins are marked late. None: never late
    half_day_hours=4,             # fewer hours than this is a half day
    code_prefix="EMP-",
    email_employees=True,
    notify=True,
    mailer=None,                  # defaults to Auth(mailer=...)
    navigation_group="HR",
)
```

## From code

```python
from tungsten_hr import approve_leave, check_in, leave_balance, mark_attendance, request_leave

check_in(db, employee)
mark_attendance(db, employee, date(2026, 11, 2), "absent")
request = request_leave(db, employee, leave_type, date(2026, 11, 2), date(2026, 11, 4), reason="Wedding")
approve_leave(db, request, user_id="1")
db.commit()
```

`request_leave` raises `LeaveError` with a plain message when the leave can't be given.

## Hooks

```python
hr = panel.get_plugin("hr")
hr.on_employee_created("payroll", lambda db, employee: ...)
hr.on_leave_requested("slack", lambda db, request: ...)
hr.on_leave_decided("whatsapp", lambda db, request, old_status: ...)
```
