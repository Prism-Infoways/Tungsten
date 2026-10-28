"""structuredContent only for objects (#83), stdio, public path, 403, load_user (#84), token screen label (#102)."""

from __future__ import annotations

import io
import json

import pytest
from conftest import Mcp, make_token
from tungsten_mcp import Tools


class TextTools(Tools):
    READ = Tools.READ + ("say", "numbers")
    result_indent = 2

    def say(self, ctx):
        return "Record 5 deleted."

    def numbers(self, ctx):
        return [1, 2]


@pytest.mark.parametrize("options", [{"tools": TextTools}])
def test_strings_and_lists(admin_mcp):
    out = admin_mcp.call("say")
    assert out["content"][0]["text"] == "Record 5 deleted." and "structuredContent" not in out
    out = admin_mcp.call("numbers")
    assert json.loads(out["content"][0]["text"]) == [1, 2] and "structuredContent" not in out
    assert out["content"][0]["text"] == "[\n  1,\n  2\n]"  # result_indent
    assert "structuredContent" in admin_mcp.call("list_resources")


def test_user_the_panel_refuses_gets_403(panel, http):
    panel.auth.can_access = lambda user: user.email != "staff@example.com"
    with panel.db() as db:
        token = make_token(db, 2)
    r = http.post("/admin/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                  headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403 and "WWW-Authenticate" not in r.headers


def test_auth_load_user_and_hook_run(panel, admin_mcp):
    seen = []
    original = type(panel.auth).load_user

    def load_user(self, ctx):
        user = original(self, ctx)
        seen.append(("load_user", user.email))
        return user

    panel.auth.load_user = load_user.__get__(panel.auth)
    panel.get_plugin("mcp").on_authenticated = lambda ctx, user: seen.append(("hook", user.email))
    admin_mcp.rpc("ping")
    assert seen == [("load_user", "admin@example.com"), ("hook", "admin@example.com")]


@pytest.mark.parametrize("options", [{"tokens_label": "Robot keys"}])
def test_invalid_token_names_the_screen(http):
    r = http.post("/admin/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                  headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and "Robot keys" in r.json()["error_description"]


def test_invalid_token_uses_the_menu_label(http):
    r = http.post("/admin/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                  headers={"Authorization": "Bearer nope"})
    assert "AI access (MCP)" in r.json()["error_description"]


@pytest.mark.parametrize("options", [{"public_path": "/mcp/shop"}])
def test_public_path(panel, http):
    with panel.db() as db:
        token = make_token(db, 1)
    r = http.post("/mcp/shop", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                  headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["result"] == {}
    r = http.post("/admin/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                  headers={"Authorization": f"Bearer {token}"})
    assert not r.headers["content-type"].startswith("application/json")  # not served under the panel any more
    r = http.post("/mcp/shop", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    meta_url = r.headers["WWW-Authenticate"].split('resource_metadata="')[1].split('"')[0]
    assert meta_url.endswith("/.well-known/oauth-protected-resource/mcp/shop")
    meta = http.get("/.well-known/oauth-protected-resource/mcp/shop").json()
    assert meta["resource"] == "https://shop.example.com/mcp/shop"


def test_stdio(panel):
    plugin = panel.get_plugin("mcp")
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "not json",
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "list_records", "arguments": {"resource": "products"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "delete_record", "arguments": {"resource": "products", "id": 1}}}),
    ]
    out = io.StringIO()
    plugin.run_stdio(user=1, stdin=io.StringIO("\n".join(lines) + "\n"), stdout=out)
    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [a.get("id") for a in answers] == [1, None, 2, 3]
    assert answers[0]["result"]["serverInfo"]["name"] == "tungsten-mcp"
    assert answers[1]["error"]["code"] == -32700
    assert answers[2]["result"]["structuredContent"]["total"] == 3
    assert "can only read" in answers[3]["result"]["content"][0]["text"]  # can_write is off by default
