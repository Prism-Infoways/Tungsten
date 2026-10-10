# tungsten-hr

HR plugin for [Tungsten](https://tungsten.prisminfoways.com/), the admin panel for FastAPI.

## What you get

- **Employees** with a code (`EMP-0007`), job title, department, manager, type (full time, part time, contract, intern), status (active, on probation, on notice, left), joining date, birthday, salary, address, emergency contact, photo, documents and your own extra details (bank, PAN, Aadhaar...).
- **Departments** with a head.
- **Attendance**: one row per person per day (present, work from home, half day, absent, on leave, holiday), check-in and check-out times, hours worked and late marks.
- A **Check in / Check out** button for each person who logs in to the panel. Short days become half days by themselves.
- **Biometric machines** (eSSL, ZKTeco and others): the machine sends punches by itself (ADMS / Cloud server), the panel fetches them over the office network, or you send them by API or upload a CSV / Excel file. First punch is the check-in, last is the check-out.
- **Mark attendance** for many people at once from the Employees list.
- **Leave requests** with leave types (Casual, Sick, Earned...), days per year, half days, and **balances** (left, used, waiting).
- Leave days skip **weekends and holidays**. Clashing requests and requests over the balance are stopped with a clear message.
- **Approve / Reject** buttons (one by one or many at once). Approved days show as "On leave" in attendance.
- The **manager** (or the department head) gets a bell note for each request. The employee gets a bell note and an **email** when it is approved or rejected.
- **Holidays** list, with optional holidays.
- Employee page with **leave left this year** and **attendance this month**, plus their attendance and leave tables.
- Dashboard numbers: employees, at work today, on leave today, leave to approve.
- Hooks so other plugins (payroll, WhatsApp, Slack...) can act on new employees and leave.

## Install

```bash
pip install tungsten-hr
```

```python
from tungsten_hr import HRPlugin

panel = Panel(..., auth=Auth(User, mailer=send_mail))
panel.plugin(HRPlugin())
panel.create_tables(engine)   # creates the HR tables too
```

To let a person check in and ask for leave, pick their panel login in the employee's **Logs in as** field.

### Options

```python
HRPlugin(
    weekend=(5, 6),               # days off: Monday is 0. (6,) for Sunday only
    late_after=time(9, 30),       # later check-ins are marked late. None: never late
    half_day_hours=4,             # fewer hours than this is a half day
    code_prefix="EMP-",
    email_employees=True,         # email people when their leave is approved or rejected
    notify=True,                  # bell notes for approvers and employees
    mailer=None,                  # defaults to Auth(mailer=...)
    navigation_group="HR",
    device_push=True,             # biometric machines send punches to /iclock/cdata
    auto_accept_devices=False,    # a new machine waits until you turn it on
    api_token=None,               # turns on POST <panel>/api/hr/punches
)
```

## Biometric machines

Set each person's **Machine ID** (their user ID / PIN on the machine). Then use any of these:

1. **Machine sends punches**: in the machine's Cloud Server / ADMS setting, put your site address (no `/admin`). It shows up under *Biometric machines*; turn it on.
2. **Panel fetches them** over the office network: `pip install "tungsten-hr[zk]"`, add the machine's IP, press *Fetch punches* (or run `pull_all(db)` from cron).
3. **API or file**: `POST <panel>/api/hr/punches` with `X-HR-Token`, or *Upload punches* on the Punches screen.

```bash
curl -X POST https://hr.example.com/admin/api/hr/punches -H "X-HR-Token: long-secret" \
  -H "Content-Type: application/json" -d '{"punches": [{"employee": "EMP-0002", "time": "2026-11-02 09:12:00"}]}'
```

See the [guide](https://tungsten.prisminfoways.com/docs/hr.html#biometric-machines) for the machine settings.

## From code

```python
from tungsten_hr import approve_leave, check_in, check_out, leave_balance, mark_attendance, request_leave

check_in(db, employee)                         # or check_out(db, employee)
mark_attendance(db, employee, date(2026, 11, 2), "absent")
request = request_leave(db, employee, leave_type, date(2026, 11, 2), date(2026, 11, 4), reason="Wedding")
approve_leave(db, request, user_id="1")
leave_balance(db, employee)                    # [{"name": "Casual", "allowed": 12, "used": 3, "left": 9, ...}]
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

## Try it

```bash
pip install -e . -e plugins/hr uvicorn
uvicorn plugins.hr.example:app --reload
```

Sign in at http://127.0.0.1:8000/admin with admin@example.com / password. Sign in as rohit@example.com / password to see the employee side.

## More Tungsten plugins

| Package | What it adds | Docs |
| --- | --- | --- |
| [`tungsten-tickets`](https://pypi.org/project/tungsten-tickets/) | Help desk: tickets, replies, notes, SLA and a customer support page | [Guide](https://tungsten.prisminfoways.com/docs/tickets.html) |
| [`tungsten-leads`](https://pypi.org/project/tungsten-leads/) | Leads list, stages, timeline and your own lead form fields | [README](https://github.com/Prism-Infoways/Tungsten/tree/claude/tungsten-admin-panel/plugins/leads) |
| [`tungsten-blog`](https://pypi.org/project/tungsten-blog/) | Blog built for SEO, GEO and AEO, with a live score, sitemap and llms.txt | [Guide](https://tungsten.prisminfoways.com/docs/blog.html) |
| [`tungsten-mcp`](https://pypi.org/project/tungsten-mcp/) | MCP server, so AI assistants like Claude can read and change your data | [Guide](https://tungsten.prisminfoways.com/docs/mcp.html) |
| [`tungsten-finance`](https://pypi.org/project/tungsten-finance/) | Finance: invoices with GST, payments, expenses, bank balances and profit reports | [Guide](https://tungsten.prisminfoways.com/docs/finance.html) |

See [all plugins](https://github.com/Prism-Infoways/Tungsten/tree/claude/tungsten-admin-panel/plugins).
