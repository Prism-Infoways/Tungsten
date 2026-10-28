from __future__ import annotations

import time

from conftest import build, client_for, give_role
from sqlalchemy import select
from tungsten_impersonate import ImpersonationLog, service

BAR = "tw-impersonate-bar"


def logs(panel) -> list[ImpersonationLog]:
    with panel.db() as db:
        return list(db.scalars(select(ImpersonationLog).order_by(ImpersonationLog.id)))


def refused(r) -> bool:
    """HTMX actions answer a refusal with a red toast instead of an error page."""
    return r.status_code == 204 and "HX-Redirect" not in r.headers and (
        "Not allowed" in r.headers.get("HX-Trigger", "") or "Can't log in" in r.headers.get("HX-Trigger", ""))


# ---------------------------------------------------------------------- the happy path
def test_button_shows_on_users_but_not_on_yourself_or_inactive(admin):
    page = admin.get("/admin/users").text
    assert page.count('title="Log in as"') == 2  # Ravi and Meena; not Asha (self) nor Old Staff (inactive)


def test_log_in_as_and_back(admin, panel):
    r = admin.get("/admin/users")
    r = admin.login_as(2, reason="Ticket 12: can't see invoice", headers={"Referer": "http://testserver/admin/users"})
    assert r.status_code == 204 and r.headers["HX-Redirect"] == "/admin/"
    page = admin.get("/admin/").text
    assert BAR in page and "You are logged in as <strong>Ravi Agent</strong>" in page
    assert "ends in 60 min" in page
    (entry,) = logs(panel)
    assert (entry.impersonator_name, entry.target_name, entry.target_id) == ("Asha Admin", "Ravi Agent", "2")
    assert entry.reason == "Ticket 12: can't see invoice" and entry.ended_at is None
    assert entry.ip

    r = admin.leave()
    assert r.status_code == 303 and r.headers["location"] == "/admin/users"  # back where the admin started
    page = admin.get("/admin/").text
    assert BAR not in page and "Welcome back, Asha Admin" in page
    (entry,) = logs(panel)
    assert entry.end_reason == "left" and entry.ended_at is not None


def test_while_impersonating_you_see_their_access(tmp_path):
    panel = build(tmp_path, rbac=True)
    give_role(panel, "admin@example.com", "Super", ["*"])
    give_role(panel, "ravi@example.com", "Agent", ["users.view_any"])
    admin = client_for(panel)
    admin.login()
    admin.get("/admin/users")
    assert admin.login_as(2).status_code == 204
    assert admin.get("/admin/users").status_code == 200
    assert admin.get("/admin/impersonation-log").status_code == 403  # Ravi can't see the log
    assert 'title="Log in as"' not in admin.get("/admin/users").text  # and can't impersonate anyone
    admin.leave()
    assert admin.get("/admin/impersonation-log").status_code == 200


# ---------------------------------------------------------------------- refusals
def test_no_self_inactive_unknown_or_nested(admin, panel):
    admin.get("/admin/users")
    assert refused(admin.login_as(1))  # yourself: the button is hidden, so the action is refused
    assert refused(admin.login_as(4))  # inactive
    assert admin.login_as(99).status_code in (204, 404) and logs(panel) == []
    assert logs(panel) == []
    admin.login_as(2)
    admin.get("/admin/")
    assert refused(admin.login_as(3))  # no "log in as" from inside another account
    assert len(logs(panel)) == 1


def test_start_refuses_with_a_clear_reason(panel):
    with panel.db() as db:
        from types import SimpleNamespace

        from conftest import User

        from tungsten.context import Context

        request = SimpleNamespace(scope={"session": {}}, session={}, headers={}, client=None,
                                  url=SimpleNamespace(netloc="x"))
        ctx = Context(panel, request, db)
        ctx.user = db.get(User, 1)
        assert service.refusal(panel.imp, ctx, None) == "This user was not found."
        assert service.refusal(panel.imp, ctx, ctx.user) == "This is your own account."
        assert service.refusal(panel.imp, ctx, db.get(User, 4)) == "This user is not active."
        assert service.refusal(panel.imp, ctx, db.get(User, 2)) is None


def test_rbac_needs_the_permission(tmp_path):
    panel = build(tmp_path, rbac=True)
    give_role(panel, "admin@example.com", "Support", ["users.view_any"])
    c = client_for(panel)
    c.login()
    c.get("/admin/users")
    assert refused(c.login_as(3))
    assert logs(panel) == []


def test_rbac_no_super_admins_and_no_more_access(tmp_path):
    panel = build(tmp_path, rbac=True)
    give_role(panel, "admin@example.com", "Support", ["users.view_any", "impersonate.start"])
    give_role(panel, "ravi@example.com", "Super", ["*"])
    give_role(panel, "meena@example.com", "Billing", ["users.view_any", "invoices.view_any"])
    c = client_for(panel)
    c.login()
    page = c.get("/admin/users").text
    assert page.count('title="Log in as"') == 0  # Ravi is a super admin, Meena can see invoices and Asha can't
    assert refused(c.login_as(2))
    assert refused(c.login_as(3))
    give_role(panel, "admin@example.com", "Billing", [])
    assert c.get("/admin/users").text.count('title="Log in as"') == 1  # now Asha has every permission Meena has
    assert c.login_as(3).status_code == 204


def test_custom_rules(tmp_path):
    panel = build(tmp_path, can_impersonate=lambda user: user.email == "admin@example.com",
                  can_be_impersonated=lambda target: target.email != "meena@example.com")
    c = client_for(panel)
    c.login()
    c.get("/admin/users")
    assert refused(c.login_as(3))
    assert c.login_as(2).status_code == 204
    c.leave()
    c.client.post("/admin/logout", data={"_token": c.token})
    c.login("ravi@example.com")
    c.get("/admin/users")
    assert refused(c.login_as(3))  # Ravi may not impersonate at all


def test_require_reason(tmp_path):
    panel = build(tmp_path, require_reason=True)
    c = client_for(panel)
    c.login()
    c.get("/admin/users")
    r = c.login_as(2)
    assert r.status_code == 200 and "required" in r.text.lower()  # the modal comes back with the error
    assert logs(panel) == []
    assert c.login_as(2, reason="Checking the bug").status_code == 204


def test_two_factor_required_users_must_have_it(tmp_path):
    panel = build(tmp_path, auth_kw={"two_factor": True})
    panel.auth.two_factor_required = True
    with panel.db() as db:
        from types import SimpleNamespace

        from conftest import User

        from tungsten.context import Context

        request = SimpleNamespace(scope={"session": {}}, session={}, headers={}, client=None,
                                  url=SimpleNamespace(netloc="x"))
        ctx = Context(panel, request, db)
        ctx.user = db.get(User, 1)
        assert service.refusal(panel.imp, ctx, db.get(User, 2)) == "This user has not set up two-step login yet."


# ---------------------------------------------------------------------- ending
def test_time_limit_sends_the_admin_back(admin, panel, monkeypatch):
    admin.get("/admin/users")
    admin.login_as(2)
    assert BAR in admin.get("/admin/").text
    later = time.time() + 61 * 60
    monkeypatch.setattr(service.time, "time", lambda: later)
    page = admin.get("/admin/").text
    assert BAR not in page and "Back to your own account" in page
    assert logs(panel)[0].end_reason == "expired"


def test_no_time_limit(tmp_path, monkeypatch):
    panel = build(tmp_path, max_minutes=0)
    c = client_for(panel)
    c.login()
    c.get("/admin/users")
    c.login_as(2)
    later = time.time() + 24 * 3600
    monkeypatch.setattr(service.time, "time", lambda: later)
    page = c.get("/admin/").text
    assert BAR in page and "ends in" not in page


def test_logout_ends_it(admin, panel):
    admin.get("/admin/users")
    admin.login_as(2)
    admin.get("/admin/")
    r = admin.client.post("/admin/logout", data={"_token": admin.token}, follow_redirects=False)
    assert r.status_code == 303
    assert logs(panel)[0].end_reason == "logged_out"
    assert admin.get("/admin/", follow_redirects=False).status_code in (302, 303)  # nobody is signed in


def test_admin_removed_meanwhile_signs_out(admin, panel):
    from conftest import User

    admin.get("/admin/users")
    admin.login_as(2)
    admin.get("/admin/")
    with panel.db() as db:
        db.get(User, 1).is_active = False
        db.commit()
    r = admin.leave()
    assert r.status_code == 303 and r.headers["location"] == "/admin/login"
    assert logs(panel)[0].end_reason == "left"
    assert admin.get("/admin/", follow_redirects=False).status_code in (302, 303)


def test_target_removed_meanwhile(admin, panel):
    from conftest import User

    admin.get("/admin/users")
    admin.login_as(2)
    with panel.db() as db:
        db.get(User, 2).is_active = False
        db.commit()
    # Ravi can't load any more: the panel sends to login, but the bar's button still brings Asha back
    assert admin.get("/admin/", follow_redirects=False).status_code in (302, 303)
    r = admin.leave()
    assert r.status_code == 303


def test_leave_needs_the_csrf_token(admin):
    admin.get("/admin/users")
    admin.login_as(2)
    admin.get("/admin/")
    r = admin.client.post("/admin/impersonate/leave", data={}, follow_redirects=False)
    assert r.status_code == 419
    assert BAR in admin.get("/admin/").text


def test_leave_without_impersonating_goes_home(admin):
    admin.get("/admin/")
    r = admin.leave()
    assert r.status_code == 303 and r.headers["location"] == "/admin/"


def test_back_url_stays_inside_the_panel(panel):
    assert service.safe_back_url(panel, "https://evil.example/admin") == "/admin/"
    assert service.safe_back_url(panel, "//evil.example/admin") == "/admin/"
    assert service.safe_back_url(panel, "/other") == "/admin/"
    assert service.safe_back_url(panel, "/admin/users?page=2") == "/admin/users?page=2"
    assert service.safe_back_url(panel, None) == "/admin/"


def test_foreign_referer_is_ignored(admin):
    admin.get("/admin/users")
    admin.login_as(2, headers={"Referer": "https://evil.example/admin/users"})
    r = admin.leave()
    assert r.headers["location"] == "/admin/"


def test_broken_session_value_is_dropped(admin, panel):
    """A session value that isn't ours (old version, hand edited) must not break the panel."""
    from tungsten_impersonate.service import state_key

    def poke(ctx, fd):
        ctx.session[state_key(panel)] = "garbage"
        return ctx.html("ok")

    from fastapi import Request

    from tungsten.routes import Routes

    @panel.routes
    def extra(app, panel_):
        @app.get("/poke")
        async def _poke(request: Request):
            return await Routes(panel_).run(request, poke)

    c = client_for(panel)
    c.login()
    c.get("/admin/poke")
    assert c.get("/admin/").status_code == 200
    assert BAR not in c.get("/admin/").text


# ---------------------------------------------------------------------- the log screen
def test_log_screen_is_read_only(admin, panel):
    admin.get("/admin/users")
    admin.login_as(2, reason="Checking")
    admin.leave()
    page = admin.get("/admin/impersonation-log").text
    assert "Ravi Agent" in page and "Went back" in page and "Checking" in page
    assert admin.get("/admin/impersonation-log/create").status_code in (403, 404)
    assert admin.get("/admin/impersonation-log/1/edit").status_code in (403, 404)


def test_pick_any_user_from_the_log_screen(admin, panel):
    admin.get("/admin/impersonation-log")
    modal = admin.client.get("/admin/_tw/action?_tw_host=resource:impersonation-log&_tw_scope=page"
                             "&_tw_name=login_as_user", headers={"HX-Request": "true"}).text
    assert "Meena Customer" in modal and "Asha Admin" not in modal
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:impersonation-log", "_tw_scope": "page",
                                         "_tw_name": "login_as_user", "user": "3"})
    assert r.headers.get("HX-Redirect") == "/admin/"
    assert "You are logged in as <strong>Meena Customer</strong>" in admin.get("/admin/").text
    admin.leave()
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:impersonation-log", "_tw_scope": "page",
                                         "_tw_name": "login_as_user", "user": "4"})
    assert "HX-Redirect" not in r.headers and len(logs(panel)) == 1
    assert "This user is not active." in admin.get("/admin/").text


def test_redirect_to_and_hooks(tmp_path):
    seen = []
    panel = build(tmp_path, redirect_to="/admin/users", on_start=lambda log: seen.append(("start", log.target_name)),
                  on_end=lambda reason: seen.append(("end", reason)))
    c = client_for(panel)
    c.login()
    c.get("/admin/users")
    assert c.login_as(2).headers["HX-Redirect"] == "/admin/users"
    c.leave()
    assert seen == [("start", "Ravi Agent"), ("end", "left")]


def test_broken_hook_does_not_trap_anyone(tmp_path):
    def boom():
        raise RuntimeError("hook bug")

    panel = build(tmp_path, on_start=boom, on_end=boom)
    c = client_for(panel)
    c.login()
    c.get("/admin/users")
    assert c.login_as(2).status_code == 204
    assert c.leave().status_code == 303
    assert BAR not in c.get("/admin/").text


def test_no_banner_option(tmp_path):
    panel = build(tmp_path, banner=False)
    c = client_for(panel)
    c.login()
    c.get("/admin/users")
    c.login_as(2)
    assert BAR not in c.get("/admin/").text
    assert c.leave().status_code == 303  # the route still works for your own button


def test_panel_without_auth_is_left_alone():
    from tungsten_impersonate import ImpersonatePlugin

    from tungsten import Panel

    panel = Panel(path="/admin", secret_key="x")
    panel.plugin(ImpersonatePlugin())
    panel.boot()
    assert panel.resource("impersonation-log") is None


def test_log_screen_follows_who_may_impersonate(tmp_path):
    """Issue #97: the log is not open to everyone."""
    panel = build(tmp_path, can_impersonate=lambda user: user.email == "admin@example.com")
    c = client_for(panel)
    c.login("ravi@example.com")
    assert c.get("/admin/impersonation-log").status_code == 403
    c.client.post("/admin/logout", data={"_token": c.token})
    c.login()
    assert c.get("/admin/impersonation-log").status_code == 200
    (tmp_path / "x").mkdir()
    other = build(tmp_path / "x", can_view_log=lambda user: False)
    o = client_for(other)
    o.login()
    assert o.get("/admin/impersonation-log").status_code == 403


def test_reason_field_can_be_left_out(tmp_path):
    panel = build(tmp_path, ask_reason=False)
    c = client_for(panel)
    c.login()
    modal = c.client.get("/admin/_tw/action?_tw_host=resource:users&_tw_scope=row&_tw_name=impersonate&_tw_record=2",
                         headers={"HX-Request": "true"}).text
    assert "Why?" not in modal and "Log in as user" in modal


def test_icon_button_keeps_its_label_for_screen_readers(panel):
    a = {"name": "x", "label": "Log in as", "icon": "venetian-mask", "color": "gray", "style": "icon", "size": None,
         "url": None, "new_tab": False, "modal": True, "endpoint": "/e", "vals": {}, "disabled": False,
         "tooltip": "Become this user", "badge": None, "outlined": False, "keyboard": None, "hidden_label": False}
    html = panel.renderer.render("tungsten/actions/button.html", a=a)
    assert 'title="Become this user"' in html and 'aria-label="Log in as"' in html


def test_times_use_the_panel_time_zone(tmp_path, monkeypatch):
    panel = build(tmp_path)
    panel.timezone = "Asia/Kolkata"
    c = client_for(panel)
    c.login()
    c.get("/admin/users")
    assert c.login_as(2).status_code == 204
    with panel.db() as db:
        entry = db.scalars(select(ImpersonationLog)).one()
    import datetime as dt
    from zoneinfo import ZoneInfo

    india = dt.datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    assert abs((entry.started_at - india).total_seconds()) < 60
