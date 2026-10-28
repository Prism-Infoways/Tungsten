---
title: Notifications
description: Show toast messages, store notifications for the bell, email them, and push them live to open tabs.
---

Tungsten has two kinds of notifications, both built with the same `Notification` class. A **toast** is a small message that pops up in the corner and disappears after a few seconds. A **database notification** is stored and shown in the notification bell in the top bar, so users see it even if they were not online.

The same notification can also go out by **email**, and be **pushed live** to the user's open tabs, so they see it right away without reloading.

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

Toasts and the bell can show any [Lucide](https://lucide.dev/icons) icon.

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

Add link buttons to a notification with `action(label, url, color="primary")`. You can add several. `color` sets the link color, like `"danger"` or `"gray"`.

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

- `users` can be a user object, a user id, or a list of either. For a user object, its primary key is stored, even when the key column is not called `id`.
- The second argument can be a database session or `ctx`.
- It commits the session.

In the bell, users can open the list (the 30 newest), click the action links, **Mark read** one notification, **Mark all read**, or **Clear** them all. The unread count updates at once over the [live connection](#live-notifications), and is also checked every 30 seconds.

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
    notifications_live=True,         # push to open tabs over a WebSocket (default True)
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

## Email notifications

`send_to_mail(users, ctx)` emails the notification. It uses the mailer you gave `Auth(mailer=...)`, the same one that sends password reset links (see [Authentication](authentication)).

```python
Notification("Invoice paid") \
    .body(f"{invoice.number} was paid by {invoice.customer.name}.") \
    .action("Open invoice", InvoiceResource.get_url(ctx, "view", invoice)) \
    .send_to_mail(accountants, ctx)
```

- `users` can be a user object, a user id, an email address, or a list of these. Users without an email are skipped.
- The title is the subject. Pass `subject="..."` for another one.
- The email text is the body, then each action as `Label: link`. Links that start with `/` become full links using the panel's `app_url` (or the current request's address). Set `app_url` so links in emails from background jobs work too.
- A mailer that also takes an `html` argument gets an HTML version with buttons. A mailer that takes `notification` gets the notification as a dict.
- If the mailer fails, the error is logged and the request carries on, so a mail server problem never undoes the user's work.

A mailer that sends both versions with Python's `smtplib`:

```python
import smtplib
from email.message import EmailMessage

def mailer(to, subject, body, html=None):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "admin@acme.example", to, subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP("smtp.acme.example", 587) as smtp:
        smtp.starttls()
        smtp.login("admin@acme.example", "app-password")
        smtp.send_message(msg)

panel = Panel(auth=Auth(User, mailer=mailer), app_url="https://admin.acme.example", ...)
```

To store a notification and email it, chain both:

```python
Notification("Ticket assigned").action("Open", url).send_to_database(agent, ctx).send_to_mail(agent, ctx)
```

## Live notifications

Every signed-in tab keeps a WebSocket open to the panel (`<path>/_tw/live`). Two things use it:

- `send_to_database(...)` tells the users' open tabs, and their bell count updates at once instead of at the next check.
- `broadcast(users, ctx)` shows the notification as a toast right now, in every open tab of those users. It is not stored, so a user with no tab open never sees it. Chain `send_to_database` too if it should also stay in the bell.

```python
# a long export finished in a background job: pop a toast and keep a copy in the bell
Notification("Export ready").body("orders.xlsx is ready to download.") \
    .action("Download", download_url).success().persistent() \
    .broadcast(user, db).send_to_database(user, db)
```

`broadcast` and `send_to_database` take `ctx` or a database session, like before. Outside a request the panel is found from the session (inside `panel.with_session(...)`), or it is the app's only panel.

### Server setup

- The server needs WebSocket support. Install `uvicorn[standard]` (or `pip install "tungsten-admin[live]"`, which adds the `websockets` package). Without it the bell still works by polling.
- Behind nginx, pass the upgrade headers for the panel path:

  ```nginx
  location /admin/_tw/live {
      proxy_pass http://127.0.0.1:8000;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_set_header Host $host;
      proxy_read_timeout 1h;
  }
  ```

- The socket only accepts the signed-in user's own session cookie from the same site, and only carries that user's notifications.
- `notifications_live=False` turns it off.

### More than one worker or server

By default, messages go to tabs connected to the same process. With several workers (`uvicorn --workers 4`, gunicorn) or servers, a message sent in one process must reach the others. Give the panel a broadcaster that passes messages through a shared channel. A Redis example:

```python
import asyncio, json
import redis
from tungsten.broadcast import Broadcaster

class RedisBroadcaster(Broadcaster):
    def __init__(self, url):
        super().__init__()
        self.redis = redis.Redis.from_url(url)
        listener = self.redis.pubsub(ignore_subscribe_messages=True)
        listener.subscribe(**{"tungsten-live": self._received})
        listener.run_in_thread(daemon=True, sleep_time=0.5)

    def publish(self, user_id, message):          # every process ...
        self.redis.publish("tungsten-live", json.dumps({"user": str(user_id), "message": message}))

    def _received(self, item):                    # ... delivers to its own tabs
        data = json.loads(item["data"])
        self.deliver(data["user"], data["message"])

panel = Panel(..., broadcaster=RedisBroadcaster("redis://localhost:6379/0"))
```

## Translations

`send(ctx)` translates the title, body and action labels into the user's language. Write them in English and add the text to your language files. See [Translations](translations).

```python
Notification("Order shipped").success().send(ctx)   # shown in Hindi to a Hindi user, if lang/hi.json has "Order shipped"
```

Database notifications are stored as written, and the bell translates the title, body and action labels into each user's language when it shows them. Text with values filled in (like an order number) is only translated if that exact text is in your language file, so it usually shows as written.

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
| `send_to_database(users, db_or_ctx)` | Store for the bell (and update open bells live). |
| `send_to_mail(users, db_or_ctx, subject=None)` | Email it through the panel's mailer. |
| `broadcast(users, db_or_ctx)` | Show as a toast now in the users' open tabs. |
| `to_dict()` | The notification as a plain dict. |

## Links in a new tab

`Notification("Ready").action("Open", url, new_tab=True)` opens the link in a new tab.
