---
title: Multi-tenancy
description: Split records between teams or companies, so each user only sees the data of the team they are working in.
---

Multi-tenancy means one panel serves several groups, such as teams, companies or stores. Each record belongs to one group (the **tenant**). Users pick the tenant they are working in, and Tungsten only shows that tenant's records.

## How it works

1. You have a tenant model, for example `Team`.
2. Your other models have a column that points to the team, for example `team_id`.
3. Each user belongs to one or more teams.
4. You pass a `Tenancy` to the panel. Tungsten filters every resource by the current team and fills in `team_id` on new records.

## Models

Here is a small setup with teams, users who belong to several teams, and products that belong to one team:

```python
from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


team_user = Table(
    "team_user", Base.metadata,
    Column("team_id", ForeignKey("teams.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password: Mapped[str] = mapped_column(String(255))
    teams: Mapped[list[Team]] = relationship(secondary=team_user)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
```

## Turning it on

```python
from tungsten import Auth, Panel, Tenancy

panel = Panel(
    session_factory=SessionLocal,
    secret_key="...",
    auth=Auth(User),
    tenancy=Tenancy(Team, ownership="team_id", tenants=lambda user: user.teams),
)
panel.resources([ProductResource, OrderResource])
```

That's all. `ProductResource` needs no changes.

### Tenancy options

| Option | Default | What it does |
| --- | --- | --- |
| `model` (first argument) | required | The tenant model, e.g. `Team` |
| `ownership` | `"tenant_id"` | The column on your models that holds the tenant's id |
| `tenants` | required | A function that returns the tenants the user may use. It can ask for `user`, `db` and `ctx`. |
| `label_attribute` | `"name"` | The tenant attribute shown in the switcher |
| `session_key` | `"tw_tenant"` | Where the chosen tenant is kept in the session |

The `tenants` function can run any query:

```python
from sqlalchemy import select

Tenancy(
    Company,
    ownership="company_id",
    tenants=lambda user, db: db.scalars(select(Company).where(Company.owner_id == user.id)).all(),
    label_attribute="legal_name",
)
```

## Switching tenants

When a user belongs to tenants, a switcher appears at the top of the sidebar. It shows the current tenant's name. Picking another tenant reloads the panel at the dashboard, showing that tenant's data.

- The choice is saved in the session, so it is kept between pages.
- The first time, or when the saved tenant is no longer in the user's list, the first tenant from `tenants` is used.
- Signing out forgets the choice.
- Users can only switch to tenants that your `tenants` function returns.

## What gets scoped

A model is scoped when it has the `ownership` column (for example `team_id`). Models without it, like `Team` itself or a shared `Country` table, are not touched.

For scoped models, Tungsten filters by the current tenant in:

- resource list pages, including search, filters, tabs and pagination,
- record view and edit pages: a record of another tenant returns "Page not found",
- row and bulk actions (they only find records of the current tenant),
- global search,
- exports,
- [table widgets](widgets#table-widgets).

And it **sets the tenant** on new records:

- records created from create pages and create popups,
- records created in [relation managers](relation-managers),
- records created by [imports](import-export).

If a new record already has a value in the ownership column, Tungsten leaves it alone.

Relation managers show the records of their owner record. Since the owner is already scoped, they need no extra filter.

## Using the current tenant yourself

Closures can ask for `tenant` (it is also `ctx.tenant`):

```python
TextInput("invoice_prefix").default(lambda tenant: tenant.name[:3].upper())
```

Use it in your own queries, for example in stats widgets:

```python
class ShopStats(StatsOverviewWidget):
    @classmethod
    def stats(cls, db, ctx):
        team_id = ctx.tenant.id if ctx.tenant else None
        orders = db.scalar(select(func.count()).select_from(Order).where(Order.team_id == team_id))
        return [Stat("Orders", f"{orders:,}").icon("shopping-cart")]
```

## What is not scoped automatically

Tenancy filters the queries Tungsten builds for resources. It does not change queries you write yourself, and a few built-in lookups don't know about tenants. Take care with these:

| Where | What to do |
| --- | --- |
| Stats, chart and progress widgets | Filter by `ctx.tenant` in your own queries (see above). |
| `navigation_badge()` and `Resource.query()` | Your own queries: add the tenant filter if needed. |
| `Select(...).relationship(...)` options | Options come from the whole table. Filter them with `modify_query` (below). |
| `.unique()` validation | Checks the whole table. If values only need to be unique per tenant, write a `.rule()` instead. |
| `Importer.unique_by` | Looks for existing records in the whole table. Override `resolve_record()` (below). |
| Roles and permissions | Roles are shared by all tenants. |

Scope select options with `modify_query`. The closure can ask for `query` and `tenant`:

```python
Select("category_id").relationship(
    "category", "name",
    modify_query=lambda query, tenant: query.where(Category.team_id == tenant.id),
)
```

Scope the importer's lookup of existing records:

```python
from sqlalchemy import select


class ProductImporter(Importer):
    model = Product
    unique_by = "sku"

    @classmethod
    def resolve_record(cls, ctx, data):
        existing = ctx.db.scalars(
            select(Product).where(Product.sku == data.get("sku"), Product.team_id == ctx.tenant.id)
        ).first()
        return existing or Product()
```

> [!WARNING]
> When a user has **no** tenants (the `tenants` function returns an empty list), there is no current tenant and nothing is filtered: the user sees records of every team. Make sure every user who can sign in belongs to at least one tenant, or block the others with `Auth(can_access=lambda user: bool(user.teams))`.

## Combining with permissions

Tenancy decides **which records** a user sees. [Roles and permissions](roles-and-permissions) decide **what they may do** with them. Use both together: tenancy keeps teams apart, and roles give each person the right abilities.

A [policy](roles-and-permissions#policies) or gate can also look at the tenant. For example, only team owners may delete:

```python
def gate(user, ability, ctx):
    if ability == "delete" and ctx.tenant is not None:
        return ctx.tenant.owner_id == user.id
    return None


Auth(User, gate=gate)
```
