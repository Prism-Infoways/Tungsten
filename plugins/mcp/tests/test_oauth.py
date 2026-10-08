from __future__ import annotations

import base64
import datetime as dt
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import Mcp
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from tungsten_mcp import McpToken

VERIFIER = secrets.token_urlsafe(48)
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
CALLBACK = "https://claude.ai/api/mcp/auth_callback"


def register(http, **extra):
    body = {"client_name": "Claude", "redirect_uris": [CALLBACK], "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], **extra}
    r = http.post("/admin/oauth/register", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def authorize_url(client_id, **extra):
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK, "state": "xyz",
              "code_challenge": CHALLENGE, "code_challenge_method": "S256",
              "scope": "mcp:read mcp:write", "resource": "https://shop.example.com/admin/mcp", **extra}
    return "/admin/oauth/authorize?" + "&".join(f"{k}={v}" for k, v in params.items())


def get_code(admin, client_id, allow_changes=True, **extra):
    r = admin.client.get(authorize_url(client_id, **extra), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/mcp-authorize", r.text
    page = admin.get("/admin/mcp-authorize")
    assert "Claude" in page.text and "wants to use this panel as" in page.text
    r = admin.post("/admin/mcp-authorize", {"can_write": "1" if allow_changes else ""})
    target = r.headers["HX-Redirect"]
    assert target.startswith(CALLBACK + "?")
    query = parse_qs(urlparse(target).query)
    assert query["state"] == ["xyz"] and query["iss"] == ["https://shop.example.com/admin"]
    return query["code"][0]


def exchange(http, client_id, code, verifier=VERIFIER):
    return http.post("/admin/oauth/token", data={"grant_type": "authorization_code", "code": code,
                                                 "redirect_uri": CALLBACK, "client_id": client_id,
                                                 "code_verifier": verifier})


def test_metadata(panel, http):
    r = http.post("/admin/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
    # the challenge names an address under the panel, because that is the one the app is always given
    meta_url = "https://shop.example.com/admin/.well-known/oauth-protected-resource/mcp"
    assert f'resource_metadata="{meta_url}"' in r.headers["www-authenticate"]
    assert http.get("/admin/.well-known/oauth-protected-resource/mcp").status_code == 200
    resource = http.get("/.well-known/oauth-protected-resource/admin/mcp").json()
    assert resource["resource"] == "https://shop.example.com/admin/mcp"
    assert resource["authorization_servers"] == ["https://shop.example.com/admin"]
    assert http.get("/admin/.well-known/oauth-protected-resource").json() == resource
    server = http.get("/.well-known/oauth-authorization-server/admin").json()
    assert server["issuer"] == "https://shop.example.com/admin"
    assert server["token_endpoint"] == "https://shop.example.com/admin/oauth/token"
    assert server["code_challenge_methods_supported"] == ["S256"]
    for path in ("/.well-known/openid-configuration/admin", "/admin/.well-known/openid-configuration",
                 "/admin/.well-known/oauth-authorization-server", "/.well-known/oauth-authorization-server"):
        assert http.get(path).json() == server, path


def test_full_flow_and_refresh(panel, http, admin):
    client = register(http)
    assert "client_secret" not in client
    code = get_code(admin, client["client_id"])
    r = exchange(http, client["client_id"], code)
    assert r.status_code == 200, r.text
    tokens = r.json()
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600 and tokens["scope"] == "mcp:read mcp:write"
    assert r.headers["cache-control"] == "no-store"

    mcp = Mcp(http, tokens["access_token"])
    assert len(mcp.rpc("tools/list")["result"]["tools"]) == 7
    assert not mcp.call("update_record", resource="products", id=1, data={"name": "Red boot"})["isError"]

    assert exchange(http, client["client_id"], code).json()["error"] == "invalid_grant"  # one use only

    r = http.post("/admin/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                              "client_id": client["client_id"]})
    fresh = r.json()
    assert r.status_code == 200 and fresh["access_token"] != tokens["access_token"]
    assert Mcp(http, fresh["access_token"]).rpc("ping")["result"] == {}
    old = http.post("/admin/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                    headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert old.status_code == 401 and 'error="invalid_token"' in old.headers["www-authenticate"]
    again = http.post("/admin/oauth/token", data={"grant_type": "refresh_token", "client_id": client["client_id"],
                                                  "refresh_token": tokens["refresh_token"]})
    assert again.json()["error"] == "invalid_grant"  # refresh tokens rotate

    with panel.db() as db:
        row = db.scalars(select(McpToken)).one()
        assert row.user_id == "1" and row.can_write and row.client_id == client["client_id"] and row.name == "Claude"
        row.expires_at = dt.datetime.now() - dt.timedelta(seconds=1)
        db.commit()
    assert Mcp(http, fresh["access_token"]).http.post(
        "/admin/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Bearer {fresh['access_token']}"}).status_code == 401
    assert "App login (OAuth)" in admin.get("/admin/mcp-tokens").text


def test_read_only_choice_and_scope(panel, http, admin):
    client = register(http)
    tokens = exchange(http, client["client_id"], get_code(admin, client["client_id"], allow_changes=False)).json()
    assert tokens["scope"] == "mcp:read"
    assert len(Mcp(http, tokens["access_token"]).rpc("tools/list")["result"]["tools"]) == 4
    # only mcp:read asked: no write, even if the form says so
    tokens = exchange(http, client["client_id"], get_code(admin, client["client_id"], scope="mcp:read")).json()
    assert tokens["scope"] == "mcp:read"


def test_pkce_and_client_checks(panel, http, admin):
    client = register(http)
    code = get_code(admin, client["client_id"])
    assert exchange(http, client["client_id"], code, verifier="x" * 50).json()["error"] == "invalid_grant"
    assert exchange(http, client["client_id"], code).json()["error"] == "invalid_grant"  # burnt by the bad try
    assert exchange(http, "mcp_nope", "c").status_code == 401

    confidential = register(http, token_endpoint_auth_method="client_secret_post")
    code = get_code(admin, confidential["client_id"])
    assert exchange(http, confidential["client_id"], code).json()["error"] == "invalid_client"
    code = get_code(admin, confidential["client_id"])
    basic = base64.b64encode(f"{confidential['client_id']}:{confidential['client_secret']}".encode()).decode()
    r = http.post("/admin/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK,
                                              "code_verifier": VERIFIER}, headers={"Authorization": f"Basic {basic}"})
    assert r.status_code == 200, r.text


def test_bad_requests(http, admin):
    assert http.post("/admin/oauth/register", json={"redirect_uris": ["http://evil.com/cb"]}).status_code == 400
    assert http.post("/admin/oauth/register", json={"redirect_uris": ["javascript:alert(1)"]}).status_code == 400
    assert http.post("/admin/oauth/register", json={"redirect_uris": ["http://127.0.0.1:3334/cb"],
                                                    "token_endpoint_auth_method": "none"}).status_code == 201
    client = register(http)
    r = admin.client.get(authorize_url("mcp_unknown"), follow_redirects=False)
    assert r.status_code == 400 and "Unknown app" in r.text
    r = admin.client.get(authorize_url(client["client_id"], redirect_uri="https://evil.com/cb"), follow_redirects=False)
    assert r.status_code == 400
    r = admin.client.get(authorize_url(client["client_id"], code_challenge_method="plain"), follow_redirects=False)
    assert r.status_code == 302 and "error=invalid_request" in r.headers["location"]
    r = admin.client.get(authorize_url(client["client_id"], scope="admin"), follow_redirects=False)
    assert "error=invalid_scope" in r.headers["location"]
    assert http.post("/admin/oauth/token", data={"grant_type": "password"}).json()["error"] == "unsupported_grant_type"


def test_login_first_then_deny(panel, http):
    from conftest import PanelClient

    client = register(http)
    browser = PanelClient(http)
    r = browser.client.get(authorize_url(client["client_id"]), follow_redirects=False)
    assert r.headers["location"] == "/admin/mcp-authorize"
    r = browser.client.get("/admin/mcp-authorize", follow_redirects=False)
    assert r.status_code in (302, 303) and "/admin/login" in r.headers["location"]
    browser.get("/admin/login")
    r = browser.client.post("/admin/login?next=/admin/mcp-authorize", data={
        "_token": browser.token, "email": "admin@example.com", "password": "password"}, follow_redirects=False)
    assert r.headers["location"] == "/admin/mcp-authorize"
    browser.get("/admin/mcp-authorize")
    r = browser.post("/admin/_tw/action", {"_tw_host": "page:mcp-authorize", "_tw_scope": "page", "_tw_name": "deny"})
    target = r.headers["HX-Redirect"]
    assert target.startswith(CALLBACK) and "error=access_denied" in target and "state=xyz" in target


@pytest.mark.parametrize("options", [{"oauth": False}])
def test_oauth_off(http):
    assert http.post("/admin/oauth/register", json={"redirect_uris": [CALLBACK]}).status_code in (404, 405)
    r = http.post("/admin/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and "resource_metadata" not in r.headers["www-authenticate"]


def test_panel_at_root(tmp_path):
    from conftest import User
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from tungsten_mcp import McpPlugin

    from tungsten import Auth, Panel

    engine = create_engine(f"sqlite:///{tmp_path / 'x.db'}")
    panel = Panel(path="", session_factory=sessionmaker(engine), secret_key="t", auth=Auth(User),
                  app_url="https://x.example.com")
    panel.plugin(McpPlugin())
    app = FastAPI()
    panel.mount(app)
    http = TestClient(app)
    assert http.get("/.well-known/oauth-authorization-server").json()["issuer"] == "https://x.example.com"
    assert http.get("/.well-known/oauth-protected-resource/mcp").json()["resource"] == "https://x.example.com/mcp"
    r = http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert 'resource_metadata="https://x.example.com/.well-known/oauth-protected-resource/mcp"' in \
        r.headers["www-authenticate"]
