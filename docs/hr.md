---
title: HR (employees, attendance, leave)
description: Add HR to your panel with employees, departments, attendance with a check-in button and biometric machines, leave requests with balances and approval, and holidays.
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

## Biometric machines

Punches from fingerprint or face machines become attendance. The first punch of a day is the check-in and the last one is the check-out. Late marks and half days work as above.

First, put each person's number on the machine (their user ID or PIN) in the employee's **Machine ID** field. Punches that arrive before that are kept, and they are used as soon as the ID is set. They show under **Punches**, in the "Not matched" tab.

Pick any of the three ways. You can use more than one.

### 1. The machine sends punches (eSSL / ZKTeco ADMS)

Most eSSL and ZKTeco machines have a **Cloud server** or **ADMS** setting. In the machine's menu, open Comm, then Cloud Server Setting:

- Server address: your site, like `hr.example.com` (no `/admin`)
- Server port: `443` with HTTPS on, or `80`
- Turn **Domain name** on if you type a name instead of an IP

The machine calls `https://your-site/iclock/cdata` and shows up under **Biometric machines**, switched off. Turn it on and its punches start coming in. To take punches from new machines at once, use `HRPlugin(auto_accept_devices=True)`.

### 2. The panel fetches punches over the office network

When the panel runs in the same network as the machine:

```bash
pip install "tungsten-hr[zk]"
```

Add the machine under **Biometric machines** with its IP address (port 4370 by default), then press **Fetch punches**. Only new punches are kept, so you can run it as often as you like, for example every 10 minutes from cron:

```python
from tungsten_hr import pull_all

panel.with_session(lambda db: pull_all(db))
```

### 3. API or file, for any machine or software

Upload a CSV or Excel file on the **Punches** screen with two columns: the machine ID or employee code, and the time.

Or send punches from your own software:

```python
HRPlugin(api_token="long-secret")
```

```bash
curl -X POST https://hr.example.com/admin/api/hr/punches \
  -H "X-HR-Token: long-secret" -H "Content-Type: application/json" \
  -d '{"punches": [{"employee": "EMP-0002", "time": "2026-11-02 09:12:00"}]}'
```

`employee` is the machine ID or the employee code. The answer counts what was saved and lists people it could not match. A punch sent twice is saved once.

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
    device_push=True,             # take punches from machines at /iclock/cdata
    auto_accept_devices=False,    # a new machine waits until you turn it on
    api_token=None,               # turns on POST <panel>/api/hr/punches
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
