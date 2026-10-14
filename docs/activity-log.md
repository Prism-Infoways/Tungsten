---
title: Activity log
description: Keep a record of who created, changed, deleted and exported what, which actions ran, and every sign-in.
---

The activity log answers "who did this, and when?". With it on, Tungsten writes a row for each change made through the panel, each action run, and each sign-in.

## Turning it on

```python
panel = Panel(..., activity_log=True)
panel.create_tables(engine)   # creates tungsten_activity_log with Tungsten's other tables
```

## What is logged

| Event | When |
| --- | --- |
| `created` | A record is created, on the create page or in a create popup. |
| `updated` | A record is saved, on the edit page or in an edit popup. |
| `deleted` | A record is deleted (or moved to the trash), alone or in a bulk delete. |
| `restored` | A record comes back from the trash. |
| `force_deleted` | A trashed record is deleted for good. |
| `action` | Any other action runs, like "Approve" or "Ship". One row per record, or one row for a page or header action. |
| `exported` | A table is exported to CSV or Excel. |
| `login` | Someone signs in (after the two-factor code, when that is on). |
| `login_failed` | A wrong email or password, or too many tries. The typed email is kept. |
| `two_factor_failed` | A wrong two-factor code. |
| `logout` | Someone signs out. |
| `registered` | Someone creates an account on the sign-up page. |
| `password_reset` | Someone sets a new password with a reset link. |

Sign-in rows also keep the IP address and browser (`ip`, `user_agent`). Action rows keep the action's name and label.

## The table

Each row of `tungsten_activity_log` has:

| Column | What it holds |
| --- | --- |
| `user_id` | Who did it (empty for a failed sign-in or a visitor). |
| `subject_type` | The model's class name, like `Product` or `User`. |
| `subject_id` | The record's primary key (empty when there is no single record). |
| `event` | One of the events above, or your own. |
| `description` | A short text, like "Ran Approve". |
| `properties` | Extra details as JSON. |
| `created_at` | When it happened. |

Read it like any other table:

```python
from sqlalchemy import select
from tungsten.models import ActivityLog

recent = db.scalars(select(ActivityLog).order_by(ActivityLog.id.desc()).limit(50)).all()
```

To browse it in the panel, add a read-only resource for the `ActivityLog` model.

## Logging your own events

Call `panel.log_activity(ctx, event, record, description, properties)` anywhere you have `ctx`:

```python
def refund(record, ctx):
    gateway.refund(record.payment_id)
    ctx.panel.log_activity(ctx, "refunded", record, f"Refunded {record.total}", {"amount": record.total})
```

- It does nothing while `activity_log` is off, so plugins can call it freely.
- Without a record, pass `subject_type="..."` (and `subject_id=...` if you have one).
- It adds the row to the request's database session, so it is saved with the session's next commit. Pass `commit=True` to save it right away.
- The same event on the same record is only written once per request, so logging a delete yourself and then calling the built-in delete does not make two rows.

## Turning logging off for an action

Actions log by default. Turn one off with `log_activity(False)`:

```python
Action("recalculate").log_activity(False).action(lambda record: record.recalculate())
```

The built-in create, edit, view, delete, restore and force delete actions don't add an `action` row, since their `created`, `updated`, `deleted` (and so on) row already says what happened.
