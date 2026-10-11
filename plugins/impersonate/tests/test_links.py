"""The plugin links into HR, the help desk and the security audit when they are installed."""

from __future__ import annotations

from conftest import build, client_for
from tungsten_hr import HRPlugin
from tungsten_hr.models import Employee
from tungsten_security_audit import SecurityAuditPlugin
from tungsten_security_audit.checks import Audit, run_checks
from tungsten_tickets import TicketsPlugin, create_ticket

BUTTON = 'title="Log in as"'


def test_hr_employee_with_a_login_gets_the_button(tmp_path):
    panel = build(tmp_path, plugins=[HRPlugin()])
    with panel.db() as db:
        db.add(Employee(first_name="Ravi", last_name="Agent", user_id="2"))
        db.add(Employee(first_name="No", last_name="Login"))
        db.add(Employee(first_name="Ghost", user_id="999"))  # the login was deleted
        db.commit()
    c = client_for(panel)
    c.login()
    page = c.get("/admin/employees").text
    assert page.count(BUTTON) == 1
    r = c.action("impersonate", 1, host="resource:employees")
    assert r.headers.get("HX-Redirect") == "/admin/"
    assert "You are logged in as <strong>Ravi Agent</strong>" in c.get("/admin/").text


def test_ticket_page_can_log_in_as_the_customer(tmp_path):
    panel = build(tmp_path, plugins=[TicketsPlugin()])
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        known = create_ticket(db, subject="Invoice missing", requester_email="MEENA@example.com")
        unknown = create_ticket(db, subject="Hello", requester_email="stranger@example.com")
        db.commit()
        known_id, unknown_id = known.id, unknown.id
    c = client_for(panel)
    c.login()
    assert "Log in as customer" not in c.get("/admin/tickets").text  # not on every row of the list
    assert "Log in as customer" in c.get(f"/admin/tickets/{known_id}/edit").text
    assert "Log in as customer" not in c.get(f"/admin/tickets/{unknown_id}/edit").text
    r = c.action("impersonate", known_id, host="resource:tickets", scope="page")
    assert r.headers.get("HX-Redirect") == "/admin/"
    assert "<strong>Meena Customer</strong>" in c.get("/admin/").text


def test_security_audit_gets_a_check(tmp_path):
    panel = build(tmp_path, plugins=[SecurityAuditPlugin()])
    panel.boot()
    audit_plugin = panel.get_plugin("security-audit")
    names = [getattr(c, "__name__", "") for c in audit_plugin.checks]
    assert names.count("impersonation_check") == 1
    panel.boot()  # booting twice adds nothing twice
    assert [getattr(c, "__name__", "") for c in audit_plugin.checks].count("impersonation_check") == 1

    class Ctx:
        pass

    ctx = Ctx()
    ctx.panel = panel
    ctx.db = None
    results = {r["key"]: r for r in run_checks(Audit(ctx, audit_plugin), [audit_plugin.checks[-1]])}
    assert results["impersonate_who"]["status"] == "warn"  # no roles: every user may impersonate
    assert results["impersonate_limit"]["status"] == "pass"
    assert results["impersonate_log"]["status"] == "pass"


def test_works_alone_without_other_plugins(tmp_path):
    panel = build(tmp_path)
    panel.boot()
    assert panel.get_plugin("hr") is None
    assert panel.resource("impersonation-log") is not None
