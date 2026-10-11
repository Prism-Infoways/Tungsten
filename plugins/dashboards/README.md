# tungsten-dashboards

Custom dashboards for [Tungsten](https://tungsten.prisminfoways.com/), the admin panel for FastAPI. People build their own dashboards by drag and drop.

## What you get

- A **Dashboards** page with a **New dashboard** button.
- **Drag and drop**: move widgets by their handle and pick a width (quarter, half, three quarters, full). Saved at once.
- **Widgets from every plugin**: your own widgets and those of HR, Finance, Tickets, Leads and any other installed plugin, grouped by plugin.
- **Built-in widgets** that need no code: record counts, quick links and notes.
- **Start from** an empty dashboard, the home page widgets, all widgets of one plugin, or a template.
- **Private or shared** dashboards. Others can make their own copy of a shared one.
- **Home page**: make a dashboard your own home page, or the home page for everyone.
- **Permissions** `dashboards.create` and `dashboards.share` for roles.
- Works with multi-tenancy: dashboards belong to the team they were made in.
- A broken widget shows a short message in its own box; the rest of the page still loads.
- Adds a **Dashboards** shortcut to the installed app with the PWA plugin.
- Adds a **Dashboard** entry to the [Quick Create](https://tungsten.prisminfoways.com/docs/quick-create) + New menu when that plugin is installed.

## Install

```bash
pip install tungsten-dashboards
```

```python
from tungsten_dashboards import DashboardsPlugin

panel.plugin(DashboardsPlugin())
panel.create_tables(engine)   # creates the dashboard tables
```

### Options

```python
DashboardsPlugin(
    home=True,               # people can make a dashboard their home page
    builtin_widgets=True,    # Record counts, Quick links and Note
    navigation_group=None,
    navigation_sort=-90,
    hide=[],                 # widgets (classes or ids) never offered on dashboards
)
```

## For other plugins

```python
dashboards = panel.get_plugin("dashboards")
if dashboards is not None:
    dashboards.add_widgets([OverdueTasks])              # offered only on custom dashboards
    dashboards.add_template("Projects", [OverdueTasks])  # a starting point in "New dashboard"
```

Widgets can set `dashboard_label`, `dashboard_description`, `dashboard_group`, `dashboard_span` and `dashboard_hidden`.

## Try it

```bash
pip install -e . -e plugins/dashboards uvicorn
uvicorn plugins.dashboards.example:app --reload
```

Full guide: https://tungsten.prisminfoways.com/docs/dashboards
