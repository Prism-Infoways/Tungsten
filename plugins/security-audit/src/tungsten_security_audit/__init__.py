"""A security health check for your Tungsten panel, plus a login log with lockout.

    from tungsten_security_audit import SecurityAuditPlugin

    panel.plugin(SecurityAuditPlugin())
    panel.create_tables(engine)
    panel.mount(app)

Open "Security audit" in the panel and press Run audit. It checks your own app only (settings,
admin accounts, logins, your site's HTTPS and headers, and optionally your packages against
osv.dev) and gives a score with a tip to fix each problem. Every login try is logged, and
repeated wrong passwords lock that login for a while.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from collections.abc import Callable

from tungsten import Plugin

from .checks import DEFAULT_CHECKS, Audit, Result, grade_of, run_checks, score_of
from .logins import LoginGuard, client_ip
from .models import LoginAttempt, SecurityAudit, SecurityBase
from .net import Net
from .resources import (
    AUDIT_PERMISSION,
    LOGINS_PERMISSION,
    LoginAttemptResource,
    SecurityAuditPage,
    SecurityAuditResource,
    run_audit,
)

__version__ = "0.1.0"


class SecurityAuditPlugin(Plugin):
    """``SecurityAuditPlugin(lockout=True, max_failures=5, lockout_minutes=15, ...)``.

    - ``lockout``: after ``max_failures`` wrong passwords for one email from one IP, that login is
      locked for ``lockout_minutes``. Admins can unlock it on the Login log screen.
    - ``log_logins``: keep a log of every login try. ``keep_login_days``: how long (0 keeps them all).
    - ``trust_proxy``: read the visitor's IP from ``X-Forwarded-For``. Only behind a proxy you run.
    - ``max_superusers``: more users with full access than this gives a warning.
    - ``idle_days``: admin accounts and AI tokens unused this long give a warning.
    - ``check_passwords``: try a short list of common passwords against each admin's password hash.
    - ``public_url``: your site's address for the website check. Default: the panel's ``app_url``.
    - ``allowed_hosts``: more host names the website check may open (e.g. your main site).
    - ``checks``: extra checks of your own, ``fn(audit) -> Result | list[Result] | None``.
    """

    id = "security-audit"
    metadata = SecurityBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, *, lockout: bool = True, max_failures: int = 5, lockout_minutes: int = 15,
                 log_logins: bool = True, keep_login_days: int = 90, trust_proxy: bool = False,
                 max_superusers: int = 3, idle_days: int = 90, check_passwords: bool = True,
                 public_url: str | None = None, allowed_hosts: Iterable[str] = (),
                 checks: Iterable[Callable[[Audit], Any]] = (), net: Net | None = None) -> None:
        self.lockout = lockout
        self.max_failures = max(1, max_failures)
        self.lockout_minutes = max(1, lockout_minutes)
        self.log_logins = log_logins or lockout  # the lockout counts the logged failures
        self.keep_login_days = keep_login_days
        self.trust_proxy = trust_proxy
        self.max_superusers = max_superusers
        self.idle_days = idle_days
        self.check_passwords = check_passwords
        self.public_url = public_url.rstrip("/") if public_url else None
        self.allowed_hosts = [h.lower() for h in allowed_hosts]
        self.checks = list(DEFAULT_CHECKS) + list(checks)
        self.net = net or Net()
        self.guard = LoginGuard(self)
        self.panel: Any = None
        #: your main app, seen by ``panel.mount(app)``, for the debug, CORS and API docs checks
        self.app: Any = None

    def register(self, panel: Any) -> None:
        self.panel = panel
        panel.pages([SecurityAuditPage])
        panel.resources([SecurityAuditResource])
        if panel.auth.enabled:
            panel.resources([LoginAttemptResource])
            if self.log_logins:
                self.guard.install(panel.auth)

    def mount(self, app: Any, panel: Any) -> None:
        self.app = app

    def permissions(self) -> list[tuple[str, str]]:
        return [(LOGINS_PERMISSION, "See the login log")]  # the audit page lists its own


__all__ = [
    "AUDIT_PERMISSION",
    "DEFAULT_CHECKS",
    "LOGINS_PERMISSION",
    "Audit",
    "LoginAttempt",
    "LoginAttemptResource",
    "LoginGuard",
    "Net",
    "Result",
    "SecurityAudit",
    "SecurityAuditPage",
    "SecurityAuditPlugin",
    "SecurityAuditResource",
    "SecurityBase",
    "__version__",
    "client_ip",
    "grade_of",
    "run_audit",
    "run_checks",
    "score_of",
]
