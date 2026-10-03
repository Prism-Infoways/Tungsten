---
title: Authentication
description: Sign-in, sign-up, password reset, the profile page, two-factor login and how emails are sent.
---

Tungsten has a complete sign-in system built in. Pass an `Auth` object to your panel and you get a login page, password reset, a profile page and, if you want them, sign-up and two-factor login.

## Turning on auth

Give `Auth` your user model:

```python
from tungsten import Auth, Panel

from app.models import User

panel = Panel(
    session_factory=SessionLocal,
    secret_key="a-long-random-string",
    auth=Auth(User),
)
panel.create_tables(engine)   # password resets, 2FA and roles live in Tungsten's own tables
```

The user model needs:

- a primary key (`id`),
- an email column (`email`),
- a password hash column (`password`),
- optionally a name column (`name`), used in the user menu and greetings.

If your columns have other names, tell `Auth`:

```python
Auth(User, email_field="login_email", password_field="password_hash", name_field="full_name")
```

> [!WARNING]
> Without `auth=`, the panel has no login and anyone who can reach the URL can use it. Only do that behind your own protection.

### Creating the first user

Use the CLI. It hashes the password for you:

```bash
tungsten make:user --panel app.admin:panel --role "Super Admin"
```

Or in code, hash the password with `hash_password`:

```python
from tungsten import hash_password

db.add(User(name="Asha", email="asha@example.com", password=hash_password("secret123")))
db.commit()
```

## Auth options

| Option | Default | What it does |
| --- | --- | --- |
| `email_field` | `"email"` | Column used to sign in |
| `password_field` | `"password"` | Column holding the password hash |
| `name_field` | `"name"` | Column shown as the user's name |
| `avatar_field` | `None` | Column with a photo path or URL. Adds a photo upload to the profile page. |
| `active_field` | `None` | Boolean column. Users where it is false can't sign in, and are signed out. |
| `can_access` | `None` | Function that decides who may use the panel, e.g. `lambda user: user.is_staff` |
| `gate` | `None` | Function that answers permission checks. See [Roles and permissions](roles-and-permissions#custom-gate). |
| `super_admin` | `None` | Function that marks users who may do everything (with RBAC) |
| `mailer` | prints to the console | Function that sends emails. See [Sending email](#sending-email). |
| `hasher` | PBKDF2-SHA256 | Your own password hasher. See [Custom password hasher](#custom-password-hasher). |
| `password_reset` | `True` | The "Forgot password?" pages |
| `profile` | `True` | The "My profile" page |
| `registration` | `False` | A "Create an account" page |
| `on_register` | `None` | Function called for each new sign-up |
| `two_factor` | `False` | Let users turn on two-factor login |
| `two_factor_required` | `False` | Make every user set up two-factor login |
| `email_verification` | `False` | Make users confirm their email. See [Email verification](email-verification). |
| `verified_field` | `"email_verified_at"` | Column storing when the email was confirmed |
| `verification_minutes` | `60` | How long a verification link works |
| `reset_token_minutes` | `60` | How long a password reset link works |
| `max_login_attempts` | `5` | Failed sign-ins allowed per minute |

## Login

The login page lives at `<panel path>/login`. Anyone who is not signed in is sent there, and back to the page they wanted after signing in.

### Who can sign in

By default every user with a correct password can sign in. Use `can_access` to limit it, for example to staff:

```python
Auth(User, can_access=lambda user: user.is_admin)
```

The function can ask for `user`, `ctx` and `panel`. It is checked at sign-in and on every request, so a user who loses access is signed out.

Use `active_field` to block disabled accounts:

```python
Auth(User, active_field="is_active")
```

### Rate limiting

After 5 failed attempts within a minute for the same IP address and email, the login form shows "Too many login attempts. Please try again in a minute." Change the number with `max_login_attempts`.

> [!NOTE]
> The attempt counter is kept in memory, per server process. With several workers, each one counts on its own, and a restart resets it. See [Security](security#login-protection).

### Signing out

The user menu has a **Sign out** button. It sends a POST to `<panel path>/logout`.

## Sign-up

Turn on `registration` to add a "Create an account" link on the login page:

```python
def setup_new_user(user, db):
    user.is_admin = True        # let them into the panel


Auth(User, registration=True, on_register=setup_new_user)
```

The sign-up form asks for name, email (must be unique), password (at least 8 characters) and password confirmation.

- `on_register` runs before the new user is saved. It can ask for `user`, `db` and `ctx`. Use it to fill extra columns or link the user to a team.
- After saving, the user is signed in right away, if `can_access` and `active_field` allow it. If not, the page says the account was created.
- With [email verification](email-verification) on, a verification email is sent straight away.

## Forgot and reset password

The login page has a "Forgot password?" link. The flow:

1. The user enters their email.
2. If a user with that email exists, Tungsten emails a reset link. The page says the same thing either way, so nobody can test which emails are registered.
3. The link opens a form for a new password (at least 8 characters, typed twice).
4. After saving, the link stops working and the user can sign in.

Links work for 60 minutes. Change it with `reset_token_minutes`:

```python
Auth(User, reset_token_minutes=30)
```

Tokens are stored as a hash in the `tungsten_password_resets` table, so you need `panel.create_tables()`. Turn the whole feature off with `password_reset=False`.

## Sending email

Tungsten sends two kinds of email: password reset links and [verification links](email-verification). Both go through the `mailer` function.

By default the mailer only prints the email to the console and the log. That is handy in development. In production, pass your own function:

```python
import smtplib
from email.message import EmailMessage


def send_mail(to, subject, body):
    msg = EmailMessage()
    msg["From"] = "Acme Admin <no-reply@acme.example>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP("smtp.acme.example", 587) as smtp:
        smtp.starttls()
        smtp.login("no-reply@acme.example", "smtp-password")
        smtp.send_message(msg)


panel = Panel(..., auth=Auth(User, mailer=send_mail))
```

The mailer always gets `to`, `subject` and `body` (plain text, already in the user's language). If you add these parameter names, it also gets:

| Parameter | What it is |
| --- | --- |
| `url` | The link inside the email |
| `user` | The user the email is for |
| `kind` | `"password_reset"` or `"verification"` |

Use them to build your own HTML email:

```python
def send_mail(to, subject, body, url, kind):
    html = render_template(f"emails/{kind}.html", url=url)
    my_mail_service.send(to=to, subject=subject, text=body, html=html)
```

> [!WARNING]
> Set the public address of your site with `Panel(app_url="https://admin.acme.example")`. Links in emails are built from it. Without `app_url`, they use the host name of the current request, which a visitor can fake. If you rely on that, make sure your server passes the real host and scheme (for example `uvicorn --proxy-headers`) and add `TrustedHostMiddleware`. See the [security checklist](security#production-checklist).

The mailer can be `async def`. This is a good idea with an [async engine](async-database), so a slow mail server doesn't block other requests.

## Profile page

Every signed-in user gets a **My profile** page from the user menu (`<panel path>/profile`). It has two sections:

- **Profile information**: name, email (must be unique) and, if you set `avatar_field`, a profile photo.
- **Update password**: current password, new password (at least 8 characters) and confirmation. The current password must be correct.

When two-factor login is on, the profile also shows a two-factor card with a **Set up** or **Manage** button.

Turn the page off with `Auth(User, profile=False)`.

## Two-factor login

Two-factor login adds a second step: after the password, the user enters a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy...). These codes are called TOTP codes (time-based one-time passwords) and change every 30 seconds.

```python
Auth(User, two_factor=True)
```

Now users can turn it on from their profile. The secrets are stored in the `tungsten_two_factor` table, so run `panel.create_tables()`.

### Setting it up (as a user)

1. Open **My profile** and click **Set up** on the two-factor card.
2. Click to enable, then scan the QR code with an authenticator app (or type the secret key shown).
3. Enter one code from the app to confirm.
4. Save the **8 recovery codes** that appear. They are shown only once.

From the same page users can create new recovery codes or turn two-factor off. Both ask for the account password.

### Signing in with two-factor

After a correct password, users with two-factor on see a second page asking for the code. They can enter:

- a 6-digit code from their app, or
- one of their recovery codes, if they lost their phone.

Each code works only once. A recovery code is removed when used. The second step must be finished within 10 minutes, and wrong codes are rate limited like the login form.

### Requiring two-factor for everyone

```python
Auth(User, two_factor_required=True)
```

Users who haven't set it up are sent to the setup page after signing in, with a message. They can't open other pages until it is done, and they can't turn it off.

## Custom password hasher

Passwords are hashed with PBKDF2-SHA256 (390,000 rounds) by default. `hash_password()` and `verify_password()` in `tungsten` do this.

To use another algorithm, pass an object with two methods: `hash(password)` returns the hash, and `verify(password, hashed)` returns `True` or `False`. Here is one for Argon2 using the `argon2-cffi` package:

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

_argon = PasswordHasher()


class ArgonHasher:
    def hash(self, password):
        return _argon.hash(password)

    def verify(self, password, hashed):
        try:
            return _argon.verify(hashed or "", password)
        except (VerificationError, InvalidHashError):
            return False


Auth(User, hasher=ArgonHasher())
```

Tungsten uses it for login, sign-up, password reset, the profile page and `tungsten make:user`.

> [!WARNING]
> If you hash passwords in your own user form, use the same hasher. `hash_password()` always uses PBKDF2. In a form you can call the panel's hasher instead:
> `TextInput("password").password().dehydrate_state_using(lambda state, ctx: ctx.panel.auth.hash(state))`

## Permissions

Signing in answers "who are you?". To decide "what can you do?", Tungsten has roles and permissions, resource policies and a custom gate function. By default, every user who can sign in can do everything.

See [Roles and permissions](roles-and-permissions) for the full guide. In short:

- `panel.rbac()` adds a **Roles & Permissions** screen.
- `Auth(User, gate=...)` lets one function decide every permission.
- `policy = OrderPolicy()` on a resource decides per record.
