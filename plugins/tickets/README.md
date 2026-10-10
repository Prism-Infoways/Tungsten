# tungsten-tickets

Help desk (ticketing) plugin for [Tungsten](https://tungsten.prisminfoways.com/), the admin panel for FastAPI.

## What you get

- **Tickets** with a number (`TCK-00012`), status, priority, category, agent, tags and the customer's name, email and phone.
- A **conversation** on each ticket: replies to the customer, the customer's messages, **internal notes** only your team sees, and a log of status and agent changes.
- **Reply** box with **saved replies** (canned answers), file attachments and "then set status".
- **SLA**: each priority has hours to resolve (urgent 4, high 8, normal 24, low 72). Late tickets show in red and in the *Overdue* tab.
- Tabs for *Open*, *My tickets*, *Unassigned*, *Overdue*, *Waiting on customer* and *Resolved*; filters; search; export.
- Bulk actions: assign, resolve, close, delete.
- **Categories** (Billing, Bug...) that can send new tickets to one agent.
- Dashboard numbers: open, unassigned, overdue, resolved this week.
- **Support page** for customers at `<panel>/support`: raise a ticket, then follow and answer it from a private link. No login needed.
- **Emails** to the customer when the ticket is received, on every reply and when resolved. New tickets and customer replies go to the agent's notification bell.
- Optional **API**: POST tickets to `<panel>/api/tickets`.
- Hooks so other plugins (WhatsApp, Slack...) can act on new tickets, replies and status changes.

## Install

```bash
pip install tungsten-tickets
```

```python
from tungsten_tickets import TicketsPlugin

panel = Panel(..., app_url="https://admin.example.com", auth=Auth(User, mailer=send_mail))
panel.plugin(TicketsPlugin())
panel.create_tables(engine)   # creates the ticket tables too
```

`mailer` is your function `send_mail(to, subject, body)`. `app_url` makes the links in emails full links.

### Options

```python
TicketsPlugin(
    statuses={"open": ("Open", "info"), ...},          # key: (label, color). "resolved" and "closed" mean done
    priorities={"low": ("Low", "gray"), ...},
    sla_hours={"urgent": 4, "high": 8, "normal": 24, "low": 72},   # None for no due time
    number_prefix="TCK-",
    portal=True, portal_path="support",                # the public support page
    api_token="long-secret",                           # turns on POST <panel>/api/tickets
    email_requester=True,                              # emails to the customer
    notify_agents=True,                                # bell notifications for agents
    mailer=None,                                       # defaults to Auth(mailer=...)
    navigation_group="Help desk",
)
```

## Open tickets from code

```python
from tungsten_tickets import add_reply, create_ticket

ticket = create_ticket(db, subject="Order late", description="Where is order 12?",
                       requester_email="amit@example.com", priority="high", source="email")
add_reply(db, ticket, "It ships today.", user_id="1", status="waiting")
db.commit()
```

## API

```bash
curl -X POST https://admin.example.com/admin/api/tickets \
  -H "X-Tickets-Token: long-secret" -H "Content-Type: application/json" \
  -d '{"subject": "Order late", "message": "Where is order 12?", "name": "Amit", "email": "amit@example.com"}'
```

Answer: `{"id": 1, "number": "TCK-00001", "url": "<customer link>"}`. Send `external_id` to skip duplicates.

## Hooks

```python
desk = panel.get_plugin("tickets")
desk.on_ticket_created("whatsapp", lambda db, ticket: ...)
desk.on_ticket_replied("whatsapp", lambda db, ticket, reply: ...)
desk.on_status_changed("slack", lambda db, ticket, old_status: ...)
```

## Try it

```bash
pip install -e . -e plugins/tickets uvicorn
uvicorn plugins.tickets.example:app --reload
```

Sign in at http://127.0.0.1:8000/admin with admin@example.com / password. The support page is http://127.0.0.1:8000/admin/support.

## More Tungsten plugins

| Package | What it adds | Docs |
| --- | --- | --- |
| [`tungsten-leads`](https://pypi.org/project/tungsten-leads/) | Leads list, stages, timeline and your own lead form fields | [README](https://github.com/Prism-Infoways/Tungsten/tree/claude/tungsten-admin-panel/plugins/leads) |
| [`tungsten-meta-leads`](https://pypi.org/project/tungsten-meta-leads/) | Facebook and Instagram lead form leads, with one-click setup | [Guide](https://tungsten.prisminfoways.com/docs/facebook-leads.html) |
| [`tungsten-whatsapp`](https://pypi.org/project/tungsten-whatsapp/) | WhatsApp for leads: click-to-chat, Cloud API or WhatsApp Web | [Guide](https://tungsten.prisminfoways.com/docs/whatsapp.html) |
| [`tungsten-mcp`](https://pypi.org/project/tungsten-mcp/) | MCP server, so AI assistants like Claude can read and change your data | [Guide](https://tungsten.prisminfoways.com/docs/mcp.html) |
| [`tungsten-blog`](https://pypi.org/project/tungsten-blog/) | Blog built for SEO, GEO and AEO, with a live score, sitemap and llms.txt | [Guide](https://tungsten.prisminfoways.com/docs/blog.html) |
| [`tungsten-seo-audit`](https://pypi.org/project/tungsten-seo-audit/) | SEO audit of your website: score, fix tips, AI search checks, history | [Guide](https://tungsten.prisminfoways.com/docs/seo-audit.html) |
| [`tungsten-security-audit`](https://pypi.org/project/tungsten-security-audit/) | Security audit with a score and fix tips, plus a login log with lockout | [Guide](https://tungsten.prisminfoways.com/docs/security-audit.html) |
| [`tungsten-finance`](https://pypi.org/project/tungsten-finance/) | Finance: invoices with GST, payments, expenses, bank balances and profit reports | [Guide](https://tungsten.prisminfoways.com/docs/finance.html) |

Core package: [`tungsten-admin`](https://pypi.org/project/tungsten-admin/). Website and docs: https://tungsten.prisminfoways.com/
