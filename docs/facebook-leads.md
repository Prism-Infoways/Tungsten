---
title: Facebook & Instagram leads
description: Connect your Facebook Page so new leads from Facebook and Instagram lead ads land in Tungsten the moment they are submitted.
---

The `tungsten-meta-leads` plugin brings leads from your Facebook and Instagram lead forms (Instant Forms) into [tungsten-leads](https://github.com/Prism-Infoways/Tungsten/tree/HEAD/plugins/leads). Once it is set up, every new lead arrives by itself, with its answers, a note on the lead's timeline, and the Page and ad it came from.

The same steps are in the panel: open **Facebook & Instagram** and press **Setup guide**. There, your own addresses are filled in and each one has a copy button.

## Install

```bash
pip install tungsten-meta-leads
```

```python
from tungsten_leads import LeadsPlugin
from tungsten_meta_leads import MetaLeadsPlugin

panel = Panel(..., app_url="https://admin.example.com")   # your public https address
panel.plugin(LeadsPlugin())
panel.plugin(MetaLeadsPlugin())
panel.create_tables(engine)
```

## Before you start

- A Facebook Page with a lead form. Instagram lead ads work too when the Instagram account is linked to that Page.
- You manage the Page (full control, or task access with Advertise).
- The panel is online on a public **https** address with a real certificate. Meta cannot reach `localhost`, and it refuses self-signed certificates.

It takes about 15 minutes. Meta changes its screens now and then, so if a name differs a little, pick the closest one.

## 1. Create a Meta app

1. Open [developers.facebook.com/apps](https://developers.facebook.com/apps/creation/). The first time, press **Get started** and confirm your phone and email.
2. Press **Create app**. Type a name (for example "My Business Leads") and your email, then **Next**.
3. Use case: pick **Capture & manage ad leads with Marketing API**, then **Next**.
4. Business: pick your business portfolio (or connect one later), then finish with **Create app**.

## 2. Add two permissions

1. In your app, open **Use cases**. Next to "Capture & manage ad leads with Marketing API" press **Customize**.
2. Find `pages_manage_metadata` and press **Add**. It lets the panel turn on new-lead alerts for your Pages.
3. Find `public_profile` and press **Increase access**. Meta asks for this before going live.

## 3. Copy the app keys

1. Left menu: **App settings**, then **Basic**.
2. Copy the **App ID**. Next to **App secret** press **Show** and copy it.
3. In the panel, paste both in **Meta app keys** on the Facebook & Instagram page and press **Save keys**. The page reloads with Connect Facebook ready.
4. On the same Basic page, fill these and press **Save changes**. Meta needs them to publish the app:
   - **App domains**: your panel's host, for example `admin.example.com`.
   - **Privacy Policy URL**: a page on your website.
   - **User data deletion**: a page that says how people can ask you to delete their data. Your privacy page can say this.
   - A **Category** and an **App icon** (512 × 512).

You can also give the keys in code: `MetaLeadsPlugin(app_id="...", app_secret="...")`.

## 4. Allow the login address

1. Left menu: **Facebook Login for Business**, then **Settings**.
2. In **Valid OAuth Redirect URIs**, paste your panel's address followed by `/meta/callback`, for example `https://admin.example.com/admin/meta/callback`. It must match exactly. The setup page shows yours as **Redirect URI**.
3. Keep **Client OAuth login**, **Web OAuth login** and **Enforce HTTPS** on, then press **Save changes**.

## 5. Publish the app

Left menu: **Publish**. Check the list, then press **Go live**.

Meta sends no leads to an app that is not live, not even test leads. For your own Pages you usually do not need App Review or Business Verification. They are needed when people outside your business connect their Pages to your app.

## 6. Connect Facebook

1. In the panel, press **Connect Facebook** on the Facebook & Instagram page.
2. Continue as yourself. Choose every Page whose leads you want (or all current and future Pages), keep every permission on, and save.
3. You come back to the panel. Your Pages show **Receiving leads**.

The panel saves your Pages and their lead forms, turns on lead alerts for each Page, and registers the webhook in your Meta app. Questions that are not name, email, phone or company become lead fields by themselves.

## 7. Send a test lead

1. Open Meta's [Lead Ads Testing Tool](https://developers.facebook.com/tools/lead-ads-testing). Pick your Page and a form, then press **Create lead**.
2. In a few seconds the lead shows in **Leads**. In the tool, **Track status** shows what Meta did.
3. A form can hold one test lead. Press **Delete lead** in the tool before making another.

## Common problems

**Facebook says "Can't load URL", or shows a redirect_uri error.** The login address is missing or different. Paste it again in step 4, exactly as the setup page shows it, and add the domain in step 3.

**Facebook says "Invalid Scopes", or "This app needs at least one supported permission".** A permission is not added to the app. Do step 2 again, then press Connect Facebook.

**No leads come in, not even test leads.** The app is not live yet. Do step 5, then send a test lead again.

**A Page is missing, or shows "Not receiving".** Press **Reconnect Facebook** and tick every Page. You need full control of the Page, or task access with Advertise.

**Nothing arrives at all.** Someone may have limited *Leads access*. In Meta Business Suite open Settings, Integrations, **Leads access**, pick your Page, then on the CRMs tab press **Assign CRMs** and tick your app. On the People tab, make sure you are listed. Then press **Sync forms and leads** in the panel to fetch the leads you missed. If none of this helps, Meta may want App Review: in your app open **App Review**, **Permissions and features**, and ask for Advanced access to `leads_retrieval`.

**The setup page shows a webhook error.** Meta could not reach your site. It must be public https with a real certificate (Let's Encrypt is fine). You can also set it by hand: in your Meta app open **Use cases**, **Customize**, then **Webhooks** (older apps: Webhooks in the left menu). Pick **Page**, paste the **Webhook callback URL** and **Verify token** from the setup page, press **Verify and save**, then subscribe to **leadgen**.

**Instagram leads do not show.** Instagram lead ads belong to the Facebook Page linked to the Instagram account. Connect that Page and they come in with the rest, marked "on Instagram".

## Options

```python
MetaLeadsPlugin(
    app_id=None,               # or paste it on the setup page
    app_secret=None,
    public_url=None,           # this site's address for Meta, if app_url is not set
    auto_create_fields=True,   # make a lead field for each new form question
    default_status="new",      # status of new leads
    sync_limit=500,            # how many recent leads per form "Sync" reads
)
```
