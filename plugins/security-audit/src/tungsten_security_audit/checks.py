"""The checks. Each one looks at your own app and says pass, warn or fail, with a tip to fix it.

A check is a function ``check(audit) -> Result | list[Result] | None``. Add your own with
``SecurityAuditPlugin(checks=[my_check])``.
"""

from __future__ import annotations

import datetime as dt
import math
import sys
from dataclasses import asdict, dataclass
from typing import Any
from collections.abc import Callable
from urllib.parse import urlsplit

from sqlalchemy import func, select

from .models import LoginAttempt

PASS, WARN, FAIL, INFO, SKIP = "pass", "warn", "fail", "info", "skip"
HIGH, MEDIUM, LOW = "high", "medium", "low"
#: points a failed check takes off the score of 100; a warning takes half
WEIGHTS = {HIGH: 15, MEDIUM: 8, LOW: 3}

WEAK_SECRETS = {"", "secret", "change-me", "changeme", "change_me", "test", "dev", "development", "key",
                "secret-key", "secret_key", "your-secret-key", "please-change-me", "password", "tungsten", "admin"}
#: tried against each admin's password hash (kept short: every try is a slow hash on purpose)
COMMON_PASSWORDS = ["password", "admin", "123456", "12345678", "admin123", "password123", "qwerty", "welcome",
                    "changeme", "secret"]
#: Python versions and the month they stop getting security fixes
PYTHON_END = {(3, 9): dt.date(2025, 10, 31), (3, 10): dt.date(2026, 10, 31), (3, 11): dt.date(2027, 10, 31),
              (3, 12): dt.date(2028, 10, 31), (3, 13): dt.date(2029, 10, 31), (3, 14): dt.date(2030, 10, 31)}


@dataclass
class Result:
    key: str
    group: str
    title: str
    status: str
    severity: str = MEDIUM
    detail: str = ""
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_of(results: list[dict]) -> int:
    lost = 0
    for r in results:
        weight = WEIGHTS.get(r["severity"], 0)
        if r["status"] == FAIL:
            lost += weight
        elif r["status"] == WARN:
            lost += math.ceil(weight / 2)
    return max(0, 100 - lost)


def grade_of(score: int) -> str:
    for limit, grade in ((90, "A"), (80, "B"), (70, "C"), (60, "D")):
        if score >= limit:
            return grade
    return "F"


class Audit:
    """What a check gets: the request context, the plugin's settings, and the scan options."""

    def __init__(self, ctx: Any, plugin: Any, url: str | None = None, packages: bool = False) -> None:
        self.ctx = ctx
        self.plugin = plugin
        self.panel = ctx.panel
        self.auth = ctx.panel.auth
        self.db = ctx.db
        self.url = url
        self.packages = packages
        self.net = plugin.net
        self._page: Any = None
        self._page_error: str | None = None
        self._admins: list | None = None

    # ------------------------------------------------------------------ helpers for checks
    @property
    def https(self) -> bool:
        target = self.url or self.panel.app_url or ""
        if target:
            return target.startswith("https://")
        return self.ctx.request.url.scheme == "https"

    def page(self) -> Any:
        """The scanned address, fetched once (None when it couldn't be reached)."""
        if self._page is None and self._page_error is None and self.url:
            try:
                self._page = self.net.get(self.url, headers={"Origin": "https://audit-check.invalid"})
            except Exception as exc:  # noqa: BLE001 - any network trouble just skips the website checks
                self._page_error = str(exc) or type(exc).__name__
        return self._page

    def admins(self) -> list:
        """Users with every permission (a role with ``*``). Without roles: every user."""
        if self._admins is None:
            model = self.auth.user_model
            if model is None:
                self._admins = []
            elif self.auth.rbac:
                from tungsten.models import Role, RoleAssignment

                rows = self.db.execute(select(RoleAssignment.user_id, Role.permissions)
                                       .join(Role, Role.id == RoleAssignment.role_id)).all()
                ids = {uid for uid, perms in rows if "*" in (perms or [])}
                self._admins = [u for u in self.db.scalars(select(model)).all() if self.auth.user_id(u) in ids]
            else:
                self._admins = list(self.db.scalars(select(model).limit(50)).all())
        return self._admins

    def name_of(self, user: Any) -> str:
        return str(getattr(user, self.auth.email_field, None) or self.auth.user_id(user))


def _r(audit_group: str):
    def make(key: str, title: str, status: str, severity: str = MEDIUM, detail: str = "", fix: str = "") -> Result:
        return Result(key, audit_group, title, status, severity, detail, fix)
    return make


def _list(items: list[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


# ====================================================================== settings
_settings = _r("Settings")


def check_login_required(audit: Audit) -> Result:
    if audit.auth.enabled:
        return _settings("login", "Login is required", PASS, HIGH, "Nobody can open the panel without logging in.")
    return _settings("login", "Login is required", FAIL, HIGH,
                     "The panel has no login: anyone who finds the address can see and change your data.",
                     "Pass auth=Auth(User) to Panel(...).")


def check_secret_key(audit: Audit) -> Result:
    key = audit.panel.secret_key or ""
    if key.strip().lower() in WEAK_SECRETS or len(key) < 32:
        return _settings("secret_key", "Secret key is strong", FAIL, HIGH,
                         "The secret key is short or a well-known value. With it, anyone can make a session "
                         "cookie and log in as any user.",
                         "Make one with python -c \"import secrets; print(secrets.token_urlsafe(48))\", keep it in "
                         "an environment variable, and pass secret_key=os.environ[...] to Panel(...).")
    return _settings("secret_key", "Secret key is strong", PASS, HIGH, f"{len(key)} characters, not a known value.")


def check_debug(audit: Audit) -> Result:
    app = audit.plugin.app
    on = bool(getattr(app, "debug", False)) or bool(getattr(audit.panel.app, "debug", False))
    if on:
        return _settings("debug", "Debug mode is off", FAIL, HIGH,
                         "Debug mode shows code and settings to visitors when an error happens.",
                         "Create your app with FastAPI(debug=False) (the default) in production.")
    return _settings("debug", "Debug mode is off", PASS, HIGH, "Errors show a plain page, not your code.")


def check_api_docs(audit: Audit) -> Result | None:
    app = audit.plugin.app
    if app is None:
        return None
    open_docs = [u for u in (getattr(app, "docs_url", None), getattr(app, "redoc_url", None),
                             getattr(app, "openapi_url", None)) if u]
    if open_docs:
        return _settings("api_docs", "API docs are private", WARN, LOW,
                         f"Your API's docs are open to everyone at {_list(open_docs)}. They list every route.",
                         "If the API isn't public, use FastAPI(docs_url=None, redoc_url=None, openapi_url=None).")
    return _settings("api_docs", "API docs are private", PASS, LOW, "No public /docs or /openapi.json.")


def check_cors(audit: Audit) -> Result | None:
    app = audit.plugin.app
    if app is None:
        return None
    for mw in getattr(app, "user_middleware", []):
        if getattr(mw.cls, "__name__", "") != "CORSMiddleware":
            continue
        kwargs = getattr(mw, "kwargs", None) or getattr(mw, "options", {}) or {}
        origins = list(kwargs.get("allow_origins") or [])
        regex = kwargs.get("allow_origin_regex") or ""
        wide = "*" in origins or regex in (".*", "^.*$", ".+")
        if wide and kwargs.get("allow_credentials"):
            return _settings("cors", "CORS is limited to your sites", FAIL, HIGH,
                             "Any website may call your API with the visitor's cookies (all origins plus "
                             "credentials).",
                             "List your own sites in CORSMiddleware(allow_origins=[...]) instead of \"*\".")
        if wide:
            return _settings("cors", "CORS is limited to your sites", WARN, MEDIUM,
                             "Any website may call your API from a browser (allow_origins=[\"*\"]).",
                             "List your own sites in CORSMiddleware(allow_origins=[...]).")
        return _settings("cors", "CORS is limited to your sites", PASS, MEDIUM, f"Allowed: {_list(origins) or regex}.")
    return _settings("cors", "CORS is limited to your sites", PASS, MEDIUM, "No CORS middleware: other sites "
                     "can't call your API from a browser.")


def check_app_url(audit: Audit) -> Result:
    if audit.panel.app_url:
        return _settings("app_url", "Site address is set", PASS, MEDIUM, f"Links in emails use {audit.panel.app_url}.")
    return _settings("app_url", "Site address is set", WARN, MEDIUM,
                     "Without app_url, password reset links are built from the address the visitor sent, "
                     "which an attacker can fake to steal reset links.",
                     "Pass app_url=\"https://your-site.com\" to Panel(...).")


def check_cookie_settings(audit: Audit) -> Result:
    if audit.panel.https_only_cookies:
        return _settings("secure_cookies", "Login cookie is HTTPS only", PASS, MEDIUM,
                         "The session cookie is never sent over plain HTTP.")
    status = FAIL if audit.https else WARN
    return _settings("secure_cookies", "Login cookie is HTTPS only", status, MEDIUM,
                     "The session cookie can also travel over plain HTTP, where others on the network can read it.",
                     "Pass https_only_cookies=True to Panel(...) once the site runs on HTTPS.")


def check_two_factor(audit: Audit) -> Result | None:
    auth = audit.auth
    if not auth.enabled:
        return None
    if not auth.two_factor:
        return _settings("two_factor", "Two-factor login", WARN, MEDIUM,
                         "Two-factor login is off, so a stolen password is enough to get in.",
                         "Pass two_factor=True to Auth(...), or two_factor_required=True to make it a must.")
    if auth.two_factor_required:
        return _settings("two_factor", "Two-factor login", PASS, MEDIUM, "Every user must set up two-factor login.")
    from tungsten.models import TwoFactorCredential

    with_2fa = set(audit.db.scalars(select(TwoFactorCredential.user_id)
                                    .where(TwoFactorCredential.confirmed_at.is_not(None))).all())
    missing = [audit.name_of(u) for u in audit.admins() if auth.user_id(u) not in with_2fa]
    if missing:
        return _settings("two_factor", "Two-factor login", WARN, MEDIUM,
                         f"Admins without two-factor login: {_list(missing)}.",
                         "Ask them to turn it on in their profile, or pass two_factor_required=True to Auth(...).")
    return _settings("two_factor", "Two-factor login", PASS, MEDIUM, "Every admin uses two-factor login.")


def check_roles(audit: Audit) -> Result | None:
    if not audit.auth.enabled:
        return None
    if audit.auth.rbac or audit.auth.gate is not None:
        return _settings("roles", "Roles limit what users can do", PASS, LOW, "Roles and permissions are on.")
    return _settings("roles", "Roles limit what users can do", WARN, LOW,
                     "Every user who can log in can do everything.",
                     "Pass rbac=True to Auth(...) and give each user only the role they need.")


def check_registration(audit: Audit) -> Result | None:
    auth = audit.auth
    if not auth.enabled or not auth.registration:
        return None
    if auth.can_access is None:
        return _settings("registration", "Sign-up is closed", WARN, MEDIUM,
                         "Anyone can make an account and open the panel.",
                         "Pass registration=False to Auth(...), or a can_access= check that only lets staff in.")
    return _settings("registration", "Sign-up is closed", PASS, MEDIUM, "Sign-up is on, with a can_access check.")


def check_activity_log(audit: Audit) -> Result:
    if audit.panel.activity_log:
        return _settings("activity_log", "Changes are logged", PASS, LOW, "The activity log records who changed what.")
    return _settings("activity_log", "Changes are logged", WARN, LOW,
                     "Without the activity log you can't see who changed or deleted a record.",
                     "Pass activity_log=True to Panel(...).")


# ====================================================================== accounts
_accounts = _r("Accounts")


def check_superusers(audit: Audit) -> Result | None:
    if not audit.auth.enabled or not audit.auth.rbac:
        return None
    admins = audit.admins()
    limit = audit.plugin.max_superusers
    if len(admins) > limit:
        return _accounts("superusers", "Few users have full access", WARN, MEDIUM,
                         f"{len(admins)} users can do everything: {_list([audit.name_of(u) for u in admins])}.",
                         f"Keep full access to {limit} or fewer people; give the others a smaller role.")
    return _accounts("superusers", "Few users have full access", PASS, MEDIUM,
                     f"{len(admins)} user{'s' if len(admins) != 1 else ''} with full access.")


def check_weak_passwords(audit: Audit) -> Result | None:
    auth = audit.auth
    if not auth.enabled or not audit.plugin.check_passwords:
        return None
    weak = []
    for user in audit.admins()[:20]:
        hashed = getattr(user, auth.password_field, None)
        email = str(getattr(user, auth.email_field, "") or "")
        tries = COMMON_PASSWORDS + [email.split("@")[0], email, audit.panel.brand_name.lower()]
        if any(t and auth.verify(t, hashed) for t in dict.fromkeys(tries)):
            weak.append(audit.name_of(user))
    if weak:
        return _accounts("weak_passwords", "Admins have strong passwords", FAIL, HIGH,
                         f"Easy-to-guess passwords: {_list(weak)}.",
                         "Change these passwords now (long and unique, a password manager helps).")
    return _accounts("weak_passwords", "Admins have strong passwords", PASS, HIGH,
                     "No admin uses a common password, their email name or the brand name.")


def check_old_hashes(audit: Audit) -> Result | None:
    auth = audit.auth
    if not auth.enabled or auth.hasher is not None:
        return None
    old = []
    for user in audit.db.scalars(select(auth.user_model).limit(1000)).all():
        hashed = str(getattr(user, auth.password_field, None) or "")
        parts = hashed.split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2_sha256" and parts[1].isdigit() and int(parts[1]) < 200_000:
            old.append(audit.name_of(user))
    if old:
        return _accounts("old_hashes", "Passwords use a strong hash", WARN, LOW,
                         f"Stored with an older, faster hash: {_list(old)}.",
                         "They get the strong hash when the user next changes their password.")
    return _accounts("old_hashes", "Passwords use a strong hash", PASS, LOW, "All passwords use PBKDF2 with "
                     "enough rounds.")


def check_idle_admins(audit: Audit) -> Result | None:
    auth = audit.auth
    if not auth.enabled:
        return None
    days = audit.plugin.idle_days
    first = audit.db.scalar(select(func.min(LoginAttempt.created_at)))
    since = dt.datetime.now() - dt.timedelta(days=days)
    if first is None or first > since:
        return _accounts("idle_admins", "No forgotten admin accounts", SKIP, LOW,
                         f"The login log is younger than {days} days, so this is checked later.")
    recent = set(audit.db.scalars(select(LoginAttempt.user_id).where(
        LoginAttempt.success.is_(True), LoginAttempt.created_at > since)).all())
    idle = [audit.name_of(u) for u in audit.admins() if auth.user_id(u) not in recent and auth.is_active(u)]
    if idle:
        return _accounts("idle_admins", "No forgotten admin accounts", WARN, LOW,
                         f"Admins with no login in {days} days: {_list(idle)}.",
                         "Switch off or remove accounts nobody uses any more.")
    return _accounts("idle_admins", "No forgotten admin accounts", PASS, LOW,
                     f"Every admin logged in within {days} days.")


# ====================================================================== logins
_logins = _r("Logins")


def check_lockout(audit: Audit) -> Result | None:
    if not audit.auth.enabled:
        return None
    plugin = audit.plugin
    if plugin.lockout:
        return _logins("lockout", "Repeated wrong passwords are locked out", PASS, MEDIUM,
                       f"{plugin.max_failures} wrong passwords lock that login for {plugin.lockout_minutes} minutes.")
    return _logins("lockout", "Repeated wrong passwords are locked out", WARN, MEDIUM,
                   f"Only the built-in limit of {audit.auth.max_login_attempts} tries a minute slows down "
                   "password guessing.",
                   "Use SecurityAuditPlugin(lockout=True).")


def check_failed_logins(audit: Audit) -> Result | None:
    if not audit.auth.enabled:
        return None
    from .logins import FAILURES

    since = dt.datetime.now() - dt.timedelta(hours=24)
    rows = audit.db.execute(
        select(LoginAttempt.ip, func.count()).where(LoginAttempt.reason.in_(FAILURES + ("locked",)),
                                                    LoginAttempt.created_at > since)
        .group_by(LoginAttempt.ip).order_by(func.count().desc())
    ).all()
    total = sum(n for _, n in rows)
    top = [f"{ip or 'unknown'} ({n})" for ip, n in rows]
    if total > 50:
        return _logins("failed_logins", "Few failed logins", FAIL, MEDIUM,
                       f"{total} failed logins in the last 24 hours, mostly from {_list(top, 3)}. "
                       "Someone may be guessing passwords.",
                       "Look at the Login log. Block those IPs in your firewall or hosting panel, and turn on "
                       "two-factor login.")
    if total > 10:
        return _logins("failed_logins", "Few failed logins", WARN, LOW,
                       f"{total} failed logins in the last 24 hours, from {_list(top, 3)}.",
                       "Look at the Login log to see if these were your own users.")
    return _logins("failed_logins", "Few failed logins", PASS, LOW, f"{total} failed logins in the last 24 hours.")


def check_locked(audit: Audit) -> Result | None:
    if not audit.auth.enabled or not audit.plugin.lockout:
        return None
    locked = audit.plugin.guard.locked_accounts(audit.db)
    if locked:
        return _logins("locked", "Locked logins", INFO, LOW,
                       "Locked right now: " + _list([f"{e} from {ip or 'unknown'}" for e, ip in locked]) + ".",
                       "If that was a real user, unlock them on the Login log screen.")
    return None


# ====================================================================== website
_web = _r("Website")


def check_website(audit: Audit) -> list[Result]:
    if not audit.url:
        return [_web("website", "Website checks", SKIP, LOW, "No address to check.")]
    page = audit.page()
    if page is None:
        return [_web("website", "Website checks", SKIP, LOW,
                     f"Could not open {audit.url}: {audit._page_error}. With an async database and one "
                     "worker the panel can't call itself; run the audit with more than one worker.")]
    h = page.headers
    out = []
    https = audit.url.startswith("https://")
    out.append(_web("https", "Site uses HTTPS", PASS if https else FAIL, HIGH,
                    "Logins and data travel encrypted." if https else
                    "The panel runs on plain HTTP: passwords and cookies can be read on the network.",
                    "" if https else "Turn on HTTPS (free with Let's Encrypt, or AutoSSL in cPanel), then set "
                                     "app_url to the https:// address."))
    hsts = h.get("strict-transport-security", "")
    if https:
        age = 0
        for part in hsts.split(";"):
            name, _, value = part.strip().partition("=")
            if name.lower() == "max-age" and value.strip().isdigit():
                age = int(value)
        out.append(_web("hsts", "Browsers are told to always use HTTPS (HSTS)",
                        PASS if age >= 15552000 else WARN if hsts else FAIL, MEDIUM,
                        f"Strict-Transport-Security: {hsts}" if hsts else "No Strict-Transport-Security header.",
                        "" if age >= 15552000 else
                        "Send Strict-Transport-Security: max-age=31536000; includeSubDomains"))
    csp = h.get("content-security-policy", "")
    out.append(_web("csp", "Content Security Policy", PASS if csp else WARN, MEDIUM,
                    f"Content-Security-Policy: {csp[:160]}" if csp else
                    "No Content-Security-Policy header, so injected scripts are not blocked.",
                    "" if csp else "Start with Content-Security-Policy: frame-ancestors 'self'; object-src 'none'; "
                                   "base-uri 'self' and tighten it over time."))
    framed = "x-frame-options" in h or "frame-ancestors" in csp
    out.append(_web("frames", "Other sites can't show the panel in a frame", PASS if framed else WARN, MEDIUM,
                    "Clickjacking is blocked." if framed else
                    "Another site could load the panel in a hidden frame and trick users into clicks.",
                    "" if framed else "Send X-Frame-Options: DENY (or frame-ancestors 'self' in the CSP)."))
    sniff = h.get("x-content-type-options", "").lower() == "nosniff"
    out.append(_web("nosniff", "Files keep their real type", PASS if sniff else WARN, LOW,
                    "X-Content-Type-Options: nosniff is set." if sniff else "No X-Content-Type-Options header.",
                    "" if sniff else "Send X-Content-Type-Options: nosniff"))
    referrer = h.get("referrer-policy", "")
    out.append(_web("referrer", "Links don't leak full addresses", PASS if referrer else WARN, LOW,
                    f"Referrer-Policy: {referrer}" if referrer else "No Referrer-Policy header.",
                    "" if referrer else "Send Referrer-Policy: strict-origin-when-cross-origin"))
    leaks = [f"{name}: {h[name]}" for name in ("server", "x-powered-by") if any(c.isdigit() for c in h.get(name, ""))]
    out.append(_web("version_leak", "Server versions are hidden", WARN if leaks else PASS, LOW,
                    f"Headers show versions: {_list(leaks)}." if leaks else "No version numbers in the headers.",
                    "Turn off version headers in your web server (e.g. ServerTokens Prod)." if leaks else ""))
    allow = h.get("access-control-allow-origin", "")
    if allow in ("*", "https://audit-check.invalid"):
        creds = h.get("access-control-allow-credentials", "").lower() == "true"
        out.append(_web("cors_header", "Other sites can't read your pages", FAIL if creds else WARN,
                        HIGH if creds else MEDIUM,
                        f"A request from a stranger's site got Access-Control-Allow-Origin: {allow}"
                        + (" with credentials." if creds else "."),
                        "Only allow your own sites in your CORS settings."))
    out.extend(_cookie_results(audit, page.cookies, https))
    if https:
        out.append(_redirect_result(audit))
        out.append(_cert_result(audit))
    return out


def _cookie_results(audit: Audit, cookies: list[str], https: bool) -> list[Result]:
    name = f"tungsten_{audit.panel.id}"
    session = next((c for c in cookies if c.split("=", 1)[0].strip() == name), None)
    if session is None:
        return []
    flags = {p.strip().split("=")[0].lower(): p.strip() for p in session.split(";")[1:]}
    missing = []
    if "httponly" not in flags:
        missing.append("HttpOnly")
    if https and "secure" not in flags:
        missing.append("Secure")
    if "samesite" not in flags or flags["samesite"].lower().endswith("none"):
        missing.append("SameSite=Lax")
    if missing:
        return [_web("cookie_flags", "Session cookie flags", FAIL if "Secure" in missing else WARN, MEDIUM,
                     f"The session cookie lacks {', '.join(missing)}.",
                     "Pass https_only_cookies=True to Panel(...)." if "Secure" in missing else
                     "Check that no proxy rewrites the panel's cookies.")]
    return [_web("cookie_flags", "Session cookie flags", PASS, MEDIUM,
                 "The session cookie is HttpOnly" + (", Secure" if https else "") + " and SameSite.")]


def _redirect_result(audit: Audit) -> Result:
    plain = "http://" + audit.url.split("://", 1)[1]
    try:
        page = audit.net.get(plain)
    except Exception:  # noqa: BLE001
        return _web("http_redirect", "Plain HTTP moves to HTTPS", PASS, LOW, "Plain HTTP doesn't answer at all.")
    location = page.headers.get("location", "")
    if 300 <= page.status < 400 and location.startswith("https://"):
        return _web("http_redirect", "Plain HTTP moves to HTTPS", PASS, LOW, f"http:// redirects to {location}.")
    return _web("http_redirect", "Plain HTTP moves to HTTPS", WARN, LOW,
                f"{plain} answers without moving to HTTPS (status {page.status}).",
                "Redirect all http:// visits to https:// in your web server or hosting panel.")


def _cert_result(audit: Audit) -> Result:
    try:
        days = audit.net.cert_days_left(audit.url)
    except Exception as exc:  # noqa: BLE001
        return _web("certificate", "HTTPS certificate is valid", FAIL, HIGH, f"The certificate check failed: {exc}.",
                    "Renew or fix the certificate (AutoSSL in cPanel, or certbot).")
    if days < 0:
        status, detail = FAIL, "The certificate has expired."
    elif days < 14:
        status, detail = FAIL, f"The certificate ends in {int(days)} days."
    elif days < 30:
        status, detail = WARN, f"The certificate ends in {int(days)} days."
    else:
        status, detail = PASS, f"The certificate is valid for {int(days)} more days."
    return _web("certificate", "HTTPS certificate is valid", status, HIGH, detail,
                "" if status == PASS else "Renew the certificate, or check that auto-renew works.")


# ====================================================================== AI access
def check_mcp_tokens(audit: Audit) -> Result | None:
    if audit.panel.get_plugin("mcp") is None:
        return None
    from tungsten_mcp.models import McpToken

    tokens = audit.db.scalars(select(McpToken).where(McpToken.client_id.is_(None))).all()
    days = audit.plugin.idle_days
    old = dt.datetime.now() - dt.timedelta(days=days)
    stale = [t.name for t in tokens if (t.last_used_at or t.created_at) < old]
    writers = [t.name for t in tokens if t.can_write]
    if stale:
        return Result("mcp_tokens", "AI access", "No forgotten AI tokens", WARN, MEDIUM,
                      f"Tokens not used in {days} days (they never expire): {_list(stale)}.",
                      "Revoke them on the AI access (MCP) screen. Prefer app login (OAuth): those tokens expire.")
    if writers:
        return Result("mcp_tokens", "AI access", "No forgotten AI tokens", PASS, MEDIUM,
                      f"{len(tokens)} tokens, {len(writers)} can change data: {_list(writers)}. "
                      "Revoke any you no longer use.")
    return Result("mcp_tokens", "AI access", "No forgotten AI tokens", PASS, MEDIUM,
                  f"{len(tokens)} tokens, all in use.")


# ====================================================================== packages
_pkgs = _r("Packages")


def check_python(audit: Audit) -> Result:
    version = sys.version_info[:2]
    ends = PYTHON_END.get(version)
    label = f"Python {version[0]}.{version[1]}"
    if ends is not None and ends < dt.date.today():
        return _pkgs("python", "Python gets security fixes", FAIL, MEDIUM,
                     f"{label} stopped getting security fixes on {ends:%d %b %Y}.",
                     "Move to a newer Python (3.12 or later).")
    if ends is not None and (ends - dt.date.today()).days < 120:
        return _pkgs("python", "Python gets security fixes", WARN, LOW,
                     f"{label} stops getting security fixes on {ends:%d %b %Y}.",
                     "Plan a move to a newer Python (3.12 or later).")
    return _pkgs("python", "Python gets security fixes", PASS, MEDIUM, f"{label} still gets security fixes.")


def installed_packages() -> list[tuple[str, str]]:
    from importlib.metadata import distributions

    seen: dict[str, str] = {}
    for dist in distributions():
        name = dist.metadata.get("Name")
        if name and dist.version:
            seen.setdefault(name.lower(), dist.version)
    return sorted(seen.items())


def check_vulnerable_packages(audit: Audit) -> Result:
    if not audit.packages:
        return _pkgs("vulnerable_packages", "No packages with known holes", SKIP, HIGH,
                     "Not checked. Tick \"Check packages\" when you run the audit.")
    packages = installed_packages()
    try:
        found = audit.net.osv(packages)
    except Exception as exc:  # noqa: BLE001
        return _pkgs("vulnerable_packages", "No packages with known holes", SKIP, HIGH,
                     f"Could not reach osv.dev: {exc}.")
    if found:
        lines = [f"{n} {v} ({', '.join(ids[:3])}{'…' if len(ids) > 3 else ''})" for (n, v), ids in found.items()]
        names = " ".join(n for n, _ in found)
        return _pkgs("vulnerable_packages", "No packages with known holes", FAIL, HIGH,
                     f"{len(found)} installed packages have known security holes: {_list(lines, 8)}.",
                     f"Update them: pip install -U {names}. Then run your tests and restart the app.")
    return _pkgs("vulnerable_packages", "No packages with known holes", PASS, HIGH,
                 f"None of the {len(packages)} installed packages has a known hole on osv.dev.")


DEFAULT_CHECKS: list[Callable[[Audit], Any]] = [
    check_login_required, check_secret_key, check_debug, check_cookie_settings, check_app_url, check_two_factor,
    check_roles, check_registration, check_cors, check_api_docs, check_activity_log,
    check_superusers, check_weak_passwords, check_old_hashes, check_idle_admins,
    check_lockout, check_failed_logins, check_locked,
    check_website, check_mcp_tokens,
    check_python, check_vulnerable_packages,
]


def run_checks(audit: Audit, checks: list[Callable[[Audit], Any]]) -> list[dict]:
    results: list[dict] = []
    for check in checks:
        try:
            out = check(audit)
        except Exception as exc:  # noqa: BLE001 - one broken check must not stop the audit
            out = Result(getattr(check, "__name__", "check"), "Other", getattr(check, "__name__", "Check"),
                         SKIP, LOW, f"This check failed to run: {exc}")
        for item in out if isinstance(out, list) else [out]:
            if item is not None:
                results.append(item.to_dict() if isinstance(item, Result) else dict(item))
    return results


def same_site(url: str, allowed: set[str]) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and (parts.hostname or "").lower() in allowed
