---
title: Notifications
description: Show toast messages after something happens, and store notifications for the bell in the top bar.
---

Tungsten has two kinds of notifications, both built with the same `Notification` class. A **toast** is a small message that pops up in the corner and disappears after a few seconds. A **database notification** is stored and shown in the notification bell in the top bar, so users see it even if they were not online.

## Toast notifications

Build a notification and call `send(ctx)`:

```python
from tungsten import Notification

Notification("Saved").body("The product was updated.").success().send(ctx)
```

The toast shows up on the response to the current request. This works in [action](actions) closures, resource [hooks](resources#lifecycle-hooks), custom page `save()` methods, or anywhere else you have `ctx`. If the request ends in a redirect, the toast is kept and shown on the next page.

```python
def approve(record, db, ctx):
    record.approved = True
    db.commit()
    Notification("Approved").body(f"{record.name} can now sign in.").success().send(ctx)

Action("approve").icon("check").action(approve)
```

> [!TIP]
> For a simple success message after an action, `success_notification_title("...")` on the action is shorter. See [Actions](actions#notifications-after-an-action).

Tungsten sends its own toasts too, for example "Created", "Saved" and "Deleted" after the built-in pages and actions.

## Status, icon and color

A status sets the color and a matching icon in one go.

```python
Notification("Order shipped").success().send(ctx)        # green, check icon
Notification("Payment failed").danger().send(ctx)        # red, cross icon
Notification("Low stock").warning().send(ctx)            # yellow, warning icon
Notification("New version available").info().send(ctx)  # blue, info icon
```

| Method | What it does |
| --- | --- |
| `success()` | Green, with a check icon. |
| `danger()` | Red, with a cross icon. |
| `warning()` | Yellow, with a warning icon. |
| `info()` | Blue, with an info icon. |
| `status("success")` | Same as above, by name. |
| `icon("shopping-cart")` | Use another icon. Default: the status icon, or a bell. |
| `color("primary")` | Use another color. Default: the status color, or gray. |

> [!NOTE]
> Toasts can only show the status icons (`circle-check`, `circle-x`, `triangle-alert`, `info`) and `bell`, `copy` and `check`. Other icons show as a bell in a toast. The notification bell can show any Lucide icon.

## How long a toast stays

Toasts hide after 5 seconds. Change it in milliseconds, or keep the toast until the user closes it:

```python
Notification("Import started").body("This can take a minute.").duration(10000).send(ctx)
Notification("Backup failed").danger().persistent().send(ctx)
```

| Method | What it does |
| --- | --- |
| `duration(ms)` | Milliseconds before the toast hides. `None` keeps it open. |
| `persistent()` | Keep the toast until it is closed. Same as `duration(None)`. |

## Action links

Add link buttons to a notification with `action(label, url, color="primary")`. You can add several.

```python
Notification("Import finished").body("3 rows failed.") \
    .action("See failed rows", "/admin/imports/12") \
    .warning().send(ctx)
```

## Database notifications

`send_to_database(users, db)` stores the notification for one or more users. It shows up in the bell in the top bar, with a count of unread notifications.

```python
admins = db.scalars(select(User).where(User.is_admin.is_(True))).all()

Notification("New order") \
    .body(f"{order.number} was placed by {order.customer.name}.") \
    .icon("shopping-cart").color("primary") \
    .action("View order", OrderResource.get_url(ctx, "edit", order)) \
    .send_to_database(admins, db)
```

- `users` can be a user object, a user id, or a list of either.
- The second argument can be a database session or `ctx`.
- It commits the session.

In the bell, users can open the list (the 30 newest), click the action links, **Mark read** one notification, **Mark all read**, or **Clear** them all. The unread count refreshes every 30 seconds.

A full example from the demo: tell every admin about a new order, in a resource hook.

```python
class OrderResource(Resource):
    model = Order

    @classmethod
    def after_create(cls, record, db, ctx):
        admins = db.scalars(select(User).where(User.is_admin.is_(True))).all()
        Notification("New order").body(f"{record.number} was placed by {record.customer.name}.") \
            .icon("shopping-cart").color("primary") \
            .action("View order", cls.get_url(ctx, "edit", record)) \
            .send_to_database(admins, db)
```

### Setup

Database notifications are stored in Tungsten's own `tungsten_notifications` table. Create it once with the other Tungsten tables:

```python
panel.create_tables(engine)
```

Two panel options control the bell:

```python
panel = Panel(
    ...,
    database_notifications=True,     # show the bell (default True)
    notifications_polling="30s",     # how often the unread count refreshes; None turns polling off
)
```

The bell is only shown to signed-in users.

### Sending from scripts and background jobs

You don't need a request to store a notification. Pass any SQLAlchemy session:

```python
with SessionLocal() as db:
    Notification("Nightly report ready").info().send_to_database(user_id, db)
```

With an async engine, use `panel.with_session(lambda db: ...)` to get a normal session. See [Async database](async-database).

## Translations

`send(ctx)` translates the title, body and action labels into the user's language. Write them in English and add the text to your language files. See [Translations](translations).

```python
Notification("Order shipped").success().send(ctx)   # shown in Hindi to a Hindi user, if lang/hi.json has "Order shipped"
```

Database notifications are stored and shown as written. Use text with the values filled in, as in the examples above.

## All methods

| Method | What it does |
| --- | --- |
| `Notification(title)` / `Notification.make(title)` | Create a notification. |
| `title("...")` | Set or change the title. |
| `body("...")` | Text under the title. |
| `success()`, `danger()`, `warning()`, `info()` | Set the status. |
| `status(name)` | Set the status by name. |
| `icon(name)` | Lucide icon name. |
| `color(name)` | Color name. |
| `duration(ms)` | Milliseconds before a toast hides; `None` keeps it open. |
| `persistent()` | Keep a toast open until closed. |
| `action(label, url, color="primary")` | Add a link button. |
| `send(ctx)` | Show as a toast now. |
| `send_to_database(users, db_or_ctx)` | Store for the bell. |
| `to_dict()` | The notification as a plain dict. |
