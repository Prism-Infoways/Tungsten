---
title: Modern widgets
description: Ten card widgets for a modern dashboard - a big number card, a target gauge, rounded columns, a funnel, a leaderboard, a timeline, a week schedule, a team card, quick actions and a checklist.
---

These widgets give your dashboard the modern look: white cards with big soft corners, bold numbers, black pills and one bright color. They work like the [basic widgets](widgets): make a class, return the data from one class method, and add it with `panel.widgets([...])`.

All of them can be imported from `tungsten`. They work in light and dark mode and right-to-left languages.

| Class | What it shows | Data method |
| --- | --- | --- |
| `HeroStatWidget` | One big number with a trend, a line of text, buttons and small bars | `stat()` and `actions()` |
| `GaugeWidget` | Progress to a target as a half circle or a ring | `value()` |
| `ColumnsWidget` | Rounded columns with one highlighted | `data()` |
| `BannerWidget` | A wide colored card with a heading and a button | class attributes |
| `ActivityWidget` | A timeline of recent events | `items()` |
| `LeaderboardWidget` | A ranked list with avatars, values and bars | `items()` |
| `FunnelWidget` | Stages with shrinking bars | `items()` |
| `ScheduleWidget` | This week as a strip of days, then a list of events | `items()` |
| `TeamWidget` | People as avatars with their name and role | `items()` |
| `QuickActionsWidget` | A grid of round icon buttons | `items()` |
| `ChecklistWidget` | A to-do list with ticks and a progress bar | `items()` |

The data methods get what they ask for, like other widgets: `db`, `ctx`, `user` and `filters` (the page filters). They can be `async def` too.

> [!TIP]
> The shop demo uses every one of these on its dashboard. See [Demo app](demo-app) and `examples/shop/widgets.py`.

## The `Item` class

Most of these widgets show a list. Each row is an `Item`. Every widget uses the fields it needs and skips the rest.

```python
from tungsten import Item

Item("Nikhil Verma", "₹12,400", description="12 orders", avatar="/media/nikhil.jpg", percent=80)
```

| Argument | What it is |
| --- | --- |
| `label` | The main text (first argument) |
| `value` | A value shown at the end, as given (second argument) |
| `description` | A muted line under the label |
| `icon` | A [Lucide](https://lucide.dev/icons) icon name |
| `color` | `primary`, `success`, `danger`, `warning`, `info`, `gray`, `purple`, `teal`, `pink` or `indigo` |
| `avatar` | An image URL. Without it, the initials are shown. |
| `url` | Makes the row a link |
| `percent` | 0 to 100. Draws a bar. Values outside are kept inside 0 to 100. |
| `time` | A short label like `"09:30"` or `"2h ago"` |
| `done` | Ticks the row in a checklist |
| `badge` | A short status text (the team widget shows it as a colored dot) |

List widgets also take `link = "/admin/orders"` and `link_label = "View all"` for a link in the card header.

## Big number card

`HeroStatWidget` shows one big number. Return a [`Stat`](widgets#stats-overview) from `stat()`. Its label, icon, trend and description are used, and `.chart([...])` is drawn as small bars. Return buttons from `actions()`. Use the color `"dark"` for a black button.

```python
from sqlalchemy import func, select
from tungsten import HeroStatWidget, Item, Stat


class RevenueHero(HeroStatWidget):
    description = "All time"          # a small chip at the top right

    @classmethod
    def stat(cls, db):
        total = db.scalar(select(func.sum(Order.total)))
        return Stat("Total revenue", f"₹{total:,.0f}").icon("wallet").trend("12%", "up") \
            .describe("Revenue is up this month").chart([3, 5, 4, 8, 6, 9])

    @classmethod
    def actions(cls, ctx):
        return [
            Item("New order", url=ctx.url("orders", "create"), icon="plus", color="primary"),
            Item("Send invoice", url="/invoices", icon="send", color="dark"),
            Item("Import", url="/import", icon="download", color="gray"),
        ]
```

It spans two columns by default.

## Target gauge

`GaugeWidget` shows how far you are towards a target. Return a dictionary from `value()`:

```python
from tungsten import GaugeWidget


class MonthlyTarget(GaugeWidget):
    heading = "Monthly target"
    description = "Revenue this month"
    label = "Target"

    @classmethod
    def value(cls, db):
        done = 134850
        return {"value": done, "max": 500000, "display": "₹1,34,850", "caption": "of ₹5,00,000"}
```

| Key | What it is |
| --- | --- |
| `value` | The number so far |
| `max` | The target. Default 100. |
| `display` | The text in the middle. Defaults to `value`. |
| `caption` | A small line under it |
| `label` | A small line above it (or set `label` on the class) |

Options on the class:

| Attribute | What it does |
| --- | --- |
| `shape = "ring"` | A full ring instead of a half circle (`"arc"`, the default) |
| `variant = "default"` | A white card. `"dark"` (the default) is near black, `"brand"` uses the primary color. |
| `color = "success"` | The color of the filled part |

The percent is kept between 0 and 100, so going past the target shows a full gauge.

## Rounded columns

`ColumnsWidget` draws rounded columns with one highlighted, like the "Sales overview" card in many modern dashboards. It needs no chart library, so it is light and fast.

```python
from tungsten import ColumnsWidget


class SalesOverview(ColumnsWidget):
    heading = "Sales overview"
    description = "Orders per month"
    column_span = 2
    filters = {"6": "6 months", "12": "12 months"}

    @classmethod
    def data(cls, db, filter):
        return {
            "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
            "values": [12, 9, 20, 6, 14, 10],
            "display": ["12 orders", "9 orders", "20 orders", "6 orders", "14 orders", "10 orders"],
        }
```

The biggest value is highlighted, with its `display` text in a black bubble above it. Pass `"highlight": 2` to pick another column. The other columns are striped. Set `color` for the highlight color and `height` (default `"12rem"`) for the chart height. `filters` works like on [chart widgets](widgets#charts).

## Banner

`BannerWidget` is a wide card with a heading, a line of text and a button. It needs no data method.

```python
from tungsten import BannerWidget


class InviteBanner(BannerWidget):
    heading = "Selling is better together"
    text = "Invite your teammates to manage orders with you."
    eyebrow = "Team"
    button_label = "Invite people"
    button_url = "/admin/users/create"
    variant = "soft"        # soft, brand or dark
    color = "purple"        # the tint for "soft"
```

To build the button URL from the request, override `get_button_url(cls, ctx)`.

## Timeline

`ActivityWidget` shows recent events with an icon each, joined by a line.

```python
from tungsten import ActivityWidget, Item


class RecentActivity(ActivityWidget):
    heading = "Recent activity"

    @classmethod
    def items(cls, db):
        return [
            Item("ORD-031 paid", description="Nikhil Verma · ₹7,196", time="2h ago", icon="badge-check", color="success"),
            Item("New customer", description="Riya Kapoor signed up", time="5h ago", icon="user-plus", color="info"),
        ]
```

## Leaderboard

`LeaderboardWidget` shows a ranked list: rank, avatar, name, value and an optional bar (`percent`). Set `ranked = False` to hide the numbers.

```python
class TopCustomers(LeaderboardWidget):
    heading = "Top customers"

    @classmethod
    def items(cls, db):
        return [Item("Varun Kapoor", "₹1,05,762", description="8 orders", percent=100),
                Item("Varun Mehta", "₹97,566", description="6 orders", percent=92)]
```

## Funnel

`FunnelWidget` shows stages with shrinking bars. Each bar is the stage's share of the first stage, worked out for you. Pass `percent=` on an item to set it yourself.

```python
class OrderFunnel(FunnelWidget):
    heading = "Order funnel"

    @classmethod
    def items(cls, db):
        return [Item("Placed", 120), Item("Confirmed", 67, color="info"), Item("Paid", 20, color="success")]
```

## Week schedule

`ScheduleWidget` shows the current week (Monday first) with today in a black pill, then your events. Without a `heading`, the card title is the month and year.

```python
class TodayPlan(ScheduleWidget):
    description = "Today's plan"

    @classmethod
    def items(cls):
        return [Item("Stand-up", description="Google Meet", time="10:00"),
                Item("Ship orders", description="Warehouse", time="12:30", color="info")]
```

## Team

`TeamWidget` shows people as round avatars with the name and role (`description`) under each. Give an item a `badge` (like `"online"`) to show a small dot in its `color`.

## Quick actions

`QuickActionsWidget` shows round icon buttons in a grid. Set `columns` (2 to 6, default 4). It is drawn with the page, not lazily.

```python
class Shortcuts(QuickActionsWidget):
    heading = "Shortcuts"
    columns = 2

    @classmethod
    def items(cls, ctx):
        return [Item("New order", url=ctx.url("orders", "create"), icon="shopping-cart"),
                Item("Customer", url=ctx.url("customers", "create"), icon="user-plus", color="info")]
```

## Checklist

`ChecklistWidget` shows a to-do list with a progress bar on top ("2/4"). Done rows are ticked and struck through; open rows with a `url` are links.

```python
class SetupGuide(ChecklistWidget):
    heading = "Setup guide"
    icon = "list-checks"
    icon_color = "success"      # also the progress bar color

    @classmethod
    def items(cls, db):
        return [Item("Add your first product", done=True),
                Item("Set up payments", description="Connect a gateway", url="/admin/settings")]
```

## Filled stats cards

The cards of a `StatsOverviewWidget` can be filled too: `Stat(...).highlight()` uses the brand color and `Stat(...).highlight("dark")` is near black. Use it for the one number that matters most.

## Laying out the dashboard

The dashboard grid has four columns on wide screens. Use `column_span` (1, 2, 3, 4 or `"full"`) and `sort` to arrange the cards. A layout that matches the reference designs:

| Row | Widgets |
| --- | --- |
| 1 | `HeroStatWidget` (2) · `GaugeWidget` (1) · `QuickActionsWidget` (1) |
| 2 | `StatsOverviewWidget` (full), first card highlighted |
| 3 | `ColumnsWidget` (2) · `FunnelWidget` (1) · `LeaderboardWidget` (1) |
| 4 | `TableWidget` (2) · `ActivityWidget` (1) · `ScheduleWidget` (1) |
| 5 | `BannerWidget` (2) · `TeamWidget` (1) · `ChecklistWidget` (1) |
