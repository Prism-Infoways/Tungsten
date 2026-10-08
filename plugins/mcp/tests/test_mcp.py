from __future__ import annotations

import json
import re
from decimal import Decimal

import pytest
from conftest import Mcp, Product, make_token
from sqlalchemy import select
from tungsten_mcp import McpToken, hash_token

from tungsten.models import ActivityLog

ACTION = "/admin/_tw/action"


def test_initialize_and_list_tools(admin_mcp):
    init = admin_mcp.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                        "clientInfo": {"name": "test", "version": "1"}})["result"]
    assert init["protocolVersion"] == "2025-03-26"
    assert init["capabilities"] == {"tools": {"listChanged": False}}
    assert init["serverInfo"]["name"] == "tungsten-mcp" and "list_resources" in init["instructions"]
    assert admin_mcp.rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"
    tools = {t["name"]: t for t in admin_mcp.rpc("tools/list")["result"]["tools"]}
    assert set(tools) == {"list_resources", "describe_resource", "list_records", "get_record",
                          "create_record", "update_record", "delete_record"}
    assert tools["list_records"]["inputSchema"]["properties"]["resource"]["enum"] == ["products", "categories", "users"]
    assert tools["delete_record"]["annotations"]["destructiveHint"] is True
    assert admin_mcp.rpc("ping")["result"] == {}
    assert admin_mcp.rpc("resources/list")["error"]["code"] == -32601


def test_notifications_get_202(http, admin_mcp):
    r = http.post("/admin/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                  headers={"Authorization": f"Bearer {admin_mcp.token}"})
    assert r.status_code == 202 and r.content == b""
    assert http.get("/admin/mcp").status_code == 405


def test_needs_a_valid_token(http, panel):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    r = http.post("/admin/mcp", json=body)
    assert r.status_code == 401 and "Bearer" in r.headers["www-authenticate"]
    assert http.post("/admin/mcp", json=body, headers={"Authorization": "Bearer nope"}).status_code == 401
    with panel.db() as db:
        token = make_token(db, 99)  # user gone
    assert http.post("/admin/mcp", json=body, headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert http.post("/admin/mcp", content=b"{bad", headers={"Authorization": "Bearer x"}).status_code == 400


def test_list_and_describe(admin_mcp):
    out = admin_mcp.call("list_resources")["structuredContent"]
    products = next(r for r in out["resources"] if r["name"] == "products")
    assert products["label"] == "Products" and products["can"]["create"] and products["trash"]
    assert "mcp-tokens" not in [r["name"] for r in out["resources"]]

    info = admin_mcp.call("describe_resource", resource="products")["structuredContent"]
    columns = {c["name"]: c for c in info["columns"]}
    assert columns["price"]["type"] == "Decimal" and columns["id"]["primary_key"]
    assert "supplier_api_key" not in columns  # secrets never leave the server
    fields = {f["name"]: f for f in info["form_fields"]}
    assert fields["name"]["required"] and fields["status"]["options"] == [
        {"value": "draft", "label": "Draft"}, {"value": "live", "label": "Live"}]
    assert fields["category_id"]["options"] == [{"value": 1, "label": "Shoes"}]

    users = admin_mcp.call("describe_resource", resource="users")["structuredContent"]
    assert "password" not in {c["name"] for c in users["columns"]}

    bad = admin_mcp.call("describe_resource", resource="secrets")
    assert bad["isError"] and "Unknown resource" in bad["content"][0]["text"]


def test_list_records_search_filter_sort_page(admin_mcp):
    out = admin_mcp.call("list_records", resource="products")["structuredContent"]
    assert out["total"] == 3 and [r["name"] for r in out["records"]] == ["Green hat", "Blue shoe", "Red shoe"]
    first = out["records"][2]
    assert first["price"] == "10.50" and first["_title"] == "Red shoe" and first["_id"] == "1"
    assert first["_url"] == "https://shop.example.com/admin/products/1"
    assert "supplier_api_key" not in first and isinstance(first["created_at"], str)

    found = admin_mcp.call("list_records", resource="products", search="shoe")["structuredContent"]
    assert found["total"] == 2
    assert admin_mcp.call("list_records", resource="products", search="GH-")["structuredContent"]["total"] == 1

    live = admin_mcp.call("list_records", resource="products", filters={"status": "live"}, sort="price")
    assert [r["name"] for r in live["structuredContent"]["records"]] == ["Green hat", "Red shoe"]
    some = admin_mcp.call("list_records", resource="products", filters={"id": ["1", 2]}, sort="-name", limit=1,
                          offset=1)["structuredContent"]
    assert some["total"] == 2 and [r["name"] for r in some["records"]] == ["Blue shoe"]
    text = json.loads(admin_mcp.call("list_records", resource="products", limit=1)["content"][0]["text"])
    assert text["limit"] == 1

    assert admin_mcp.call("list_records", resource="products", filters={"supplier_api_key": "k1"})["isError"]
    assert admin_mcp.call("list_records", resource="products", sort="nope")["isError"]
    assert admin_mcp.call("list_records", resource="products", bogus=1)["isError"]


def test_get_record(admin_mcp):
    record = admin_mcp.call("get_record", resource="products", id=2)["structuredContent"]
    assert record["name"] == "Blue shoe" and record["sku"] == "BS-1"
    missing = admin_mcp.call("get_record", resource="products", id=404)
    assert missing["isError"] and "No product with id 404" in missing["content"][0]["text"]


def test_create_update_delete(admin_mcp, panel):
    made = admin_mcp.call("create_record", resource="products",
                          data={"name": "Yellow cap", "sku": "YC-1", "price": 7.25, "category_id": 1})
    assert not made["isError"], made
    record = made["structuredContent"]["record"]
    assert record["status"] == "draft" and record["price"] == "7.25" and record["active"] is True
    assert record["category_id"] == 1

    bad = admin_mcp.call("create_record", resource="products", data={"name": "", "sku": "RS-1", "status": "gone"})
    errors = json.loads(bad["content"][0]["text"])
    assert bad["isError"] and set(errors["errors"]) == {"name", "sku", "status"}
    assert "already been taken" in errors["errors"]["sku"][0]
    unknown = admin_mcp.call("create_record", resource="products", data={"name": "x", "supplier_api_key": "k"})
    assert unknown["isError"] and "Unknown field(s): supplier_api_key" in unknown["content"][0]["text"]

    changed = admin_mcp.call("update_record", resource="products", id=record["_id"],
                             data={"status": "live", "active": False})["structuredContent"]["record"]
    assert changed["status"] == "live" and changed["active"] is False and changed["name"] == "Yellow cap"

    gone = admin_mcp.call("delete_record", resource="products", id=record["_id"])["structuredContent"]
    assert gone == {"deleted": True, "id": record["_id"], "trashed": True}
    assert admin_mcp.call("list_records", resource="products")["structuredContent"]["total"] == 3
    assert admin_mcp.call("update_record", resource="products", id=record["_id"], data={"name": "z"})["isError"]

    with panel.db() as db:
        product = db.get(Product, int(record["_id"]))
        assert product.deleted_at is not None and product.price == Decimal("7.25")
        events = [a.event for a in db.scalars(select(ActivityLog).order_by(ActivityLog.id))]
        assert events == ["created", "updated", "deleted"]


def test_permissions_apply(staff_mcp):
    resources = staff_mcp.call("list_resources")["structuredContent"]["resources"]
    assert [r["name"] for r in resources] == ["products"]
    assert resources[0]["can"] == {"create": False, "update": True, "delete": False}
    assert staff_mcp.call("list_records", resource="users")["isError"]
    denied = staff_mcp.call("create_record", resource="products", data={"name": "x", "sku": "x"})
    assert denied["isError"] and "not allowed" in denied["content"][0]["text"]
    assert staff_mcp.call("delete_record", resource="products", id=1)["isError"]
    assert not staff_mcp.call("update_record", resource="products", id=1, data={"name": "Red boot"})["isError"]


def test_read_only_token(panel, http):
    with panel.db() as db:
        mcp = Mcp(http, make_token(db, 1, can_write=False))
    names = {t["name"] for t in mcp.rpc("tools/list")["result"]["tools"]}
    assert names == {"list_resources", "describe_resource", "list_records", "get_record"}
    out = mcp.call("delete_record", resource="products", id=1)
    assert out["isError"] and "can only read" in out["content"][0]["text"]
    assert "only read" in mcp.rpc("initialize")["result"]["instructions"]


@pytest.mark.parametrize("options", [{"read_only": True, "exclude": ["users"],
                                      "hidden_fields": ["products.sku", "name"], "max_limit": 2}])
def test_plugin_options(admin_mcp):
    names = {t["name"] for t in admin_mcp.rpc("tools/list")["result"]["tools"]}
    assert "create_record" not in names and "update_record" not in names
    assert admin_mcp.call("create_record", resource="products", data={})["isError"]
    resources = [r["name"] for r in admin_mcp.call("list_resources")["structuredContent"]["resources"]]
    assert resources == ["products", "categories"]
    page = admin_mcp.call("list_records", resource="products", limit=50)["structuredContent"]
    assert page["limit"] == 2 and "sku" not in page["records"][0] and "name" not in page["records"][0]
    assert admin_mcp.call("list_records", resource="categories")["structuredContent"]["records"][0].keys() == {
        "_id", "_title", "id", "_url"}


@pytest.mark.parametrize("options", [{"resources": ["categories"], "path": "/ai"}])
def test_only_some_resources(panel, http):
    with panel.db() as db:
        token = make_token(db, 1)
    r = http.post("/admin/ai", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "list_resources", "arguments": {}}},
                  headers={"Authorization": f"Bearer {token}"})
    assert [x["name"] for x in r.json()["result"]["structuredContent"]["resources"]] == ["categories"]


def test_token_screen(admin, panel):
    page = admin.get("/admin/mcp-tokens")
    assert page.status_code == 200 and "AI access (MCP)" in page.text and "No tokens yet" in page.text
    guide = admin.get(f"{ACTION}?_tw_host=resource:mcp-tokens&_tw_scope=page&_tw_name=guide",
                      headers={"HX-Request": "true"})
    assert "https://shop.example.com/admin/mcp" in guide.text and "claude mcp add --transport http" in guide.text
    assert "Add custom connector" in guide.text
    r = admin.post(ACTION, {"_tw_host": "resource:mcp-tokens", "_tw_scope": "page", "_tw_name": "create",
                            "name": "My Claude", "can_write": "1"})
    assert r.status_code == 200 and "Token created" in r.text and "tw-refresh" in r.headers["HX-Trigger"]
    token = re.search(r"tgmcp_[A-Za-z0-9_-]{40,}", r.text).group(0)
    assert f'Authorization: Bearer {token}' in r.text and "tgmcp_" not in r.headers.get("set-cookie", "")
    with panel.db() as db:
        row = db.scalars(select(McpToken)).one()
        assert row.name == "My Claude" and row.can_write and row.user_id == "1"
        assert row.token_hash == hash_token(token) and token not in (row.hint + "x")
    tools = Mcp(admin.client, token).rpc("tools/list")["result"]["tools"]
    assert len(tools) == 7
    with panel.db() as db:
        assert db.scalars(select(McpToken)).one().last_used_at is not None
    assert "My Claude" in admin.get("/admin/mcp-tokens").text
