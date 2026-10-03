---
title: Async database
description: Run Tungsten on an async SQLAlchemy engine, write async closures and hooks, and create tables with or without an event loop.
---

Tungsten works with a normal SQLAlchemy engine and with an async one (`create_async_engine`). Your resources, forms, tables and closures stay exactly the same. You only change how the panel connects.

## Installing

Install the `async` extra and an async database driver:

```bash
pip install "tungsten-admin[async]" asyncpg        # PostgreSQL
pip install "tungsten-admin[async]" aiosqlite      # SQLite
```

## Using an async engine

Pass the async engine to the panel with `engine=`:

```python
from sqlalchemy.ext.asyncio import create_async_engine
from tungsten import Auth, Panel

engine = create_async_engine("postgresql+asyncpg://shop:secret@localhost/shop")

panel = Panel(
    engine=engine,
    secret_key="...",
    auth=Auth(User),
)
panel.resources([ProductResource, OrderResource])
```

Tungsten makes an `async_sessionmaker` for you (with `expire_on_commit=False`). You can also pass your own:

```python
from sqlalchemy.ext.asyncio import async_sessionmaker

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
panel = Panel(session_factory=SessionLocal, ...)
```

`panel.is_async` tells you which mode the panel is in.

For comparison, the sync version is either of these:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine("postgresql+psycopg://shop:secret@localhost/shop")
panel = Panel(engine=engine, ...)
# or
panel = Panel(session_factory=sessionmaker(engine, expire_on_commit=False), ...)
```

## How it works

Tungsten's request handlers are normal (sync) Python functions. What changes is where they run:

| Engine | Where handlers run |
| --- | --- |
| Sync engine | In a worker thread from a thread pool, with a normal `Session` |
| Async engine | On the event loop, inside SQLAlchemy's `AsyncSession.run_sync()` |

`run_sync()` gives the handler a normal sync `Session` that talks to the async driver underneath. This means:

- **Your closures still get a normal `db` session.** You write `db.scalar(...)`, `db.scalars(...)`, `db.add(...)`, `db.commit()` without `await`, in both modes.
- **Lazy loading keeps working.** `record.category.name` loads the category on demand, even on an async engine.
- **Slow work is moved off the event loop.** Password hashing and saving uploaded files run in a worker thread, so they don't block other requests.

So the same resource works with both engines:

```python
class OrderResource(Resource):
    model = Order

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).where(Order.status == "pending"))
```

## Async closures and hooks

Any closure or hook that Tungsten calls can be an `async def` function. Tungsten awaits it. This works in both modes.

```python
import httpx


class OrderResource(Resource):
    model = Order

    @classmethod
    async def after_create(cls, record, db):
        async with httpx.AsyncClient() as client:
            await client.post("https://hooks.acme.example/orders", json={"number": record.number})
```

```python
async def fetch_cities(get):
    async with httpx.AsyncClient() as client:
        r = await client.get("https://api.acme.example/cities", params={"state": get("state")})
    return r.json()


Select("city").options(fetch_cities)
```

This covers options and visibility closures, resource hooks (`before_create`, `after_save`...), action callbacks, widget data methods (`stats()`, `data()`, `items()`), page `mount()` and `save()`, the `Auth` mailer, `gate`, `can_access` and `on_register`, render hooks and more.

> [!NOTE]
> Inside an `async def` closure, `db` is still the normal sync session. Use it without `await`. Use `await` for your own async work, like HTTP calls.

Some methods are called directly instead of as closures, so they must stay plain functions: resource [policy](roles-and-permissions#policies) methods, `Plugin.register()` and `boot()`, and the `Importer` class methods.

### Don't block the event loop

With an async engine, handlers run on the event loop. Slow sync code in a closure (like `time.sleep()`, `requests.get()` or `smtplib`) pauses every other request until it finishes. Use an `async def` closure with an async library instead:

```python
import aiosmtplib
from email.message import EmailMessage


async def send_mail(to, subject, body):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "no-reply@acme.example", to, subject
    msg.set_content(body)
    await aiosmtplib.send(msg, hostname="smtp.acme.example", port=587, start_tls=True,
                          username="no-reply@acme.example", password="smtp-password")


Auth(User, mailer=send_mail)
```

With a sync engine this isn't a problem, because each request has its own worker thread.

## Creating tables

`panel.create_tables()` creates Tungsten's own tables (roles, notifications, password resets, two-factor and the activity log). It works with both engine types:

```python
panel.create_tables()          # uses the panel's engine
panel.create_tables(engine)    # or pass one
```

With an async engine, `create_tables()` starts its own event loop. That only works **outside** a running loop, for example at the top of a script. Inside async code, such as FastAPI's lifespan, use `acreate_tables()`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)   # your own tables
    await panel.acreate_tables()                        # Tungsten's tables
    yield


app = FastAPI(lifespan=lifespan)
panel.mount(app)
```

| Method | Use it |
| --- | --- |
| `panel.create_tables(engine=None)` | From sync code: a script, a CLI, module level. Works with both engines. |
| `await panel.acreate_tables(engine=None)` | From async code, with an async engine. |

If you pass `session_factory=` instead of `engine=`, Tungsten finds the engine through the session factory's `bind`.

## Scripts and the CLI

For seed scripts, cron jobs or a quick check in a shell, use `panel.with_session()`. It runs your function with a normal sync session and returns its result:

```python
from sqlalchemy import func, select

count = panel.with_session(lambda db: db.scalar(select(func.count()).select_from(Product)))
print(f"{count} products")


def add_admin(db):
    db.add(User(name="Asha", email="asha@example.com", password=hash_password("secret123")))
    db.commit()


panel.with_session(add_admin)
```

It works with both engine types. With an async engine it starts a private event loop, so call it from sync code only, never inside a running event loop.

The `tungsten make:user` command uses `with_session()`, so it works with async panels too.

### Keeping a sync engine for scripts

You don't need a sync engine for Tungsten. But for migrations or a big seed script it can be simpler to use a plain sync engine next to the async one. The shop demo does this: it creates its own tables and seeds data with a sync engine, and runs the panel on an async one.

```python
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

sync_engine = create_engine("sqlite:///shop.db")
Base.metadata.create_all(sync_engine)

panel = Panel(engine=create_async_engine("sqlite+aiosqlite:///shop.db"), ...)
panel.create_tables(sync_engine)    # works at module level with either engine
```

## Trying it in the demo

The demo runs on an async engine when `DATABASE_URL` uses an async driver:

```bash
python -m examples.shop.seed
DATABASE_URL=sqlite+aiosqlite:///shop.db uvicorn examples.shop.app:app --reload
```

## Testing

Use FastAPI's `TestClient` as usual. It runs the app's event loop for you, so async panels need no special handling in tests:

```python
from fastapi.testclient import TestClient


def test_products_page():
    client = TestClient(app)
    r = client.get("/admin/login")
    assert r.status_code == 200
```

Tungsten's own test suite can run every test on both engine types. If you work on Tungsten itself:

```bash
pip install -e ".[dev]"
pytest                         # sync engine
TUNGSTEN_TEST_ASYNC=1 pytest   # the same tests on an async engine (aiosqlite)
```

You can use the same idea in your own project: read an environment variable in your test fixture and build the panel with a sync or an async engine, so one test suite covers both.
