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

Then open **WhatsApp setup** in the panel.

## Cloud API

1. In your Meta app (developers.facebook.com), add the **WhatsApp** product and a phone number.
2. Make a permanent token: Business settings, System users, add a user, generate a token with `whatsapp_business_messaging` and `whatsapp_business_management`.
3. In WhatsApp setup, pick *Cloud API (official)* and fill in the Phone number ID, the WhatsApp Business Account ID, the token and the App secret.
4. In the Meta app, open WhatsApp, Configuration, Webhook. Paste the Callback URL and Verify token shown on the setup page, then subscribe to **messages**.
5. Press **Sync templates** to use your approved templates.

WhatsApp only lets you send free text within 24 hours of the person's last message. Outside that window, use a template.

## WhatsApp Web

1. Run a WAHA gateway on a server with Docker:
   ```bash
   docker run -d -p 3000:3000 -e WAHA_API_KEY=long-random-text devlikeapro/waha
   ```
2. In WhatsApp setup, pick *WhatsApp Web*, fill in the gateway URL and API key, and save.
3. Press **Link phone**, then scan the QR code on your phone: WhatsApp, Linked devices, Link a device.

WhatsApp Web is not an official API. Message people who expect it and keep bulk sends small, or WhatsApp may block the number. Shared hosting usually can't run Docker, so the gateway needs a VPS (or WAHA's hosted plan).
