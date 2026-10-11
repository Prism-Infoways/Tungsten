---
title: Saved table views
description: Let every user save their own table filters, search, sort, tab and columns as one-click views like "My leads" or "Pending", share them with the team and pick the view a list opens with.
---

The `tungsten-saved-views` plugin adds a row of views above every resource table. A user sets filters, a search, a sort, a tab or hides some columns, clicks **Save view**, and gets a one-click tab like **My leads** or **Pending** from then on. It is like Filament's Advanced Tables "user views".

## Install

```bash
pip install tungsten-saved-views
```

```python
from tungsten_saved_views import SavedViewsPlugin

panel.plugin(SavedViewsPlugin())
panel.create_tables(engine)   # also creates the saved view tables
```

That's all. Every resource list now shows the views bar. It needs `tungsten-admin` 0.1.7 or newer. Opening a list straight into its default view needs the next Tungsten release; with 0.1.7 the page loads once and then moves to the default view.

## What users can do

- **Save view**: keeps the filters, search, sort, tab, page size, grouping and the columns they see.
- **Open a view**: one click. The view they are on is highlighted, and the highlight moves when they change a filter.
- **Open the list with this view**: makes a view their default. **All** always shows every record.
- **Save current filters here**: changes a view to what they see now.
- **Rename**, **Share with everyone** and **Delete** from the small arrow next to each view.
- **Saved views** page in the user menu: rename, recolour, pick an icon, set the order and delete views.

Views belong to the user who saved them. A shared view shows to everyone who can open that list, and anyone can make it their own default. Views are kept per team when the panel uses [multi-tenancy](multi-tenancy).

## Options

```python
SavedViewsPlugin(
    resources=None,        # slugs that get the bar; None means every resource
    exclude=["audit-log"], # slugs that never get it
    presets=True,          # ready views for installed plugins, like "My tickets"
    sharing=True,          # allow sharing views with everyone
    manage_page=True,      # the "Saved views" page in the user menu
    max_views=30,          # most views one user may save on one list
)
```

## Ready views from code

Add views everyone sees with `preset()`. The query is the table address, the part after `?` when you set the filters by hand:

```python
views = SavedViewsPlugin()
views.preset("orders", "My orders", "filters.owner_id.value={me}", icon="user-round", color="primary")
views.preset("orders", "Big orders", "sort=total&direction=desc", icon="trending-up")
views.preset("orders", "Placed today", "filters.placed_on.from={today}&filters.placed_on.until={today}")
views.preset("orders", "Refunds", "tab=refunds", visible=lambda user: user.is_admin)
panel.plugin(views)
```

`{me}` becomes the signed-in user's id and `{today}` today's date. `visible(ctx, user)` can hide a preset from some users. Users can make a preset their default too.

When these plugins are installed, ready views are added for you:

| Plugin | Ready view |
| --- | --- |
| [Help desk](tickets) | **My tickets**: tickets given to me |
| [Leads](leads) | **My leads**: leads given to me |

With [Tags](tags) installed, the tag filter is saved like any other filter, so a view like **VIP customers** works out of the box.

Every other list, like HR employees, attendance and leave, or Finance invoices and payments, works with saved views the same way, with no setup.

## Roles

With [roles](roles-and-permissions) on, two permissions show in the Roles screen:

- `saved_views.share`: may share a view with everyone. Without it the "Share" box is hidden.
- `saved_views.manage`: may rename, change and delete views other people shared.

Everyone can always save, change and delete their own views. Without roles, everyone may share, and only the person who saved a view may change it.

## For other plugins

A Kanban board, a dashboard or any other code can use the same views:

```python
views = panel.get_plugin("saved-views")
if views is not None:
    for view in views.views_for(ctx, "leads"):
        print(view.name, view.url, view.query)   # query is the table address, with {me} filled in

    views.on_view_saved("my-plugin", lambda db, view: ...)
    views.on_view_deleted("my-plugin", lambda db, view: ...)
```

The plugin works fine alone, and every hook is optional.

## Good to know

- A view keeps only table settings. The page number and open panels are not saved.
- If a filter is later removed from the table, views that used it still open; the old filter is ignored.
- Names are up to 80 letters and must be different on one list for one user.
- Views are saved with normal form posts with the panel's CSRF token, and only the owner (or someone with `saved_views.manage`) can change one.
