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

## Your own tools

Beside the record tools, a panel can add tools of its own: subclass `Tools`, name them in `READ` or
`WRITE`, add them to `definitions()`, and pass the class as `tools=`.

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

A tool named in `WRITE` needs a token with **Allow changes**. Raise `ToolError("...")` for a problem
the AI can fix; the message goes back as the tool's answer.

## A panel under a sub-path

Apps also look for the metadata at the site root (`/.well-known/oauth-protected-resource/...`). When the web
server gives your app only the panel's path — a cPanel Python app with base URI `/admin`, say — those root
addresses answer from the site next to it, and an app that builds them itself cannot log in ("couldn't
register"). Send them on in the site's `.htaccess`:

```apache
RewriteEngine On
RewriteRule ^\.well-known/oauth-protected-resource/admin/mcp$ /admin/.well-known/oauth-protected-resource/mcp [R=302,L]
RewriteRule ^\.well-known/oauth-authorization-server/admin$ /admin/.well-known/oauth-authorization-server [R=302,L]
RewriteRule ^\.well-known/openid-configuration/admin$ /admin/.well-known/openid-configuration [R=302,L]
RewriteRule ^\.well-known/oauth-protected-resource$ /admin/.well-known/oauth-protected-resource [L]
RewriteRule ^\.well-known/oauth-authorization-server$ /admin/.well-known/oauth-authorization-server [L]
RewriteRule ^\.well-known/openid-configuration$ /admin/.well-known/openid-configuration [L]
```

(On LiteSpeed an internal rewrite of the addresses that carry the panel path came back 404 from the app, so
those three are sent on with a redirect, which metadata readers follow.)

With [multi-tenancy](https://tungsten.prisminfoways.com/docs/multi-tenancy.html), the token's user works in their first tenant. Send an `X-Tenant: <id>` header to pick another.

## More Tungsten plugins

| Package | What it adds | Docs |
| --- | --- | --- |
| [`tungsten-leads`](https://pypi.org/project/tungsten-leads/) | Leads list, stages, timeline and your own lead form fields | [README](https://github.com/Prism-Infoways/Tungsten/tree/claude/tungsten-admin-panel/plugins/leads) |
| [`tungsten-meta-leads`](https://pypi.org/project/tungsten-meta-leads/) | Facebook and Instagram lead form leads, with one-click setup | [Guide](https://tungsten.prisminfoways.com/docs/facebook-leads.html) |
| [`tungsten-whatsapp`](https://pypi.org/project/tungsten-whatsapp/) | WhatsApp for leads: click-to-chat, Cloud API or WhatsApp Web | [Guide](https://tungsten.prisminfoways.com/docs/whatsapp.html) |
| [`tungsten-tickets`](https://pypi.org/project/tungsten-tickets/) | Help desk: tickets, replies, notes, SLA and a customer support page | [Guide](https://tungsten.prisminfoways.com/docs/tickets.html) |
| [`tungsten-blog`](https://pypi.org/project/tungsten-blog/) | Blog built for SEO, GEO and AEO, with a live score, sitemap and llms.txt | [Guide](https://tungsten.prisminfoways.com/docs/blog.html) |
| [`tungsten-seo-audit`](https://pypi.org/project/tungsten-seo-audit/) | SEO audit of your website: score, fix tips, AI search checks, history | [Guide](https://tungsten.prisminfoways.com/docs/seo-audit.html) |
| [`tungsten-security-audit`](https://pypi.org/project/tungsten-security-audit/) | Security audit with a score and fix tips, plus a login log with lockout | [Guide](https://tungsten.prisminfoways.com/docs/security-audit.html) |
| [`tungsten-finance`](https://pypi.org/project/tungsten-finance/) | Finance: invoices with GST, payments, expenses, bank balances and profit reports | [Guide](https://tungsten.prisminfoways.com/docs/finance.html) |

Core package: [`tungsten-admin`](https://pypi.org/project/tungsten-admin/). Website and docs: https://tungsten.prisminfoways.com/
