# tungsten-mcp

Let AI assistants like Claude work with your [Tungsten](https://tungsten.prisminfoways.com/) panel, through the [Model Context Protocol](https://modelcontextprotocol.io) (MCP).

Ask things like *"Show the 10 newest orders"*, *"How many products are out of stock?"* or *"Mark order 1042 as shipped"*, and the AI does it with your panel's data.

## What you get

- An MCP server inside your panel, at `/admin/mcp`.
- Tools for every resource: `list_resources`, `describe_resource`, `list_records` (search, filters, sort, pages), `get_record`, and with a token that allows changes, `create_record`, `update_record`, `delete_record`.
- Login with OAuth: in Claude, add the server URL as a custom connector, press Connect, log in to your panel and press Allow. No token to copy.
- An **AI access (MCP)** screen to see and revoke connected apps and tokens, with a **How to connect** guide for Claude, Claude Code, Claude Desktop and other apps.

It is safe by default:

- Each token acts as the user who made it. Their roles, policies and tenancy apply, as in the panel.
- Writes go through the resource's form: the same validation, defaults and hooks, and they show in the activity log.
- Tokens are read-only unless you switch on **Allow changes**. Only a hash of each token is stored.
- Password hashes, tokens, secrets and API keys are never sent.

## Install

```bash
pip install tungsten-mcp
```

```python
from tungsten_mcp import McpPlugin

panel = Panel(..., app_url="https://admin.example.com")
panel.plugin(McpPlugin())
panel.create_tables(engine)
```

Then open **AI access (MCP)** in the panel and press **How to connect**. Needs `tungsten-admin` 0.1.4 or newer.

## Connect

**Claude (web, desktop, phone)**: Settings, Connectors, Add custom connector, paste `https://admin.example.com/admin/mcp`, then Connect. Log in to the panel and press Allow.

**Claude Code** with login: `claude mcp add --transport http tungsten https://admin.example.com/admin/mcp`, then `/mcp` in Claude Code.

Apps without MCP login use a token: press **New token** on the AI access (MCP) screen.

**Claude Code** with a token

```bash
claude mcp add --transport http tungsten https://admin.example.com/admin/mcp --header "Authorization: Bearer YOUR_TOKEN"
```

**Claude Desktop** (Settings, Developer, Edit Config; needs Node.js)

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

**Cursor, VS Code and others**: a Streamable HTTP server with the URL and an `Authorization: Bearer YOUR_TOKEN` header.

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
    oauth=True,                       # apps can connect by logging in (needs a panel with login)
    token_minutes=60,                 # how long an OAuth access token works
)
```

With [multi-tenancy](https://tungsten.prisminfoways.com/docs/multi-tenancy.html), the token's user works in their first tenant. Send an `X-Tenant: <id>` header to pick another.
