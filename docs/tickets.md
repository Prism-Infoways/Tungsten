---
title: Help desk (tickets)
description: Add a ticketing desk to your panel with replies, internal notes, saved replies, SLA due times, a customer support page, emails and an API.
---

The `tungsten-tickets` plugin turns your panel into a help desk. Customers raise tickets from a support page, by API or through your team. Agents answer them in the panel, and customers get the answers by email and on their own ticket page.

## Install

```bash
pip install tungsten-tickets
```

```python
from tungsten_tickets import TicketsPlugin

panel = Panel(..., app_url="https://admin.example.com", auth=Auth(User, mailer=send_mail))
panel.plugin(TicketsPlugin())
panel.create_tables(engine)
```

This adds a **Help desk** menu with **Tickets**, **Ticket categories** and **Saved replies**, and dashboard numbers. It needs `tungsten-admin` 0.1.4 or newer.

`mailer` is your own `send_mail(to, subject, body)` function (SMTP, SES, Zoho...). Without it, emails are printed to the console. `app_url` makes the links in emails full links.

## Tickets

Each ticket has a number like `TCK-00012`, a subject, status, priority, category, agent, tags and the customer's name, email and phone.

- **Statuses**: Open, In progress, Waiting on customer, Resolved, Closed.
- **Priorities**: Low, Normal, High, Urgent.
- **Tabs**: Open, My tickets, Unassigned, Overdue, Waiting on customer, Resolved, All.
- **Bulk actions**: assign to an agent, resolve, close, export, delete.

Open a ticket to see the **conversation**: the customer's messages, your replies, internal notes, and a log of status and agent changes.

- **Reply** sends your message to the customer by email and shows it on their ticket page. Pick a **saved reply** to fill the message, add files, and choose the status to set next (usually *Waiting on customer*).
- **Internal note** is only for your team. The customer never sees it.
- **Resolve** marks the ticket resolved and emails the customer. If they reply, it opens again.
- **Assign to me** takes an unassigned ticket.

## SLA (due times)

Each priority has hours to resolve a ticket. A new ticket gets its **Due by** time from its priority. Late tickets show in red and in the **Overdue** tab.

```python
TicketsPlugin(sla_hours={"urgent": 2, "high": 8, "normal": 24, "low": None})   # None: no due time
```

You can change **Due by** on any ticket by hand.

## Categories

Add categories like Billing, Technical or Sales under **Ticket categories**. Pick an agent in **Give new tickets to**, and new tickets of that category go to them. Switch off **Show on the support page** to keep a category for your team only.

## Support page for customers

Customers raise tickets at `/admin/support` without logging in. They give their name, email, topic, subject and message. After sending, they land on their ticket page, and they get an email with its private link. On that page they see your replies (never internal notes) and can answer.

- A customer reply opens a waiting or resolved ticket again and alerts the agent.
- A hidden field stops simple bots, and one browser can raise 5 tickets an hour.

Turn it off with `TicketsPlugin(portal=False)`, or move it with `portal_path="help"`.

## Notifications

- **Customer emails**: ticket received, every reply, ticket resolved. Turn off with `email_requester=False`.
- **Agent bell**: a new ticket for them, a ticket assigned to them, a customer reply. Turn off with `notify_agents=False`.

## API

Let your website, app or email parser open tickets:

```python
TicketsPlugin(api_token="long-secret")
```

```bash
curl -X POST https://admin.example.com/admin/api/tickets \
  -H "X-Tickets-Token: long-secret" -H "Content-Type: application/json" \
  -d '{"subject": "Order late", "message": "Where is order 12?", "name": "Amit", "email": "amit@example.com", "priority": "high"}'
```

The answer has the ticket's `id`, `number` and the customer's `url`. Optional fields: `phone`, `category` (its name), `priority`, `source` and `external_id` (the same id twice gives the same ticket).

## From your own code

```python
from tungsten_tickets import add_reply, create_ticket, set_status

ticket = create_ticket(db, subject="Can't log in", requester_email="amit@example.com", source="email")
add_reply(db, ticket, "Please try the reset link.", user_id="1", status="waiting")
add_reply(db, ticket, "Customer is on the old app", internal=True)
set_status(db, ticket, "resolved")
db.commit()
```

## Hooks for other plugins

```python
desk = panel.get_plugin("tickets")
desk.on_ticket_created("whatsapp", lambda db, ticket: send_whatsapp(ticket.requester_phone, ...))
desk.on_ticket_replied("slack", lambda db, ticket, reply: ...)        # reply.kind: reply, customer, note
desk.on_status_changed("slack", lambda db, ticket, old_status: ...)
```

## Change the lists

```python
TicketsPlugin(
    statuses={"open": ("Open", "info"), "doing": ("Doing", "primary"), "waiting": ("Waiting", "warning"),
              "resolved": ("Resolved", "success"), "closed": ("Closed", "gray")},
    priorities={"normal": ("Normal", "info"), "urgent": ("Urgent", "danger")},
    sla_hours={"normal": 48, "urgent": 4},
    number_prefix="SUP-",
    navigation_group="Support",
)
```

> [!NOTE]
> Keep `open`, `waiting`, `resolved` and `closed` among your statuses: replies and the support page use them.

With the [MCP plugin](mcp.html) installed, AI assistants like Claude can read and answer tickets too.
