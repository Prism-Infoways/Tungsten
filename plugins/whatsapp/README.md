# tungsten-whatsapp

WhatsApp for [Tungsten](https://tungsten.prisminfoways.com/) leads (needs [tungsten-leads](../leads)).

## Three ways to send

| Way | Setup | What you get |
| --- | --- | --- |
| **Links only** | None | The WhatsApp button on a lead opens WhatsApp (app or web) with the chat ready. |
| **Cloud API** (official) | A Meta app with WhatsApp | Send texts and approved templates from the panel, get replies, delivered and read ticks. |
| **WhatsApp Web** (linked phone) | A [WAHA](https://waha.devlike.pro) gateway | Send from your own WhatsApp number, linked by QR code. Get replies. |

Everything sent and received shows on the lead's timeline and in **WhatsApp chats**. New chats can become leads by themselves, and new leads can get a welcome message (for example only leads from Facebook).

## Install

```bash
pip install tungsten-whatsapp
```

```python
from tungsten_leads import LeadsPlugin
from tungsten_whatsapp import WhatsAppPlugin

panel = Panel(..., app_url="https://admin.example.com")
panel.plugin(LeadsPlugin())
panel.plugin(WhatsAppPlugin())
panel.create_tables(engine)
```

Then open **WhatsApp setup** in the panel and press **Setup guide**. It walks through every click for each way, with your own addresses filled in. The full guide, with common problems, is also in [WhatsApp](https://github.com/Prism-Infoways/Tungsten/blob/HEAD/docs/whatsapp.md).

## Cloud API

1. At [developers.facebook.com](https://developers.facebook.com/apps/creation/), create an app with the use case **Connect with customers through WhatsApp**, and add your phone number in *API Setup*.
2. Make a permanent token: Business settings, System users, add an Admin user, give it full control of the app and the WhatsApp account, and generate a token that never expires with `whatsapp_business_messaging` and `whatsapp_business_management`.
3. In WhatsApp setup, pick *Cloud API (official)*, fill in the Phone number ID, the WhatsApp Business Account ID, the token and the App secret, and save.
4. Press **More, Register number** once, with a 6-digit PIN.
5. In the Meta app, open *Use cases, Customize* next to WhatsApp, then *Configuration*. Paste the Callback URL and Verify token shown on the setup page, then subscribe to **messages**.
6. Publish the app, add a payment method, and press **Check connection**.

WhatsApp only lets you send free text within 24 hours of the person's last message. Outside that window, use an approved template (press **More, Sync templates** to load them). Meta charges per message.

## WhatsApp Web

1. On a server with Docker, set up the free [WAHA](https://waha.devlike.pro/blog/waha-on-docker/) gateway with its compose file:
   ```bash
   mkdir waha && cd waha
   wget -O docker-compose.yaml https://raw.githubusercontent.com/devlikeapro/waha/refs/heads/core/docker-compose.yaml
   touch .env
   # change "image: devlikeapro/waha-plus" to "image: devlikeapro/waha" (ARM server: devlikeapro/waha:arm), then:
   docker compose run --no-deps -v "$(pwd)":/app/env waha init-waha /app/env
   docker compose up -d
   ```
   Copy the API key it prints.
2. In WhatsApp setup, pick *WhatsApp Web*, fill in the gateway URL (`http://127.0.0.1:3000` on the same server, else an https address in front of it) and the API key, and save.
3. Press **Link phone**, then scan the QR code on your phone: WhatsApp, Linked devices, Link a device.

WhatsApp Web is not an official API. Message people who expect it and keep bulk sends small, or WhatsApp may block the number. Shared hosting can't run Docker, so the gateway needs a VPS; the panel itself can stay on shared hosting.

## More Tungsten plugins

| Package | What it adds | Docs |
| --- | --- | --- |
| [`tungsten-leads`](https://pypi.org/project/tungsten-leads/) | Leads list, stages, timeline and your own lead form fields | [README](https://github.com/Prism-Infoways/Tungsten/tree/claude/tungsten-admin-panel/plugins/leads) |
| [`tungsten-meta-leads`](https://pypi.org/project/tungsten-meta-leads/) | Facebook and Instagram lead form leads, with one-click setup | [Guide](https://tungsten.prisminfoways.com/docs/facebook-leads.html) |
| [`tungsten-mcp`](https://pypi.org/project/tungsten-mcp/) | MCP server, so AI assistants like Claude can read and change your data | [Guide](https://tungsten.prisminfoways.com/docs/mcp.html) |
| [`tungsten-tickets`](https://pypi.org/project/tungsten-tickets/) | Help desk: tickets, replies, notes, SLA and a customer support page | [Guide](https://tungsten.prisminfoways.com/docs/tickets.html) |
| [`tungsten-blog`](https://pypi.org/project/tungsten-blog/) | Blog built for SEO, GEO and AEO, with a live score, sitemap and llms.txt | [Guide](https://tungsten.prisminfoways.com/docs/blog.html) |
| [`tungsten-seo-audit`](https://pypi.org/project/tungsten-seo-audit/) | SEO audit of your website: score, fix tips, AI search checks, history | [Guide](https://tungsten.prisminfoways.com/docs/seo-audit.html) |
| [`tungsten-security-audit`](https://pypi.org/project/tungsten-security-audit/) | Security audit with a score and fix tips, plus a login log with lockout | [Guide](https://tungsten.prisminfoways.com/docs/security-audit.html) |
| [`tungsten-finance`](https://pypi.org/project/tungsten-finance/) | Accounts like Tally or Zoho Books: GST invoices, bills, ledger, stock, P&L, balance sheet, GSTR-1/3B | [Guide](https://tungsten.prisminfoways.com/docs/finance.html) |

Core package: [`tungsten-admin`](https://pypi.org/project/tungsten-admin/). Website and docs: https://tungsten.prisminfoways.com/
