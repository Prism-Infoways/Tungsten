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

This adds **AI access (MCP)** under Settings, and the server at `/admin/mcp`.

## Make a token

1. Open **AI access (MCP)** and press **New token**.
2. Give it a name. Switch on **Allow changes** only if the AI should create, change or delete records.
3. Press **Create token**. The token is shown once, with the connect steps below already filled in for it.

Each token acts as the user who made it: their roles, policies and tenancy apply, as in the panel. Users only see and revoke their own tokens. Only a hash of each token is stored.

## Connect your AI app

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
)
```

Columns whose names contain *password*, *secret*, *token*, *api_key* or *otp* are never sent, whatever the options.

With [multi-tenancy](multi-tenancy), the AI works in the user's first tenant. Send the header `X-Tenant: <id>` to pick another.

## Common problems

**401 Unauthorized.** The token is wrong or revoked, or its user was deleted or switched off. Make a new token.

**The AI says it can't create or change records.** The token is read-only, the plugin has `read_only=True`, or the user's role doesn't allow it. Make a token with *Allow changes*, or give the role the permission.

**A resource is missing.** The user's role can't list it, or it is in `exclude` (or not in `resources`).

**Claude Desktop shows no tools.** Check that Node.js is installed (`npx --version`), and that the URL is the public https address of your panel.
