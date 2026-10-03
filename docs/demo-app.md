---
title: Demo app
description: Run the shop demo that ships with Tungsten and see every major feature in a real-looking admin panel.
---

The repository includes a full demo: an online shop admin with users, products, orders, customers, a blog, roles, custom pages and a dashboard. It is the fastest way to see what Tungsten can do, and its code is a good place to copy patterns from.

## Run the demo

The demo lives in `examples/shop` in the repository, so you run it from a clone:

```bash
git clone https://github.com/Prism-Infoways/Tungsten.git
cd Tungsten
pip install -e ".[dev]"
python -m examples.shop.seed
uvicorn examples.shop.app:app --reload
```

What each step does:

1. `pip install -e ".[dev]"` installs Tungsten from the clone, plus Uvicorn, openpyxl (Excel files) and aiosqlite (async SQLite).
2. `python -m examples.shop.seed` creates `shop.db` (SQLite) in the current folder and fills it with demo data.
3. `uvicorn examples.shop.app:app --reload` starts the server.

Open <http://127.0.0.1:8000/admin> (the site root `/` redirects there) and sign in with:

- **Email:** `admin@example.com`
- **Password:** `password`

This user has the **Super Admin** role, so it can see everything.

> [!NOTE]
> Running the seed script again deletes all data in `shop.db` and starts fresh. Uploaded files are kept in `storage/tungsten`, and the settings page saves to `storage/settings.json`.

### Try it on an async engine

The same demo can run on an async SQLAlchemy engine. Seed the database first, then start the app with an async database URL:

```bash
python -m examples.shop.seed
DATABASE_URL=sqlite+aiosqlite:///shop.db uvicorn examples.shop.app:app --reload
```

Everything works the same way. See [Async database](async-database) for how this works.

### Settings you can change

The demo reads two environment variables:

| Variable | Default | What it does |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///shop.db` | The database to use. An `+aiosqlite` URL switches to an async engine. |
| `SECRET_KEY` | `dev-secret-change-me` | Signs the session cookie. |

## What to look at

### Dashboard

The home page is a custom dashboard (`ShopDashboard`) with a **period picker** ("Last 7 days", "Last 30 days"...) in the header. Every widget reads the chosen period. It shows:

- stats cards with trends and small sparkline charts,
- a revenue line chart,
- recent orders and top products as table widgets,
- a users-by-role chart,
- sales by category as a progress list.

See [Widgets](widgets).

### Users

- **Create** uses a four-step **wizard**: basic details, roles, extra details, and a review step that sums up what you typed.
- **Edit** uses **tabs** with sections, a roles picker and a key-value field for preferences.
- The list has an avatar column, list tabs (All / Active / Inactive) with counts, filters, custom bulk actions (Activate, Deactivate) and export.

### Products

Products show most of the table and form features:

- a form with **tabs**, image uploads, tags, a rich text editor and a color picker,
- a **query builder** filter: click **Custom filters** to build your own AND/OR rules,
- list tabs (All, Published, Drafts, Low stock), grouping, column totals, and show/hide columns,
- soft delete with restore (a **Trashed** filter), and a **Replicate** action,
- **import and export** (CSV or Excel),
- a **view page** built as an infolist,
- a **Tags** relation manager to attach and detach tags.

**Categories** and **Brands** appear nested under Products in the sidebar. Both are "simple" resources that work in pop-ups. Categories can be reordered by dragging rows, and Brands can be edited right in the table.

### Orders

- The order form has a **repeater** for order lines. Prices update live as you pick products and change quantities.
- List tabs for each order status, each with a count and color.
- A **Mark paid** bulk action.
- The sidebar badge shows the number of pending orders.

### Customers

- **Dependent fields**: pick a state and the city list changes to match.
- An **Orders** relation manager on the customer page.

### Blog

The **Blog** item (in the Marketing group) uses a **Builder** field for the post body, made of heading, paragraph and quote blocks, and **ToggleButtons** for the status.

### Roles and permissions

**Settings → Roles & Permissions** lists the seeded roles: Super Admin, Admin, Manager, Editor and Viewer. Open one to see how permissions are picked per resource. See [Roles and permissions](roles-and-permissions).

### Custom pages

- **Reports** (in the Shop group) shows HTML and widgets on a custom page.
- **Settings → System settings** is a form page that saves to a JSON file. Only users with the `page.settings` permission can open it.

See [Custom pages](custom-pages).

### Sign-in features

The demo turns on most of the [authentication](authentication) options:

- **Sign-up**: the login page has a "Create an account" link.
- **Email verification**: new accounts must click a link before they get in. The demo has no mail server, so the email (with the link) is printed in the terminal where Uvicorn runs.
- **Two-factor login**: turn it on from **My profile** in the user menu and scan the QR code with an authenticator app.
- Only users with `is_admin` set can sign in, and inactive users are blocked.

### Languages, search and the rest

- **Hindi**: switch language from the user menu or the login page. The demo's own labels are translated in `examples/shop/lang/hi.json`. See [Translations](translations).
- **Global search**: press **Ctrl+K** (or **⌘K**) and type a product, customer or order number.
- **SPA mode** is on, so moving between pages does not reload the whole page. See [Theming](theming).
- A small **plugin** adds a "Documentation" link to the sidebar and a demo-login hint under the login form. See [Plugins and hooks](plugins-and-hooks).

## How the demo is organised

| File | What is in it |
| --- | --- |
| `examples/shop/models.py` | SQLAlchemy models: users, categories, brands, tags, products, customers, orders, order items and posts. |
| `examples/shop/resources.py` | One resource per model, plus the relation managers and the product importer. |
| `examples/shop/widgets.py` | The dashboard and its widgets. |
| `examples/shop/pages.py` | The Reports and System settings pages. |
| `examples/shop/factory.py` | Builds the `Panel` and the FastAPI app, and defines the small plugin. |
| `examples/shop/app.py` | The app that Uvicorn runs. |
| `examples/shop/seed.py` | Fills the database with demo data. |
| `examples/shop/lang/hi.json` | Hindi translations for the demo's own text. |

The panel itself is set up in `factory.py`. It is a good real-world example of a `Panel(...)` call:

```python
panel = Panel(
    path="/admin",
    session_factory=session_factory,
    secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    auth=Auth(User, avatar_field="avatar", active_field="is_active",
              can_access=lambda user: user.is_admin,
              registration=True, two_factor=True, email_verification=True),
    dashboard=ShopDashboard,
    spa=True,
    brand_name="Tungsten",
    colors={"primary": "orange"},
    navigation_groups=["Shop", "Catalog", "Marketing", "Settings"],
    storage=LocalStorage(storage_dir),
    activity_log=True,
    locales=["en", "hi"],
    lang_dirs=[Path(__file__).with_name("lang")],
)
panel.resources(ALL_RESOURCES).pages([Reports, SystemSettings]).widgets(DASHBOARD_WIDGETS)
panel.rbac()
panel.plugin(DocsPlugin())
```

Every option here is explained in [Panel configuration](panel-configuration).
