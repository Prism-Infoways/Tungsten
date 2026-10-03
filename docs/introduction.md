---
title: Introduction
description: What Tungsten is, who it is for, and what you get out of the box.
---

Tungsten is an admin panel builder for FastAPI, inspired by Filament for Laravel. You describe your database models once in Python, and Tungsten gives you list, create, edit and view pages, with search, filters, actions, dashboards, login and roles.

## What it looks like

Here is a complete resource for a `Product` model. It gives you a searchable, sortable product list, a create page, an edit page and a view page.

```python
from tungsten import Resource
from tungsten.actions import DeleteAction, DeleteBulkAction, EditAction
from tungsten.forms import Select, TextInput, Toggle
from tungsten.tables import SelectFilter, TextColumn


class ProductResource(Resource):
    model = Product
    icon = "package"

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required().max_length(150),
            Select("category_id").relationship("category", "name").searchable(),
            TextInput("price").numeric().prefix("₹"),
            Toggle("is_featured"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").searchable().sortable(),
                TextColumn("category.name").badge(),
                TextColumn("price").money("INR").sortable(),
            ])
            .filters([SelectFilter("category").relationship("category", "name")])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
        )
```

You write no HTML and no JavaScript. The form and the table are plain Python objects built with chained method calls.

## Who it is for

Tungsten is for Python developers who:

- already use (or plan to use) **FastAPI** and **SQLAlchemy 2.0** (SQLModel models work too),
- need an internal tool, back office or customer admin area,
- want it to look good and behave well without building a separate frontend.

If you have used Filament, Django admin or Laravel Nova, the ideas will feel familiar. Tungsten adds the Filament style of building screens: small, chainable components that read like a description of the page.

## Features

### Building screens

| Feature | What you get | Read more |
| --- | --- | --- |
| Resources | List, create, edit and view pages for a model from one class. Soft delete with restore. "Simple" resources that work fully in pop-ups. | [Resources](resources) |
| Relation managers | Manage related records (a customer's orders, a product's tags) on the record page. | [Relation managers](relation-managers) |
| Infolists | Read-only view pages with text, badge, icon, image and key-value entries. | [Infolists](infolists) |
| Custom pages | Your own pages with HTML, widgets, a form, or all three. | [Custom pages](custom-pages) |
| Actions | Buttons, confirm boxes and modal forms, plus ready-made create, edit, delete, restore and replicate actions. | [Actions](actions) |
| Notifications | Toast messages and an in-app notification bell. | [Notifications](notifications) |

### Forms

| Feature | What you get | Read more |
| --- | --- | --- |
| Fields | Text, select, checkbox, toggle, radio, date and time pickers, file upload, rich editor, color picker, tags, repeater, builder, key-value and more. | [Form fields](form-fields) |
| Layouts | Sections, grids, fieldsets, tabs and step-by-step wizards. | [Form layouts](form-layouts) |
| Validation and live fields | Required, length, unique, regex and custom rules. Fields that show, hide or fill other fields as the user types. | [Forms](forms) |

### Tables

| Feature | What you get | Read more |
| --- | --- | --- |
| Columns | Text, badge, image, icon and color columns, plus inline-editable toggle, checkbox, text input and select columns. | [Table columns](table-columns) |
| Filters | Select, true/false, date and custom filters. | [Table filters](table-filters) |
| Query builder | Users build their own AND/OR filter rules. | [Query builder](query-builder) |
| More | List tabs with counts, grouping, totals, drag-to-reorder rows, show/hide columns. | [Table features](table-features) |

### Dashboards

| Feature | What you get | Read more |
| --- | --- | --- |
| Widgets | Stats cards with trends and sparklines, charts, table widgets and progress lists. Dashboard filters passed to every widget. | [Widgets](widgets) |

### Users and access

| Feature | What you get | Read more |
| --- | --- | --- |
| Authentication | Login, sign-up, forgot/reset password, profile page, two-factor login. | [Authentication](authentication) |
| Email verification | Signed links that new users must click before they get in. | [Email verification](email-verification) |
| Roles and permissions | A Roles screen, per-resource permissions, policies or a custom gate. | [Roles and permissions](roles-and-permissions) |
| Security | CSRF checks, signed cookies, rate-limited login, safe uploads. | [Security](security) |

### The panel itself

| Feature | What you get | Read more |
| --- | --- | --- |
| Panel options | Path, brand, auth, storage, languages and more in one `Panel(...)` call. | [Panel configuration](panel-configuration) |
| Navigation | Sidebar groups, icons, badge counts, nested items and ⌘K global search. | [Navigation](navigation) |
| Theming | Brand colors, font, logo, dark mode, SPA mode, collapsible sidebar. | [Theming](theming) |
| Translations | Every screen can be translated. Hindi ships built in. | [Translations](translations) |

### Extras

| Feature | What you get | Read more |
| --- | --- | --- |
| Import and export | CSV and Excel import and export. | [Import and export](import-export) |
| Multi-tenancy | Teams or companies, with records filtered to the current one. | [Multi-tenancy](multi-tenancy) |
| Async database | Works with `create_async_engine` as well as a normal engine. | [Async database](async-database) |
| Plugins and hooks | Bundle features into plugins, inject HTML at named spots. | [Plugins and hooks](plugins-and-hooks) |
| CLI | Generators for resources, pages, widgets and plugins, plus a command to create users. | [CLI](cli) |

## How it works

Tungsten renders every page on the server with **Jinja2** templates. In the browser, **HTMX** swaps parts of the page (a table after a search, a modal form, a widget) without full reloads, and **Alpine.js** handles small bits of state like dropdowns and tabs. Styling uses **Tailwind CSS**. All of these ship inside the package, so nothing loads from a CDN (except the optional Google font). The panel is its own small FastAPI app, which you mount into your app with `panel.mount(app)` at a path such as `/admin`.

```python
from fastapi import FastAPI

app = FastAPI()
panel.mount(app)   # the admin now lives at /admin
```

## Closures get what they ask for

One idea shows up on almost every page of these docs: most options take a plain value **or** a function. When you pass a function, Tungsten looks at its parameter names and passes in only what it asks for.

```python
Select("city").options(lambda get: CITIES[get("state")]).visible(lambda get: bool(get("state")))
TextInput("password").required(lambda operation: operation == "create")
```

Common names are `get`, `set`, `state`, `record`, `operation` (`"create"`, `"edit"` or `"view"`), `user`, `ctx`, `db`, `request`, `tenant`, `data`, `records`, `query` and `model`. Which ones are available depends on where the function is used. A function can also be `async def`; Tungsten awaits it.

## Next steps

- [Installation](installation): install the package and check the requirements.
- [Quick start](quick-start): build a small admin panel from scratch in a few minutes.
- [Demo app](demo-app): run the full shop demo and click around.
