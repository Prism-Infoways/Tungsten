# Tungsten plugins

Official plugins for Tungsten. Each folder is its own pip package with its own version.

| Folder | Package | What it adds |
| --- | --- | --- |
| [leads](leads) | `tungsten-leads` | Leads list, stages, timeline and your own lead form fields |
| [meta-leads](meta-leads) | `tungsten-meta-leads` | Facebook and Instagram lead form leads, with one-click setup (needs `tungsten-leads`) |
| [whatsapp](whatsapp) | `tungsten-whatsapp` | WhatsApp for leads: click-to-chat, Cloud API or WhatsApp Web (needs `tungsten-leads`) |
| [mcp](mcp) | `tungsten-mcp` | An MCP server, so AI assistants like Claude can read and change your panel's data |
| [tickets](tickets) | `tungsten-tickets` | Help desk: tickets, replies, internal notes, SLA, saved replies and a customer support page |
| [hr](hr) | `tungsten-hr` | HR: employees, departments, attendance with check-in and biometric machines, leave requests with balances and approval, holidays |
| [security-audit](security-audit) | `tungsten-security-audit` | A security audit with a score and fix tips, plus a login log with lockout |
| [seo-audit](seo-audit) | `tungsten-seo-audit` | SEO audit of your website: score, issues with fix tips, AI search checks, history |
| [finance](finance) | `tungsten-finance` | Finance and accounts like Tally or Zoho Books: GST invoices, bills, double-entry ledger, stock, reports, GSTR-1/3B |
| [blog](blog) | `tungsten-blog` | A blog built for SEO, GEO and AEO, with a live score in the editor, schema.org data, sitemap and llms.txt |
| [environment-indicator](environment-indicator) | `tungsten-environment-indicator` | A Local / Staging / Live badge, colored line and tab title, so nobody works on live by mistake |
| [quick-create](quick-create) | `tungsten-quick-create` | A + New button in the top bar to create any record from any page, in a side panel |
| [dashboards](dashboards) | `tungsten-dashboards` | Users build their own dashboards by drag and drop, with widgets from every plugin; private or shared |

## Working on a plugin

```bash
pip install -e ".[dev]" -e plugins/leads -e plugins/meta-leads -e plugins/whatsapp -e plugins/mcp -e plugins/tickets -e plugins/hr -e plugins/finance -e plugins/security-audit -e plugins/seo-audit -e plugins/blog -e plugins/quick-create -e plugins/environment-indicator -e plugins/dashboards
for p in leads meta-leads whatsapp mcp tickets hr finance security-audit seo-audit blog quick-create environment-indicator dashboards; do pytest plugins/$p/tests || break; done
```

## Releasing a plugin

```bash
cd plugins/leads
python -m build
twine upload dist/*
```
