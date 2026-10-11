"""A Security audit check for the impersonate plugin (added when tungsten-security-audit is installed)."""

from __future__ import annotations

from typing import Any

#: names kept in sync with tungsten_security_audit.checks, without importing it
PASS, WARN, INFO = "pass", "warn", "info"


def impersonation_check(audit: Any) -> Any:
    from tungsten_security_audit.checks import HIGH, LOW, MEDIUM, Result

    plugin = audit.panel.get_plugin("impersonate")
    if plugin is None:
        return None
    auth = audit.auth
    results = []
    open_to_all = plugin.can_impersonate is None and not auth.rbac and auth.gate is None
    results.append(Result(
        "impersonate_who", "Accounts", "Who can log in as other users",
        WARN if open_to_all else PASS, HIGH,
        "Every panel user can log in as any other user." if open_to_all
        else "Only allowed admins can log in as other users.",
        "Turn on roles (panel.rbac()) and give the \"Log in as other users\" permission only to support "
        "admins, or pass ImpersonatePlugin(can_impersonate=...)." if open_to_all else ""))
    no_limit = not plugin.max_minutes or plugin.max_minutes > 240
    results.append(Result(
        "impersonate_limit", "Accounts", "Time limit on \"Log in as\"", WARN if no_limit else PASS, MEDIUM,
        "Logging in as a user never ends by itself." if not plugin.max_minutes
        else f"It ends by itself after {plugin.max_minutes} minutes.",
        "Set ImpersonatePlugin(max_minutes=60) so a forgotten session goes back to the admin." if no_limit else ""))
    results.append(Result(
        "impersonate_log", "Accounts", "Impersonation log", PASS if plugin.log_resource else INFO, LOW,
        "Every \"Log in as\" is saved with who, as whom, when and why." if plugin.log_resource
        else "The log is saved but its screen is turned off.",
        "" if plugin.log_resource else "Pass ImpersonatePlugin(log_resource=True) to see it in the panel."))
    return results
