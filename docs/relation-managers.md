---
title: Relation managers
description: Manage related records, like a customer's orders or a product's tags, in a table on the record's page.
---

A relation manager shows the related records of one record in a table under its form. For example, the customer edit page can list that customer's orders, with buttons to add, edit and delete them, without leaving the page.

## Defining a relation manager

Subclass `RelationManager`, name the SQLAlchemy relationship, and give it a form and a table, just like a resource.

```python
import datetime as dt

from tungsten import RelationManager
from tungsten.actions import CreateAction, DeleteAction, DeleteBulkAction, EditAction
from tungsten.forms import Select, Textarea, TextInput
from tungsten.tables import TextColumn


class OrdersRelationManager(RelationManager):
    relationship = "orders"            # Customer.orders
    icon = "shopping-cart"

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("number").required().unique().default(lambda: f"ORD-{dt.datetime.now():%y%m%d%H%M%S}"),
            Select("status").options(OrderStatus).required().default("pending"),
            TextInput("total").numeric().prefix("₹").default(0),
            Textarea("notes").column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("number").label("#").searchable(),
                TextColumn("status").badge(),
                TextColumn("total").money("INR"),
                TextColumn("created_at").label("Date").date().sortable(),
            ])
            .header_actions([CreateAction()])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
            .default_sort("created_at", "desc")
        )
```

Then list it in the resource's `relations`:

```python
class CustomerResource(Resource):
    model = Customer
    relations = [OrdersRelationManager]
```

The customer edit page now has an "Orders" table under the form. **New order** opens the form in a popup. The new order is linked to the customer for you, so the form does not need a `customer_id` field.

> [!TIP]
> `tungsten make:relation-manager Customer orders` writes the class for you. Add `--attach` for a many-to-many relationship. See [CLI](cli).

## Where it appears

- On the **edit** and **view** pages of the owner record. It is not shown on the create page, because the record does not exist yet.
- With one relation manager, the table has a heading. With several, they become tabs, and each tab shows a count of related records.
- Set `show_on_view = False` to show it on the edit page only.

The table works like any other [table](tables): search, sort, filters, pagination, row actions and bulk actions. `EditAction`, `ViewAction` and `CreateAction` open popups here, because a relation manager has no pages of its own.

## Options

| Attribute | What it does |
| --- | --- |
| `relationship` | Name of the relationship on the owner model (required). |
| `title` | Heading and tab text. Default: made from the relationship name ("Orders"). |
| `label` | Singular name used in buttons ("New order"). Default: the title without a trailing "s". |
| `icon` | Icon next to the heading or tab. |
| `record_title_attribute` | Attribute used as the record title in popup headings and in the attach list. Without it, popups use the first of `name`, `title`, `number` or `email`. |
| `soft_delete_column` | Soft-delete column of the related model. Default: `"deleted_at"` when it exists. `None` turns it off. |
| `show_on_view` | `False` hides it on the view page. Default: `True`. |

### The count badge

When there are several relation managers, the number on each tab is the length of the relationship. Override `badge()` to show something else, or return `None` to hide it. It can ask for `ctx` and `owner`.

```python
class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def badge(cls, owner):
        return sum(1 for o in owner.orders if o.status == "pending") or None
```

## Many-to-many relationships

For a many-to-many relationship (one with a `secondary` table), use `AttachAction` to link existing records and `DetachAction` / `DetachBulkAction` to unlink them.

```python
from tungsten.actions import AttachAction, CreateAction, DetachAction, DetachBulkAction, EditAction


class TagsRelationManager(RelationManager):
    relationship = "tags"              # Product.tags
    icon = "tags"
    record_title_attribute = "name"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required().max_length(60).unique()])

    @classmethod
    def table(cls, table):
        return (
            table.columns([TextColumn("name").badge().searchable()])
            .header_actions([AttachAction(), CreateAction()])
            .actions([EditAction(), DetachAction()])
            .bulk_actions([DetachBulkAction()])
        )
```

| Action | What it does |
| --- | --- |
| `AttachAction()` | Opens a popup with a searchable multi-select of records that are not linked yet. The chosen ones are linked. |
| `DetachAction()` | Unlinks one record, after a confirmation. The record itself is kept. |
| `DetachBulkAction()` | Unlinks the selected records. |
| `CreateAction()` | Creates a new record and links it. |
| `DeleteAction()` | Unlinks the record **and deletes it**. Use `DetachAction` if the record is shared. |

The attach list shows up to 500 records, using `record_title_attribute` for the text (without it, `str(record)` is shown). Pass `AttachAction(title_attribute="name")` to use another attribute.

## Scoping the related records

By default the table shows every record in the relationship. Add a `query()` class method to filter or change it. It can ask for `query` (the starting `select()`), `owner` and `ctx`, and must return a query.

```python
class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def query(cls, query, owner):
        return query.where(Order.status != "cancelled")
```

## View popup

`ViewAction()` in a relation manager opens a read-only popup. Give the relation manager an `infolist()` to show formatted values there; without one, the form is shown disabled. See [Infolists](infolists).

```python
from tungsten.actions import ViewAction
from tungsten.infolists import TextEntry


class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def infolist(cls, infolist):
        return infolist.schema([
            TextEntry("number"),
            TextEntry("status").badge(),
            TextEntry("total").money("INR"),
            TextEntry("created_at").datetime(),
        ])

    @classmethod
    def table(cls, table):
        return table.columns([...]).actions([ViewAction(), EditAction()])
```

## Hooks

Relation managers support the same lifecycle hooks as resources: `mutate_form_data_before_create`, `before_create`, `after_create`, `mutate_form_data_before_save`, `before_save`, `after_save`, `before_delete`, `after_delete` and `after_restore`. They also get `owner`, the parent record.

```python
class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def after_create(cls, record, owner, db):
        owner.last_order_at = record.created_at
```

See [Resources](resources#lifecycle-hooks) for when each hook runs.

## Permissions

By default:

- Users who can **view** the owner record can see the relation manager.
- Users who can **update** the owner record can create, edit, delete, attach and detach related records.

Override `can()` to decide yourself. It receives `ctx`, the `ability` (such as `"create"`, `"update"`, `"delete"`, `"attach"`, `"detach"`), the related `record` (or `None`), and keyword arguments `owner` and `resource`.

```python
class OrdersRelationManager(RelationManager):
    relationship = "orders"

    @classmethod
    def can(cls, ctx, ability, record=None, *, owner=None, resource=None):
        if ability in ("view", "view_any"):
            return True
        return ctx.user.is_admin
```

## Soft-deleted related records

If the related model has a `deleted_at` column, deleting a related record soft-deletes it, just like on a resource. Add `TrashedFilter()`, `RestoreAction()` and `ForceDeleteAction()` to the relation manager's table to see and restore them. See [Resources](resources#soft-deletes).
