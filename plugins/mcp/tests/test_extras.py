"""MCP resources and prompts registered next to the tools (issue #70)."""

from __future__ import annotations

import base64

import pytest
from conftest import Product
from sqlalchemy import func, select
from tungsten_mcp import McpPlugin, McpPrompt, McpResource, PromptArgument


def _count(db):
    return f"{db.scalar(select(func.count()).select_from(Product))} products"


DOCS = [
    McpResource("docs://format", "Doc format", "# Format\nA doc has rows.", description="Read first"),
    McpResource("docs://count", "Product count", _count, mime_type="text/plain"),
    McpResource("docs://logo", "Logo", b"\x89PNG", mime_type="image/png"),
    McpResource("docs://secret", "Admins only", "secret", can=lambda user: user.email == "nobody@x.com"),
    McpResource("docs://broken", "Broken", lambda: 1 / 0),
]
PROMPTS = [
    McpPrompt("set-up-company", "Set up the company {name} in {city}.", description="Walks through setup",
              arguments=["name", PromptArgument("city", "Where it is", required=False)]),
    McpPrompt("review", lambda user, focus: [{"role": "user", "content": f"Review for {user.name}: {focus}"},
                                             {"role": "assistant", "content": "On it."}], arguments=["focus"]),
]


@pytest.mark.parametrize("options", [{"documents": DOCS, "prompts": PROMPTS}])
def test_resources(admin_mcp):
    caps = admin_mcp.rpc("initialize")["result"]["capabilities"]
    assert caps == {"tools": {"listChanged": False}, "resources": {"listChanged": False},
                    "prompts": {"listChanged": False}}
    listed = admin_mcp.rpc("resources/list")["result"]["resources"]
    assert [r["uri"] for r in listed] == ["docs://format", "docs://count", "docs://logo", "docs://broken"]
    assert listed[0] == {"uri": "docs://format", "name": "Doc format", "mimeType": "text/markdown",
                         "description": "Read first"}
    read = admin_mcp.rpc("resources/read", {"uri": "docs://format"})["result"]["contents"]
    assert read == [{"uri": "docs://format", "mimeType": "text/markdown", "text": "# Format\nA doc has rows."}]
    assert admin_mcp.rpc("resources/read", {"uri": "docs://count"})["result"]["contents"][0]["text"].endswith(
        "products")
    blob = admin_mcp.rpc("resources/read", {"uri": "docs://logo"})["result"]["contents"][0]["blob"]
    assert base64.b64decode(blob) == b"\x89PNG"
    assert admin_mcp.rpc("resources/read", {"uri": "docs://secret"})["error"]["code"] == -32002
    assert admin_mcp.rpc("resources/read", {"uri": "docs://nope"})["error"]["code"] == -32002
    assert "could not be read" in admin_mcp.rpc("resources/read", {"uri": "docs://broken"})["error"]["message"]


@pytest.mark.parametrize("options", [{"documents": DOCS, "prompts": PROMPTS}])
def test_prompts(admin_mcp):
    listed = admin_mcp.rpc("prompts/list")["result"]["prompts"]
    assert listed[0] == {"name": "set-up-company", "description": "Walks through setup", "arguments": [
        {"name": "name", "required": True}, {"name": "city", "description": "Where it is", "required": False}]}
    got = admin_mcp.rpc("prompts/get", {"name": "set-up-company", "arguments": {"name": "Acme"}})["result"]
    assert got["messages"] == [{"role": "user", "content": {"type": "text", "text": "Set up the company Acme in ."}}]
    err = admin_mcp.rpc("prompts/get", {"name": "set-up-company", "arguments": {}})["error"]
    assert err["code"] == -32602 and "name" in err["message"]
    got = admin_mcp.rpc("prompts/get", {"name": "review", "arguments": {"focus": "prices"}})["result"]
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][0]["content"]["text"].endswith(": prices")
    assert admin_mcp.rpc("prompts/get", {"name": "nope"})["error"]["code"] == -32602


def test_nothing_registered_keeps_the_old_answers(admin_mcp):
    assert admin_mcp.rpc("initialize")["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert admin_mcp.rpc("resources/list")["error"]["code"] == -32601
    assert admin_mcp.rpc("prompts/list")["error"]["code"] == -32601


def test_duplicate_uris_are_refused():
    with pytest.raises(ValueError, match="same uri"):
        McpPlugin(documents=[McpResource("a://x", "A", ""), McpResource("a://x", "B", "")])


def test_path_content_is_read_each_time(tmp_path):
    path = tmp_path / "format.md"
    doc = McpResource("docs://f", "F", path)

    class Ctx:
        db = user = tenant = None

    path.write_text("v1")
    assert doc.read(Ctx())["text"] == "v1"
    path.write_text("v2")
    assert doc.read(Ctx())["text"] == "v2"

