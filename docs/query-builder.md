---
title: Query builder
description: Let users build their own AND/OR filter rules from the constraints you allow.
---

The `QueryBuilder` filter lets users write their own conditions in the filter panel, without you coding each one. You choose which attributes they may filter on (the *constraints*); users pick an attribute, an operator and a value.

## Adding the query builder

Add a `QueryBuilder` to the table filters and list its constraints.

```python
from tungsten.tables import (
    BooleanConstraint, DateConstraint, NumberConstraint, QueryBuilder,
    RelationshipConstraint, SelectConstraint, TextConstraint,
)

table.filters([
    QueryBuilder().constraints([
        TextConstraint("name"),
        TextConstraint("sku").label("SKU"),
        NumberConstraint("price"),
        NumberConstraint("stock").integer(),
        SelectConstraint("status").options({"draft": "Draft", "published": "Published"}),
        BooleanConstraint("is_featured").label("Featured"),
        DateConstraint("created_at").label("Created"),
        TextConstraint("category.name").label("Category name"),
        RelationshipConstraint("tags").selectable("name"),
    ]),
])
```

A **Custom filters** section appears in the filter panel. It works well next to normal [filters](table-filters).

## How rules combine

Users add **rules** with the **Add rule** button. Rules sit in **groups**:

- All rules in one group must match (AND).
- Groups are joined with OR. **Add "or" group** starts a new group.

For example:

> *Price is greater than 3000* **and** *Tags has at least 1*
> **or**
> *Featured is true*

A rule that is not finished yet (for example, no value typed) is marked "Not applied yet" and ignored. The active rules show as chips above the table, and they are saved in the URL like other filters. A builder can hold up to 10 groups of up to 20 rules each.

## Options

`QueryBuilder(name="query")` options:

| Method | What it does |
| --- | --- |
| `constraints([...])` | The attributes users can filter on. |
| `label(text)` | Section title (default "Custom filters"). |
| `default(groups)` | Rules to start with. A list of groups, each a list of rules like `{"c": "price", "op": "gt", "v": 3000}`. A flat list of rules is one group. |

```python
QueryBuilder().constraints([...]).default([{"c": "status", "op": "is", "v": "published"}])
```

Every constraint has:

| Method | What it does |
| --- | --- |
| `label(text)` | The name users see. By default it comes from the attribute name. |
| `icon_name(icon)` | Change the icon shown in the **Add rule** menu. |

All constraints except `RelationshipConstraint` take an optional second argument: the attribute to filter, when it differs from the constraint name.

```python
TextConstraint("customer", "customer_name").label("Customer")
```

## Through relationships

Use a dotted name to filter on a related table. This works with every constraint type except `RelationshipConstraint`.

```python
TextConstraint("category.name").label("Category name")
NumberConstraint("items.quantity").label("Item quantity")
```

For to-many relationships, the rule matches when **any** related row matches.

## TextConstraint

For text columns. All checks ignore upper and lower case.

| Operator | Matches |
| --- | --- |
| Contains | The text appears anywhere. |
| Does not contain | The text does not appear (empty values match too). |
| Starts with | The value starts with the text. |
| Ends with | The value ends with the text. |
| Equals | The value is exactly the text. |
| Does not equal | The value is different (empty values match too). |
| Is filled | The value is not empty. |
| Is blank | The value is empty or `NULL`. |

## NumberConstraint

For number columns. Values are read as decimals; call `integer()` for whole numbers.

```python
NumberConstraint("price")
NumberConstraint("stock").integer()
```

| Operator | Matches |
| --- | --- |
| Equals | `= value` |
| Does not equal | `!= value` (`NULL` matches too) |
| Is greater than | `> value` |
| Is at least | `>= value` |
| Is less than | `< value` |
| Is at most | `<= value` |
| Is between | Between two values, both included. The order of the two values does not matter. |
| Is filled | Not `NULL`. |
| Is blank | `NULL`. |

## DateConstraint

For date and datetime columns. Users pick dates; for datetime columns, a date covers the whole day.

| Operator | Matches |
| --- | --- |
| Is on | That day. |
| Is before | Before that day. |
| Is after | After that day. |
| Is between | From the first day to the end of the second day. |
| Is in the last (days) | From N days ago until now. |
| Is filled | Not `NULL`. |
| Is blank | `NULL`. |

## BooleanConstraint

For true/false columns.

| Operator | Matches |
| --- | --- |
| Is true | `True`. |
| Is false | `False` or `NULL`. |

## SelectConstraint

For columns with a fixed list of values. Options work like a [Select field](form-fields#select): a dict, a list, `(value, label)` pairs, an Enum class, or a closure that returns one of these.

```python
SelectConstraint("status").options(OrderStatus)
SelectConstraint("department").options(lambda db: [d.name for d in db.scalars(select(Department))])
```

| Operator | Matches |
| --- | --- |
| Is | Equals the picked option. |
| Is not | Anything else (`NULL` matches too). |
| Is any of | One of several picked options. |
| Is none of | None of the picked options (`NULL` matches too). |
| Is filled | Not `NULL`. |
| Is blank | `NULL`. |

Only values from the option list are accepted.

## RelationshipConstraint

Filter on whether related records exist, how many there are, or which ones they are. Pass the relationship name.

```python
RelationshipConstraint("tags").selectable("name")
RelationshipConstraint("orders")
RelationshipConstraint("category").selectable("name")
```

| Operator | Matches | Available |
| --- | --- | --- |
| Is any of | Linked to at least one of the picked records. | with `selectable()` |
| Is none of | Not linked to any of the picked records. | with `selectable()` |
| Has any | Has at least one related record. | always |
| Has none | Has no related records. | always |
| Has at least | At least N related records. | to-many relationships |
| Has at most | At most N related records. | to-many relationships |
| Has exactly | Exactly N related records. | to-many relationships |

Whether a relationship is to-many (like `tags`) or to-one (like `category`) is read from the SQLAlchemy relationship, so the count operators only appear where they make sense.

| Method | What it does |
| --- | --- |
| `selectable(title_attribute, modify_query=None)` | Let users pick related records by this attribute. `modify_query` gets the `query` of related records. The list shows up to 500 records, sorted by title. |
| `multiple(True \| False)` | Show or hide the count operators yourself, instead of reading it from the relationship. |

## Custom constraints

To filter in a way the built-in types don't cover, subclass `Constraint`. List the operators as `{key: (label, input)}` and build the SQL condition in `compare()`. The input is `None` (no value), `"text"`, `"number"`, `"date"` or `"between"`.

```python
from tungsten.tables import Constraint


class EmailDomainConstraint(Constraint):
    kind = "text"
    icon = "at-sign"
    operators = {
        "domain": ("Has domain", "text"),
        "not_domain": ("Does not have domain", "text"),
    }

    def compare(self, column, rule):
        condition = column.ilike(f"%@{rule['v']}")
        return condition if rule["op"] == "domain" else ~condition


QueryBuilder().constraints([EmailDomainConstraint("email").label("Email")])
```

`rule["v"]` is the value (and `rule["v2"]` the second value for `"between"`). Dotted names work for custom constraints too.
