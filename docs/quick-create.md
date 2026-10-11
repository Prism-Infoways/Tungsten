---
title: Quick Create
description: Add a "+ New" button to the top bar of your FastAPI admin panel, so users can create any record from any page in a side panel, with permissions, validation and other plugins built in.
---

The `tungsten-quick-create` plugin adds a **+ New** button to the top bar. It lists everything the signed-in user may create. Pick one, and its create form opens in a side panel on top of the page you are on. Save, and you stay where you were.

## Install

```bash
pip install tungsten-quick-create
```

```python
from tungsten_quick_create import QuickCreatePlugin

panel.plugin(QuickCreatePlugin())
```

There are no tables to create and nothing else to set up. It needs `tungsten-admin` 0.1.7 or newer.

## What shows in the menu

Every resource that has a create page or a create form, from your own code and from other plugins: Leads, Tickets, Employees, Leave requests, Invoices, Bills, Blog posts and so on. Entries are grouped like the sidebar.

A user only sees what they may create. The plugin asks the resource's policy, the roles from `panel.rbac()` and the current tenant, the same checks the normal create page uses. A user also needs "view list" on the resource, because live form fields talk to it.

These never show up:

- resources without a create page, like `pages = ("index",)` or `("index", "view")`
- resources with `quick_create = False`

```python
class AuditLogResource(Resource):
    model = AuditLog
    quick_create = False
```

When the menu would be empty, the button is not shown at all.

## The form

The form is the resource's own form, so fields, layout, live updates, file uploads, validation and the `before_create` / `after_create` hooks all work the same.

- **Create** saves, closes the panel and shows a toast with an **Open** link to the new record.
- **Create & create another** saves and opens an empty form again.
- Any table on the page behind refreshes by itself, so the new record shows up at once.
- If a field is wrong, the panel stays open with the message under the field and what you typed kept.
- If saving fails (for example a duplicate in the database), you get a "Not saved" message and the form stays open. The error is logged.
- With the [Environment indicator](environment-indicator) plugin on Live, the form says "You are on Live. This record goes into real data."

## Options

```python
QuickCreatePlugin(
    include=None,             # only these resources (classes or slugs), in this order
    exclude=(),               # hide these resources (classes or slugs)
    label="New",              # "" shows just the + icon
    icon="plus",
    slide_over=True,          # False: a centred popup
    width="4xl",              # sm, md, lg, xl, 2xl, 3xl, 4xl, 5xl
    create_another=True,      # the "Create & create another" button
    open_after_create=False,  # True: go to the new record after saving
    group=True,               # split the menu by sidebar group
    search_from=8,            # show a search box once the menu has this many entries
    shortcut=None,            # e.g. "mod+shift+n" (mod is Ctrl, or Cmd on a Mac)
)
```

Examples:

```python
# just three forms, in this order
QuickCreatePlugin(include=["leads", "tickets", "invoices"])

# everything except two
QuickCreatePlugin(exclude=[LedgerAccountResource, "tags"])

# icon only, popup, and a keyboard shortcut
QuickCreatePlugin(label="", slide_over=False, shortcut="mod+shift+n")
```

With a long menu, a search box appears at the top. Type to filter and press Enter to open the first match.

## Add your own entries

Plugins and apps can add entries that are plain links, for things that are not a resource form (a calendar event, a file upload, a report):

```python
quick = panel.get_plugin("quick-create")
if quick is not None:
    quick.add_link("event", "Event", "/admin/calendar?new=1", icon="calendar", group="Planning")
    quick.add_link("upload", "Upload file", lambda ctx: ctx.url("media", "upload"), icon="upload",
                   visible=lambda user: user.is_staff)
```

- `url` is a string or a function that gets `ctx` and `user`.
- `visible` is `True`, `False` or a function that gets `ctx` and `user`.
- `group` puts the entry under a heading; `sort` orders it.
- The same key replaces an entry, and `quick.remove_link("event")` removes it.

A link whose function fails is left out and logged; the rest of the page keeps working.

## App shortcuts

With the [PWA plugin](pwa) (`tungsten-pwa`), the installed app gets *New ...* shortcuts for the first four resources that have a create page, plus links added with a plain string URL. A long press on the app icon opens them. Change the number with `QuickCreatePlugin.pwa_shortcut_limit`.

## Questions

**Does it work with my own resources?**
Yes. Any resource with a create page or create form shows up, with no extra code.

**Do users see forms they are not allowed to use?**
No. Each entry is checked against the user's permissions, and the server checks again when the form opens and when it is saved.

**Does it need its own database tables?**
No. It saves through each resource's normal create code.

**Can I put it somewhere other than the top bar?**
The button uses the `topbar.end` render hook. To build your own button, open `<panel>/_quick-create/<resource slug>` into `#tw-modal` with HTMX.
