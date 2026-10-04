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

1. Go to [developers.facebook.com](https://developers.facebook.com/apps), create an app of type **Business**, and add the **Facebook Login for Business** and **Webhooks** products.
2. In *Facebook Login, Settings*, add `https://admin.example.com/admin/meta/callback` as a valid OAuth redirect URI.
3. Open **Facebook & Instagram** in your panel, paste the App ID and App secret, and press **Connect Facebook**.

Your site must be reachable on the internet over https so Meta can send leads to it. While the Meta app is in development mode, only people with a role on the app can connect. For live use, Meta must approve the `leads_retrieval`, `pages_manage_ads`, `pages_manage_metadata`, `pages_read_engagement` and `pages_show_list` permissions (App Review).

You can also give the keys in code: `MetaLeadsPlugin(app_id="...", app_secret="...")`.

## Where answers go

Each form has a map from Meta question to lead field. The targets are `name`, `first_name`, `last_name`, `email`, `phone`, `company`, `notes`, or the key of a lead field. Leave a target empty to skip that answer. Standard questions (full name, email, phone, company) are mapped for you.
