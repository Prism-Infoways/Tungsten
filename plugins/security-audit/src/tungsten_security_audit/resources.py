"""The Security audit screen, the audit history and the login log."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select

from tungsten import Notification, Page, Resource
from tungsten.actions import Action, DeleteAction, DeleteBulkAction
from tungsten.forms import TextInput, Toggle
from tungsten.tables import SelectFilter, TernaryFilter, TextColumn

from .checks import FAIL, PASS, WARN, Audit, grade_of, run_checks, same_site, score_of
from .models import LoginAttempt, SecurityAudit

AUDIT_PERMISSION = "security.audit"
LOGINS_PERMISSION = "security.logins"
GROUPS = ("Settings", "Accounts", "Logins", "Website", "AI access", "Packages", "Other")
REASONS = {
    "success": ("Logged in", "success"),
    "wrong_password": ("Wrong password", "danger"),
    "unknown_user": ("Unknown email", "danger"),
    "not_allowed": ("Account blocked", "warning"),
    "locked": ("Locked out", "danger"),
    "throttled": ("Too many tries", "warning"),
    "unlocked": ("Unlocked by admin", "info"),
}


def plugin_of(ctx: Any) -> Any:
    return ctx.panel.get_plugin("security-audit")


def _user_id(ctx: Any) -> str | None:
    return ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None


# ====================================================================== running an audit
def allowed_hosts(ctx: Any) -> set[str]:
    """The website check only looks at this site: the panel's own address."""
    plugin = plugin_of(ctx)
    hosts = {(urlsplit(u).hostname or "").lower() for u in (plugin.public_url, ctx.panel.app_url) if u}
    if not hosts:
        hosts.add((ctx.request.url.hostname or "").lower())
    return hosts | {h.lower() for h in plugin.allowed_hosts}


def default_url(ctx: Any) -> str:
    plugin = plugin_of(ctx)
    base = plugin.public_url or ctx.panel.app_url
    if not base:
        proto = ctx.request.headers.get("x-forwarded-proto") or ctx.request.url.scheme
        base = f"{proto}://{ctx.request.headers.get('host') or ctx.request.url.netloc}"
    return base.rstrip("/") + ctx.panel.url("login")


def run_audit(ctx: Any, db: Any, url: str | None = None, packages: bool = False) -> SecurityAudit | None:
    plugin = plugin_of(ctx)
    url = (url or "").strip() or None
    if url and not same_site(url, allowed_hosts(ctx)):
        Notification("Only your own site").body(
            "The website check only opens this panel's own address: " + ", ".join(sorted(allowed_hosts(ctx)))
            + ".").danger().send(ctx)
        return None
    results = run_checks(Audit(ctx, plugin, url=url, packages=packages), plugin.checks)
    score = score_of(results)
    audit = SecurityAudit(score=score, grade=grade_of(score), url=url, results=results, user_id=_user_id(ctx),
                          passed=sum(r["status"] == PASS for r in results),
                          warnings=sum(r["status"] == WARN for r in results),
                          failed=sum(r["status"] == FAIL for r in results))
    db.add(audit)
    db.commit()
    return audit


def report(ctx: Any, audit: SecurityAudit | None) -> Any:
    groups = []
    if audit is not None:
        order = {"fail": 0, "warn": 1, "info": 2, "pass": 3, "skip": 4}
        rows = sorted(audit.results or [], key=lambda r: order.get(r["status"], 9))
        names = list(GROUPS) + sorted({r["group"] for r in rows} - set(GROUPS))
        groups = [(g, [r for r in rows if r["group"] == g]) for g in names]
        groups = [(g, items) for g, items in groups if items]
    return ctx.panel.renderer.render("tungsten_security_audit/report.html", ctx=ctx, audit=audit, groups=groups)


def _run(ctx: Any, db: Any, data: dict) -> None:
    audit = run_audit(ctx, db, data.get("url"), bool(data.get("packages")))
    if audit is None:
        return
    color = "success" if audit.score >= 80 else "warning" if audit.score >= 60 else "danger"
    Notification(f"Score {audit.score} ({audit.grade})").body(
        f"{audit.failed} failed, {audit.warnings} warnings, {audit.passed} passed.").status(color).send(ctx)
    ctx.redirect(SecurityAuditPage.get_url(ctx))


def run_action() -> Action:
    return (
        Action("run").label("Run audit").icon("scan-search")
        .modal_heading("Run a security audit").modal_width("lg")
        .modal_description("Checks your settings, admin accounts and logins. Only your own site is checked.")
        .form([
            TextInput("url").label("Website address to check").url().default(lambda ctx: default_url(ctx))
            .helper_text("Its HTTPS, headers and certificate are checked. Leave empty to skip."),
            Toggle("packages").label("Check packages for known holes")
            .helper_text("Sends the names and versions of installed Python packages to osv.dev."),
        ])
        .modal_submit_action_label("Run audit")
        .action(lambda ctx, db, data: _run(ctx, db, data))
    )


class SecurityAuditPage(Page):
    slug = "security-audit"
    title = "Security audit"
    subheading = "A health check of your panel's security, with a score and tips to fix each problem."
    icon = "shield-check"
    navigation_group = "Security"
    navigation_label = "Security audit"
    navigation_sort = 90
    permission = AUDIT_PERMISSION

    @classmethod
    def content(cls, ctx):
        latest = ctx.db.scalars(select(SecurityAudit).order_by(SecurityAudit.created_at.desc(),
                                                               SecurityAudit.id.desc()).limit(1)).first()
        return report(ctx, latest)

    @classmethod
    def header_actions(cls, ctx):
        return [
            Action("history").label("History").icon("history").color("gray").outlined()
            .url(lambda ctx: SecurityAuditResource.get_url(ctx)),
            run_action(),
        ]


# ====================================================================== history
class _Guarded(Resource):
    permission = AUDIT_PERMISSION

    @classmethod
    def can(cls, ctx, ability, record=None):
        if ability in ("create", "update", "replicate"):
            return False
        return ctx.can(cls.permission)

    @classmethod
    def abilities(cls):
        return []  # one permission covers the whole screen


class SecurityAuditResource(_Guarded):
    model = SecurityAudit
    slug = "security-audits"
    label = "Security audit"
    icon = "history"
    navigation_group = "Security"
    navigation_label = "Audit history"
    navigation_sort = 91
    description = "Every audit you ran, to see how your score changes."
    record_title_attribute = "grade"
    simple = True
    pages = ("index",)

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return [run_action()]

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("created_at").label("Checked").datetime().sortable(),
                TextColumn("score").sortable()
                .color(lambda record: "success" if record.score >= 80 else "warning" if record.score >= 60 else "danger"),
                TextColumn("grade").badge()
                .color(lambda record: "success" if record.score >= 80 else "warning" if record.score >= 60 else "danger"),
                TextColumn("failed").color(lambda record: "danger" if record.failed else "gray"),
                TextColumn("warnings").color(lambda record: "warning" if record.warnings else "gray"),
                TextColumn("passed").color("gray"),
                TextColumn("url").label("Website").placeholder("Not checked").color("gray").limit(50),
            ])
            .actions([
                Action("view").label("View").icon("eye").color("gray").slide_over().modal_width("4xl")
                .modal_heading(lambda record: f"Audit of {record.created_at:%d %b %Y, %H:%M}")
                .modal_content(lambda ctx, record: report(ctx, record))
                .modal_submit_action(False).modal_cancel_action_label("Close"),
                DeleteAction(),
            ])
            .bulk_actions([DeleteBulkAction()])
            .empty_state("No audits yet", "Press Run audit to check your panel.", "shield-check")
            .default_sort("created_at", "desc")
        )


# ====================================================================== login log
def _unlock(ctx: Any, db: Any, email: str) -> None:
    email = (email or "").strip().lower()
    plugin_of(ctx).guard.unlock(db, email, user_id=None)
    Notification("Unlocked").body(f"{email} can log in again.").success().send(ctx)


class LoginAttemptResource(_Guarded):
    model = LoginAttempt
    slug = "login-log"
    label = "Login"
    plural_label = "Login log"
    icon = "log-in"
    navigation_group = "Security"
    navigation_label = "Login log"
    navigation_sort = 92
    description = "Every login try on this panel: who, from where, and if it worked."
    record_title_attribute = "email"
    simple = True
    pages = ("index",)
    permission = LOGINS_PERMISSION

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return [
            Action("unlock").label("Unlock a login").icon("lock-open").color("gray").outlined()
            .visible(lambda ctx: plugin_of(ctx).lockout)
            .modal_heading("Unlock a login").modal_width("md")
            .modal_description("Lets this email try again right away, from every IP.")
            .form([TextInput("email").label("Email").email().required()])
            .modal_submit_action_label("Unlock")
            .action(lambda ctx, db, data: _unlock(ctx, db, data["email"])),
        ]

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("created_at").label("When").since().sortable(),
                TextColumn("email").searchable().sortable(),
                TextColumn("reason").label("Result").badge()
                .state(lambda record: REASONS.get(record.reason, (record.reason, "gray"))[0])
                .color(lambda record: REASONS.get(record.reason, (record.reason, "gray"))[1]),
                TextColumn("ip").label("IP").searchable().placeholder("Unknown").color("gray"),
                TextColumn("user_agent").label("Browser").placeholder("Unknown").color("gray").limit(40),
            ])
            .filters([
                TernaryFilter("success").label("Worked").true_label("Logged in").false_label("Failed"),
                SelectFilter("reason").label("Result").options({k: v[0] for k, v in REASONS.items()}),
            ])
            .actions([
                Action("unlock_row").label("Unlock").icon("lock-open").color("warning")
                .visible(lambda ctx, record: not record.success and plugin_of(ctx).lockout
                         and plugin_of(ctx).guard.is_locked(ctx.db, record.email, record.ip))
                .requires_confirmation().modal_heading("Unlock this login?")
                .modal_description(lambda record: f"{record.email} can try again right away.")
                .action(lambda ctx, db, record: _unlock(ctx, db, record.email)),
            ])
            .bulk_actions([DeleteBulkAction()])
            .empty_state("No logins yet", "Every login try on the panel shows here.", "log-in")
            .default_sort("created_at", "desc")
        )
