---
title: Security audit
description: Check your panel's security in one click, get a score with a tip for each problem, and keep a login log that locks out password guessing.
---

The `tungsten-security-audit` plugin gives your panel a security health check. Press **Run audit** and you get a score out of 100, a grade from A to F, and a plain tip to fix each problem. It also logs every login try and locks out repeated wrong passwords.

It only checks your own app. It never scans or attacks other sites.

## Install

```bash
pip install tungsten-security-audit
```

```python
from tungsten_security_audit import SecurityAuditPlugin

panel = Panel(..., app_url="https://admin.example.com")   # your public address
panel.plugin(SecurityAuditPlugin())
panel.create_tables(engine)
panel.mount(app)
```

This adds a **Security** group with **Security audit**, **Audit history** and **Login log**. It needs `tungsten-admin` 0.1.4 or newer.

## Run an audit

1. Open **Security audit** and press **Run audit**.
2. The website address is filled in for you. Leave it, or clear it to skip the website checks.
3. Tick **Check packages for known holes** to look up your installed Python packages on [osv.dev](https://osv.dev). Only package names and versions are sent.
4. Press **Run audit**.

Failed items come first. Fix the red ones first: they are the biggest risks.

Every audit is saved. **Audit history** shows how your score changes, and **View** opens an old report.

## What it checks

| Group | Checks |
| --- | --- |
| Settings | Login required, strong secret key, debug mode off, HTTPS-only session cookie, `app_url` set, two-factor login for admins, roles on, sign-up closed, CORS limited to your sites, API docs private, activity log on |
| Accounts | Few users with full access, no admin with a common password (or their email name), strong password hashes, no forgotten admin accounts |
| Logins | Lockout on, failed logins in the last 24 hours and their IPs, logins locked right now |
| Website | HTTPS, HSTS, Content Security Policy, clickjacking protection, `X-Content-Type-Options`, `Referrer-Policy`, no server versions in headers, CORS headers, session cookie flags, HTTP to HTTPS redirect, certificate expiry |
| AI access | MCP tokens nobody used for a long time (with [tungsten-mcp](mcp)) |
| Packages | Your Python version still gets security fixes, installed packages with known holes |

A failed check takes 15 points off for high risk, 8 for medium and 3 for low. A warning takes half.

> [!NOTE]
> The website check only opens your own address: the host of `app_url` (or `public_url`), or the address in your browser when neither is set. Add more with `allowed_hosts=[...]`.

## Add the security headers

Many sites fail the header checks. Your web server or hosting panel can add them, or your app can:

```python
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'; object-src 'none'; base-uri 'self'")
    return response
```

Send HSTS only once the whole site works on HTTPS.

## Login log and lockout

Every try on the login page is logged: the email, IP, browser, and the result (**Logged in**, **Wrong password**, **Unknown email**, **Account blocked**, **Locked out**, **Too many tries**). Filter the **Login log** by result, or search by email or IP.

After 5 wrong passwords for one email from one IP, that login is locked for 15 minutes, even with the right password. To let someone in sooner, press **Unlock** on their row, or **Unlock a login** at the top and type their email.

```python
SecurityAuditPlugin(
    lockout=True,          # False: log only, keep just the built-in limit of 5 tries a minute
    max_failures=5,
    lockout_minutes=15,
    keep_login_days=90,    # older rows are removed; 0 keeps them all
    trust_proxy=False,     # True: read the IP from X-Forwarded-For
)
```

> [!WARNING]
> Set `trust_proxy=True` only when your app runs behind a proxy you control (nginx, a load balancer). Otherwise visitors can fake their IP in that header.

## Who can see it

With roles on, the audit needs the **Open Security audit** permission and the log needs **See the login log**. Super admins have both. Without roles, every logged-in user can open them, and the audit warns about that.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `lockout` | `True` | Lock a login after too many wrong passwords |
| `max_failures` | `5` | Wrong passwords before the lock |
| `lockout_minutes` | `15` | How long the lock lasts |
| `log_logins` | `True` | Keep the login log (always on with `lockout`) |
| `keep_login_days` | `90` | Remove older log rows (`0` keeps them) |
| `trust_proxy` | `False` | Read the IP from `X-Forwarded-For` |
| `max_superusers` | `3` | Warn when more users have full access |
| `idle_days` | `90` | Warn about admins and AI tokens unused this long |
| `check_passwords` | `True` | Try common passwords against admin password hashes |
| `public_url` | `app_url` | The address the website check opens |
| `allowed_hosts` | `[]` | More host names the website check may open |
| `checks` | `[]` | Your own checks |

## Your own checks

A check gets the audit and returns a `Result` (or a list, or `None` to leave it out). `audit.ctx`, `audit.db`, `audit.panel` and `audit.plugin` are there to use.

```python
from pathlib import Path

from tungsten_security_audit import Result, SecurityAuditPlugin

def check_backups(audit):
    ok = Path("/backups/latest.sql.gz").exists()
    return Result(
        key="backups", group="Settings", title="Database backups exist",
        status="pass" if ok else "fail", severity="high",
        detail="Found the latest backup." if ok else "No backup found.",
        fix="" if ok else "Set up a daily backup job.",
    )

panel.plugin(SecurityAuditPlugin(checks=[check_backups]))
```

`status` is `pass`, `warn`, `fail`, `info` or `skip`. `severity` is `high`, `medium` or `low`.
