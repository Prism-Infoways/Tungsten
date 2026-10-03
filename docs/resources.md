---
title: Resources
description: Turn one SQLAlchemy model into list, create, edit and view pages with a single Python class.
---

A resource is a Python class that describes how one model is managed in the panel. From it Tungsten builds a list page with a table, create and edit pages with a form, and a view page. This page covers everything a resource can do.

## Defining a resource

Subclass `Resource`, point `model` at your SQLAlchemy model, and describe the form and the table.

```python
from tungsten import Resource
from tungsten.actions import DeleteAction, DeleteBulkAction, EditAction
from tungsten.forms import Select, TextInput, Toggle
from tungsten.tables import TextColumn


class ProductResource(Resource):
    model = Product
    icon = "package"
    navigation_group = "Catalog"

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required().max_length(150),
            Select("category_id").label("Category").relationship("category", "name"),
            TextInput("price").numeric().prefix("₹").required(),
            Toggle("is_featured"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").searchable().sortable(),
                TextColumn("category.name").label("Category").badge(),
                TextColumn("price").money("INR").sortable(),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
        )
```

Then register it on the panel:

```python
panel.resources([ProductResource, OrderResource])
```

The product list now shows up in the sidebar under "Catalog".

- `form()` is explained in [Forms](forms). Inside it, `form.operation` is `"create"`, `"edit"` or `"view"`, and `form.record` is the record (or `None` on create), so you can return different fields per page.
- `table()` is explained in [Tables](tables).
- `infolist()` is optional and gives the view page formatted values. See [Infolists](infolists).

> [!TIP]
> `tungsten make:resource Product -m app.models:Product -g` writes a resource file for you, with fields and columns built from the model. See [CLI](cli).

## Pages and URLs

A resource has four pages. With the panel at `/admin` and the slug `products`:

| Page | URL | What it shows |
| --- | --- | --- |
| List | `/admin/products` | The table, widgets and header buttons. |
| Create | `/admin/products/create` | An empty form. |
| View | `/admin/products/5` | The record, read-only. |
| Edit | `/admin/products/5/edit` | The filled form, plus any relation managers. |

After a record is created, the user goes to its edit page (or the view page if they may not edit, or the list). The create page also has a **Create & create another** button.

You can turn pages off with `pages`:

```python
class TagResource(Resource):
    model = Tag
    pages = ("index", "create", "edit")   # no view page
```

Without a view page, view links go to the edit page. Without a create page, the **New** button opens the form in a popup instead.

To build a link to a page in your own code, use `get_url()`:

```python
ProductResource.get_url(ctx)                     # /admin/products
ProductResource.get_url(ctx, "create")           # /admin/products/create
ProductResource.get_url(ctx, "edit", record)     # /admin/products/5/edit
ProductResource.get_url(ctx, "view", record)     # /admin/products/5
```

## Labels and slug

Tungsten guesses names from the model class. For a model called `OrderItem` you get the label "Order item", the plural "Order items" and the slug `order-items`. Override them when the guess is wrong:

```python
class CategoryResource(Resource):
    model = Category
    label = "Category"
    plural_label = "Categories"
    slug = "categories"
    description = "Group products so customers can find them."
```

| Attribute | What it does |
| --- | --- |
| `model` | The SQLAlchemy (or SQLModel) model class. |
| `label` | Singular name, used in buttons and headings ("New category"). |
| `plural_label` | Plural name, used for the page title and menu item. |
| `slug` | The URL part (`/admin/categories`). |
| `description` | A short line under the title on the list and create pages. |

All labels are translated automatically. See [Translations](translations).

## Navigation

These attributes control the sidebar item. See [Navigation](navigation) for groups and custom items.

```python
class OrderResource(Resource):
    model = Order
    icon = "shopping-cart"          # any Lucide icon name
    navigation_group = "Shop"
    navigation_sort = 3
    navigation_badge_color = "danger"

    @classmethod
    def navigation_badge(cls, db):  # number next to the menu item
        return db.scalar(select(func.count()).where(Order.status == "pending")) or None
```

| Attribute | What it does |
| --- | --- |
| `icon` | Icon next to the menu item. Default: `"file-text"`. |
| `navigation_group` | Group heading to put the item under. |
| `navigation_label` | Menu text, if it should differ from `plural_label`. |
| `navigation_sort` | Lower numbers come first. Default: `0`. |
| `navigation_parent` | Label of another menu item to nest this one under (for example `"Products"`). |
| `show_in_navigation` | `False` hides the item. The pages still work. |
| `navigation_badge()` | A class method returning a badge value. It can ask for `ctx`, `db` or `user`. Return `None` to hide the badge. |
| `navigation_badge_color` | Badge color. Default: `"primary"`. |

## Record titles

Tungsten shows a title for each record in headings, breadcrumbs and search results. By default it uses the first of `name`, `title`, `label` or `email` that has a value, and falls back to "Order #12". Set `record_title_attribute` to pick the attribute yourself:

```python
class OrderResource(Resource):
    model = Order
    record_title_attribute = "number"
```

## Global search

Global search is the search box in the top bar (also opened with Ctrl/⌘+K). List the attributes a resource should be searched by. Dot notation searches through relationships.

```python
class ProductResource(Resource):
    model = Product
    global_search_attributes = ["name", "sku", "category.name"]
    global_search_limit = 5          # results per resource (default 5)

    @classmethod
    def global_search_details(cls, record):
        return {"SKU": record.sku, "Category": record.category.name if record.category else "—"}

    @classmethod
    def global_search_image(cls, record):
        return record.image_url
```

| Method | What it returns |
| --- | --- |
| `global_search_title(record)` | The result title. Default: the record title. |
| `global_search_details(record)` | A dict of small "Label: value" lines under the title. |
| `global_search_image(record)` | An image URL shown next to the result, or `None`. |

A resource without `global_search_attributes` is not searched. Results link to the edit page when the user may edit, otherwise to the view page. Soft-deleted records are left out.

## Simple resources

For small models, like tags or brands, you may not want separate pages. Set `simple = True` and the resource works fully from the list page: create, edit and view open in popups.

```python
class BrandResource(Resource):
    model = Brand
    icon = "badge-check"
    simple = True

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required().unique(), TextInput("website").url()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable()]).actions([EditAction(), DeleteAction()])
```

> [!NOTE]
> Relation managers are shown on the edit and view pages, so a simple resource does not show them.

## Scoping the query

Override `query()` to change which records every page of the resource can see. It receives `ctx` and returns a SQLAlchemy `select()`.

```python
from sqlalchemy import select


class OrderResource(Resource):
    model = Order

    @classmethod
    def query(cls, ctx):
        return select(Order).where(Order.archived.is_(False))
```

This query is the starting point for the table, the record pages, actions and global search. A record outside it gives a "not found" page. With [multi-tenancy](multi-tenancy), the tenant filter is added on top.

## Lifecycle hooks

Hooks are class methods that run while a record is created, saved or deleted. Like other closures, they get only the arguments they ask for: `record`, `data`, `form`, `ctx`, `db` and `user`.

```python
class OrderResource(Resource):
    model = Order

    @classmethod
    def mutate_form_data_before_create(cls, data, user):
        data["created_by_id"] = user.id
        return data

    @classmethod
    def after_save(cls, record, db):
        db.flush()
        db.refresh(record)
        record.total = sum(i.quantity * i.unit_price for i in record.items)
```

| Hook | When it runs | Useful arguments |
| --- | --- | --- |
| `mutate_form_data_before_create` | Before a new record is made. Return the changed `data`. | `data` |
| `before_create` | After the record object exists, before the form values are set on it. | `record`, `data` |
| `after_create` | After the record and its relationships are saved, before commit. | `record`, `data` |
| `mutate_form_data_before_save` | Before an existing record is updated. Return the changed `data`. | `data`, `record` |
| `before_save` | Before the form values are set on an existing record. | `record`, `data` |
| `after_save` | After the record and its relationships are updated, before commit. | `record`, `data` |
| `before_delete` | Before a delete or force delete. | `record` |
| `after_delete` | After a delete or force delete, before commit. | `record` |
| `after_restore` | After a soft-deleted record is restored, before commit. | `record` |

Some details:

- The `mutate_*` hooks may return `None`; the data is then used unchanged.
- All hooks run before `db.commit()`, so changes you make to `record` are saved too.
- The hooks run for the create and edit pages and also for the ready-made `CreateAction`, `EditAction`, `DeleteAction` and `DeleteBulkAction`.
- `async def` hooks work too. Tungsten awaits them.

Sending a notification after an order is placed (from the demo):

```python
@classmethod
def after_create(cls, record, db, ctx):
    admins = db.scalars(select(User).where(User.is_admin.is_(True))).all()
    Notification("New order").body(f"{record.number} was placed.") \
        .action("View order", cls.get_url(ctx, "edit", record)) \
        .send_to_database(admins, db)
```

## Header actions

The buttons at the top of each page come from `header_actions()`. By default you get:

| Page | Default buttons |
| --- | --- |
| List (`"list"`) | **Create** (links to the create page) |
| Create (`"create"`) | none |
| Edit (`"edit"`) | Delete, plus Restore and Force delete for deleted records |
| View (`"view"`) | Delete and Edit |

Override it to add your own [actions](actions). The `page` argument tells you which page is asking.

```python
from tungsten.actions import Action, DeleteAction, ViewAction


class OrderResource(Resource):
    model = Order

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        if page == "edit":
            return [
                ViewAction().button().color("gray"),
                Action("ship").icon("truck").requires_confirmation()
                .visible(lambda record: record.status == "paid")
                .action(lambda record, db: (setattr(record, "status", "shipped"), db.commit())),
                DeleteAction().outlined(),
            ]
        return super().header_actions(ctx, page, record)
```

After a header action runs, the page reloads. A `DeleteAction` in the header sends the user back to the list.

## Soft deletes

If the model has a nullable `deleted_at` column, soft deletes turn on by themselves. Deleting a record then sets `deleted_at` instead of removing the row.

```python
class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
```

What changes:

- Deleted records are hidden from the table. Add a `TrashedFilter()` to the table to show them ("With deleted records" / "Only deleted records").
- The edit page of a deleted record shows a warning, cannot be saved, and offers **Restore** and **Force delete** buttons.
- `RestoreAction` and `ForceDeleteAction` only appear for deleted rows. `EditAction` and `DeleteAction` are hidden for them.
- Four more permissions exist: `restore`, `restore_any`, `force_delete` and `force_delete_any`.

```python
from tungsten.actions import (BulkActionGroup, DeleteAction, DeleteBulkAction, EditAction,
                              ForceDeleteAction, ForceDeleteBulkAction, RestoreAction, RestoreBulkAction)
from tungsten.tables import TrashedFilter


@classmethod
def table(cls, table):
    return (
        table.columns([...])
        .filters([TrashedFilter()])
        .actions([EditAction(), DeleteAction(), RestoreAction(), ForceDeleteAction()])
        .bulk_actions([
            DeleteBulkAction(),
            BulkActionGroup([RestoreBulkAction(), ForceDeleteBulkAction()]),
        ])
    )
```

To use another column name, set `soft_delete_column = "removed_at"`. To turn soft deletes off even though the model has `deleted_at`, set `soft_delete_column = None`.

## Replicating records

`ReplicateAction` copies a record: every column except the primary key, `created_at`, `updated_at` and any names you exclude. Relationships are not copied.

```python
import datetime as dt

from tungsten.actions import ReplicateAction

ReplicateAction(excluded=["sku"]).before_replica_saved(
    lambda replica: setattr(replica, "sku", f"{replica.name[:3].upper()}-{dt.datetime.now():%H%M%S}")
)
```

The `before_replica_saved` closure can ask for `replica` (the copy), `record` (the original) and `data`. More in [Actions](actions#ready-made-actions).

## Widgets above the list

Put [widgets](widgets) at the top of the list page with `widgets`:

```python
class ProductResource(Resource):
    model = Product
    widgets = [ProductStats]
```

For more control, override `header_widgets(cls, ctx, page)` and return a list. It is used on the list page.

## Relation managers

List [relation managers](relation-managers) in `relations`. They appear as tables under the record on the edit and view pages.

```python
class CustomerResource(Resource):
    model = Customer
    relations = [OrdersRelationManager]
```

## Authorization

Each page and action checks an ability, such as `view_any`, `view`, `create`, `update`, `delete` or `delete_any`. By default Tungsten asks the panel for the permission `<slug>.<ability>`, for example `products.update`. See [Roles and permissions](roles-and-permissions).

You can also give a resource a `policy`: any object with methods named after abilities. A method asks for what it needs by name: `user`, `record` (`None` when there is no record), `ctx`, `db`, `tenant` or `ability`. It can be `async def`. Abilities without a method fall back to the permission check. See [Policies](roles-and-permissions#policies).

```python
class OrderPolicy:
    def update(self, user, record):
        return user.is_admin or (record is not None and record.status == "pending")

    def delete(self, user):
        return user.is_admin


class OrderResource(Resource):
    model = Order
    policy = OrderPolicy()
```

Check an ability in your own code with `OrderResource.can(ctx, "update", record)`.

If you add custom abilities for your own actions, such as `.authorize("publish")`, list them in `extra_permissions` so they show up on the Roles screen:

```python
class ProductResource(Resource):
    model = Product
    extra_permissions = ["publish"]   # adds products.publish
```
