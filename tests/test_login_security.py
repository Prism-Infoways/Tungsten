"""Login and security: email codes for 2FA, verified email changes, idle timeout, API tokens, security headers."""

from __future__ import annotations

import datetime as dt
import re

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import PanelClient, db_session


def _code(mail: dict) -> str:
    return re.search(r"\b(\d{6})\b", mail["body"]).group(1)


def _link(mail: dict) -> str:
    return re.search(r"https?://[^/\s]+(/\S+)", mail["body"]).group(1)


def _user(panel, email="admin@example.com"):
    from examples.shop.models import User

    with db_session(panel) as db:
        return db.scalars(select(User).where(User.email == email)).first()


# ---------------------------------------------------------------------- two-factor codes by email


def _turn_on_email_codes(admin, panel):
    panel.auth.two_factor_email = True
    r = admin.post("/admin/two-factor", {"_do": "email_enable"}, htmx=False)
    assert "Code from the email" in r.text
    mail = panel.test_mails[-1]
    assert mail["to"] == "admin@example.com" and "sign-in code" in mail["subject"]
    r = admin.post("/admin/two-factor", {"_do": "email_confirm", "code": "000000"}, htmx=False)
    assert "not valid" in r.text
    r = admin.post("/admin/two-factor", {"_do": "email_confirm", "code": _code(mail)}, htmx=False)
    assert "Email codes are on" in r.text


def test_two_factor_by_email(admin, app_and_panel):
    app, panel = app_and_panel
    _turn_on_email_codes(admin, panel)

    fresh = PanelClient(TestClient(app))
    r = fresh.login()
    assert r.headers["location"] == "/admin/two-factor/challenge"
    sent = len(panel.test_mails)
    html = fresh.get("/admin/two-factor/challenge").text
    assert len(panel.test_mails) == sent + 1  # the code goes out as soon as the page opens
    assert "a•••@example.com" in html and "Email me a code instead" not in html
    fresh.get("/admin/two-factor/challenge")
    assert len(panel.test_mails) == sent + 1  # reloading doesn't send another
    code = _code(panel.test_mails[-1])
    r = fresh.client.post("/admin/two-factor/challenge", data={"_token": fresh.token, "code": "111111"},
                          follow_redirects=False)
    assert "not valid" in r.text
    r = fresh.client.post("/admin/two-factor/challenge", data={"_token": fresh.token, "code": code},
                          follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/"
    assert fresh.get("/admin/products").status_code == 200
    # the session cookie never holds the code itself
    assert code not in str(fresh.client.cookies.get("tungsten_admin"))


def test_email_code_works_once_and_app_users_can_ask_for_one(admin, app_and_panel):
    from tungsten.auth.two_factor import totp

    app, panel = app_and_panel
    r = admin.post("/admin/two-factor", {"_do": "enable"}, htmx=False)
    secret = re.search(r"<code[^>]*>([A-Z2-7]+)</code>", r.text).group(1)
    admin.post("/admin/two-factor", {"_do": "confirm", "code": totp(secret)}, htmx=False)
    _turn_on_email_codes(admin, panel)

    fresh = PanelClient(TestClient(app))
    fresh.login()
    sent = len(panel.test_mails)
    html = fresh.get("/admin/two-factor/challenge").text
    assert len(panel.test_mails) == sent  # app users aren't emailed unless they ask
    assert "Email me a code instead" in html
    r = fresh.client.post("/admin/two-factor/challenge", data={"_token": fresh.token, "_do": "email"},
                          follow_redirects=False)
    assert r.status_code == 303 and len(panel.test_mails) == sent + 1
    code = _code(panel.test_mails[-1])
    fresh.client.post("/admin/two-factor/challenge", data={"_token": fresh.token, "_do": "email"})
    assert len(panel.test_mails) == sent + 1  # once a minute
    r = fresh.client.post("/admin/two-factor/challenge", data={"_token": fresh.token, "code": code},
                          follow_redirects=False)
    assert r.status_code == 303

    # a used code is gone
    again = PanelClient(TestClient(app))
    again.login()
    again.get("/admin/two-factor/challenge")
    r = again.client.post("/admin/two-factor/challenge", data={"_token": again.token, "code": code},
                          follow_redirects=False)
    assert r.status_code == 200 and "not valid" in r.text


def test_email_codes_only_for_users_who_turned_them_on(app_and_panel, admin):
    from tungsten.auth.two_factor import totp

    app, panel = app_and_panel
    panel.auth.two_factor_email = True
    r = admin.post("/admin/two-factor", {"_do": "enable"}, htmx=False)
    secret = re.search(r"<code[^>]*>([A-Z2-7]+)</code>", r.text).group(1)
    admin.post("/admin/two-factor", {"_do": "confirm", "code": totp(secret)}, htmx=False)

    fresh = PanelClient(TestClient(app))
    fresh.login()
    assert "Email me a code instead" not in fresh.get("/admin/two-factor/challenge").text
    sent = len(panel.test_mails)
    fresh.client.post("/admin/two-factor/challenge", data={"_token": fresh.token, "_do": "email"})
    assert len(panel.test_mails) == sent


def test_required_two_factor_is_met_by_email_codes(app_and_panel, admin):
    _, panel = app_and_panel
    panel.auth.two_factor_required = True
    _turn_on_email_codes(admin, panel)
    assert admin.get("/admin/products", follow_redirects=False).status_code == 200
    # the only method left can't be turned off
    r = admin.post("/admin/two-factor", {"_do": "email_disable", "password": "password"}, htmx=False)
    assert "required for this panel" in r.text
    panel.auth.two_factor_required = False
    r = admin.post("/admin/two-factor", {"_do": "email_disable", "password": "wrong"}, htmx=False)
    assert "password is incorrect" in r.text
    r = admin.post("/admin/two-factor", {"_do": "email_disable", "password": "password"}, htmx=False)
    assert "Turn on email codes" in r.text


# ---------------------------------------------------------------------- verified email change


def test_email_change_waits_for_the_new_address(admin, app_and_panel):
    app, panel = app_and_panel
    assert panel.auth.email_change_verification  # follows email_verification=True in the shop
    sent = len(panel.test_mails)
    r = admin.post("/admin/profile", {"name": "Admin", "email": "new@example.com"})
    assert r.headers.get("HX-Redirect") == "/admin/profile"
    assert _user(panel).email == "admin@example.com"  # unchanged until confirmed
    to_new, to_old = panel.test_mails[sent:]
    assert to_new["to"] == "new@example.com" and to_old["to"] == "admin@example.com"
    assert "/block" in to_old["body"] and "/block" not in to_new["body"]
    assert "new@example.com" in admin.get("/admin/profile").text  # the pending banner

    # someone else opening the confirm link (not signed in) still works, and lands on login
    r = TestClient(app).get(_link(to_new), follow_redirects=False)
    assert r.headers["location"] == "/admin/login"
    user = _user(panel, "new@example.com")
    assert user is not None and user.email_verified_at is not None
    # the link only works once
    r = admin.get(_link(to_new), follow_redirects=False)
    assert _user(panel, "new@example.com") is not None and r.status_code == 303


def test_old_address_can_block_email_change(admin, panel):
    sent = len(panel.test_mails)
    admin.post("/admin/profile", {"name": "Admin", "email": "thief@example.com"})
    to_new, to_old = panel.test_mails[sent:]
    r = admin.get(_link(to_old), follow_redirects=False)
    assert r.headers["location"] == "/admin/profile"
    r = admin.get(_link(to_new), follow_redirects=False)
    assert _user(panel).email == "admin@example.com"
    assert _user(panel, "thief@example.com") is None


def test_email_change_cancel_resend_limit_and_taken_address(admin, panel):
    from examples.shop.models import User
    from tungsten.auth import hash_password

    sent = len(panel.test_mails)
    admin.post("/admin/profile", {"name": "Admin", "email": "one@example.com"})
    first = panel.test_mails[sent]
    admin.post("/admin/profile", {"name": "Admin", "email": "two@example.com"})
    assert len(panel.test_mails) == sent + 2  # a second change within a minute sends nothing
    admin.post("/admin/email-change/cancel", {}, htmx=False)
    assert "one@example.com" not in admin.get("/admin/profile").text
    admin.get(_link(first))
    assert _user(panel).email == "admin@example.com"  # cancelled links do nothing

    # someone took the address before the link was opened (a fresh session skips the once-a-minute limit)
    other = PanelClient(TestClient(admin.client.app))
    other.login()
    other.get("/admin/")
    sent = len(panel.test_mails)
    other.post("/admin/profile", {"name": "Admin", "email": "taken@example.com"})
    link = _link(panel.test_mails[sent])
    with db_session(panel) as db:
        db.add(User(name="Taken", email="taken@example.com", password=hash_password("x"), is_admin=False))
        db.commit()
    other.get(link)
    assert _user(panel).email == "admin@example.com"


def test_expired_email_change_link(admin, panel):
    from tungsten.models import EmailChange

    sent = len(panel.test_mails)
    admin.post("/admin/profile", {"name": "Admin", "email": "late@example.com"})
    with db_session(panel) as db:
        row = db.scalars(select(EmailChange)).one()
        row.created_at = dt.datetime.now() - dt.timedelta(hours=5)
        db.commit()
    admin.get(_link(panel.test_mails[sent]))
    assert _user(panel).email == "admin@example.com"


# ---------------------------------------------------------------------- idle timeout


def test_idle_timeout_signs_out(admin, panel, monkeypatch):
    import tungsten.auth as auth_module

    panel.auth.idle_timeout = 10
    clock = [auth_module.time.time()]
    monkeypatch.setattr(auth_module.time, "time", lambda: clock[0])
    html = admin.get("/admin/products").text
    assert 'data-tw-idle="10"' in html and "/admin/_tw/ping" in html

    clock[0] += 9 * 60
    assert admin.get("/admin/_tw/ping").status_code == 204  # activity resets the clock
    clock[0] += 9 * 60
    # polling doesn't count as activity
    assert admin.get("/admin/products", headers={"X-TW-Background": "1"}).status_code == 200
    clock[0] += 2 * 60
    r = admin.get("/admin/products", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/login")
    assert "signed you out" in admin.get("/admin/login").text
    assert admin.login().status_code == 303  # signing in again works
    assert admin.get("/admin/products", follow_redirects=False).status_code == 200


def test_no_idle_timeout_by_default(admin, panel, monkeypatch):
    import tungsten.auth as auth_module

    clock = [auth_module.time.time() + 3 * 24 * 3600]  # days later (the cookie itself lasts 14)
    monkeypatch.setattr(auth_module.time, "time", lambda: clock[0])
    assert admin.get("/admin/products", follow_redirects=False).status_code == 200
    assert "data-tw-idle" not in admin.get("/admin/products").text


# ---------------------------------------------------------------------- API tokens


def _api_app(app_and_panel):
    app, panel = app_and_panel
    panel.auth.api_tokens = True
    panel.auth.api_abilities = {"orders:read": "Read orders", "orders:write": "Change orders"}

    @app.get("/api/me")
    def me(user=Depends(panel.api_user())):
        return {"email": user.email}

    @app.post("/api/orders")
    def write(user=Depends(panel.api_user("orders:write"))):
        return {"ok": True}

    return app, panel


def test_api_tokens_page_and_bearer_auth(admin, app_and_panel):
    app, panel = _api_app(app_and_panel)
    assert "API tokens" in admin.get("/admin/profile").text
    r = admin.post("/admin/api-tokens", {"_do": "create", "name": "Reports", "abilities": ["orders:read", "bogus"],
                                         "expires": "30"}, htmx=False)
    plain = re.search(r"(tw_[A-Za-z0-9_-]{20,})", r.text).group(1)
    assert "Read orders" in r.text and "bogus" not in r.text

    api = TestClient(app)
    assert api.get("/api/me").status_code == 401
    assert api.get("/api/me", headers={"Authorization": "Bearer tw_nope"}).status_code == 401
    r = api.get("/api/me", headers={"Authorization": f"Bearer {plain}"})
    assert r.status_code == 200 and r.json() == {"email": "admin@example.com"}
    r = api.post("/api/orders", headers={"Authorization": f"Bearer {plain}"})
    assert r.status_code == 403  # read-only token

    html = admin.get("/admin/api-tokens").text
    assert plain not in html and "Last used" in html  # shown once only
    from tungsten.models import ApiToken

    with db_session(panel) as db:
        token = db.scalars(select(ApiToken)).one()
        assert token.token_hash != plain and token.expires_at is not None
        token_id = token.id
    admin.post("/admin/api-tokens", {"_do": "revoke", "id": str(token_id)}, htmx=False)
    assert api.get("/api/me", headers={"Authorization": f"Bearer {plain}"}).status_code == 401


def test_api_token_expiry_inactive_user_and_other_users_tokens(admin, app_and_panel):
    from examples.shop.models import User
    from tungsten.auth import tokens
    from tungsten.models import ApiToken

    app, panel = _api_app(app_and_panel)
    api = TestClient(app)
    with db_session(panel) as db:
        user = db.scalars(select(User).where(User.email == "admin@example.com")).one()
        _, everything = tokens.create(db, panel, user, "All", ["*"])
        _, old = tokens.create(db, panel, user, "Old", ["*"], dt.datetime.now() - dt.timedelta(days=1))
        other = User(name="Other", email="other@example.com", password="x", is_admin=True)
        db.add(other)
        db.commit()
        _, theirs = tokens.create(db, panel, other, "Theirs", ["*"])
        their_id = db.scalars(select(ApiToken).where(ApiToken.name == "Theirs")).one().id
    h = {"Authorization": f"Bearer {everything}"}
    assert api.post("/api/orders", headers=h).status_code == 200  # "*" can do anything
    assert api.get("/api/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    # you can't delete someone else's token
    admin.post("/admin/api-tokens", {"_do": "revoke", "id": str(their_id)}, htmx=False)
    assert api.get("/api/me", headers={"Authorization": f"Bearer {theirs}"}).status_code == 200
    with db_session(panel) as db:
        db.scalars(select(User).where(User.email == "other@example.com")).one().is_active = False
        db.commit()
    assert api.get("/api/me", headers={"Authorization": f"Bearer {theirs}"}).status_code == 401


def test_api_tokens_page_is_off_by_default(admin):
    assert admin.get("/admin/api-tokens").status_code == 404
    assert "/admin/api-tokens" not in admin.get("/admin/profile").text


# ---------------------------------------------------------------------- security headers


def test_security_headers_on_every_response(client):
    r = client.get("/admin/login")
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in csp and "object-src 'none'" in csp and "fonts.googleapis.com" in csp
    assert "strict-transport-security" not in r.headers  # plain http
    r = client.get("/admin/login", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["strict-transport-security"].startswith("max-age=31536000")
    assert client.get("/admin/assets/tungsten.css").headers["x-content-type-options"] == "nosniff"


def test_security_headers_can_be_changed(tmp_path):
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    from tungsten.security import SecurityHeadersMiddleware, build_csp

    csp = build_csp({"script-src": "https://cdn.example.com", "frame-ancestors": None})
    assert "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.example.com" in csp
    assert "frame-ancestors" not in csp
    assert build_csp(False) is None and build_csp("default-src 'none'") == "default-src 'none'"

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, headers={"X-Frame-Options": "DENY", "Referrer-Policy": None},
                       content_security_policy=False, hsts="always")

    @app.get("/")
    def home():
        return PlainTextResponse("hi", headers={"Content-Security-Policy": "sandbox"})

    r = TestClient(app).get("/")
    assert r.headers["x-frame-options"] == "DENY" and "referrer-policy" not in r.headers
    assert r.headers["content-security-policy"] == "sandbox"  # a route's own header wins
    assert "strict-transport-security" in r.headers


def test_panel_without_security_headers(tmp_path):
    from sqlalchemy import create_engine

    from tungsten import Panel

    panel = Panel(engine=create_engine(f"sqlite:///{tmp_path / 'x.db'}"), security_headers=False,
                  content_security_policy=False)
    r = TestClient(panel.app).get("/login")
    assert "x-frame-options" not in r.headers and "content-security-policy" not in r.headers
