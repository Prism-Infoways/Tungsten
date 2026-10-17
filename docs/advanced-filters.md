---
title: Advanced filters
description: Filter one column with an operator and a value, like "Price is between 1000 and 5000" or "Created is this month".
---

An advanced filter is a filter on one column where the user picks an **operator** (contains, is greater than, is this month...) and types a **value**. It is the quick, everyday cousin of the [query builder](query-builder): no rules to add, just pick and type.

## Add one filter per column

`advanced_filters()` adds an advanced filter for each table column. The kind of filter comes from the database column type.

```python
table.columns([
    TextColumn("name"),
    TextColumn("category.name").label("Category"),
    TextColumn("price").money("INR"),
    TextColumn("created_at").date(),
]).advanced_filters()
```

| Column type | Filter |
| --- | --- |
| `String`, `Text` | Text: contains, starts with, equals, is blank... |
| `Integer` | Whole number: =, ≠, >, ≥, <, ≤, between, not between... |
| `Numeric`, `Float` | Number, same operators. |
| `Date`, `DateTime` | Date: today, this month, in the last N days, between... |
| `Boolean` | Yes/no: is true, is false. |
| `Enum` | Select: is, is not, is any of, is none of. |
| A relationship (`tags`) | Relationship: is any of, has any, has at least N... |

Dotted names like `category.name` follow the relationship. Columns that are not real model columns (computed with `state()`, or JSON) are skipped. The filter takes the column's label.

| Option | What it does |
| --- | --- |
| `advanced_filters(columns=[...])` | Only these names. They don't have to be table columns. |
| `advanced_filters(exclude=[...])` | Skip these columns. |

Filters you add yourself with `filters()` stay. If one has the same name, yours wins.

## Add them one by one

`AdvancedFilter` gives you full control:

```python
from tungsten.tables import AdvancedFilter

table.filters([
    AdvancedFilter.text("name"),
    AdvancedFilter.number("price"),
    AdvancedFilter.number("stock", integer=True),
    AdvancedFilter.date("created_at").label("Created"),
    AdvancedFilter.boolean("is_featured").label("Featured"),
    AdvancedFilter.select("status", OrderStatus),
    AdvancedFilter.relationship("tags", "name"),
    AdvancedFilter("available_from"),          # kind guessed from the model column
])
```

Any [constraint](query-builder#custom-constraints) works too, including your own:

```python
AdvancedFilter(NumberConstraint("total").label("Order total"))
```

| Method | What it does |
| --- | --- |
| `label(text)` | The name users see. |
| `operators([...])` | Offer only these operators, in this order. Use the keys from the tables below, like `["gte", "lte", "between"]`. |
| `default_operator(op)` | The operator used when users only type a value. By default it is the first one that needs a value ("contains" for text, "equals" for numbers). |
| `default("today")` / `default({"op": "gt", "v": 100})` | Apply this when the page first opens. |
| `inline()` | Show it in the toolbar instead of the filter panel. |

The operator list starts with **Any**, which means "not filtering". If a user types a value and leaves the operator on Any, the default operator is used. A filter with an operator but no value yet shows a small dot ("Not applied yet") and does nothing.

## Date operators

Dates have many ready-made ranges. Weeks start on Monday. For datetime columns, a date covers the whole day.

| Key | Operator |
| --- | --- |
| `on`, `not_on` | Is on / is not on a day. |
| `before`, `after` | Is before / after a day. |
| `between`, `not_between` | Is (not) between two days, both included. |
| `today`, `yesterday`, `tomorrow` | That day. |
| `this_week`, `last_week`, `next_week` | Monday to Sunday. |
| `this_month`, `last_month`, `next_month` | The calendar month. |
| `this_year`, `last_year`, `next_year` | The calendar year. |
| `last_days`, `last_weeks`, `last_months`, `last_years` | From N days/weeks/months/years ago up to the end of today. |
| `next_days`, `next_weeks`, `next_months` | From today for the next N days/weeks/months. |
| `past`, `future` | Before today / after today. |
| `filled`, `blank` | Has a date / has none. |

The same operators are in the query builder's `DateConstraint`. Text, number, select, yes/no and relationship operators are listed on the [query builder](query-builder) page.

## How it behaves

- Each advanced filter adds to the others (AND). For OR, use the [query builder](query-builder).
- Active filters show as chips above the table, like *Price is between 1000 and 5000*.
- The values live in the URL (`filters.price.op=between&filters.price.v=1000&filters.price.v2=5000`), so links, [deferred filters](table-filters), "remember filters" and the Saved Views plugin all keep them.
- A dotted column like `category.name` is named `category__name` in the URL.
