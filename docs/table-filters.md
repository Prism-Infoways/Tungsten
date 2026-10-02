---
title: Table filters
description: Narrow table rows with checkbox, select, yes/no, date range, trashed and custom form filters.
---

Filters let users narrow the rows in a table. Add them with `filters()`. Simple filters sit in the toolbar next to the search box; the rest go in a filter panel that opens with the **Filters** button.

```python
from tungsten.tables import DateFilter, Filter, SelectFilter, TernaryFilter, TrashedFilter

table.filters([
    SelectFilter("status").options({"draft": "Draft", "published": "Published"}),
    SelectFilter("category").relationship("category", "name"),
    TernaryFilter("is_featured").label("Featured"),
    DateFilter("created_at").label("Created"),
    Filter("low_stock").label("Low stock only").query(lambda query, model: query.where(model.stock < 10)),
    TrashedFilter(),
])
```

Filter values are kept in the URL, like the search and sort.

## Options for every filter

| Method | What it does |
| --- | --- |
| `label(text)` | The label. By default it comes from the name. |
| `default(value)` | A value that is applied when the page first opens. |
| `inline(condition=True)` | Show the filter in the toolbar (`True`) or in the filter panel (`False`). |
| `query(fn)` | Your own query code. `fn` gets `query`, `data` and `model`, and returns the new query. |
| `indicate_using(fn)` | Text for the "Active filters" chips. `fn` gets `data` and returns a string or a list of strings. |

Filter closures can also ask for `db`, `user`, `ctx`, `table` and the other [table closure arguments](tables#closures-in-tables).

## Filter

A plain `Filter` is a checkbox. When it is ticked, its `query` runs.

```python
Filter("big_orders").label("Over ₹10,000").query(lambda query, model: query.where(model.total > 10000))
Filter("mine").label("My orders").query(lambda query, model, user: query.where(model.owner_id == user.id))
```

Turn it on by default with `default()`:

```python
Filter("in_stock").query(lambda query, model: query.where(model.stock > 0)).default()
```

### Filters with a form

Give a filter its own fields with `form()`. The `data` dict holds the clean values (numbers, dates...), keyed by field name. The query runs when at least one field has a value.

```python
from tungsten.forms import TextInput


def price_range(query, data, model):
    if data.get("min") is not None:
        query = query.where(model.price >= data["min"])
    if data.get("max") is not None:
        query = query.where(model.price <= data["max"])
    return query


Filter("price").form([
    TextInput("min").label("Min price").numeric(),
    TextInput("max").label("Max price").numeric(),
]).query(price_range).indicate_using(
    lambda data: f"Price {data.get('min') or 0} – {data.get('max') or '∞'}"
)
```

Any [form field](form-fields) works here. For a form filter, `default()` takes a dict: `.default({"min": 100})`.

## SelectFilter

A dropdown of values. Rows match when the attribute equals the picked value.

```python
SelectFilter("status").options({"draft": "Draft", "published": "Published", "archived": "Archived"})
SelectFilter("status").options(OrderStatus).multiple()
SelectFilter("department").options(["Sales", "Marketing", "Support"]).default("Sales")
```

Options work like a [Select field](form-fields#select): a dict, a list, `(value, label)` pairs, an Enum class or a closure.

```python
SelectFilter("role_id").label("Role").options(lambda db: [(r.id, r.name) for r in db.scalars(select(Role))])
```

### Relationship options

`relationship()` loads the options from a related table and filters by it. It works for to-one and to-many relationships.

```python
SelectFilter("category").relationship("category", "name").placeholder("All categories")
SelectFilter("customer").relationship("customer", "name").searchable()
SelectFilter("tags").relationship("tags", "name").multiple()
```

`relationship(name, title_attribute, modify_query=None)`: `modify_query` gets the `query` of related records, for example to hide inactive ones.

| Method | What it does |
| --- | --- |
| `options(options)` | The choices. |
| `relationship(name, title_attribute, modify_query=None)` | Load choices from a relationship. |
| `multiple()` | Pick several values (a checkbox list in the filter panel). |
| `searchable()` | Add a search box to the dropdown. |
| `placeholder(text)` | Text when nothing is picked (default: the label). |
| `attribute(name)` | Filter on another attribute than the filter name. Also `SelectFilter(name, attribute)`. |
| `default(value)` | Starting value; a list with `multiple()`. |

With your own `query()`, the picked value is in `data["value"]` (or the list in `data["values"]` with `multiple()`):

```python
SelectFilter("role").options(lambda db: [(r.id, r.name) for r in db.scalars(select(Role))])
    .query(lambda query, data, model: query.where(model.id.in_(
        select(RoleAssignment.user_id).where(RoleAssignment.role_id == int(data["value"]))
    )))
```

## TernaryFilter

Three choices: all, yes, no. Use it for boolean columns.

```python
TernaryFilter("is_active").label("Status").true_label("Active").false_label("Inactive")
```

"Yes" matches `True`. "No" matches everything that is not `True` (so `NULL` counts as no).

Use `nullable()` to check whether a column is filled instead, and `queries()` for your own conditions:

```python
TernaryFilter("email_verified_at").label("Verified").nullable()

TernaryFilter("in_stock").queries(
    true=lambda query, model: query.where(model.stock > 0),
    false=lambda query, model: query.where(model.stock <= 0),
)
```

| Method | What it does |
| --- | --- |
| `true_label(text)`, `false_label(text)` | Labels for the two choices (default Yes / No). |
| `placeholder(text)` | Text for "all" (default: the label). |
| `nullable()` | Yes = not `NULL`, no = `NULL`. |
| `queries(true=fn, false=fn)` | Your own query for each choice. Each `fn` gets `query` and `model`. |
| `default(True \| False)` | Start on yes or no. |

## DateFilter

Two date pickers, from and until. The "until" date includes the whole day.

```python
DateFilter("created_at").label("Order date")
DateFilter("shipped", "shipped_at")         # filter name, then attribute
```

The chips read "Order date from 2025-03-01" and "Order date until 2025-03-31".

## TrashedFilter

For resources with soft deletes (a `deleted_at` column). Users choose between **without** deleted records (the default), **with** them, or **only** deleted records.

```python
TrashedFilter()
```

Add it so users can find deleted records and restore them. See [Resources](resources).

## QueryBuilder

The `QueryBuilder` filter lets users build their own rules, like *Price is greater than 3000 and Tags has at least 1*. It has its own page: [Query builder](query-builder).

## Where filters appear

By default:

- `SelectFilter` (single) and `TernaryFilter` sit in the toolbar.
- `Filter`, `DateFilter`, `TrashedFilter`, `QueryBuilder` and multiple `SelectFilter`s go in the filter panel.

Move one filter with `inline()` or `inline(False)`. To put **all** filters in the toolbar, pass `layout="above"`:

```python
table.filters([...], layout="above")
```

The **Filters** button shows how many panel filters are active. The panel has a **Clear filters** button.

## Active filter chips

When filters are active, a row of chips under the toolbar lists them, for example "Status: Published" or "Featured: Yes". A small cross clears all filters at once.

Each filter builds its own chip text. Change it with `indicate_using()`:

```python
Filter("big_orders").query(...).indicate_using(lambda data: "Big orders only")
```
