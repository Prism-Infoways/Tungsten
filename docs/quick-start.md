---
title: Quick start
description: Build a small working admin panel with login, a product resource, a form and a table in a few minutes.
---

In this guide you build a tiny shop admin from scratch: a products list with search and filters, a form to create and edit products, a categories screen, and a login page. It takes three small files.

## 1. Install

```bash
pip install tungsten-admin uvicorn
```

Make a folder for the project with an empty `app/__init__.py` file. You will add three files next to it:

```text
app/
  __init__.py
  models.py
  admin.py
  main.py
```

## 2. Define the models

Tungsten works with normal SQLAlchemy 2.0 models. Create `app/models.py` with a user, a category and a product:

```python
# app/models.py
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

engine = create_engine("sqlite:///app.db")
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password: Mapped[str] = mapped_column(String(255))  # stores the hash, never the plain password


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    is_featured: Mapped[bool] = mapped_column(default=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))

    category: Mapped[Category | None] = relationship()
```

The `User` model has the fields that login needs: an `email`, a `password` (the hash) and a `name`. See [Installation](installation#requirements-for-the-user-model) for how to use other field names.

## 3. Build the panel

Now describe how each model is managed. A **resource** is one class per model with a `form()` and a `table()`. Create `app/admin.py`:

```python
# app/admin.py
from tungsten import Auth, Panel, Resource
from tungsten.actions import DeleteAction, DeleteBulkAction, EditAction
from tungsten.forms import Select, TextInput, Toggle
from tungsten.tables import IconColumn, SelectFilter, TextColumn

from .models import Base, Category, Product, SessionLocal, User, engine


class CategoryResource(Resource):
    model = Category
    plural_label = "Categories"
    icon = "folder-tree"
    simple = True  # create and edit in pop-ups, on one page

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required().unique()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable().sortable()]).actions([EditAction(), DeleteAction()])


class ProductResource(Resource):
    model = Product
    icon = "package"
    global_search_attributes = ["name"]

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required().max_length(150),
            Select("category_id").label("Category").relationship("category", "name").searchable(),
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
                IconColumn("is_featured").boolean(),
            ])
            .filters([SelectFilter("category").relationship("category", "name")])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([DeleteBulkAction()])
        )


panel = Panel(
    path="/admin",
    session_factory=SessionLocal,
    secret_key="change-me",      # signs the session cookie: use a real secret in production
    auth=Auth(User),             # turns on the login page
    brand_name="Acme Shop",
    colors={"primary": "orange"},
)
panel.resources([ProductResource, CategoryResource])

Base.metadata.create_all(engine)  # your own tables
panel.create_tables(engine)        # Tungsten's tables (roles, notifications...)
```

What each part does:

- **`form()`** lists the fields on the create and edit pages. `Select(...).relationship("category", "name")` loads the options from the `Category` table and shows each category's `name`.
- **`table()`** lists the columns on the list page. `TextColumn("category.name")` follows the relationship. `searchable()` adds the column to the search box, and `sortable()` makes the header clickable.
- **`filters`, `actions` and `bulk_actions`** add a category filter, Edit and Delete buttons on each row, and a "Delete selected" button for checked rows.
- **`simple = True`** on the categories resource keeps everything on one page: create and edit open in pop-ups.
- **`global_search_attributes`** lets users find products from the search box at the top of every page.
- **`icon`** is any [Lucide](https://lucide.dev/icons) icon name.

## 4. Mount it into FastAPI

Create `app/main.py`:

```python
# app/main.py
from fastapi import FastAPI

from .admin import panel

app = FastAPI()
panel.mount(app)
```

`panel.mount(app)` adds the whole admin, with its pages, assets and session cookie, under `/admin`. The rest of your FastAPI app is not touched.

## 5. Create your first user

The `tungsten` command can create a user for you. Point it at your panel with `--panel module:attribute`, and run it from the folder that contains `app/`:

```bash
tungsten make:user --panel app.admin:panel
```

It asks for a name, email and password (the password twice), hashes the password, and saves the user:

```text
Name: Admin
Email: admin@example.com
Password:
Repeat for confirmation:
User admin@example.com created.
```

## 6. Run it

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/admin` and sign in with the email and password you just chose.

You now have:

- a **dashboard** at `/admin`,
- a **Products** list at `/admin/products` with search, sorting, a category filter, row actions and bulk delete,
- **create, edit and view pages** for products,
- a **Categories** screen where everything happens in pop-ups,
- a **search box** that finds products by name,
- a **light/dark switch** in the top bar and a **user menu** with a profile page and sign out.

## Where to go next

Grow the panel one step at a time:

| You want to... | Read |
| --- | --- |
| Put fields in sections, tabs or a wizard | [Form layouts](form-layouts) |
| Use more field types (dates, images, rich text...) | [Form fields](form-fields) |
| Format columns, add badges, inline toggles | [Table columns](table-columns) |
| Add stats and charts to the dashboard | [Widgets](widgets) |
| Group the sidebar and show counts | [Navigation](navigation) |
| Add roles so not everyone can delete | [Roles and permissions](roles-and-permissions) |
| Change colors, logo and font | [Theming](theming) |
| Generate resources from your models | [CLI](cli) |

To see a much bigger example with all of these in use, run the [demo app](demo-app).
