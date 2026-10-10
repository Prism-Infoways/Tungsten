# What's new in Tungsten

All notable changes to Tungsten (`tungsten-admin`) and its official plugins. Newest first.

## 2026-10-10 · HR, Finance and a faster core

- **New plugin: HR** (`tungsten-hr`). Employees, departments, attendance with check-in, leave with approval, and holidays. Works with biometric machines by push, pull, API or CSV.
- **New plugin: Finance and accounts** (`tungsten-finance` 0.2.0). Double-entry books like Tally, Busy and Zoho Books: invoices, payments, expenses, GST and reports.
- **tungsten-admin 0.1.6**: a faster core, with fewer database queries per page and cheaper table rendering.
- **tungsten-admin 0.1.7**: fixes validation rules inside Repeater fields.
- **Website**: a page for every plugin, this What's new page, clean addresses without `.html`, and SEO, GEO and AEO across the site.

## 2026-10-09 · Help desk, blog and audits

- **New plugin: Help desk** (`tungsten-tickets`). Tickets with replies, internal notes, saved replies, SLA due times, emails and a customer support page.
- **New plugin: Blog** (`tungsten-blog`). A blog built for SEO, GEO and AEO, with a live score in the editor, schema.org data, sitemap, RSS and llms.txt.
- **New plugin: SEO audit** (`tungsten-seo-audit`). Audits your website and gives a score out of 100 with a fix tip for every issue, including AI search checks.
- **New plugin: Security audit** (`tungsten-security-audit`). A security score for your panel, a login log and lockout after wrong passwords.
- **tungsten-admin 0.1.5**: links inside the rich text editor no longer break the editor.
- Plugin updates: `tungsten-leads` 0.1.2, `tungsten-mcp` 0.1.2, `tungsten-meta-leads` 0.1.1 and `tungsten-whatsapp` 0.1.1.

## 2026-10-08 · AI access with MCP

- **New plugin: AI access** (`tungsten-mcp`). An MCP server inside your panel, so Claude and other AI assistants can read and change your data with the same roles and rules.
- Connect with OAuth login: add the address in Claude, log in and press Allow. No token to copy.
- Add your own MCP tools in Python.
- **tungsten-admin 0.1.4**: plugins can mount their own routes with `Plugin.mount`.
- `tungsten-leads` 0.1.1: send an `external_id` and the same lead is never added twice.

## 2026-10-04 · Plugins arrive

- Plugins now ship as their own pip packages.
- **New plugin: Leads** (`tungsten-leads`). A simple CRM with stages, a timeline, follow-ups and lead fields you add without code.
- **New plugin: Facebook and Instagram leads** (`tungsten-meta-leads`). Meta lead ads land in your panel the moment someone fills the form.
- **New plugin: WhatsApp** (`tungsten-whatsapp`). Click-to-chat links, the official Cloud API or WhatsApp Web.
- Step by step setup guides for Facebook leads and WhatsApp, inside the panel.
- **tungsten-admin 0.1.3**: plugin templates, static files and translations; `Panel.of(db)`.
- Fixes: menus cut off inside tables, the filter panel on phones, and the phone sidebar in right-to-left languages.

## 2026-10-03 · First release on PyPI

- **tungsten-admin 0.1.0 to 0.1.2** on PyPI: `pip install tungsten-admin`.
- A new design, the website at tungsten.prisminfoways.com, a demo video and screenshots.

## 2026-10-01 · Tungsten begins

- A Filament-style admin panel for FastAPI: resources, forms, tables, actions, widgets, logins and roles from Python classes.
- Infolists, list tabs, inline editing, two-factor login, async SQLAlchemy engines, a query builder filter, email verification and translations.
