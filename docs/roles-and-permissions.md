---
title: Roles and permissions
description: Control what each user can see and do with roles, permission names, resource policies or a custom gate.
---

By default, every user who can sign in can do everything in the panel. This page shows the three ways to limit that: **roles and permissions** (managed on a screen in the panel), **policies** (Python classes per resource), and a **gate** (one function for every check). You can mix them.

## Turning on roles

Call `panel.rbac()` (RBAC means "role-based access control"):

```python
panel = Panel(..., auth=Auth(User))
panel.resources([ProductResource, OrderResource])
panel.rbac()
panel.create_tables(engine)    # creates the roles tables
```

This does two things:

- Permissions are now checked. A user can only do what one of their roles allows.
- A **Roles & Permissions** screen appears in the sidebar under **Settings**.

Roles are stored in Tungsten's own tables (`tungsten_roles` and `tungsten_role_user`), so `panel.create_tables()` must run once. Your user model doesn't need any changes.

> [!WARNING]
> As soon as RBAC is on, a user with no roles sees an empty sidebar: no resources and no pages that need a permission. Give yourself a super admin role first (see below).

## The Roles screen

On the **Roles & Permissions** screen you create roles. Each role has:

- a **name** (unique),
- a **color** for its badge,
- a short **description**,
- a list of **permissions**, shown as checkboxes grouped by resource, with search and "select all".

The table shows each role's permission count and how many users have it.

The Roles screen is a normal resource with the slug `roles`, so it is protected by its own permissions (`roles.view_any`, `roles.create`...). To use RBAC without this screen:

```python
panel.rbac(roles_resource=False)
```

## Super admins

A role with the permission `*` can do everything. The quickest way to get one is the CLI:

```bash
tungsten make:user --panel app.admin:panel --role "Super Admin"
```

If the role doesn't exist yet, the CLI creates it. When the role name contains "admin", it gets `*`. Otherwise it starts with no permissions.

You can also decide super admins with a function. They pass every check:

```python
Auth(User, super_admin=lambda user: user.email == "owner@acme.example")
```

## Permission names

Permissions are plain strings named `<resource-slug>.<ability>`:

| Permission | Allows |
| --- | --- |
| `products.view_any` | Open the products list (and see it in the sidebar) |
| `products.view` | Open one product's view page |
| `products.create` | Create products (also needed for import) |
| `products.update` | Edit products, inline-edit table cells, reorder rows |
| `products.delete` | Delete one product |
| `products.delete_any` | Bulk delete |
| `products.restore` / `products.restore_any` | Restore soft-deleted products (one / bulk) |
| `products.force_delete` / `products.force_delete_any` | Delete soft-deleted products for good (one / bulk) |

The restore and force delete permissions only exist for models with soft deletes (a `deleted_at` column).

Some permissions include others, so you need to tick fewer boxes:

| If a role has | It also gets |
| --- | --- |
| `products.view_any` | `products.view` |
| `products.delete` | `products.delete_any` |
| `products.restore` | `products.restore_any` |
| `products.force_delete` | `products.force_delete_any` |
| `products.update` | `attach` and `detach` in relation managers |

### Wildcards

| Permission | Allows |
| --- | --- |
| `*` | Everything |
| `products.*` | Every ability on products |

### Pages

A [custom page](custom-pages) can require a permission:

```python
class Settings(Page):
    permission = "page.settings"
```

It then shows up in the Roles screen under **Pages** as "Open Settings". Users without it don't see the page in the sidebar and get "Not allowed" if they open its URL.

### Relation managers

A [relation manager](relation-managers) follows its owner record by default. Users who can view the owner can see the related records. Users who can edit the owner can create, edit, delete, attach and detach them.

## Assigning roles to users

### In your user form

Add `RolesField()` to your user resource's form. It shows a multi-select of all roles and saves the choice for you:

```python
from tungsten.auth.rbac import RolesField


class UserResource(Resource):
    model = User

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required(),
            TextInput("email").email().required().unique(),
            RolesField().helper_text("Roles decide what this user can see and do."),
        ])
```

### In code

```python
panel.auth.assign_role(db, user, "Editor")
```

The role must already exist, otherwise you get a `ValueError`. To create roles in a seed script, use the `Role` model:

```python
from tungsten.models import Role

db.add(Role(name="Editor", color="info", permissions=["products.*", "categories.view_any"]))
db.add(Role(name="Support", permissions=["orders.view_any", "orders.update", "customers.view_any"]))
db.commit()
```

### From the CLI

`tungsten make:user --role "Editor"` gives the new user that role. See [CLI](cli).

## Checking permissions yourself

### In closures

Most closures can ask for `ctx`. Use `ctx.can()` to check a permission:

```python
Action("refund")
    .icon("rotate-ccw")
    .visible(lambda ctx: ctx.can("orders.update"))
    .action(lambda record, db: refund(record, db))
```

`ctx.can(permission, record=None)` returns `True` or `False`. It goes through the gate, roles and super admin rules described on this page.

### Action authorization

Every action has `.authorize()`. Give it an ability name and Tungsten checks it on the current resource (policy first, then roles). The action is hidden when the check fails, and the server refuses it too:

```python
Action("ship").authorize("update")                         # needs orders.update
Action("archive").authorize(lambda user: user.is_admin)    # or a closure
```

The built-in actions already authorize themselves: `CreateAction` needs `create`, `EditAction` needs `update`, `ViewAction` needs `view`, `DeleteAction` needs `delete`, `DeleteBulkAction` needs `delete_any`, `ImportAction` needs `create`, and so on.

### Your own abilities

Add abilities to a resource with `extra_permissions`. They appear in the Roles screen next to the standard ones:

```python
class OrderResource(Resource):
    model = Order
    extra_permissions = ["ship", "refund"]

    @classmethod
    def table(cls, table):
        return table.columns([...]).actions([
            Action("ship").icon("truck").authorize("ship")          # needs orders.ship
                .action(lambda record, db: mark_shipped(record, db)),
        ])
```

### In a resource

`Resource.can(ctx, ability, record=None)` runs the same check Tungsten uses for its own pages:

```python
if OrderResource.can(ctx, "update", order):
    ...
```

### Widgets

Override `can_view()` on a [widget](widgets#showing-a-widget-to-some-users-only):

```python
class RevenueChart(ChartWidget):
    @classmethod
    def can_view(cls, ctx):
        return ctx.can("orders.view_any")
```

## Policies

A policy is an object with one method per ability. Set it on a resource to decide in Python, usually based on the record:

```python
class OrderPolicy:
    def view_any(self, user):
        return True

    def update(self, user, record=None):
        # shipped orders can't be edited
        return record is None or record.status != "shipped"

    def delete(self, user, record=None):
        return user.is_admin and (record is None or record.status == "pending")


class OrderResource(Resource):
    model = Order
    policy = OrderPolicy()
```

How it works:

- Methods are called as `method(user, record)` when there is a record, and `method(user)` when there isn't (lists, bulk actions, create). So give `record` a default of `None`.
- If the policy has a method for the ability, its answer is final.
- If it has no method for an ability, Tungsten falls back to the gate and roles.
- Policies work with or without `panel.rbac()`.

> [!NOTE]
> Set `policy` to an **instance** (`OrderPolicy()`), not the class, because the methods are called with `user` as the first argument.

## Custom gate

A gate is one function that answers every permission check in the panel. Use it when your app already has its own permission system:

```python
def gate(user, permission, record):
    if user.is_superuser:
        return True
    if permission.startswith("roles."):
        return False
    return None          # no opinion: fall back to roles (or allow, without RBAC)


panel = Panel(..., auth=Auth(User, gate=gate))
```

The gate can ask for these arguments:

| Argument | What it is |
| --- | --- |
| `user` | The signed-in user |
| `permission` | The full name, e.g. `"orders.update"` |
| `ability` | Only the last part, e.g. `"update"` |
| `record` | The record being checked, or `None` |
| `ctx` | The request context |

Return `True` to allow, `False` to deny, or `None` to let the normal rules decide. The gate runs before roles. A resource [policy](#policies) runs before the gate.

## Who may sign in at all

Permissions decide what a signed-in user can do. To decide who may sign in in the first place, use `can_access`:

```python
Auth(User, can_access=lambda user: user.is_staff)
```

See [Authentication](authentication#who-can-sign-in).

## The order of checks

When Tungsten checks an ability on a resource, it asks in this order and stops at the first answer:

1. The resource's **policy**, if it has a method for this ability.
2. The **gate**, if it returns `True` or `False`.
3. Without `panel.rbac()`: **allowed**.
4. The **super admin** function, if set.
5. The user's **roles**: `*`, the exact permission, `<slug>.*`, or an implied permission.
6. Otherwise: **denied**.
