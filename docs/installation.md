---
title: Installation
description: Install Tungsten, pick the extras you need, and mount the panel into your FastAPI app.
---

Tungsten is a normal Python package. Install it, create a `Panel`, and mount it into your FastAPI app.

## Requirements

- **Python 3.10 or newer** (3.10 to 3.13 are tested).
- **FastAPI** 0.110 or newer.
- **SQLAlchemy 2.0** models. SQLModel models work too, because they are SQLAlchemy models underneath.
- Any database SQLAlchemy supports: SQLite, PostgreSQL, MySQL and others.

These are installed for you as dependencies: `fastapi` (which brings `starlette`), `sqlalchemy`, `jinja2`, `python-multipart` and `itsdangerous`. The `tungsten` command uses only the standard library.

## Install the package

```bash
pip install tungsten-admin
```

The package is called `tungsten-admin`, but you import it as `tungsten`:

```python
from tungsten import Panel, Resource, Auth
```

It also installs the `tungsten` command line tool. Check that it works:

```bash
tungsten version
```

You also need a server to run your app, such as Uvicorn:

```bash
pip install uvicorn
```

## Optional extras

Some features need extra packages. Install them with "extras" in square brackets.

| Extra | Installs | You need it for |
| --- | --- | --- |
| `excel` | `openpyxl` | Importing and exporting `.xlsx` files. CSV works without it. See [Import and export](import-export). |
| `async` | `sqlalchemy[asyncio]` | Running the panel on an async engine (`create_async_engine`). See [Async database](async-database). |

```bash
pip install "tungsten-admin[excel]"
pip install "tungsten-admin[excel,async]"
```

> [!NOTE]
> The `async` extra does not include a database driver. Install the async driver for your database too, for example `aiosqlite` for SQLite or `asyncpg` for PostgreSQL.

## Mount the panel

A panel is its own small FastAPI app. You create it with your database session factory and mount it into your main app.

```python
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tungsten import Panel

engine = create_engine("sqlite:///app.db")
SessionLocal = sessionmaker(engine, expire_on_commit=False)

panel = Panel(
    path="/admin",
    session_factory=SessionLocal,
    secret_key="change-me",
)
panel.create_tables(engine)   # Tungsten's own tables (roles, notifications...)

app = FastAPI()
panel.mount(app)
```

Run it and open <http://127.0.0.1:8000/admin>:

```bash
uvicorn main:app --reload
```

What happens here:

- `panel.mount(app)` mounts the panel at `path` (here `/admin`). The panel brings its own session cookie, CSRF protection and static files (CSS, JavaScript, icons), served from `/admin/assets`.
- You can pass `engine=...` instead of `session_factory=...`. Tungsten then makes the session factory for you. This works for both normal and async engines.
- `panel.create_tables(engine)` creates Tungsten's own tables, such as roles, notifications and password reset tokens. Your own tables are still yours to create (for example with `Base.metadata.create_all(engine)` or your migration tool).

> [!WARNING]
> Always set `secret_key` to a fixed secret value, for example from an environment variable. It signs the session cookie. If you leave it out, Tungsten makes a random key on every start, so everyone is signed out when the app restarts.

Without an `auth=` setting, the panel has no login and anyone who can reach the URL can use it. That is fine to try things out, but not for real use. Turn on login as shown below.

## Requirements for the user model

To turn on login, pass your user model to `Auth`:

```python
from tungsten import Auth

panel = Panel(
    path="/admin",
    session_factory=SessionLocal,
    secret_key="change-me",
    auth=Auth(User),
)
```

The user model needs:

| Attribute | Default name | Used for |
| --- | --- | --- |
| Primary key | any (`id`) | Remembering who is signed in. |
| Login field | `email` | The address users sign in with. Matched without caring about upper or lower case. |
| Password field | `password` | The **hashed** password, never the plain one. |
| Name field | `name` | The name shown in the user menu. Falls back to the email. |

A minimal user model looks like this:

```python
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password: Mapped[str] = mapped_column(String(255))  # stores the hash
```

If your columns have other names, tell `Auth`:

```python
Auth(User, email_field="username", password_field="password_hash", name_field="full_name")
```

Two more optional settings use your model:

- `avatar_field="avatar"` shows the user's picture in the user menu.
- `active_field="is_active"` blocks sign-in for users where that field is false.

Passwords are hashed with PBKDF2-SHA256. Use `tungsten.hash_password("secret")` when you create users in your own code, or create the first user with the CLI:

```bash
tungsten make:user --panel main:panel
```

See [Authentication](authentication) for sign-up, password reset, two-factor login and custom password hashers, and [CLI](cli) for all `make:user` options.

## Install from source

To work on Tungsten itself, or to run the demo, clone the repository and install it in editable mode with the development extras:

```bash
git clone https://github.com/Prism-Infoways/Tungsten.git
cd Tungsten
pip install -e ".[dev]"
```

The `dev` extra adds pytest, httpx, uvicorn, openpyxl, `sqlalchemy[asyncio]` and aiosqlite. See [Demo app](demo-app) to run the shop demo.

## Next steps

- [Quick start](quick-start): build a small panel with a resource, a form and a table.
- [Panel configuration](panel-configuration): every `Panel(...)` option.
