# tungsten-meta-leads

Facebook and Instagram lead forms for [Tungsten](https://tungsten.prisminfoways.com/). New leads from your Meta lead ads land in [tungsten-leads](../leads) the moment someone submits a form.

## What you get

- **One-click setup**: press *Connect Facebook*, allow access, done. Your pages, their lead forms and the webhook are set up for you.
- Every answer goes to the lead: name, email, phone, company, and your own questions as lead fields (created for you).
- Per form: switch it on or off, choose the starting status and who the leads are assigned to, and change where each answer goes.
- *Sync* reads recent leads from Meta, for leads sent while your site was down. The same lead is never added twice.
- A *Meta lead log* shows every lead Meta sent and what happened to it, with *Try again* for failures.

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

## Setup (once)

Open **Facebook & Instagram** in your panel and press **Setup guide**. It walks through every click, with your own addresses filled in. In short:

1. At [developers.facebook.com](https://developers.facebook.com/apps/creation/), create an app with the use case **Capture & manage ad leads with Marketing API**, and add the `pages_manage_metadata` permission to it.
2. Paste the app's App ID and App secret on the setup page.
3. In the app's *Facebook Login for Business, Settings*, add the **Redirect URI** shown on the setup page (for example `https://admin.example.com/admin/meta/callback`).
4. Publish the app (*Publish, Go live*). Until then Meta only sends leads from people who work on the app.
5. Press **Connect Facebook** and allow every Page and permission.

Your site must be reachable on the internet over https so Meta can send leads to it. You don't need App Review for your own Pages; it is only needed when other businesses connect their Pages to your app. The full guide, with common problems, is in [Facebook & Instagram leads](https://github.com/Prism-Infoways/Tungsten/blob/HEAD/docs/facebook-leads.md).

You can also give the keys in code: `MetaLeadsPlugin(app_id="...", app_secret="...")`.

## Where answers go

Each form has a map from Meta question to lead field. The targets are `name`, `first_name`, `last_name`, `email`, `phone`, `company`, `notes`, or the key of a lead field. Leave a target empty to skip that answer. Standard questions (full name, email, phone, company) are mapped for you.
