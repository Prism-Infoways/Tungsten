# tungsten-quick-create

Quick Create plugin for [Tungsten](https://tungsten.prisminfoways.com/), the admin panel for FastAPI.

A **+ New** button in the top bar. Pick what you want to add (a product, a lead, a ticket, an
employee, an invoice...) and its form opens in a side panel, on top of the page you are on. Save,
and you are still where you were.

## What you get

- A **+ New** button on every page, listing every resource the signed-in user may create.
- Works with **other plugins** out of the box: leads, tickets, HR, finance, blog and your own resources all show up.
- Respects **permissions**: a user only sees what they may create (roles, policies and tenants).
- The form opens in a **side panel** (or a popup) with live fields, uploads and validation, like the normal create page.
- **Create & create another** for adding many records in a row.
- After saving: a toast with an **Open** link to the new record, and any table on the page refreshes.
- Grouped by sidebar group, with a **search box** when the list is long.
- Optional **keyboard shortcut**.
- Safe: a database error or a broken policy shows a message and never breaks the page.

## Install

```bash
pip install tungsten-quick-create
```

```python
from tungsten_quick_create import QuickCreatePlugin

panel.plugin(QuickCreatePlugin())
```

No tables, no settings needed.

### Options

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

### Hide one resource

```python
class AuditLogResource(Resource):
    quick_create = False
```

Resources without a create page (`pages = ("index",)`) never show up.

### Add your own entries (for plugin authors)

Anything that is not a resource form can be a link in the menu:

```python
quick = panel.get_plugin("quick-create")
if quick is not None:
    quick.add_link("event", "Event", "/admin/calendar?new=1", icon="calendar", group="Planning")
    quick.add_link("upload", "Upload file", lambda ctx: ctx.url("media", "upload"), icon="upload",
                   visible=lambda user: user.is_staff)
```

The same key replaces an entry; `quick.remove_link("event")` removes it.

## Try it

```bash
pip install -e . -e plugins/quick-create uvicorn
uvicorn plugins.quick-create.example:app --reload   # from the repo root
```

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.

## License

MIT
