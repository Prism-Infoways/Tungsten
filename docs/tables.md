---
title: Tables
description: Define the list page of a resource, with search, sorting, pagination, empty states, row links and polling.
---

The table is the list page of a resource. You choose the columns, and Tungsten builds the database query, the search box, sorting, pagination and filters for you. The table state (search, sort, filters, page) lives in the URL, so users can bookmark and share it.

## Defining a table

Give your resource a `table()` class method. It receives an empty table and returns it with columns.

```python
from tungsten import Resource
from tungsten.actions import DeleteAction, DeleteBulkAction, EditAction
from tungsten.tables import SelectFilter, TextColumn


class ProductResource(Resource):
    model = Product

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").searchable().sortable(),
                TextColumn("category.name").label("Category").badge(),
                TextColumn("price").money("INR").sortable(),
                TextColumn("created_at").date().sortable(),
            ])
            .filters([SelectFilter("category").relationship("category", "name")])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
            .default_sort("created_at", "desc")
        )
```

A column name is a model attribute. Use dots to read through relationships: `category.name`. Tungsten loads those relationships up front (one extra query per relationship), so you don't get one query per row.

Every column type is described in [Table columns](table-columns). Filters are in [Table filters](table-filters), and row and bulk buttons in [Actions](actions).

## Search

Call `searchable()` on the columns you want to search. A search box appears above the table. Tungsten finds rows where **any** searchable column contains the text, ignoring upper and lower case.

```python
TextColumn("name").searchable()
TextColumn("sku").searchable()
```

### Searching through relationships

A column with a dotted name searches the related table:

```python
TextColumn("customer.name").label("Customer").searchable()
```

This finds orders whose customer's name matches. It works for to-many relationships too (`tags.name`).

### Searching other attributes

Use `columns=` to search different attributes from the one the column shows. Dotted paths work here too.

```python
TextColumn("name").description(lambda record: f"@{record.username}")
    .searchable(columns=["name", "username", "company.name"])
```

### Custom search

For full control, pass `query=`. The function gets the `search` text and the `model`, and returns a SQLAlchemy condition.

```python
TextColumn("full_name").searchable(
    query=lambda search, model: (model.first_name + " " + model.last_name).ilike(f"%{search}%")
)
```

### Search options on the table

| Method | What it does |
| --- | --- |
| `searchable(False)` | Hide the search box even when columns are searchable. `searchable(True)` forces it on. |
| `search_placeholder(text)` | Text in the empty search box (default "Search products..."). |

## Sorting

Call `sortable()` on a column. Users click the heading to sort ascending, again for descending, and a third time to go back to the default order.

```python
TextColumn("price").money("INR").sortable()
TextColumn("customer.name").sortable()     # sorts by the related column
```

Set the starting order with `default_sort()`:

```python
table.default_sort("created_at", "desc")
```

With no sort at all, rows come newest first (by primary key).

### Custom sorting

Pass `query=` to write the ORDER BY yourself. The function gets the `query`, the `direction` (`"asc"` or `"desc"`) and the `model`.

```python
TextColumn("full_name").sortable(
    query=lambda query, direction, model: query.order_by(
        model.last_name.desc() if direction == "desc" else model.last_name.asc()
    )
)
```

## Pagination

Tables show 10 rows per page, and users can pick 10, 25, 50 or 100. Change the choices with `paginated()`. The first value is the default unless you pass `default`.

```python
table.paginated([5, 10, 25])            # default 5
table.paginated([10, 25, 50], 25)       # default 25
table.paginated(False)                  # all rows on one page
```

| Method | What it does |
| --- | --- |
| `paginated(options, default=None)` | Per-page choices, or `False` to turn pagination off. |
| `default_per_page(n)` | Rows per page when the user has not picked. |
| `limit(n)` | Show only the first `n` rows, with no pagination. Handy in [widgets](widgets). |

## Scoping the query

`modify_query_using()` changes the query for this table: add a WHERE, a join or eager loading. The function gets the `query` and returns a new one.

```python
table.modify_query_using(lambda query, model: query.where(model.is_archived.is_(False)))
```

`query()` is another name for the same method. To scope every page of a resource (list, edit, global search), override the resource's `query(cls, ctx)` instead. See [Resources](resources).

## Clicking a row

By default, clicking a row opens the record's edit page, or its view page if the user may only view it. Change this with `record_url()`:

```python
table.record_url(lambda record: f"/shop/products/{record.slug}")
table.record_url(False)        # rows are not links
```

Cells of editable columns and columns with their own `url()` are not wrapped in the row link.

## Empty state

When there are no rows, the table shows an icon, a heading and a short text. Set your own with `empty_state()`, and add buttons with `empty_state_actions()`.

```python
from tungsten.actions import CreateAction

table.empty_state(
    heading="No orders yet",
    description="Orders appear here after checkout.",
    icon="shopping-cart",
).empty_state_actions([CreateAction()])
```

By default the heading is "No products" (the resource name). The text is "Create one to get started." or, when a search or filter is active, "Try a different search or filter."

## Polling

`poll()` reloads the table every few seconds, so new rows appear by themselves.

```python
table.poll("10s")
```

The value is an interval like `"5s"`, `"30s"` or `"1m"`.

## Heading and look

| Method | What it does |
| --- | --- |
| `heading(text)` | A title above the table. |
| `description(text)` | Smaller text under the heading. |
| `striped()` | Shade every other row. |
| `row_index()` | Add a `#` column with the row number. |
| `record_classes(fn)` | Extra CSS classes per row. `fn` gets the `record`. |
| `toolbar(False)` | Hide the toolbar (search, filters, column toggles, header actions). |

```python
table.striped().row_index().record_classes(
    lambda record: "row-sold-out" if record.stock <= 0 else ""
)
```

The panel CSS only holds the classes Tungsten itself uses, so define your own class (for example in a `head.end` [render hook](plugins-and-hooks)).

## Closures in tables

Like forms, table options take values or functions. Tungsten passes what the function asks for. In table closures you can ask for `ctx`, `request`, `user`, `db`, `tenant`, `table`, `model`, `host` and `owner` (the parent record in a [relation manager](relation-managers)). Column closures can also ask for `record`, `state` (the cell value) and `column`.

```python
TextColumn("stock").color(lambda record: "danger" if record.stock < 10 else "success")
SelectFilter("role").options(lambda db: [(r.id, r.name) for r in db.scalars(select(Role))])
```

## Table state in the URL

Search text, sort, page, per-page, list tab, grouping and filter values are stored in the query string. Reloading the page or sharing the link shows the same view. The table updates in place (no full page reload) as users type, sort or filter.

More features — list tabs, grouping, totals, toggleable columns, drag-to-reorder and inline editing — are covered in [Table features](table-features).
