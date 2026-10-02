---
title: Widgets
description: Add stats cards, charts, tables and progress lists to your dashboard, custom pages and resource list pages.
---

Widgets are small blocks of information: a row of stats cards, a chart, a short table or a list of progress bars. You put them on the dashboard, on a custom page, or above a resource's list.

Every widget is a class. You override one class method that returns the data, and Tungsten draws the rest.

## Registering widgets

Widgets passed to `panel.widgets()` appear on the dashboard:

```python
from tungsten import Panel

panel = Panel(...)
panel.widgets([ShopStats, RevenueChart, RecentOrders, SalesByCategory])
```

You can also show widgets in other places:

| Where | How |
| --- | --- |
| Dashboard | `panel.widgets([...])`, or `widgets = [...]` on your own `Dashboard` class |
| Custom page | `widgets = [...]` on a [custom page](custom-pages) |
| Resource list page | `widgets = [...]` on a [resource](resources) (shown above the table) |

Tungsten ships five widget types:

| Class | What it shows |
| --- | --- |
| `StatsOverviewWidget` | A row of stats cards with trends and sparklines |
| `ChartWidget` | A Chart.js chart: line, bar, pie, doughnut, radar or polar area |
| `TableWidget` | A small table of records |
| `ProgressListWidget` | A list of labelled progress bars |
| `AccountWidget` | A "Welcome" card with the user's name and a link to their profile |

All of them can be imported from `tungsten`.

> [!TIP]
> `tungsten make:widget Sales --type chart` writes a starter widget for you. The types are `stats`, `chart`, `table` and `progress`. See [CLI](cli).

## Data methods get what they ask for

The data methods (`stats()`, `data()`, `items()`, `query()`) work like other Tungsten closures: name the arguments you need and Tungsten passes them in. You can ask for:

| Argument | What it is |
| --- | --- |
| `db` | The database session |
| `ctx` | The request context (panel, request, user, tenant...) |
| `user` | The signed-in user |
| `filters` | The dashboard filter values (see [Dashboard filters](#dashboard-filters)) |
| `filter` | Chart widgets only: the chart's own selected filter |

```python
@classmethod
def stats(cls, db, filters):
    ...
```

The methods can also be `async def`. Tungsten awaits them. See [Async database](async-database).

## Stats overview

A `StatsOverviewWidget` shows a row of cards. Return a list of `Stat` objects from `stats()`:

```python
from sqlalchemy import func, select
from tungsten import Stat, StatsOverviewWidget

from app.models import Order, Product, User


class ShopStats(StatsOverviewWidget):
    @classmethod
    def stats(cls, db, ctx):
        users = db.scalar(select(func.count()).select_from(User))
        orders = db.scalar(select(func.count()).select_from(Order))
        active = db.scalar(select(func.count()).select_from(Product).where(Product.status == "published"))
        return [
            Stat("Total users", f"{users:,}").icon("users").trend("12%", "up").chart([3, 5, 4, 8, 9]),
            Stat("Orders", f"{orders:,}").icon("shopping-cart").color("success").url(ctx.url("orders")),
            Stat("Active products", f"{active:,}").icon("package").color("purple"),
            Stat("Refunds", "12").icon("rotate-ccw").color("danger").trend("4%", "down"),
        ]
```

`Stat(label, value)` takes the card label and the value to show. The value is shown as given, so format numbers yourself.

### Stat options

| Method | What it does |
| --- | --- |
| `.icon("users")` | An icon in the card. Any [Lucide](https://lucide.dev/icons) icon name. |
| `.color("success")` | The card color: `primary`, `success`, `danger`, `warning`, `info`, `gray`, `purple`, `teal`, `pink`... Default `primary`. |
| `.describe("vs last month")` | A short line of text under the value. |
| `.trend("12%", "up")` | A trend badge. The direction is `"up"` (green) or `"down"` (red). |
| `.trend("25%", "up", "danger")` | Pass a third argument to pick the trend color yourself, for example when "up" is bad. |
| `.chart([3, 5, 4, 8, 9])` | A small sparkline (a tiny line chart) drawn from the numbers. |
| `.url("/admin/orders")` | Makes the whole card a link. |

### Cards per row

By default four cards fit in a row on wide screens. Change it with `columns` (2 to 6):

```python
class OrderStats(StatsOverviewWidget):
    columns = 3
```

A stats widget spans the full width of the grid by default (`column_span = "full"`).

## Charts

A `ChartWidget` draws a chart with Chart.js. Set the `type` and return the data from `data()`:

```python
import datetime as dt

from sqlalchemy import func, select
from tungsten import ChartWidget

from app.models import Order


class RevenueChart(ChartWidget):
    heading = "Revenue overview"
    description = "Monthly revenue."
    type = "bar"

    @classmethod
    def data(cls, db):
        labels, revenue = [], []
        for month in range(1, 13):
            start = dt.datetime(2026, month, 1)
            end = dt.datetime(2026 + month // 12, month % 12 + 1, 1)
            labels.append(start.strftime("%b"))
            revenue.append(float(db.scalar(
                select(func.coalesce(func.sum(Order.total), 0))
                .where(Order.created_at >= start, Order.created_at < end)
            )))
        return {
            "labels": labels,
            "datasets": [{"label": "Revenue", "data": revenue, "color": "primary"}],
        }
```

`data()` returns a dictionary with `labels` (the x-axis labels) and `datasets`. Each dataset has a `label`, a list of numbers in `data`, and an optional `color` name. If you leave out the color, Tungsten picks one for you.

### Chart types

Set `type` to one of:

| Type | Chart |
| --- | --- |
| `"line"` | Line chart (the default), with a soft filled area |
| `"bar"` | Bar chart with rounded bars |
| `"pie"` | Pie chart |
| `"doughnut"` | Doughnut chart |
| `"radar"` | Radar chart |
| `"polarArea"` | Polar area chart |

For pie, doughnut and polar area charts, each slice gets its own color automatically. To choose them, give the dataset a `colors` list instead of `color`:

```python
{"label": "Orders", "data": [42, 18, 7], "colors": ["success", "warning", "danger"]}
```

### Mixing bar and line

Give one dataset `"type": "line"` to draw it as a line on a bar chart. Other Chart.js dataset keys (like `yAxisID` or `fill`) are passed through as they are:

```python
class SalesChart(ChartWidget):
    heading = "Revenue and orders"
    type = "bar"
    options = {"scales": {"y1": {"display": True, "position": "right", "grid": {"display": False}}}}

    @classmethod
    def data(cls, db):
        return {
            "labels": ["Jan", "Feb", "Mar"],
            "datasets": [
                {"label": "Revenue", "data": [52000, 61000, 58000], "color": "primary", "yAxisID": "y"},
                {"label": "Orders", "data": [120, 140, 131], "color": "gray", "type": "line",
                 "yAxisID": "y1", "fill": False},
            ],
        }
```

`options` is a dictionary of [Chart.js options](https://www.chartjs.org/docs/latest/configuration/). It is merged on top of Tungsten's defaults.

### Doughnut extras

For doughnut and pie charts you can show the legend as a list next to the chart with percentages, and put a value in the middle of a doughnut:

```python
class UsersByRole(ChartWidget):
    heading = "Users by role"
    type = "doughnut"
    column_span = 1
    side_legend = True          # list of labels with value and percent
    max_height = "14rem"

    @classmethod
    def data(cls, db):
        return {
            "labels": ["Admin", "Editor", "Viewer"],
            "datasets": [{"label": "Users", "data": [4, 12, 30]}],
            "center": {"value": "46", "label": "Users"},   # text in the middle
        }
```

### Chart filters

A chart can have its own dropdown, for example to pick a time range. List the choices in `filters`. The chosen key reaches `data()` as `filter`:

```python
class RevenueChart(ChartWidget):
    heading = "Revenue"
    type = "line"
    filters = {"12": "Last 12 months", "6": "Last 6 months", "3": "Last 3 months"}
    default_filter = "12"       # optional; the first choice is used otherwise

    @classmethod
    def data(cls, db, filter):
        months = int(filter)
        ...
```

Changing the dropdown reloads only this widget.

### Chart settings

| Setting | Default | What it does |
| --- | --- | --- |
| `type` | `"line"` | The chart type |
| `heading` / `description` | `None` | Title and subtitle above the chart |
| `max_height` | `"18rem"` | Height of the chart area (any CSS size) |
| `filters` | `None` | Choices for the chart's dropdown |
| `default_filter` | `None` | The choice selected at first |
| `options` | `{}` | Extra Chart.js options |
| `side_legend` | `False` | Show a list legend next to pie and doughnut charts |
| `column_span` | `2` | How many grid columns the chart covers |

## Table widgets

A `TableWidget` shows a few records in a table. Set the `model`, and optionally a `query()` and a `table()`:

```python
from sqlalchemy import select
from tungsten import TableWidget
from tungsten.tables import TextColumn

from app.models import Order


class RecentOrders(TableWidget):
    heading = "Recent orders"
    model = Order

    @classmethod
    def query(cls, ctx):
        return select(Order).where(Order.status != "cancelled")

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("number").label("#").weight("medium"),
                TextColumn("customer.name").label("Customer"),
                TextColumn("total").money("INR").label("Amount"),
                TextColumn("status").badge(),
                TextColumn("created_at").label("Date").date(),
            ])
            .default_sort("created_at", "desc")
            .limit(5)
            .toolbar(False)
        )
```

The table is a normal Tungsten table, so columns, sorting, row actions and the rest work as described in [Tables](tables). By default it is paginated with 5 rows per page.

Good to know:

- If the model has a [resource](resources), a **View all** link to that resource's list appears in the header. Set `link = "/admin/orders?status=pending"` to use another URL, and `link_label` to change the text.
- Row actions such as `EditAction()` use the permissions of the model's resource.
- With [multi-tenancy](multi-tenancy), the query is scoped to the current tenant.
- The search box is hidden unless a column is searchable.

## Progress lists

A `ProgressListWidget` shows labelled progress bars, like "Sales by category". Return `ProgressItem` objects from `items()`:

```python
from tungsten import ProgressItem, ProgressListWidget


class SalesByCategory(ProgressListWidget):
    heading = "Sales by category"
    column_span = 1
    link = "/admin/categories"      # optional link in the header

    @classmethod
    def items(cls, db):
        return [
            ProgressItem("Clothing", "35%", 35, icon="shirt"),
            ProgressItem("Footwear", "25%", 25, icon="footprints", color="info"),
            ProgressItem("Accessories", "12%", 12, icon="watch", color="success"),
        ]
```

`ProgressItem(label, value, percent, icon=None, color="primary")` takes the label, the text shown on the right, and the bar fill as a number from 0 to 100.

## Account widget

`AccountWidget` shows the signed-in user's avatar and name with a **Profile** button. It has no settings:

```python
from tungsten import AccountWidget

panel.widgets([AccountWidget, ShopStats, RevenueChart])
```

## Layout: column span and sort

Widgets sit in a grid. On the dashboard the grid has 4 columns on wide screens (on small screens every widget takes the full width).

```python
class RevenueChart(ChartWidget):
    column_span = 2     # 1, 2, 3, 4, 6 or "full"
    sort = 2            # lower numbers come first on the dashboard
```

| Setting | Default | What it does |
| --- | --- | --- |
| `column_span` | `1` (stats: `"full"`, charts and tables: `2`) | Grid columns the widget covers |
| `sort` | `0` | Order on the dashboard |
| `heading` | `None` | Title (charts, tables and progress lists) |
| `description` | `None` | Subtitle under the heading |

To change the number of grid columns on the dashboard or a custom page, set `widget_columns` on the page class (1, 2, 3, 4 or 6):

```python
class Reports(Page):
    widgets = [RevenueChart, UsersByRole, SalesByCategory]
    widget_columns = 3
```

## Lazy loading and polling

Widgets load **lazily** by default. The page shows a grey placeholder for each widget, then fetches each one in its own small request. A slow chart doesn't hold up the rest of the page.

Turn it off for widgets that are fast and should show at once, such as stats above a resource list:

```python
class UserStats(StatsOverviewWidget):
    lazy = False
```

To refresh a widget on a timer, set `polling_interval`. It uses HTMX time syntax, like `"10s"` or `"1m"`:

```python
class LiveOrders(TableWidget):
    model = Order
    polling_interval = "30s"
```

> [!NOTE]
> Polling only works on lazy widgets. If you set `lazy = False`, the widget is drawn once with the page and is not refreshed.

## Showing a widget to some users only

Override `can_view()` to hide a widget. It receives the request context:

```python
class RevenueChart(ChartWidget):
    @classmethod
    def can_view(cls, ctx):
        return ctx.can("orders.view_any")
```

Hidden widgets are left out of the page, and their URL returns "Not allowed". See [Roles and permissions](roles-and-permissions) for `ctx.can()`.

## Dashboard filters

A dashboard can have filters in its header, for example a "Last 30 days" picker. The values reach every widget as `filters`.

Make your own `Dashboard` class with a `filters_form`, and pass it to the panel:

```python
from tungsten import Dashboard, Panel, Stat, StatsOverviewWidget
from tungsten.forms import Select


class ShopDashboard(Dashboard):
    @classmethod
    def filters_form(cls, form):
        return form.schema([
            Select("period")
            .options({"7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days"})
            .default("30"),
        ])


class ShopStats(StatsOverviewWidget):
    @classmethod
    def stats(cls, db, filters):
        days = int(filters.get("period") or 30)
        ...
        return [Stat("Orders", "312").describe(f"Last {days} days")]


panel = Panel(..., dashboard=ShopDashboard)
```

How it works:

- The filter fields are drawn in the dashboard header. Changing a value reloads the page.
- The values live in the URL (`?period=7`), so a filtered dashboard can be bookmarked.
- If a value doesn't pass the form's validation, the defaults are used.
- `filters` is a dictionary. Every widget data method can ask for it, including chart `data()`, table `query()` and progress `items()`.

> [!NOTE]
> Filters come from the dashboard's `filters_form` only. Custom pages don't show a filter form.

### Dashboard options

The `Dashboard` class is a normal [custom page](custom-pages), so you can also set:

```python
class ShopDashboard(Dashboard):
    title = "Dashboard"
    subheading = "Your shop at a glance."
    widgets = [ShopStats, RevenueChart]   # if empty, the panel's widgets are used
    widget_columns = 4
```

Pass `dashboard=None` to `Panel` to have no dashboard. The home page then opens the first resource the user can see.

## Widgets on resource pages

Set `widgets` on a resource to show widgets above its list table:

```python
class ProductResource(Resource):
    model = Product
    widgets = [ProductStats]
```

They use a 4-column grid. To pick widgets per page yourself, override `header_widgets()`. It receives the context and the page name (`"list"` or `"index"` for the list page):

```python
class ProductResource(Resource):
    @classmethod
    def header_widgets(cls, ctx, page):
        return [ProductStats] if page in ("list", "index") else []
```

> [!TIP]
> Widgets above a list page are often quick counts. Set `lazy = False` on them so the numbers appear with the table.
