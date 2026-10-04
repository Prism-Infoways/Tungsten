---
title: WhatsApp
description: Send and receive WhatsApp messages with your leads, through Meta's Cloud API, your own number on WhatsApp Web, or plain wa.me links.
---

The `tungsten-whatsapp` plugin adds WhatsApp to [tungsten-leads](https://github.com/Prism-Infoways/Tungsten/tree/HEAD/plugins/leads). Everything sent and received shows on the lead's timeline and in **WhatsApp chats**. New chats can become leads by themselves, and new leads can get a welcome message.

The same steps are in the panel: open **WhatsApp setup** and press **Setup guide**. There, your own addresses are filled in and each one has a copy button.

## Install

```bash
pip install tungsten-whatsapp
```

```python
from tungsten_leads import LeadsPlugin
from tungsten_whatsapp import WhatsAppPlugin

panel = Panel(..., app_url="https://admin.example.com")   # your public https address
panel.plugin(LeadsPlugin())
panel.plugin(WhatsAppPlugin())
panel.create_tables(engine)
```

## Pick how to send

| Way | You need | What you get |
| --- | --- | --- |
| **Links only** | Nothing | The WhatsApp button on a lead opens WhatsApp with the chat ready. You press send there. Nothing is saved in the panel. |
| **Cloud API** (official) | A Meta app and a phone number that is not on the WhatsApp app | Send texts and approved templates from the panel, get replies and delivered and read ticks. Meta charges per message. |
| **WhatsApp Web** (linked phone) | A server with Docker for the free [WAHA](https://waha.devlike.pro) gateway | Send from your own WhatsApp number, linked by QR code, and get replies. Not an official API. |

## Cloud API

### Before you start

- A phone number that is **not** on the WhatsApp app. To use a number that is, delete its WhatsApp account on the phone first (back up chats). A new SIM is easiest.
- The panel online on a public **https** address, so replies can come in.
- A card, or UPI funds in India, for Meta's message charges.

### 1. Create a Meta app

1. Open [developers.facebook.com/apps](https://developers.facebook.com/apps/creation/). The first time, press **Get started** and confirm your phone and email.
2. Press **Create app**, type a name and your email, then **Next**.
3. Use case: pick **Connect with customers through WhatsApp**. Pick your business portfolio (or make one), then **Create app**.

### 2. Add your phone number

1. In the app open **Use cases**, then **Customize** next to WhatsApp, then **API Setup** (older apps: WhatsApp, API Setup).
2. In **From**, press **Add phone number**. Type your business name and category, then your number, and enter the code Meta sends by SMS or call.
3. Pick your number in **From**. Copy its **Phone number ID** and the **WhatsApp Business Account ID** (Meta may call it Messaging account ID).

Adding your number makes a new WhatsApp Business Account for it. Use that account's ID, and pick that account for billing (step 9) and templates, not the test one.

Meta also gives a free test number. It is fine for a first try, but switch to your own number for real use.

### 3. Make a permanent access token

1. Open [Business settings](https://business.facebook.com/latest/settings), then **Users**, **System users**. Press **Add**, give a name, pick role **Admin**.
2. Press **Assign assets**. Give it **Full control** of your app and of your WhatsApp account.
3. Press **Generate token**. Pick your app, expiry **Never**, and tick `whatsapp_business_messaging` and `whatsapp_business_management`. Copy the token right away; Meta shows it once.

Do not use the temporary token from API Setup. It stops working within hours.

### 4. Copy the App secret

In your app open **App settings**, then **Basic**. Next to App secret press **Show** and copy it. The panel uses it to check that messages really come from Meta.

### 5. Fill the setup page

In the panel open **WhatsApp setup**. In **How to send** pick **Cloud API (official)**, paste the Phone number ID, WhatsApp Business Account ID, Access token and App secret, then press **Save changes**. The page reloads with the buttons for the next steps.

### 6. Register your number

Press **More**, then **Register number**, and type a 6-digit PIN. Meta needs this once before your own number can send. If two-step verification is already on for the number, type that PIN. Keep the PIN safe.

### 7. Connect the webhook

1. In your app open **Use cases**, **Customize** next to WhatsApp, then **Configuration** (older apps: WhatsApp, Configuration).
2. Paste the **Callback URL** and **Verify token** from the setup page (the callback is your panel's address followed by `/whatsapp/webhook`), and press **Verify and save**.
3. Under **Webhook fields**, press **Subscribe** next to **messages**.

### 8. Publish the app

In **App settings**, **Basic**, fill the contact email, a Privacy Policy URL and a Terms of Service URL (pages on your website), a category and an icon, then save. Then press **Publish** in the left menu; the list shows anything still missing. Then press **Go live**. Some messages are not sent to apps that are still in development.

### 9. Add a payment method

In [Billing](https://business.facebook.com/latest/billing_hub/payment_methods/), pick your WhatsApp account and add a card. In India you can add funds by UPI instead. Choose with care: Meta does not let you switch between prepaid (UPI) and card later.

### 10. Check and test

1. Press **Check connection**. It checks your number and makes sure Meta sends replies to the panel.
2. From your own phone, send "Hi" to the business number. It shows in **WhatsApp chats**.
3. Press **Send a test** and send a message back to your phone.

### Templates

WhatsApp only lets you send free text within 24 hours of the person's last message. To write first, or later, you need a template that Meta approved. Make one in [WhatsApp Manager](https://business.facebook.com/latest/whatsapp_manager/message_templates) with **Create template**, using number variables like `{{1}}` for the name. When Meta approves it, press **More**, then **Sync templates**. It now shows in the WhatsApp button on leads and in the welcome message settings.

### Common problems

**Error 190, or the token expired.** The temporary token from API Setup was used. Make the permanent one in step 3.

**Error 133010 or 131045, or the number is not registered.** Do step 6, then press Check connection.

**Error 131047, or "re-engagement message".** More than 24 hours passed since the person's last message. Send a template instead.

**Error 132001, or the template does not exist.** The template is not approved yet, or its language is different. Press Sync templates and pick it from the list.

**Error 131042, or a payment problem.** Add a payment method or funds in step 9.

**Verify and save fails in Meta.** The panel must be public https with a real certificate, and the token must match exactly. Save the setup page first, then copy both values again.

**Messages go out, but replies never show.** Publish the app (step 8), check that messages is subscribed (step 7), then press Check connection. If the App secret was reset in Meta, paste the new one.

**A chat from a strange number appeared after Meta's Test button.** Meta's test sends a made-up message. You can delete that chat and lead.

## WhatsApp Web

WhatsApp Web mode is not an official API. It links your own WhatsApp number, like WhatsApp Web on a laptop. WhatsApp may block numbers that send bulk or unwanted messages, so use it to talk with people who expect your messages.

It needs the free WAHA gateway on a Linux server with Docker. A VPS with 2 CPU and 4 GB memory is safe. Shared cPanel hosting cannot run it, but the panel can stay there.

### 1. Install the WAHA gateway

Log in to your server with SSH and install Docker:

```bash
curl -fsSL https://get.docker.com | sh
```

Download WAHA's setup file:

```bash
mkdir waha && cd waha
wget -O docker-compose.yaml https://raw.githubusercontent.com/devlikeapro/waha/refs/heads/core/docker-compose.yaml
touch .env
```

Open `docker-compose.yaml` and change the line `image: devlikeapro/waha-plus` to `image: devlikeapro/waha`. On an ARM server (for example Oracle Ampere or Hetzner CAX) use `image: devlikeapro/waha:arm`. Then make the passwords and the API key, and start it:

```bash
docker compose run --no-deps -v "$(pwd)":/app/env waha init-waha /app/env
docker compose up -d
```

The first command prints **Use this API key in the x-api-key header** and a key under it. Copy that key. It is also saved in the `.env` file.

This setup keeps WAHA private on the server (`127.0.0.1:3000`), keeps your phone linked after restarts, and starts again by itself. More in WAHA's [Docker guide](https://waha.devlike.pro/blog/waha-on-docker/).

### 2. Let the panel reach WAHA

- **Same server as the panel**: the Gateway URL is `http://127.0.0.1:3000`.
- **Another server** (for example the panel on cPanel): point a subdomain such as `waha.yourbusiness.in` at the server, and put Nginx with a free Let's Encrypt certificate in front of port 3000. The Gateway URL is then `https://waha.yourbusiness.in`.
- Never open port 3000 itself to the internet. The API key goes with every call.
- WAHA also calls the panel when a message comes in, at the **Webhook URL** the setup page shows once you save it in step 3 (your panel's address followed by `/whatsapp/web-webhook`), so the panel must be reachable from the WAHA server.

### 3. Fill the setup page

In **How to send** pick **WhatsApp Web (linked phone)**. Type the Gateway URL and the API key, leave the session name as `default`, and press **Save changes**. The page reloads, and the **Link phone** button shows at the top.

### 4. Link your phone

1. Open the setup page on a computer, not on the phone you are linking.
2. Press **Link phone**. On the phone open WhatsApp, then the ⋮ menu (iPhone: Settings), **Linked devices**, **Link a device**, and scan the code.
3. The code renews itself every few seconds, so take your time. Once scanned, the popup says **Linked**.
4. Press **I have scanned it** to save it. The status turns **Linked**.

### 5. Test it

From a different phone, send a message to your WhatsApp number. It shows in **WhatsApp chats**, and becomes a lead if "New chats become leads" is on. Then press **Send a test** to send one back.

### Keep it working

- Open WhatsApp on the main phone at least once every 14 days, or WhatsApp logs out all linked devices.
- A number can have 4 linked devices. If linking fails, remove an old one under Linked devices.
- Messages you type on the phone itself do not show in the panel.
- To stay safe: reply to people who wrote first, keep first messages short and personal, and do not send the same text to many new numbers. If sending to new numbers fails with error 463 or 475, WhatsApp is limiting you for a while. Wait; linking again does not help.

### Common problems

**"Unauthorized" or 401.** The API key is wrong or missing. Find it on the WAHA server with `cd waha && grep WAHA_API_KEY .env`, paste it on the setup page and save.

**"Could not reach" the gateway.** Check the Gateway URL, and that WAHA runs: `cd waha && docker compose ps`. `docker compose logs -f` shows what it does.

**"pull access denied" while installing.** The image line still says `waha-plus`. Change it to `devlikeapro/waha`.

**"env file not found", or "exec format error".** For the first, run `touch .env` in the waha folder, then the setup command again. The second means the server is ARM: use `devlikeapro/waha:arm`.

**The phone must be linked again after every restart.** The sessions folder is missing. Use WAHA's setup file from step 1; it keeps that folder.

**Incoming messages do not show.** WAHA cannot reach the panel. The Webhook URL from the setup page must open from the WAHA server. Messages sent from the linked phone itself are not shown.

## Links only

Pick **Links only** and set the **Country code** (it is added to 10-digit numbers). The WhatsApp button on a lead opens WhatsApp on your computer or phone with the chat ready.

## Options

```python
WhatsAppPlugin(
    public_url=None,   # this site's address for webhooks, if app_url is not set
    welcome=True,      # send the welcome message (when switched on in the panel) to new leads
)
```
