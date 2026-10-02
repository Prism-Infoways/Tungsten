---
title: Table features
description: List tabs with counts, grouping, totals, show/hide columns, drag-to-reorder, inline editing and table actions.
---

Beyond columns, search and filters, a table can have tabs, grouped rows, totals, columns users can hide, drag-and-drop ordering, editable cells and buttons. This page shows each one.

## List tabs

Tabs above the table split the records into common views, like *All*, *Published* and *Drafts*. Each tab can show a count.

```python
from tungsten.tables import ListTab

table.tabs([
    ListTab("all").label("All products").badge(),
    ListTab("published").badge(color="success")
        .query(lambda query, model: query.where(model.status == "published")),
    ListTab("draft").label("Drafts").badge(color="warning")
        .query(lambda query, model: query.where(model.status == "draft")),
    ListTab("low").label("Low stock").icon("triangle-alert").badge(color="danger")
        .query(lambda query, model: query.where(model.stock < 10)),
])
```

The first tab is the default. The open tab is kept in the URL (`?tab=draft`), and search, filters and sorting work inside it.

| Method | What it does |
| --- | --- |
| `ListTab(name, label=None)` | The tab. The name goes in the URL; the label defaults to the name. |
| `label(text)` | The tab text. |
| `icon(icon)` | An icon before the text. |
| `query(fn)` | Narrow the rows. `fn` gets `query` and `model` (and `db`, `user`...), and returns the new query. Leave it out for an "all" tab. |
| `badge(value=True, color="gray")` | `True` shows the number of records in the tab. Or pass a value or a closure. |

The count uses the tab's query and the resource's own scope, but not the current search or filters.

Tabs can be built in a loop. Bind the loop variable as a default argument so each tab keeps its own value:

```python
table.tabs([ListTab("all").label("All orders").badge()] + [
    ListTab(s.value).badge(color=s.color).query(lambda query, model, s=s: query.where(model.status == s))
    for s in (OrderStatus.PENDING, OrderStatus.SHIPPED, OrderStatus.PAID)
])
```

## Grouping rows

`groups()` lets users group rows by an attribute. A **Group by** dropdown appears in the toolbar, and each group gets a heading row.

```python
from tungsten.tables import Group

table.groups([
    "status",
    Group("customer.name").label("Customer"),
])
```

Pass attribute names, or `Group` objects for more control. Dotted names group by a related value.

| Method | What it does |
| --- | --- |
| `groups([...], default=None)` | The groups users can pick. `default` is the attribute grouped by when the page opens. |
| `default_group(attribute)` | Same as `default=`. |
| `Group(attribute, label=None)` | One way to group. |
| `Group.label(text)` | Name in the dropdown ("Group by customer"). |
| `Group.title(fn)` | The heading text. `fn` gets a `record`; a new heading starts whenever the text changes. |
| `Group.collapsible()` | Users can click a group heading to hide or show its rows. |

```python
table.groups(
    [Group("created_at").label("Day").title(lambda record: record.created_at.strftime("%d %b %Y"))],
    default="created_at",
)
```

Rows are sorted by the group attribute first, then by the user's sort. Users can pick **No grouping** to turn it off.

## Totals and summaries

`summarize()` adds a footer row with totals. The numbers are computed over **all** rows that match the current search, filters and tab, not only the current page.

```python
from tungsten.tables import Average, Count, Max, Min, Sum

TextColumn("total").money("INR", 0).summarize(Sum().money("INR", 0))
TextColumn("stock").summarize(Sum(), Average().numeric(1))
TextColumn("price").money("INR").summarize(Min("Cheapest").money("INR"), Max("Dearest").money("INR"))
TextColumn("email").summarize(Count())
```

| Summarizer | Shows |
| --- | --- |
| `Sum()` | The total. |
| `Average()` | The average. |
| `Count()` | How many rows have a value. |
| `Min()`, `Max()` | The smallest or largest value. |

Each summarizer takes an optional label as its first argument, and has:

| Method | What it does |
| --- | --- |
| `label(text)` | The text before the value (default "Sum", "Average"...). |
| `money(currency="$", decimals=2)` | Show the value as money. |
| `numeric(decimals=0)` | Show the value with thousands separators. |
| `format_state_using(fn)` | Your own format. `fn` gets `state` (the value). |

Summaries of real columns are computed in the database. For a column that computes its value with `state()`, the summary is worked out in Python from the values in the cells, which loads every matching row. That is fine for small tables; for big ones, prefer a real column.

```python
TextColumn("products_count").state(lambda record: len(record.products)).summarize(Sum())
```

> [!NOTE]
> Summaries are skipped for dotted names (`customer.name`) unless the column has `state()`.

## Show and hide columns

Mark columns as `toggleable()` and a **Columns** dropdown appears in the toolbar. Users tick the columns they want to see.

```python
TextColumn("sku").toggleable()
TextColumn("department").toggleable(hidden_by_default=True)
TextColumn("created_at").date().toggleable()
```

`hidden_by_default=True` starts the column hidden. Each user's choice is remembered in their session for that table.

## Drag to reorder

`reorderable()` adds a **Reorder** button. In reorder mode, users drag rows by a handle, and the new order is saved to a number column after each drop.

```python
table.reorderable("sort").default_sort("sort")
```

The argument is the column that stores the position (default `"sort"`). Your model needs that column, for example `sort: Mapped[int] = mapped_column(default=0)`.

While reordering, the table shows all rows on one page, sorted by that column, without grouping or row selection. Click **Done reordering** to go back. Only users who may update records see the button.

You can reorder with a search, filter or tab active. The rows you move swap places among themselves, and rows that are not on screen keep their place. After each drop, every record gets a fresh position from 1 up, so no two rows share a number.

## Inline editing

Editable columns let users change a value right in the table. The value is checked with normal field rules and saved at once.

```python
from tungsten.tables import CheckboxColumn, SelectColumn, TextInputColumn, ToggleColumn

table.columns([
    TextInputColumn("name").required().input_width("w-48"),
    TextInputColumn("stock").integer().configure(lambda field: field.min_value(0)),
    SelectColumn("status").options({"draft": "Draft", "published": "Published"}),
    ToggleColumn("is_visible"),
    CheckboxColumn("is_featured"),
])
```

A bad value is not saved and an error message explains why. See [Editable columns](table-columns#editable-columns) for all options.

## Row actions

`actions()` adds buttons at the end of each row. Put less common ones in an `ActionGroup`, which shows them in a dropdown menu.

```python
from tungsten.actions import Action, ActionGroup, DeleteAction, EditAction, ViewAction

table.actions([
    Action("ship").label("Mark shipped").icon("truck").color("info")
        .visible(lambda record: record.status == "paid")
        .requires_confirmation()
        .action(lambda record, db: (setattr(record, "status", "shipped"), db.commit())),
    EditAction(),
    ActionGroup([ViewAction(), DeleteAction()]),
])
```

## Bulk actions

`bulk_actions()` adds checkboxes to the rows. When users select rows, a bar appears with the number selected and the bulk buttons. A bulk action's function gets the selected `records`.

```python
from tungsten.actions import BulkAction, BulkActionGroup, DeleteBulkAction
from tungsten.importexport import ExportBulkAction

table.bulk_actions([
    BulkAction("publish").label("Publish").icon("circle-check").color("success")
        .action(lambda records, db: ([setattr(r, "status", "published") for r in records], db.commit()))
        .success_notification_title("Products published"),
    DeleteBulkAction(),
    BulkActionGroup([ExportBulkAction()]).label("More actions"),
])
```

The checkboxes only appear when the user may run at least one bulk action. Use `selectable()` to show them anyway, or `selectable(False)` to hide them.

## Header actions

`header_actions()` adds buttons to the table toolbar, next to the search box. Good for create, import and export.

```python
from tungsten.actions import CreateAction
from tungsten.importexport import ExportAction, ImportAction

table.header_actions([ImportAction(ProductImporter), ExportAction()])
```

In a [relation manager](relation-managers), this is where `CreateAction()` and `AttachAction()` go. On a resource list page, the **Create** button is a page header action instead; change those with the resource's `header_actions(cls, ctx, page, record)` method.

All the action options (modals, forms, confirmation, notifications) are on the [Actions](actions) page. Import and export are on [Import & export](import-export).
