# Tungsten

**A Filament-style admin panel for FastAPI.** Describe a model once in Python and get list, create, edit and view pages, with search, filters, bulk actions, modals, dashboards, login and roles.

Tungsten renders HTML on the server (Jinja2) and uses HTMX + Alpine.js in the browser. You write no JavaScript. It works with SQLAlchemy 2.0 models (SQLModel models work too).

```python
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

---

## Features

| Area | What you get |
| --- | --- |
| **Resources** | List / create / edit / view pages from one class. Soft delete with restore and force delete. "Simple" resources that work fully in popups. |
| **Infolists** | Read-only view pages with entries (text, badge, icon, image, color, key-value, repeatable) in the same layouts as forms. |
| **Forms** | TextInput, Textarea, Select (searchable, multiple, relationship), CheckboxList, Checkbox, Toggle, ToggleButtons, Radio, DatePicker, DateTimePicker, TimePicker, FileUpload (images, multiple), RichEditor, ColorPicker, TagsInput, Repeater (JSON or related rows), Builder (content blocks), KeyValue, Hidden, Placeholder. |
| **Layouts** | Section (cards, collapsible, aside), Grid, Fieldset, Group, Tabs, Wizard (step-by-step, validates each step). |
| **Validation** | Required, length, min/max, email, URL, regex, unique, "same as", custom rules. Clear messages under each field. |
| **Dependent fields** | `.live()` fields re-render the form on the server: show/hide fields, change options, fill other fields. |
| **Tables** | Text, badge, image, icon, color columns, plus inline-editable toggle, checkbox, text input and select columns. Search (also through relations), sort, filters, list tabs with counts, pagination, row and bulk actions, show/hide columns, grouping, totals, drag-to-reorder rows. |
| **Actions** | Buttons, confirm boxes and modal forms. Ready-made create, edit, view, delete, restore, replicate, attach and detach actions. |
| **Relations** | Relation managers: manage a customer's orders, or attach tags to a product, on the record page. |
| **Widgets** | Stats cards with trends and sparklines, charts (line, bar, pie, doughnut...), table widgets, progress lists. Loaded lazily, optional polling. Dashboard filters (e.g. "Last 30 days") passed to every widget. |
| **Auth & roles** | Login, sign-up, forgot/reset password, profile page, two-factor login (TOTP + recovery codes), role-based permissions with a Roles screen, policies or a custom gate. |
| **Notifications** | Toast messages and an in-app notification bell (stored in the database). |
| **Navigation** | Sidebar groups, icons, badge counts, nested items, ⌘K global search across records and pages. |
| **Theming & UX** | Brand colors (any Tailwind palette or a hex color), logo, dark mode, SPA mode (no full page reloads), unsaved-changes warning, collapsible sidebar, keyboard shortcuts (Ctrl/⌘+S saves). |
| **Extras** | CSV/Excel import and export, custom pages, multi-tenancy (teams/companies), plugins, render hooks, CLI generators. |

---

## Install

```bash
pip install tungsten-admin            # add [excel] for .xlsx import/export
```

## Quick start

```python
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tungsten import Auth, Panel

engine = create_engine("sqlite:///app.db")
SessionLocal = sessionmaker(engine, expire_on_commit=False)

panel = Panel(
    path="/admin",
    session_factory=SessionLocal,
    secret_key="change-me",          # signs the session cookie
    auth=Auth(User),                 # needs email + password (hash) fields
    brand_name="Acme",
    colors={"primary": "orange"},    # or a hex color: "#ec5b1d"
)
panel.resources([ProductResource, OrderResource])
panel.widgets([StatsWidget, RevenueChart])
panel.rbac()                         # optional: roles & permissions
panel.create_tables(engine)          # Tungsten's own tables (roles, notifications...)

app = FastAPI()
panel.mount(app)
```

Create your first user:

```bash
tungsten make:user --panel app.admin:panel --role "Super Admin"
```

Passwords are hashed with PBKDF2-SHA256 (`tungsten.hash_password`). Pass `hasher=` to `Auth` to use your own.

## Try the demo

```bash
git clone … && cd tungsten
pip install -e ".[dev]"
python -m examples.shop.seed
uvicorn examples.shop.app:app --reload
```

Open <http://127.0.0.1:8000/admin> and sign in with **admin@example.com / password**. The demo has users (wizard on create, tabs on edit), products (tabs, images, tags, import/export), orders (repeater with live prices), customers (dependent state → city, orders relation manager), roles, a settings page and a full dashboard.

---

## Guide

### Closures get what they ask for

Almost every option takes a value **or** a function. Tungsten looks at the parameter names and passes what you ask for: `get`, `set`, `state`, `record`, `operation` (`"create"`, `"edit"`, `"view"`), `user`, `ctx`, `db`, `request`, `tenant`, `data`, `records`, `query`, `model`.

```python
Select("city").options(lambda get: CITIES[get("state")]).visible(lambda get: bool(get("state")))
TextInput("password").required(lambda operation: operation == "create")
```

### Resources

```python
class OrderResource(Resource):
    model = Order
    icon = "shopping-cart"              # any Lucide icon name
    navigation_group = "Shop"
    navigation_sort = 3
    record_title_attribute = "number"
    global_search_attributes = ["number", "customer.name"]
    relations = [ItemsRelationManager]
    widgets = [OrderStats]              # shown above the list
    simple = False                      # True = create/edit in popups
    policy = None                       # object with view_any/update/delete(user, record) ...

    @classmethod
    def navigation_badge(cls, db):      # number next to the menu item
        return db.scalar(select(func.count()).where(Order.status == "pending"))

    @classmethod
    def query(cls, ctx):                # scope every page
        return select(Order).where(Order.archived.is_(False))

    # hooks
    @classmethod
    def after_create(cls, record, db, ctx): ...
    @classmethod
    def after_save(cls, record, db): ...
```

Other hooks: `mutate_form_data_before_create`, `before_create`, `mutate_form_data_before_save`, `before_save`, `before_delete`, `after_delete`. Soft deletes turn on by themselves when the model has a `deleted_at` column.

Change the header buttons with `header_actions(cls, ctx, page, record)`.

### Forms

```python
form.columns(3).schema([
    Tabs().column_span(2).tabs([
        Tab("General").schema([
            TextInput("name").required(),
            RichEditor("description").column_span("full"),
            Select("tags").relationship("tags", "name").multiple(),
        ]),
        Tab("Media").icon("image").schema([
            FileUpload("images").image().multiple().max_size(2048).directory("products"),
        ]),
    ]),
    Section("Status").schema([
        Radio("status").options({"draft": "Draft", "published": "Published"}),
        Toggle("is_featured"),
    ]),
])
```

- **Wizard**: `Wizard([Step("Basic").schema([...]), Step("Review").schema([...])]).submit_label("Create")`
- **Repeater**: `Repeater("items").relationship("items", order_column="sort").table().schema([...])`, or leave out `.relationship()` to save a JSON list.
- **Dependent fields**: add `.live()` to the field others depend on. `after_state_updated(lambda state, set: set("slug", slugify(state)))` fills other fields.
- **Saving tricks**: `.dehydrated(False)` (don't save), `.dehydrate_state_using(fn)` (e.g. hash a password), `.save_relationships_using(fn)`, `.format_state_using(fn)`.
- **Rules**: `.rule(lambda value: value != "admin" or "That name is reserved.")`.

### Tables

```python
table.columns([
    TextColumn("name").avatar("photo").description(lambda record: record.email).searchable().sortable(),
    TextColumn("status").badge().colors({"success": "paid", "danger": ["failed", "refunded"]}),
    TextColumn("total").money("INR").summarize(Sum().money("INR")),
    ImageColumn("logo").circular(),
    IconColumn("is_active").boolean(),
    ToggleColumn("is_visible"),
    TextColumn("created_at").since().toggleable(hidden_by_default=True),
])
.filters([
    SelectFilter("status").options(Status).multiple(),
    TernaryFilter("is_active"),
    DateFilter("created_at"),
    Filter("big").label("Over ₹10,000").query(lambda query, model: query.where(model.total > 10000)),
    TrashedFilter(),
])
.groups(["status", "customer.name"])
.actions([EditAction(), ActionGroup([ViewAction(), DeleteAction()])])
.bulk_actions([DeleteBulkAction(), BulkActionGroup([ExportBulkAction()])])
.header_actions([ImportAction(ProductImporter), ExportAction()])
.default_sort("created_at", "desc")
.paginated([10, 25, 50])
.row_index()
.striped()
```

Table state (search, sort, filters, page) is kept in the URL, so you can bookmark and share it.

### Actions

```python
Action("ship").icon("truck").color("info")
    .visible(lambda record: record.status == "paid")
    .requires_confirmation()
    .action(lambda record, db: (setattr(record, "status", "shipped"), db.commit()))
    .success_notification_title("Order shipped")

Action("email").form([TextInput("subject").required(), Textarea("body")])
    .action(lambda record, data: send_mail(record.email, **data))
```

Use them in table rows, bulk (`BulkAction`, gets `records`), table headers, or page headers. Raise `Halt` to keep the popup open.

### Infolists (view pages)

Give a resource an `infolist()` and its view page shows formatted values instead of a disabled form. Entries take every `TextColumn` option:

```python
@classmethod
def infolist(cls, infolist):
    return infolist.columns(3).schema([
        Section("Product").column_span(2).schema([
            TextEntry("name").weight("semibold"),
            TextEntry("category.name").badge(),
            TextEntry("description").html().column_span("full"),
            ImageEntry("images").stacked(),
        ]),
        Section("Pricing").schema([
            TextEntry("price").money("INR"),
            IconEntry("is_featured").boolean(),
            KeyValueEntry("attributes"),
            TextEntry("created_at").datetime().inline_label(),
        ]),
    ])
```

`RepeatableEntry("items").schema([...])` shows each related row (or JSON list item) with its own entries. Relation managers can have an `infolist()` too, used by their View popup.

### More table features

```python
table.tabs([                                   # tabs above the table, with counts
    ListTab("all").badge(),
    ListTab("active").badge(color="success").query(lambda query, model: query.where(model.is_active)),
])
table.reorderable("sort")                      # a "Reorder" button: drag rows, order saved to `sort`
TextInputColumn("stock").integer().configure(lambda field: field.min_value(0))   # edit in the table
SelectColumn("status").options({"draft": "Draft", "published": "Published"})
CheckboxColumn("is_featured")
```

Inline-edited values are checked with the same rules as form fields; a bad value shows an error toast and isn't saved.

### Builder and ToggleButtons

```python
Builder("content").blocks([
    Block("heading").icon("heading").schema([TextInput("text").required()]),
    Block("paragraph").icon("pilcrow").schema([RichEditor("body")]),
    Block("image").icon("image").schema([FileUpload("image").image()]),
])   # saved as [{"type": "heading", "data": {...}}, ...]

ToggleButtons("status").options({"draft": "Draft", "published": "Published"})
    .icons({"draft": "pencil", "published": "circle-check"})
    .colors({"draft": "gray", "published": "success"})
```

### Relation managers

```python
class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def form(cls, form): ...
    @classmethod
    def table(cls, table):
        return table.columns([...]).header_actions([CreateAction()]).actions([EditAction(), DeleteAction()])
```

For many-to-many use `AttachAction()`, `DetachAction()` and `DetachBulkAction()`.

### Widgets

```python
class Stats(StatsOverviewWidget):
    @classmethod
    def stats(cls, db):
        return [Stat("Users", "1,248").icon("users").trend("12%", "up").chart([3, 5, 4, 8, 9])]

class Revenue(ChartWidget):
    heading = "Revenue"
    type = "bar"
    filters = {"12": "Last 12 months", "3": "Last 3 months"}

    @classmethod
    def data(cls, db, filter):
        return {"labels": [...], "datasets": [{"label": "Revenue", "data": [...], "color": "primary"}]}
```

Also `TableWidget` (with `model`, `query()`, `table()`), `ProgressListWidget` and `AccountWidget`. Set `column_span`, `sort`, `lazy` and `polling_interval` on any widget.

**Dashboard filters.** Give your dashboard a `filters_form`; the values show in the header and reach every widget as `filters`:

```python
class MyDashboard(Dashboard):
    @classmethod
    def filters_form(cls, form):
        return form.schema([Select("period").options({"7": "Last 7 days", "30": "Last 30 days"}).default("30")])

class Stats(StatsOverviewWidget):
    @classmethod
    def stats(cls, db, filters):
        days = int(filters["period"])
        ...

Panel(..., dashboard=MyDashboard)
```

### Roles & permissions

`panel.rbac()` adds a **Roles & Permissions** screen. Permissions are named `<resource-slug>.<ability>`: `view_any`, `view`, `create`, `update`, `delete`, `delete_any`, `restore`, `force_delete`… Wildcards work (`products.*`, `*`). Give users roles with `RolesField()` in your user form, `auth.assign_role(db, user, "Admin")`, or the CLI.

You can also use a `policy` on a resource, `Auth(gate=lambda user, permission, record: ...)`, or `Auth(can_access=lambda user: user.is_staff)` to decide who can sign in.

### Sign-up and two-factor login

```python
Auth(User,
     registration=True,              # adds a "Create an account" page
     on_register=lambda user, db: ...,
     two_factor=True,                # users can turn on 2FA from their profile
     two_factor_required=False)      # True forces everyone to set it up
```

Two-factor uses 6-digit codes from any authenticator app (Google Authenticator, Microsoft Authenticator, 1Password…). Users scan a QR code, confirm one code, and get 8 one-time recovery codes. Each code works only once.

### Notifications

```python
Notification("Saved").body("The product was updated.").success().send(ctx)                  # toast
Notification("New order").body("#ORD-12").action("View", url).send_to_database(admins, db)   # bell
```

### Custom pages

```python
class Settings(Page):
    icon = "settings"
    navigation_group = "Settings"
    permission = "page.settings"

    @classmethod
    def form(cls, form): return form.schema([TextInput("site_name").required()])
    @classmethod
    def mount(cls, ctx): return load_settings()
    @classmethod
    def save(cls, ctx, data): store_settings(data)
```

Pages can also return `content()` HTML, use a `content_template`, and show `widgets`.

### Import & export

`ExportAction()` downloads the current table (with its search and filters) as CSV or Excel. `ExportBulkAction()` exports the selected rows. For import, describe the columns:

```python
class ProductImporter(Importer):
    model = Product
    unique_by = "sku"                    # update rows that already exist
    columns = [
        ImportColumn("name").required(),
        ImportColumn("price").numeric(),
        ImportColumn("category").relationship("category", "name"),
    ]
```

Rows that fail are skipped and offered as a "failed rows" CSV download.

### Multi-tenancy

```python
Panel(..., tenancy=Tenancy(Team, ownership="team_id", tenants=lambda user: user.teams))
```

Models with a `team_id` column are filtered to the current team, and new records get it set automatically. Users switch teams from the sidebar.

### Plugins & render hooks

```python
class BlogPlugin(Plugin):
    id = "blog"
    def register(self, panel): panel.resources([PostResource])
    def boot(self, panel): panel.render_hook("sidebar.footer", lambda: Markup("<p>Blog</p>"))

panel.plugin(BlogPlugin())
```

Hook names: `head.end`, `body.start`, `body.end`, `sidebar.nav.start`, `sidebar.nav.end`, `sidebar.footer`, `topbar.start`, `topbar.end`, `content.start`, `content.end`, `user-menu.items`, `auth.login.form.after`, `resource.list.before-table`.

### Layout & UX options

```python
Panel(...,
      spa=True,                     # move between pages without full reloads
      unsaved_changes_alerts=True,  # warn before leaving a changed form (default on)
      sidebar_collapsible=True)     # desktop sidebar can collapse to icons (default on)
```

Save buttons on record pages respond to **Ctrl/⌘+S**. Give any action a shortcut with `.keyboard_shortcut("mod+e")`. In global search, use the arrow keys to move through results.

Override any template by passing `template_dirs=[...]` and putting your own file at the same path (for example `tungsten/components/brand.html`).

### CLI

```bash
tungsten init                                            # admin/panel.py
tungsten make:resource Product -m app.models:Product -g  # -g builds fields/columns from the model
tungsten make:resource Tag --simple
tungsten make:relation-manager Customer orders
tungsten make:page Settings --form
tungsten make:widget Sales --type chart                  # stats, chart, table, progress
tungsten make:plugin Blog
tungsten make:user --panel app.admin:panel --role "Super Admin"
```

---

## Security notes

- Every POST checks a CSRF token. The session cookie is signed, `SameSite=Lax` (set `https_only_cookies=True` in production).
- Login is rate-limited per IP and email.
- Rich text is cleaned to a safe allow-list of tags. Uploads of HTML, SVG and scripts are refused, and stored files are served with `nosniff` and a sandbox CSP.
- CSV exports escape spreadsheet formulas.

## Development

```bash
pip install -e ".[dev]"
pytest                       # 75 tests

# rebuild CSS/JS assets after changing templates or classes
cd frontend && npm install && npm run build
```

The built assets (Tailwind CSS, HTMX, Alpine.js, Chart.js, Trix, Tom Select, SortableJS, a QR code generator and Lucide icons) ship inside the package. Nothing loads from a CDN, except the optional Google font (`Panel(font=None)` turns it off).

## Roadmap

- Async SQLAlchemy sessions
- Advanced query-builder filter
- Email verification and impersonation
- More languages (translations)

## License

MIT
