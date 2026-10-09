# tungsten-leads

Leads plugin for [Tungsten](https://tungsten.prisminfoways.com/), the admin panel for FastAPI.

## What you get

- **Leads** list with stages (New, Contacted, Qualified, Proposal sent, Won, Lost), source, owner, deal value and next follow-up.
- Tabs for *My leads*, *Follow-up due*, *New* and *Won*; filters; search; export to CSV or Excel.
- Bulk actions: assign to a user, mark won, mark lost, delete.
- A **timeline** on each lead for notes, calls, emails and messages.
- **Lead fields**: admins add their own form fields (text, number, date, dropdown, checkboxes, yes/no...) from the panel, without code. Values are saved on the lead.
- Dashboard numbers: total, new this week, follow-ups due, won and win rate.
- Optional **website form API**: POST leads to `<panel>/api/leads`.

## Install

```bash
pip install tungsten-leads
```

```python
from tungsten_leads import LeadsPlugin

panel.plugin(LeadsPlugin())
panel.create_tables(engine)   # creates the leads tables too
```

### Options

```python
LeadsPlugin(
    statuses={"new": ("New", "info"), "demo": ("Demo booked", "primary"), "won": ("Won", "success"), "lost": ("Lost", "danger")},
    sources={"manual": "Added by hand", "website": "Website", "walk_in": "Walk-in"},
    capture_token="long-random-text",   # turns on the website form API
    dashboard_widget=True,
)
```

## Website form API

```bash
curl -X POST https://admin.example.com/admin/api/leads \
  -H "X-Leads-Token: long-random-text" -H "Content-Type: application/json" \
  -d '{"name": "Amit", "phone": "+91 98765 43210", "city": "Pune"}'
```

`name`, `email`, `phone`, `company` and `notes` go to the lead itself. Any other key is saved in the lead's extra
fields. Send an `external_id` (the row id in your own site's database) and the same lead is never added twice, so a
form that posts again is safe.

## Use it from your code or other plugins

```python
from tungsten_leads import add_activity, create_lead, find_lead, on_lead_created

lead = create_lead(db, name="Amit", phone="+919876543210", source="meta", external_id="meta-lead-id")
add_activity(db, lead, "Asked about the MBA course", type="call")
db.commit()

@on_lead_created
def welcome(db, lead):
    ...  # send a WhatsApp message, an email...
```

`create_lead` skips a lead whose `external_id` is already saved, so the same Meta lead is never added twice.

### Hooks for other plugins

```python
leads = panel.get_plugin("leads")
leads.on_lead_created("my-plugin.welcome", lambda db, lead: ...)   # only this panel's leads
leads.add_lead_action(lambda: Action("quote").label("Send quote").action(...))   # a button on every lead
leads.add_lead_bulk_action(lambda: BulkAction("tag").label("Tag").action(...))   # a bulk action
```

## More Tungsten plugins

| Package | What it adds | Docs |
| --- | --- | --- |
| [`tungsten-meta-leads`](https://pypi.org/project/tungsten-meta-leads/) | Facebook and Instagram lead form leads, with one-click setup | [Guide](https://tungsten.prisminfoways.com/docs/facebook-leads.html) |
| [`tungsten-whatsapp`](https://pypi.org/project/tungsten-whatsapp/) | WhatsApp for leads: click-to-chat, Cloud API or WhatsApp Web | [Guide](https://tungsten.prisminfoways.com/docs/whatsapp.html) |
| [`tungsten-mcp`](https://pypi.org/project/tungsten-mcp/) | MCP server, so AI assistants like Claude can read and change your data | [Guide](https://tungsten.prisminfoways.com/docs/mcp.html) |
| [`tungsten-tickets`](https://pypi.org/project/tungsten-tickets/) | Help desk: tickets, replies, notes, SLA and a customer support page | [Guide](https://tungsten.prisminfoways.com/docs/tickets.html) |
| [`tungsten-blog`](https://pypi.org/project/tungsten-blog/) | Blog built for SEO, GEO and AEO, with a live score, sitemap and llms.txt | [Guide](https://tungsten.prisminfoways.com/docs/blog.html) |
| [`tungsten-seo-audit`](https://pypi.org/project/tungsten-seo-audit/) | SEO audit of your website: score, fix tips, AI search checks, history | [Guide](https://tungsten.prisminfoways.com/docs/seo-audit.html) |
| [`tungsten-security-audit`](https://pypi.org/project/tungsten-security-audit/) | Security audit with a score and fix tips, plus a login log with lockout | [Guide](https://tungsten.prisminfoways.com/docs/security-audit.html) |

Core package: [`tungsten-admin`](https://pypi.org/project/tungsten-admin/). Website and docs: https://tungsten.prisminfoways.com/
