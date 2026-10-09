import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import select
from tungsten_security_audit import LoginAttempt, SecurityAudit, grade_of, score_of
from tungsten_security_audit.checks import installed_packages

from tungsten import hash_password


def fast_hash(password):
    return hash_password(password, iterations=1000)

ACTION = "/admin/_tw/action"


def run(admin, panel, url="https://shop.example.com/admin/login", packages=False):
    admin.get("/admin/security-audit")
    data = {"_tw_host": "page:security-audit", "_tw_scope": "page", "_tw_name": "run", "url": url}
    if packages:
        data["packages"] = "1"
    r = admin.post(ACTION, data)
    assert r.status_code in (200, 204), r.text
    with panel.db() as db:
        audit = db.scalars(select(SecurityAudit).order_by(SecurityAudit.id.desc())).first()
    return audit, ({row["key"]: row for row in audit.results} if audit else {})


def test_score_and_grade():
    assert score_of([]) == 100 and grade_of(100) == "A"
    rows = [{"status": "fail", "severity": "high"}, {"status": "warn", "severity": "medium"},
            {"status": "pass", "severity": "high"}]
    assert score_of(rows) == 100 - 15 - 4
    assert [grade_of(s) for s in (95, 85, 75, 65, 10)] == ["A", "B", "C", "D", "F"]


def test_well_set_up_panel_scores_high(admin, panel, net):
    page = admin.get("/admin/security-audit")
    assert page.status_code == 200 and "No audit yet" in page.text and "Run audit" in page.text

    audit, r = run(admin, panel)
    assert audit is not None and audit.user_id == "1"
    for key in ("login", "secret_key", "debug", "secure_cookies", "app_url", "roles", "cors", "api_docs",
                "activity_log", "superusers", "weak_passwords", "lockout", "https", "hsts", "csp", "frames",
                "nosniff", "referrer", "version_leak", "cookie_flags", "http_redirect", "certificate"):
        assert r[key]["status"] == "pass", (key, r[key])
    assert r["two_factor"]["status"] == "warn" and "admin@example.com" in r["two_factor"]["detail"]
    assert r["vulnerable_packages"]["status"] == "skip" and "osv" not in net.calls
    assert audit.score >= 90 and audit.grade == "A"

    page = admin.get("/admin/security-audit").text
    assert f">{audit.score}<" in page and "Grade A" in page and "Two-factor login" in page
    assert "Ask them to turn it on" in page  # the fix tip

    history = admin.get("/admin/security-audits").text
    assert "Audit history" in history or "Security audits" in history
    view = admin.get(f"{ACTION}?_tw_host=resource:security-audits&_tw_scope=row&_tw_name=view&_tw_record={audit.id}",
                     headers={"HX-Request": "true"})
    assert view.status_code == 200 and "Grade A" in view.text


@pytest.mark.parametrize("panel_options", [{"secret_key": "change-me", "https_only_cookies": False}])
def test_weak_settings_and_headers(admin, panel, net, user_model):
    net.headers = {"server": "Apache/2.4.41 (Ubuntu)", "x-powered-by": "PHP/7.4.3"}
    net.cookies = ["tungsten_admin=abc; path=/; httponly; samesite=lax"]
    net.redirect = "http://shop.example.com/other"
    net.days = 5
    with panel.db() as db:  # an admin with the email name as password
        db.get(user_model, 1).password = fast_hash("admin")
        db.commit()
    audit, r = run(admin, panel)
    for key in ("secret_key", "secure_cookies", "hsts", "cookie_flags", "certificate", "weak_passwords"):
        assert r[key]["status"] == "fail", (key, r[key])
    for key in ("csp", "frames", "nosniff", "referrer", "version_leak", "http_redirect"):
        assert r[key]["status"] == "warn", (key, r[key])
    assert "Apache/2.4.41" in r["version_leak"]["detail"]
    assert "admin@example.com" in r["weak_passwords"]["detail"]
    assert audit.grade == "F" and audit.failed >= 6


@pytest.mark.parametrize("panel_options", [{"app_url": None}])
def test_only_own_site_is_opened(admin, panel, net):
    audit, _ = run(admin, panel, url="https://someone-else.example.org/")
    assert audit is None and net.calls == []
    audit, r = run(admin, panel, url="https://shop.example.com/admin/login")  # the address in the browser
    assert audit is not None and r["https"]["status"] == "pass"
    assert r["app_url"]["status"] == "warn"


def test_site_down_and_no_url(admin, panel, net):
    net.down = True
    _, r = run(admin, panel)
    assert r["website"]["status"] == "skip" and "connection refused" in r["website"]["detail"]
    _, r = run(admin, panel, url="")
    assert r["website"]["status"] == "skip" and "https" not in r


def test_packages_against_osv(admin, panel, net):
    name, version = next(p for p in installed_packages() if p[0] == "fastapi")
    net.vulns = {(name, version): ["GHSA-aaaa", "PYSEC-1"]}
    _, r = run(admin, panel, packages=True)
    assert "osv" in net.calls
    row = r["vulnerable_packages"]
    assert row["status"] == "fail" and f"fastapi {version} (GHSA-aaaa, PYSEC-1)" in row["detail"]
    assert "pip install -U fastapi" in row["fix"]


def test_app_checks_debug_cors_docs(panel, net, make_client):
    app = FastAPI(debug=True)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)
    panel.mount(app)
    admin = make_client(TestClient(app, base_url="https://shop.example.com"))
    assert admin.login().status_code == 303
    _, r = run(admin, panel)
    assert r["debug"]["status"] == "fail" and r["cors"]["status"] == "fail"
    assert r["api_docs"]["status"] == "warn" and "/docs" in r["api_docs"]["detail"]


def test_login_log_and_lockout(panel, http, make_client, user_model):
    client = make_client(http)
    for _ in range(5):
        r = client.login(password="nope")
        assert r.status_code == 200 and "do not match" in r.text
    r = client.login()  # right password, but locked now
    assert r.status_code == 200 and "Too many failed logins" in r.text
    client.login(email="ghost@example.com", password="x")

    with panel.db() as db:
        rows = db.scalars(select(LoginAttempt).order_by(LoginAttempt.id)).all()
    assert [r.reason for r in rows] == ["wrong_password"] * 5 + ["locked", "unknown_user"]
    assert rows[0].ip == "testclient" and rows[0].user_id == "1" and rows[0].user_agent

    admin = make_client(TestClient(http.app, base_url="https://shop.example.com"))  # own cookies
    with panel.db() as db:  # a second admin, to unlock the first
        db.add(user_model(name="Ola", email="ola@example.com", password=fast_hash("Another-Long-Passw0rd")))
        db.commit()
        from tungsten.models import RoleAssignment
        db.add(RoleAssignment(role_id=1, user_id="3"))
        db.commit()
    assert admin.login("ola@example.com", "Another-Long-Passw0rd").status_code == 303
    log = admin.get("/admin/login-log")
    assert log.status_code == 200 and "Wrong password" in log.text and "Locked out" in log.text
    assert "Unknown email" in log.text

    _, r = run(admin, panel, url="")
    assert r["locked"]["status"] == "info" and "admin@example.com from testclient" in r["locked"]["detail"]

    admin.post(ACTION, {"_tw_host": "resource:login-log", "_tw_scope": "page", "_tw_name": "unlock",
                        "email": "Admin@Example.com"})
    assert client.login().status_code == 303
    with panel.db() as db:
        reasons = [r.reason for r in db.scalars(select(LoginAttempt).order_by(LoginAttempt.id)).all()]
    assert reasons[-2:] == ["unlocked", "success"]


def test_lock_ends_after_its_time(panel, http, make_client):
    plugin = panel.get_plugin("security-audit")
    with panel.db() as db:
        old = dt.datetime.now() - dt.timedelta(minutes=20)
        for _ in range(5):
            db.add(LoginAttempt(email="admin@example.com", ip="testclient", success=False, reason="wrong_password",
                                created_at=old))
        db.commit()
        assert not plugin.guard.is_locked(db, "admin@example.com", "testclient")
        assert plugin.guard.locked_until(db, "admin@example.com", "testclient",
                                         now=old + dt.timedelta(minutes=1)) is not None
    assert make_client(http).login().status_code == 303


@pytest.mark.parametrize("options", [{"lockout": False}])
def test_no_lockout_still_logs(panel, http, make_client):
    client = make_client(http)
    for _ in range(5):
        client.login(password="nope")
    r = client.login()
    assert "Too many login attempts" in r.text  # only the built-in per-minute limit
    with panel.db() as db:
        assert db.scalars(select(LoginAttempt.reason).order_by(LoginAttempt.id.desc())).first() == "throttled"


def test_staff_without_permission_is_kept_out(http, make_client):
    staff = make_client(http)
    assert staff.login("staff@example.com", "password").status_code == 303
    assert staff.get("/admin/security-audit").status_code == 403
    assert staff.get("/admin/login-log").status_code == 403
    assert staff.get("/admin/security-audits").status_code == 403
    nav = staff.get("/admin/").text
    assert "Security audit" not in nav and "Login log" not in nav


def test_roles_screen_lists_permissions(panel):
    keys = [k for k, _ in panel.permission_options()]
    assert "security.audit" in keys and "security.logins" in keys
    assert not [k for k in keys if k.startswith(("login-log.", "security-audits."))]


def test_custom_check(tmp_path):
    from tungsten_security_audit import Result, SecurityAuditPlugin

    plugin = SecurityAuditPlugin(checks=[lambda audit: Result("backups", "Settings", "Backups", "fail", "high")])
    assert plugin.checks[-1].__name__ == "<lambda>"
