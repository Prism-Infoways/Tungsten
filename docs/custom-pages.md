---
title: Custom pages
description: Add your own pages to the panel, with HTML content, widgets, a settings form and header buttons.
---

Not every screen is a list of records. A custom page is a page in the panel that you fill yourself: a settings form, a reports page full of widgets, or any HTML. It gets the panel layout, the sidebar item and the permission checks for free.

## Your first page

Subclass `Page` and return some HTML from `content()`.

```python
from markupsafe import Markup

from tungsten import Page


class Reports(Page):
    icon = "chart-column"
    navigation_group = "Shop"
    subheading = "Sales and customer reports."

    @classmethod
    def content(cls, ctx):
        return Markup('<div class="tw-card p-6 text-sm">Reports for the current month.</div>')
```

Register it on the panel:

```python
panel.pages([Reports])
```

The page is now at `/admin/reports` and has an item in the sidebar under "Shop".

> [!TIP]
> `tungsten make:page Settings --form` writes a page class with a form for you. See [CLI](cli).

## URL and title

The slug and title come from the class name. `SystemSettings` gets the URL `/admin/system-settings` and the title "System settings".

| Attribute | What it does |
| --- | --- |
| `slug` | The URL part. Default: the class name in kebab case. |
| `title` | The page heading. Default: made from the class name. |
| `subheading` | A short line under the heading. |

> [!NOTE]
> If a page and a resource have the same slug, the resource wins. Pick a different slug for the page.

## Navigation

Pages use the same navigation attributes as resources. See [Navigation](navigation).

| Attribute | What it does |
| --- | --- |
| `icon` | Icon next to the menu item (any Lucide icon name). Default: `"file"`. |
| `navigation_group` | Group heading to put the item under. |
| `navigation_label` | Menu text, if it should differ from the title. |
| `navigation_sort` | Lower numbers come first. Default: `0`. |
| `navigation_parent` | Label of another menu item to nest this one under. |
| `show_in_navigation` | `False` hides the menu item. The URL still works. |
| `navigation_badge()` | Class method returning a badge value. It can ask for `ctx`, `db` or `user`. |
| `navigation_badge_color` | Badge color. Default: `"primary"`. |

```python
class Inbox(Page):
    icon = "inbox"

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(Message).where(Message.read.is_(False))) or None
```

## Page content

There are three ways to fill the page body.

**Return HTML from `content()`.** It receives `ctx`, so you can read the database with `ctx.db` and the user with `ctx.user`. Wrap the HTML in `Markup` so it is not escaped, and escape any user data yourself.

```python
from markupsafe import Markup, escape


class Welcome(Page):
    @classmethod
    def content(cls, ctx):
        return Markup(f"<p class='text-lg'>Hello, {escape(ctx.user.name)}!</p>")
```

**Use a template with `content_template`.** Tungsten renders the template inside the page and passes it `ctx` and `page`. Add your template folder with `Panel(template_dirs=[...])`.

```python
class Help(Page):
    icon = "life-buoy"
    content_template = "admin/help.html"     # templates/admin/help.html

panel = Panel(..., template_dirs=["templates"])
```

```html
<!-- templates/admin/help.html -->
<div class="tw-card p-6">
  <h2 class="text-lg font-semibold">Need help, {{ ctx.user.name }}?</h2>
  <p class="mt-2 text-sm text-gray-500">Write to support@example.com.</p>
</div>
```

**Replace the whole page template with `template`.** The default is `tungsten/pages/page.html`. Your template should extend `tungsten/layout/app.html` and fill the `content` block. It receives `page`, `form`, `title`, `subheading`, `content`, `widgets` and `header_actions`, plus `ctx` and `user`.

> [!NOTE]
> The panel's stylesheet is built from Tungsten's own templates, so it only has the Tailwind classes Tungsten already uses. Common ones (`tw-card`, spacing, text sizes and colors) are safe. For anything else, add your own CSS with a `head.end` [render hook](plugins-and-hooks).

## Widgets on a page

List [widgets](widgets) in `widgets`. They are shown in a grid at the top of the page.

```python
class Reports(Page):
    icon = "chart-column"
    widgets = [RevenueChart, UsersByRole, SalesByCategory]
    widget_columns = 4          # grid columns (1, 2, 3, 4 or 6)
```

Widgets the user may not see (their own `can_view()` check) are left out. A page can show widgets, content and a form together.

## Forms on a page

A page can have one form, for example for store settings. Give it three class methods:

- `form(form)` describes the fields, just like a resource form. See [Forms](forms).
- `mount(ctx)` returns the starting values as a dict.
- `save(ctx, data)` stores the validated values.

```python
from tungsten import Page
from tungsten.forms import Section, Select, TextInput, Toggle


class SystemSettings(Page):
    icon = "settings"
    navigation_group = "Settings"
    save_label = "Save settings"

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            Section("General").schema([
                TextInput("store_name").required(),
                TextInput("support_email").email().required(),
                Select("currency").options({"INR": "Indian Rupee (₹)", "USD": "US Dollar ($)"}).required(),
            ]),
            Section("Notifications").schema([
                Toggle("email_notifications").column_span("full"),
            ]),
        ])

    @classmethod
    def mount(cls, db):
        return load_settings(db)          # a dict like {"store_name": "...", ...}

    @classmethod
    def save(cls, data, db):
        store_settings(db, data)
        db.commit()
```

What happens:

- The form is filled with what `mount()` returns.
- On submit, the values are checked with the field rules. Errors show under each field.
- If the data is valid, `save()` runs, and the user sees a "Saved" toast.
- The button text comes from `save_label` (default: "Save changes").

`mount()` and `save()` get what they ask for: `ctx`, `db` and `user`, plus `data` for `save()`. To send the user somewhere else after saving, call `ctx.redirect(url)` inside `save()`. You can also return a Starlette `Response` from `save()` to send it as is.

Dependent fields (`.live()`) and file uploads work in page forms too.

## Header actions

Add buttons to the top of the page with `header_actions()`. They are normal [actions](actions), so they can confirm, open a modal form or link somewhere.

```python
from tungsten.actions import Action
from tungsten.forms import TextInput


class SystemSettings(Page):
    @classmethod
    def header_actions(cls, ctx):
        return [
            Action("clear_cache").icon("trash").color("gray").requires_confirmation()
            .action(lambda: cache.clear())
            .success_notification_title("Cache cleared"),
            Action("test_email").icon("mail").form([TextInput("to").email().required()])
            .action(lambda data: send_test_mail(data["to"]))
            .success_notification_title("Test email sent"),
        ]
```

After a header action runs, the page reloads.

## Who can open a page

Set `permission` to a permission name. Users without it don't see the menu item and get a "Not allowed" page if they open the URL.

```python
class SystemSettings(Page):
    permission = "page.settings"
```

With [roles and permissions](roles-and-permissions) turned on, the permission appears on the Roles screen as "Open System settings".

For other rules, override `can_access()`:

```python
class SystemSettings(Page):
    @classmethod
    def can_access(cls, ctx):
        return ctx.user is not None and ctx.user.is_admin
```

## The dashboard

The panel home page is also a page: `Dashboard`, a subclass of `Page`. Subclass it to change its widgets, subheading or filters, and pass it with `Panel(dashboard=MyDashboard)`. Its heading greets the user ("Welcome back, Asha!"); override `greeting(ctx)` to change that text. See [Widgets](widgets).

```python
from tungsten import Dashboard


class ShopDashboard(Dashboard):
    subheading = "Your store at a glance."
    widgets = [SalesStats, RevenueChart, LatestOrders]

    @classmethod
    def greeting(cls, ctx):
        return "Store overview"


panel = Panel(..., dashboard=ShopDashboard)
```
