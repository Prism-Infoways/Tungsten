# tungsten-security-audit

A security health check for your [Tungsten](https://tungsten.prisminfoways.com/) panel. Press **Run audit** and get a score out of 100, a grade, and a plain tip to fix each problem. It also keeps a **login log** and locks out repeated wrong passwords.

It only checks your own app. It never scans or attacks other sites.

## What it checks

- **Settings**: login required, a strong secret key, debug mode off, HTTPS-only session cookie, `app_url` set, two-factor login, roles, open sign-up, CORS, public API docs, activity log.
- **Accounts**: how many users have full access, admins with common passwords, old password hashes, admin accounts nobody uses.
- **Logins**: lockout on, failed logins in the last 24 hours (and from which IPs), logins locked right now.
- **Website** (your own address): HTTPS, HSTS, Content Security Policy, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, server versions in headers, CORS headers, session cookie flags (Secure, HttpOnly, SameSite), HTTP to HTTPS redirect, certificate expiry.
- **AI access**: MCP tokens nobody used for a long time (with `tungsten-mcp`).
- **Packages**: Python version still getting security fixes, and (when you tick it) installed packages with known holes from [osv.dev](https://osv.dev).

Every audit is saved, so **Audit history** shows how your score changes.

## Login log and lockout

Every login try is logged: email, IP, browser, and the result (logged in, wrong password, unknown email, locked out...). After 5 wrong passwords for one email from one IP, that login is locked for 15 minutes. Unlock it early from the **Login log** screen.

## Install

```bash
pip install tungsten-security-audit
```

```python
from tungsten_security_audit import SecurityAuditPlugin

panel = Panel(..., app_url="https://admin.example.com")
panel.plugin(SecurityAuditPlugin())
panel.create_tables(engine)
panel.mount(app)
```

This adds **Security audit**, **Audit history** and **Login log** under a **Security** group. It needs `tungsten-admin` 0.1.4 or newer.

## Options

```python
SecurityAuditPlugin(
    lockout=True,            # lock a login after too many wrong passwords
    max_failures=5,          # wrong passwords before the lock
    lockout_minutes=15,      # how long the lock lasts
    keep_login_days=90,      # delete login log rows older than this (0 keeps them)
    trust_proxy=False,       # read the IP from X-Forwarded-For (only behind your own proxy)
    max_superusers=3,        # warn when more users have full access
    idle_days=90,            # warn about admins and AI tokens unused this long
    check_passwords=True,    # try common passwords against admin password hashes
    allowed_hosts=[],        # more host names the website check may open
    checks=[],               # your own checks
)
```

With roles on, only users with the **Open Security audit** permission see the audit, and **See the login log** for the log. Super admins see both.

## Your own checks

```python
from tungsten_security_audit import Result

def check_backups(audit):
    ok = Path("/backups/latest.sql.gz").exists()
    return Result("backups", "Settings", "Database backups exist", "pass" if ok else "fail", "high",
                  "Found today's backup." if ok else "No backup found.",
                  "" if ok else "Set up a daily backup job.")

panel.plugin(SecurityAuditPlugin(checks=[check_backups]))
```

## License

MIT
