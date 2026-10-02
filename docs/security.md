---
title: Security
description: How Tungsten protects your panel, and the settings to check before you go to production.
---

Tungsten has safe defaults for the common web risks: forged form posts, stolen sessions, password guessing, script injection and dangerous uploads. This page explains what each protection does and what you still need to set up yourself.

## Secret key and sessions

Tungsten keeps the signed-in user in a session cookie. The cookie is **signed** with the panel's `secret_key`, so nobody can change it without the key.

```python
import os

panel = Panel(
    ...,
    secret_key=os.environ["TUNGSTEN_SECRET_KEY"],
    https_only_cookies=True,
)
```

Make a good key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> [!WARNING]
> If you don't pass `secret_key`, Tungsten makes a random one each time the app starts. Everyone is signed out on every restart, and with several server processes each one has a different key, so sessions break. Always set a fixed key in production, and keep it out of your code.

The key also signs [email verification](email-verification) links. Changing the key signs everyone out and makes old links stop working. That is the quickest way to end all sessions at once.

About the cookie:

| Setting | Value |
| --- | --- |
| Name | `tungsten_<panel id>` (`tungsten_admin` by default) |
| `SameSite` | `Lax`: the browser doesn't send it with posts from other sites |
| `Secure` | Only with `https_only_cookies=True` (then it is sent over HTTPS only) |
| Lifetime | 14 days |

The cookie is signed, not encrypted. Tungsten only stores small things in it (the user id, the CSRF token, the chosen language and tenant). Don't put secrets in `ctx.session` yourself.

## CSRF protection

CSRF (cross-site request forgery) is when another website makes your browser send a form to your panel. Tungsten blocks it by checking a secret token on **every POST request**.

- Each session gets a random token.
- Tungsten's own forms send it as a hidden `_token` field, and HTMX requests send it in an `X-CSRF-Token` header.
- A POST without the right token gets a "Page expired. Please refresh and try again." response (status 419).

You don't need to do anything for Tungsten's pages, forms and actions. If you write your own HTML form that posts to a panel URL (for example in a custom page's `content_template`), add the token as a hidden field:

```html
<input type="hidden" name="_token" value="{{ ctx.panel.csrf_token(ctx) }}">
```

> [!NOTE]
> Routes you add with `panel.routes` are plain FastAPI routes. They don't get Tungsten's CSRF check or login check, so protect them yourself.

## Passwords

Passwords are hashed with **PBKDF2-SHA256** using 390,000 rounds and a random salt per password. The hash looks like `pbkdf2_sha256$390000$<salt>$<hash>`. Checking a password uses a constant-time compare.

```python
from tungsten import hash_password, verify_password

hashed = hash_password("secret123")
verify_password("secret123", hashed)   # True
```

To use Argon2, bcrypt or your framework's hasher, pass `Auth(hasher=...)`. See [Custom password hasher](authentication#custom-password-hasher).

Built-in forms ask for at least 8 characters for new passwords (sign-up, reset, profile). Add your own rules to your user form with `.min_length()` or `.rule()`. See [Form fields](form-fields).

## Login protection

- **Rate limiting.** 5 failed sign-ins per minute for the same IP address and email, then the form refuses for a minute. Change it with `Auth(max_login_attempts=...)`. The two-factor code page has the same limit.
- **Same error for everything.** A wrong email and a wrong password both show "These credentials do not match our records."
- **Password reset doesn't reveal users.** The "Forgot password?" page says the same thing whether the email exists or not.
- **Reset links** are random, stored only as a hash, work once, and expire after 60 minutes (`reset_token_minutes`).
- **Safe redirects.** After login, the `next` address must be inside the panel, so the login page can't be used to send people to other sites.
- **Two-factor login** with authenticator apps and one-time recovery codes. You can require it for everyone. See [Two-factor login](authentication#two-factor-login).

> [!NOTE]
> The login attempt counter lives in memory, in each server process. It is not shared between workers or servers, and it is reset when the app restarts. With 4 workers, an attacker can get about 4 times as many tries. For public panels, add rate limiting at your proxy as well.

## Who can do what

Being signed in is not the same as being allowed. Without any rules, every user who can sign in can do everything. Before going live, decide:

- **Who may sign in**: `Auth(can_access=lambda user: user.is_staff)` and `Auth(active_field="is_active")`.
- **What they may do**: roles (`panel.rbac()`), resource policies, or a gate.

Permissions are checked on the server for every page, action, inline edit and export, not only by hiding buttons. See [Roles and permissions](roles-and-permissions).

Download endpoints only do what the screen offers. An export only works when the table has an `ExportAction` (or an `ExportBulkAction` for selected rows) that the user may run, and the example file of an import only when its `ImportAction` is available to the user.

## Rich text and HTML

Text from `RichEditor` fields is cleaned on save. Only a safe list of tags is kept (paragraphs, headings, lists, links, bold, italic, code, quotes, tables, images...). `<script>`, `<style>`, `<iframe>`, event attributes like `onclick` and `javascript:` links are removed.

The same cleaning is used when a table column or infolist entry shows HTML with `.html()`.

Everything else Tungsten shows is escaped by the template engine, so text from the database can't inject HTML.

> [!WARNING]
> Render hooks, `Page.content()` and widget templates output what you give them. If you return `Markup(...)` that contains user data, escape it first (for example with `markupsafe.escape`).

## File uploads

Uploads are checked when they arrive:

- **Blocked file types.** Files ending in `.html`, `.htm`, `.xhtml`, `.svg`, `.js`, `.mjs`, `.php`, `.py`, `.sh`, `.exe` and `.bat` are always refused, whatever the field allows. A browser could run these as code.
- **Random names.** Files are saved under a random name (a UUID) with the original extension. The user's file name is never used as a path.
- **No path tricks.** Paths with `..` are cleaned, and reading a file outside the storage folder is refused.
- **Safe serving.** Stored files are served with `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`, so the browser won't run them as a page.
- **Signed-in users only.** The panel only serves stored files to signed-in users. Others are sent to the login page.

Limit size and type on each field:

```python
FileUpload("images").image().multiple().max_size(2048).max_files(6)
FileUpload("invoice").accepted_file_types([".pdf", "application/pdf"]).max_size(5120)
```

`max_size` is in kilobytes. There is no size limit unless you set one. The type check uses the file name and the type the browser reports, so treat it as a convenience, not proof of what the file contains.

> [!NOTE]
> Files in the default `LocalStorage` are served at `<panel path>/storage/...` to signed-in users. The panel doesn't check *which* user uploaded a file, so any signed-in user who has the link can open it. The random names make links impossible to guess. Use your own `Storage` class if files need stricter rules.

If files must be visible without signing in (for example product photos on a public shop), make the storage public:

```python
Panel(..., storage=LocalStorage("storage/tungsten", public=True))
```

Even then, files in the `imports` folder (uploaded import files and the "failed rows" reports) still need a signed-in user.

## Exports

CSV and Excel exports protect against **formula injection**: a cell value that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets a `'` in front, so spreadsheet apps show it as text instead of running it. Exports only contain records the user can see, with the current filters, and only work when the table offers an export action the user may run. See [Import and export](import-export).

## Multi-tenancy

With [multi-tenancy](multi-tenancy), resource lists, record pages, global search, exports, relationship select options, `.unique()` checks and imports are limited to the current team. A user who belongs to no team sees no team records at all. Read the notes on that page about things that are **not** scoped automatically, such as your own widget queries.

## Production checklist

Go through this list before you put a panel on the internet:

1. **Set a fixed `secret_key`** from an environment variable. Never commit it.
2. **Serve over HTTPS** and set `https_only_cookies=True`.
3. **Use a real mailer** (`Auth(mailer=...)`). The default only prints emails to the console.
4. **Set `app_url`.** Password reset and email verification links are built from `Panel(app_url=...)`, the public address of your site:

    ```python
    panel = Panel(..., app_url="https://admin.acme.example")
    ```

    Without it, links use the host from the request, and a forged `Host` header could put another site's address in the emails. As extra protection, add FastAPI's `TrustedHostMiddleware`, so requests for other host names are refused:

    ```python
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["admin.acme.example"])
    ```

    Behind a proxy, run uvicorn with `--proxy-headers` (and `--forwarded-allow-ips`) so the right scheme and host are used.
5. **Limit who can sign in** with `can_access` and `active_field`.
6. **Turn on permissions** (`panel.rbac()`, policies or a gate), and give each person only the roles they need.
7. **Consider two-factor login** for admins (`two_factor=True`, or `two_factor_required=True`).
8. **Run `panel.create_tables()`** once, so password resets, roles and two-factor work.
9. **Set upload limits** (`max_size`, `accepted_file_types`) on every `FileUpload`.
10. **Keep the storage folder out of your web root**, and back it up with your database.
11. **Protect custom routes** you add with `panel.routes`: they skip Tungsten's login and CSRF checks.
12. **Turn on `activity_log=True`** if you want a record of who created and changed what. Rows are written to the `tungsten_activity_log` table when records are created or saved on the create and edit pages.
13. **Rate limit at the proxy** for public panels, since the built-in login limit is per process.
