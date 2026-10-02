---
title: Email verification
description: Make users confirm their email address with a signed link before they can use the panel.
---

Email verification makes sure a user really owns the email address on their account. Tungsten emails them a link. Until they open it, they can sign in but only see a "Verify your email" page.

## Turning it on

Add a nullable date-time column to your user model, then turn on `email_verification`:

```python
import datetime as dt

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)
    password: Mapped[str]
    email_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
```

```python
from tungsten import Auth, Panel

panel = Panel(..., auth=Auth(User, email_verification=True))
```

A user counts as verified when `email_verified_at` has a value. It is empty (`None`) until they click the link, then Tungsten stores the current date and time.

### Using another column name

If your column is called something else, pass `verified_field`:

```python
Auth(User, email_verification=True, verified_field="confirmed_at")
```

## What users see

1. A new user signs up (with `registration=True`). Tungsten emails them a verification link right away.
2. They can sign in, but every panel page sends them to the **Verify your email** page. It shows their address, a **Resend verification email** button and a **Sign out** button.
3. They open the link from the email. Their email is marked as verified and they are sent to the dashboard (or to the login page, if they opened the link while signed out).

If a user who is already verified opens the "Verify your email" page, they go straight to the dashboard.

> [!NOTE]
> The link works without being signed in. Users can open it on another device, then sign in normally.

## The email

The email is sent through your `Auth(mailer=...)` function, like password reset emails. The subject is "Verify your *Brand name* email address" and the body has the link and how long it works. Both are translated into the user's language.

Your mailer gets `kind="verification"` if it asks for it, so you can use a special template:

```python
def send_mail(to, subject, body, url, kind):
    if kind == "verification":
        html = f'<p>Welcome! <a href="{url}">Confirm your email</a></p>'
    else:
        html = f'<p><a href="{url}">Reset your password</a></p>'
    my_mail_service.send(to=to, subject=subject, text=body, html=html)


Auth(User, email_verification=True, mailer=send_mail)
```

By default emails are only printed to the console. See [Sending email](authentication#sending-email) to send real ones.

### The link's address

The link starts with `Panel(app_url=...)`, for example `https://admin.acme.example/admin/email-verification/verify/...`. Set `app_url` in production. Without it, the link uses the host name of the request, which a visitor can fake. See the [security checklist](security#production-checklist).

## Link lifetime

Links work for 60 minutes. Change it with `verification_minutes`:

```python
Auth(User, email_verification=True, verification_minutes=24 * 60)   # one day
```

An expired, changed or fake link shows a "This link has expired" page. A signed-in user can ask for a new link from there. A signed-out user is asked to sign in first.

### How the link is protected

The link holds a signed token. It contains the user's id and their email address, and is signed with the panel's `secret_key`. This means:

- Nobody can make a valid link without the secret key.
- The link stops working after `verification_minutes`.
- If the user's email changes, old links stop working, because the email inside no longer matches.
- If you change `secret_key`, all old links stop working.

There is nothing to store in the database for verification links.

## Resend throttle

The **Resend verification email** button sends a fresh link. To stop people flooding an inbox, it works once a minute. Pressing it again sooner shows "Please wait a moment. You can ask for a new link once a minute."

The limit is counted per browser session.

## Changing the email address

When a user changes their email on the **My profile** page:

1. The verified date is cleared, so the new address counts as unverified.
2. A new verification link is sent to the new address (the resend limit is skipped for this one).
3. The user is taken to the "Verify your email" page.

Links sent to the old address stop working.

> [!NOTE]
> This only happens on the user's own profile page. If an admin changes a user's email in your own user resource, the verified date stays as it is. Clear it yourself in a resource hook if you want re-verification there.

For example:

```python
class UserResource(Resource):
    model = User

    @classmethod
    def before_save(cls, record, data):
        # runs before the new values are copied onto the record
        if "email" in data and data["email"].lower() != (record.email or "").lower():
            record.email_verified_at = None
```

## Users you create yourself

Only sign-up sends a verification email.

Users made with `tungsten make:user` are marked as verified, because an admin created them on purpose. Pass `--unverified` to make them confirm their email instead. See [CLI](cli).

Users you create another way (a seed script, or your own user form) start with an empty `email_verified_at`. When they sign in, they see the "Verify your email" page and can press **Resend** to get a link.

To skip that for trusted users, set the date when you create them:

```python
import datetime as dt

db.add(User(
    name="Asha",
    email="asha@example.com",
    password=hash_password("secret123"),
    email_verified_at=dt.datetime.now(),
))
```

## Showing who is verified

The column is a normal model column, so you can show it in your user table. The demo adds a check icon next to verified users' emails:

```python
TextColumn("email")
    .icon(lambda record: "badge-check" if record.email_verified_at else None, "after")
    .icon_color("success")
```

Or filter by it:

```python
from tungsten.tables import TernaryFilter

TernaryFilter("email_verified_at").label("Email verified").nullable()
```

See [Table columns](table-columns) and [Table filters](table-filters) for more.
