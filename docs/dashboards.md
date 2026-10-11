---
title: Custom dashboards
description: Let users of your FastAPI admin panel build their own dashboards by drag and drop, with widgets from every installed Tungsten plugin, shared or private, and pick one as their home page.
---

The `tungsten-dashboards` plugin adds a **Dashboards** page to your panel. Each person can build their own dashboards: pick widgets, drag them into place and choose how wide each one is. Widgets come from your own code and from every plugin you installed, like HR, Finance, Tickets and Leads.

## Install

```bash
pip install tungsten-dashboards
```

```python
from tungsten_dashboards import DashboardsPlugin

panel.plugin(DashboardsPlugin())
panel.create_tables(engine)   # creates the dashboard tables
```

It needs `tungsten-admin` 0.1.5 or newer.

## Build a dashboard

1. Open **Dashboards** and click **New dashboard**.
2. Give it a name and pick what it starts with: empty, the same widgets as the home page, all widgets of one plugin, or a template.
3. In edit mode, drag a widget by its handle to move it, and pick a width: quarter, half, three quarters or full.
4. Add more widgets from the **Add widgets** list below the grid. Remove one with the bin button.
5. Click **Done**. Changes are saved as you make them.

Every widget from `panel.widgets([...])`, from your pages and resources, and from installed plugins shows up in the list, grouped by the plugin it comes from. A person only sees widgets whose `can_view()` lets them in.

## Built-in widgets

The plugin brings three widgets of its own that need no code:

| Widget | What it shows |
| --- | --- |
| Record counts | How many records there are in the lists you pick, with a link to each list |
| Quick links | Buttons that open the lists and pages you use most |
| Note | A short note or to-do list for everyone who sees the dashboard |

Turn them off with `DashboardsPlugin(builtin_widgets=False)`.

## Sharing and home pages

- A new dashboard is **private**: only its maker sees it.
- **Share with everyone** shows it to every user (in the same team, with multi-tenancy). Others can view it and make their own copy, but only its maker and people allowed to share can change it.
- **Use as my home page** shows the dashboard on the panel's home page for you. Other people keep their own home page.
- **Home page for everyone** makes a shared dashboard the home page for all users who did not pick their own.

## Permissions

With `panel.rbac()` turned on, two permissions show in the Roles screen:

| Permission | Lets a user |
| --- | --- |
| `dashboards.create` | make their own dashboards |
| `dashboards.share` | share dashboards with everyone and set the home page for all |

Without roles, every signed-in user can do both. You can also decide in `Auth(gate=...)`.

## Options

```python
DashboardsPlugin(
    home=True,               # people can make a dashboard their home page
    builtin_widgets=True,    # Record counts, Quick links and Note
    navigation_group=None,   # menu group of the Dashboards page
    navigation_sort=-90,
    hide=[SecretWidget],     # widgets (classes or ids) never offered on dashboards
)
```

## For plugin authors

Widgets you register with `panel.widgets([...])` show up by themselves. A few optional class attributes change how they look in the list:

```python
class OverdueTasks(StatsOverviewWidget):
    dashboard_label = "Overdue tasks"        # name in the list (defaults to heading or class name)
    dashboard_description = "Tasks past their due date."
    dashboard_group = "Kanban"               # group in the list (defaults to the plugin's name)
    dashboard_span = 2                       # starting width: 1 to 4 quarters
    dashboard_hidden = False                 # True: never offer it on dashboards
```

To offer widgets only on custom dashboards (not on the normal home page), and to add a ready-made starting point:

```python
dashboards = panel.get_plugin("dashboards")
if dashboards is not None:
    dashboards.add_widgets([OverdueTasks, TasksByStatus])
    dashboards.add_template("Projects", [OverdueTasks, TasksByStatus])
```

With the [Quick Create](quick-create) plugin installed, its **+ New** menu gets a **Dashboard** entry. With the [PWA](pwa) plugin, the installed app's icon menu gets a **Dashboards** shortcut. Widgets of [Calendar](calendar), [Backups](backups) and every other plugin show up in the **Add widgets** list by themselves.

## Safe by design

- A widget that fails shows a short message in its own box. The rest of the dashboard still loads.
- A widget whose plugin was removed is hidden for viewers, and its maker sees a note to remove it.
- Private dashboards can't be opened, changed or copied by others, even with a guessed link.
- Each dashboard holds up to 40 widgets, and each person up to 50 dashboards.
