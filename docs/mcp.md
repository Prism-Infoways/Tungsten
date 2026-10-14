---
title: AI access (MCP)
description: Let Claude and other AI assistants read and change your panel's data through the Model Context Protocol, with tokens, permissions and read-only mode.
---

The `tungsten-mcp` plugin puts an [MCP](https://modelcontextprotocol.io) server inside your panel. Connect Claude Code, Claude Desktop, Cursor or any other MCP app, and ask things like *"Show the 10 newest orders"*, *"How many products are out of stock?"* or *"Mark order 1042 as shipped"*.

## Install

```bash
pip install tungsten-mcp
```

```python
from tungsten_mcp import McpPlugin

panel = Panel(..., app_url="https://admin.example.com")   # your public address
panel.plugin(McpPlugin())
panel.create_tables(engine)
```

This adds **AI access (MCP)** under Settings, and the server at `/admin/mcp`. It needs `tungsten-admin` 0.1.4 or newer.

## Connect with login (OAuth)

Apps that support MCP login, like Claude, need no token. They log in to your panel, like "Sign in with Google":

1. In Claude (web, desktop or phone) open **Settings, Connectors, Add custom connector**.
2. Paste `https://admin.example.com/admin/mcp` and press **Add**, then **Connect**.
3. Your panel's login page opens. Log in, then press **Allow** on the **Connect an AI app** page. Switch on **Allow changes** first if the app should create, change or delete records.

Claude Code works the same way:

```bash
claude mcp add --transport http tungsten https://admin.example.com/admin/mcp
```

Then type `/mcp` in Claude Code and pick **tungsten** to log in.

The app gets an access token that works for an hour, and swaps it for a new one by itself. Each connected app shows on the **AI access (MCP)** screen as *App login (OAuth)*. Revoke it there to disconnect it.

Under the hood this is OAuth 2.1 with PKCE, as the [MCP authorization spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) asks: protected resource metadata, authorization server metadata, dynamic client registration, and refresh tokens that change on each use. The metadata lives at `/.well-known/...` on your site, so mount the panel with `panel.mount(app)`.

> [!NOTE]
> OAuth needs a panel with login (`auth=Auth(...)`). Set `McpPlugin(oauth=False)` to use tokens only, or `allow_registration=False` to stop new apps from connecting.

## Make a token

For apps without MCP login, or scripts.

1. Open **AI access (MCP)** and press **New token**.
2. Give it a name. Switch on **Allow changes** only if the AI should create, change or delete records.
3. Press **Create token**. The token is shown once, with the connect steps below already filled in for it.

Each token acts as the user who made it: their roles, policies and tenancy apply, as in the panel. Users only see and revoke their own tokens. Only a hash of each token is stored.

## Connect with a token

The **How to connect** button shows these steps with your own URL.

### Claude Code

```bash
claude mcp add --transport http tungsten https://admin.example.com/admin/mcp --header "Authorization: Bearer YOUR_TOKEN"
```

### Claude Desktop

Open **Settings, Developer, Edit Config**, add this, save and restart Claude. It needs [Node.js](https://nodejs.org).

```json
{
  "mcpServers": {
    "tungsten": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://admin.example.com/admin/mcp", "--header", "Authorization:${AUTH_HEADER}"],
      "env": {"AUTH_HEADER": "Bearer YOUR_TOKEN"}
    }
  }
}
```

### Other apps

Cursor, VS Code, Windsurf and others: add a **Streamable HTTP** server with your URL and the header `Authorization: Bearer YOUR_TOKEN`.

## The tools

| Tool | What it does |
| --- | --- |
| `list_resources` | The resources this user can see, and whether they may create, update and delete. |
| `describe_resource` | Columns, and the form fields to write with: type, required, allowed options. |
| `list_records` | Search, exact filters (`{"status": "paid"}`), sort (`-created_at`) and pages. Returns the total too. |
| `get_record` | One record by id. |
| `create_record` | Create with the resource's form. *Allow changes* tokens only. |
| `update_record` | Change some fields; the rest keep their value. *Allow changes* tokens only. |
| `delete_record` | Delete, or move to the trash when the resource has one. *Allow changes* tokens only. |

Every record comes with `_id`, `_title` and `_url`, a link to it in the panel.

Writes go through the resource's form, so the same validation (required, unique, options), defaults and hooks run as in the panel, and the changes show in the [activity log](panel-configuration). Invalid values come back to the AI with the form's error messages, so it can fix them and try again.

> [!WARNING]
> A token opens your data like a password does. Keep it out of shared chats and code, and use a read-only token when the AI only needs to look.

## Your own tools

Beside the record tools, a panel can add tools of its own: subclass `Tools`, name them in `READ` or `WRITE`, add them to `definitions()`, and pass the class as `tools=`.

```python
from tungsten_mcp import McpPlugin, Tools

class ShopTools(Tools):
    READ = Tools.READ + ("shop_hours",)

    def definitions(self, ctx, can_write):
        return super().definitions(ctx, can_write) + [
            {"name": "shop_hours", "description": "When the shop is open.",
             "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
        ]

    def shop_hours(self, ctx):
        return {"open": "9 to 5"}

panel.plugin(McpPlugin(tools=ShopTools))
```

A tool named in `WRITE` needs a token with **Allow changes**. Raise `ToolError("...")` for a problem the AI can fix; the message goes back as the tool's answer. Arguments that do not match the method are answered with "Wrong arguments"; any other error inside a tool is logged on the server and the AI is told the tool failed there.

## Resources and prompts

An MCP server can also hand the AI **resources** (documents it reads before calling tools, such as a format guide or a field dictionary) and **prompts** (ready-made workflows the AI app offers, such as "Set up a company"). Pass them as `documents=` and `prompts=`:

```python
from pathlib import Path
from tungsten_mcp import McpPlugin, McpPrompt, McpResource, PromptArgument

panel.plugin(McpPlugin(
    tools=ShopTools,
    documents=[
        McpResource("docs://doc-format", "Doc format", Path("mcp/doc-format.md"),
                    description="Read this before building a template"),
        McpResource("docs://fields", "Field dictionary", lambda db: field_dictionary(db)),
    ],
    prompts=[
        McpPrompt("set-up-company", "Set up the company {name}: create it, then its locations.",
                  description="Walks through a new company",
                  arguments=[PromptArgument("name", "The company's name")]),
    ],
))
```

- A resource's content is text, bytes, a `Path` (read on each request) or a function that can ask for `ctx`, `db`, `user` and `tenant`. Set `mime_type` for anything that is not Markdown; bytes are sent base64-encoded.
- A prompt's text is a template where `{argument}` is replaced, or a function that gets the arguments by name and returns text or a list of `{"role": ..., "content": ...}` messages.
- Both take `can=lambda user: ...` to hide them from users who may not see them.
- The server only says it has resources or prompts when you register some.

## Options

```python
McpPlugin(
    path="/mcp",                      # where the server answers, under the panel
    read_only=False,                  # True: no create, update or delete for any token
    resources=None,                   # only these resources (slugs or classes)
    exclude=["users"],                # leave these out
    hidden_fields=["customers.phone", "notes"],   # never send these columns
    max_limit=100,                    # most records per list_records call
    name="Shop admin",                # the name the AI app shows
    instructions=None,                # your own hints for the AI
    oauth=True,                       # apps can connect by logging in
    allow_registration=True,          # new apps may register themselves
    token_minutes=60,                 # how long an OAuth access token works
    tools=Tools,                      # a Tools subclass with tools of your own
    documents=[],                     # McpResource items the AI can read
    prompts=[],                       # McpPrompt items the AI app offers
)
```

Columns whose names contain *password*, *secret*, *token*, *api_key* or *otp* are never sent, whatever the options.

With [multi-tenancy](multi-tenancy), the AI works in the user's first tenant. Send the header `X-Tenant: <id>` to pick another.

## Common problems

**401 Unauthorized.** The token is wrong, revoked or expired, or its user was deleted or switched off. Make a new token, or connect the app again.

**Claude says it couldn't connect, or the login page doesn't open.** The panel must be on a public https address, and `app_url` must be that address. Behind a proxy, check that `/.well-known/oauth-authorization-server/admin` on your site shows JSON.

**The AI says it can't create or change records.** The token is read-only, the plugin has `read_only=True`, or the user's role doesn't allow it. Make a token with *Allow changes*, or give the role the permission.

**A resource is missing.** The user's role can't list it, or it is in `exclude` (or not in `resources`).

**Claude Desktop shows no tools.** Check that Node.js is installed (`npx --version`), and that the URL is the public https address of your panel.
