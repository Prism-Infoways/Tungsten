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

A model is scoped when it has the `ownership` column (for example `team_id`). Models without it, like `Team` itself or a shared `Country` table, are not touched. A resource can change this, see [Per-resource settings](#per-resource-settings).

For scoped models, Tungsten filters by the current tenant in:

- resource list pages, including search, filters, tabs and pagination,
- record view and edit pages: a record of another tenant returns "Page not found",
- row and bulk actions (they only find records of the current tenant),
- global search,
- exports,
- [table widgets](widgets#table-widgets),
- the options of `Select(...).relationship(...)` fields, and the records offered by `AttachAction`,
- `.unique()` validation: a value only has to be unique inside the current tenant,
- imports: `Importer.unique_by` only finds the current tenant's records, and `ImportColumn(...).relationship(...)` only finds the current tenant's related records.

And it **sets the tenant** on new records:

- records created from create pages and create popups,
- records created in [relation managers](relation-managers),
- records created by [imports](import-export).

If a new record already has a value in the ownership column, Tungsten leaves it alone.

Relation managers show the records of their owner record. Since the owner is already scoped, they need no extra filter.

### Users without a tenant

When a user has **no** tenants (the `tenants` function returns an empty list), there is no current tenant. That user sees **no** records of scoped models: lists are empty, record pages return "Page not found", and they can't create records there. Models that are not scoped stay visible.

To keep such users out of the panel completely, block them with `Auth(can_access=lambda user: bool(user.teams))`.

## Per-resource settings

Two class attributes on a resource change how it is scoped:

| Attribute | Default | What it does |
| --- | --- | --- |
| `tenant_scoped` | `True` | Set it to `False` for records that all tenants share. The resource is then not filtered, and new records don't get a tenant, even if the model has the ownership column. |
| `tenant_ownership` | `None` | The column or relationship that links this model to its tenant, when it is not the panel's `ownership` column. |

```python
class AnnouncementResource(Resource):
    model = Announcement
    tenant_scoped = False            # every team sees all announcements


class InvoiceResource(Resource):
    model = Invoice
    tenant_ownership = "company"     # a relationship to the tenant model
```

`tenant_ownership` can be a column name (like `"owner_team_id"`) or a relationship name. A many-to-one relationship (like `"company"`) is set to the current tenant on new records. A many-to-many relationship (like `"teams"`) shows a record to every tenant in it, and new records get the current tenant added.

These settings are also used when the model shows up somewhere else, for example in select options or imports.

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

Tenancy filters the queries Tungsten builds. It does not change queries you write yourself. Take care with these:

| Where | What to do |
| --- | --- |
| Stats, chart and progress widgets | Filter by `ctx.tenant` in your own queries (see above). |
| `navigation_badge()` and `Resource.query()` | Your own queries: add the tenant filter if needed. |
| Select options from `.options(...)` | Your own list or query: filter by `tenant` if needed. |
| Your own `Importer.resolve_record()` | Filter by `ctx.tenant` in your query. |
| Roles and permissions | Roles are shared by all tenants. |

You can still narrow relationship options further with `modify_query`. The closure can ask for `query` and `tenant`:

```python
Select("category_id").relationship(
    "category", "name",
    modify_query=lambda query: query.where(Category.is_active),
)
```

> [!NOTE]
> `.unique()` checks only the current tenant's records. If a column must be unique across **all** tenants (for example a login email), keep a unique index in the database as well. The database then refuses a duplicate from another tenant (the user sees an error page instead of a message under the field).

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
