---
title: Panel configuration
description: Every option you can pass to Panel(...) and every method you can call on a panel.
---

A `Panel` is one admin area mounted into your FastAPI app. You set it up with keyword arguments when you create it, then register resources, pages and widgets with methods.

## A typical panel

```python
from tungsten import Auth, Panel

panel = Panel(
    path="/admin",
    session_factory=SessionLocal,
    secret_key=os.environ["SECRET_KEY"],
    auth=Auth(User),
    brand_name="Acme Shop",
    colors={"primary": "orange"},
    navigation_groups=["Shop", "Catalog", "Settings"],
)
panel.resources([ProductResource, OrderResource, CustomerResource])
panel.pages([Settings])
panel.widgets([StatsWidget, RevenueChart])
panel.rbac()
panel.create_tables()

app = FastAPI()
panel.mount(app)
```

All options are keyword-only and have defaults, so you only pass what you want to change.

## All options

### Core

| Option | Default | What it does |
| --- | --- | --- |
| `id` | `"admin"` | A short name for the panel. It is used in the session cookie name (`tungsten_<id>`). Give each panel its own `id` if you mount more than one. |
| `path` | `"/admin"` | Where the panel is mounted. Use `""` or `"/"` to mount it at the site root. |
| `session_factory` | `None` | A SQLAlchemy `sessionmaker` (or `async_sessionmaker`). Tungsten opens a session for every request. |
| `engine` | `None` | A SQLAlchemy engine. If you pass an engine and no `session_factory`, Tungsten makes the session factory for you. Async engines work too. |
| `secret_key` | random | Signs the session cookie. Always set it: a random key changes on every restart, which signs everyone out. |
| `auth` | no login | An [`Auth`](authentication) object. Without it the panel has no login page. |
| `dashboard` | `Dashboard` | The page shown at the panel root. Pass your own `Dashboard` subclass, or `None` to send users to the first resource they can see instead. See [Widgets](widgets). |

### Branding and look

| Option | Default | What it does |
| --- | --- | --- |
| `brand_name` | `"Tungsten"` | The name in the sidebar, on the login page and in the browser tab title. |
| `brand_logo` | `None` | URL of a logo image. It replaces the default icon and brand name. |
| `brand_logo_dark` | `None` | URL of a logo shown in dark mode instead of `brand_logo`. |
| `brand_tagline` | `None` | A short line shown under the brand on the sign-in pages. |
| `favicon` | Tungsten icon | URL of the browser tab icon. |
| `colors` | orange primary | Brand colors as palette names, hex values or shade maps, e.g. `{"primary": "indigo"}`. |
| `font` | `"Inter"` | A Google Fonts family name. `None` turns off the web font. |
| `dark_mode` | `True` | Shows the light / dark / system switch. `False` keeps the panel light. |
| `default_theme` | `"system"` | The theme before a user picks one: `"light"`, `"dark"` or `"system"`. |
| `login_hero` | built-in text | A dict with `heading` and `text` for the left side of the login page. |
| `sidebar_footer` | brand card | HTML (for example `Markup(...)`) that replaces the card at the bottom of the sidebar. |
| `template_dirs` | `()` | Folders with your own templates, to override Tungsten's. |

All of these are explained with examples in [Theming](theming).

### Behaviour

| Option | Default | What it does |
| --- | --- | --- |
| `spa` | `False` | Move between pages without full page reloads. |
| `unsaved_changes_alerts` | `True` | Warn before leaving a form with unsaved changes. |
| `sidebar_collapsible` | `True` | Desktop users can shrink the sidebar to icons. |
| `global_search` | `True` | Shows the search box in the top bar, the sidebar search button and the Ctrl+K shortcut. See [Navigation](navigation#global-search). |
| `navigation_groups` | `None` | The order of sidebar groups, as names or `NavigationGroup` objects. See [Navigation](navigation#groups). |
| `database_notifications` | `True` | Shows the notification bell. See [Notifications](notifications). |
| `notifications_polling` | `"30s"` | How often the bell checks for new notifications. `None` checks only when a page loads. |

### Data, files and tenants

| Option | Default | What it does |
| --- | --- | --- |
| `storage` | `LocalStorage()` | Where uploaded files go. The default saves under `storage/tungsten` and serves files from `<path>/storage/...`. |
| `tenancy` | none | A `Tenancy(...)` object for teams or companies. See [Multi-tenancy](multi-tenancy). |
| `activity_log` | `False` | Records a row in the `tungsten_activity_log` table each time a record is created or updated through the panel. |

### Languages

| Option | Default | What it does |
| --- | --- | --- |
| `locale` | `"en"` | The default language. |
| `locales` | `[locale]` | Languages users can pick. The language switcher appears when there is more than one. |
| `lang_dirs` | `()` | Folders with your own `<code>.json` translation files. |

See [Translations](translations).

### Security

| Option | Default | What it does |
| --- | --- | --- |
| `https_only_cookies` | `False` | Sends the session cookie only over HTTPS. Turn it on in production. |

See [Security](security).

## Database setup

Pass either a session factory or an engine:

```python
# a session factory you already have
panel = Panel(session_factory=SessionLocal, secret_key="...")

# or just the engine
panel = Panel(engine=create_engine("postgresql+psycopg://..."), secret_key="...")
```

With an async engine, everything else stays the same:

```python
from sqlalchemy.ext.asyncio import create_async_engine

panel = Panel(engine=create_async_engine("postgresql+asyncpg://..."), secret_key="...")
```

See [Async database](async-database) for the details.

## Registering things

These methods add things to the panel. Most return the panel, so you can chain them.

```python
(
    panel.resources([ProductResource, OrderResource])
    .pages([Settings, Reports])
    .widgets([StatsWidget, RevenueChart])
    .rbac()
)
```

| Method | What it does |
| --- | --- |
| `resources([...])` | Registers [resources](resources). Each one gets its pages and a sidebar item. |
| `pages([...])` | Registers [custom pages](custom-pages). |
| `widgets([...])` | Registers [widgets](widgets) for the default dashboard. |
| `rbac(roles_resource=True)` | Turns on [roles and permissions](roles-and-permissions) and adds the **Roles & Permissions** screen. Pass `roles_resource=False` to skip the screen. |
| `plugin(plugin)` | Adds a [plugin](plugins-and-hooks). Its `register()` runs right away. |
| `navigation_items([...])` | Adds custom sidebar links (`NavigationItem`). See [Navigation](navigation#custom-links). |
| `navigation_group(label, icon=None)` | Adds a sidebar group, for example to give it an icon. See [Navigation](navigation#groups). |
| `user_menu_item(label, url, icon=None)` | Adds a link to the user menu. See [Navigation](navigation#user-menu). |
| `render_hook(name, fn)` | Injects HTML at a named spot in the layout. See [Plugins and hooks](plugins-and-hooks). |
| `routes(fn)` | Decorator to add your own routes to the panel app. See below. |

Registering the same resource, page or widget twice has no effect.

### Adding your own routes

`panel.routes` registers a function that receives the panel's FastAPI app (here called `router`) and the panel. Add routes to it like any FastAPI app:

```python
@panel.routes
def shop_api(router, panel):
    @router.get("/api/stats")
    def stats():
        return {"ok": True}
```

This route is served at `/admin/api/stats`. Any path works, even a short one like `/ping`.

> [!WARNING]
> Your routes come before the panel's page and resource routes. A route with the same path as a page or resource (like `/products`) replaces it, so pick paths that don't clash. These routes also do not check who is signed in; add your own checks if needed.

## Setting up the database tables

Tungsten keeps a few tables of its own: roles, role assignments, notifications, password reset tokens, two-factor secrets and the activity log. Their names all start with `tungsten_`.

| Method | What it does |
| --- | --- |
| `create_tables(engine=None)` | Creates Tungsten's tables if they do not exist. Uses the panel's engine when you pass none. |
| `await acreate_tables(engine=None)` | The same, for an async engine inside a running event loop. |

```python
panel.create_tables()   # safe to call on every start
```

It only creates Tungsten's tables, never your own. With an async engine, `create_tables()` works outside a running event loop (for example at import time); inside one, use `await panel.acreate_tables()`.

## Mounting

| Method or property | What it does |
| --- | --- |
| `mount(app)` | Mounts the panel into your FastAPI (or Starlette) app at `path`. |
| `app` | The panel's own FastAPI app. It is built the first time you use it. |

```python
app = FastAPI()
panel.mount(app)
```

The panel app has its own session middleware, CSRF checks and static files, so you do not need to add anything to your main app.

## Helpers

These are handy in scripts, plugins and custom code.

| Method | What it does |
| --- | --- |
| `with_session(fn)` | Runs `fn(db)` with a database session and returns its result. Works with sync and async engines. Call it from normal (non-async) code, such as scripts. |
| `url(*parts, **query)` | Builds a panel URL: `panel.url("products", "create")` gives `/admin/products/create`. Keyword arguments become the query string. |
| `get_resources()` | The registered resources. |
| `get_pages()` | The registered custom pages. |
| `get_widgets()` | The widgets registered with `widgets([...])`. |
| `resource(slug)` | Finds a resource by its URL slug, e.g. `panel.resource("products")`. |
| `resource_for_model(model)` | Finds the resource for a model class. |
| `page(slug)` | Finds a custom page (or the dashboard) by slug. |
| `get_plugin(id)` | Finds a registered plugin by its `id`. |

For example, a script that counts products:

```python
from sqlalchemy import func, select

count = panel.with_session(lambda db: db.scalar(select(func.count()).select_from(Product)))
print(count)
```

## More than one panel

You can mount several panels into one app, for example an admin area for staff and a smaller one for partners. Give each a different `id` and `path`:

```python
admin = Panel(id="admin", path="/admin", session_factory=SessionLocal, secret_key=SECRET, auth=Auth(User))
partner = Panel(id="partner", path="/partner", session_factory=SessionLocal, secret_key=SECRET,
                auth=Auth(User, can_access=lambda user: user.is_partner))

admin.resources([ProductResource, OrderResource]).mount(app)
partner.resources([PartnerOrderResource]).mount(app)
```

Each panel has its own session cookie, so signing in to one does not sign you in to the other.
