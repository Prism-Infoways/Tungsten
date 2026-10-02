"""Glue between Tungsten's sync handlers and async code.

Tungsten handlers are plain sync functions. They run either in a worker
thread (sync engine) or inside SQLAlchemy's ``AsyncSession.run_sync`` on the
event loop (async engine). These helpers let sync code wait for a coroutine,
and move slow CPU or disk work off the event loop, in both cases.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

try:  # SQLAlchemy ships greenlet glue; it is only usable when greenlet is installed
    from sqlalchemy.util.concurrency import await_only, in_greenlet
except ImportError:  # pragma: no cover
    await_only = None  # type: ignore[assignment]

    def in_greenlet() -> bool:  # type: ignore[misc]
        return False


async def _await(awaitable: Any) -> Any:
    return await awaitable


def in_async_session() -> bool:
    """True when running inside ``AsyncSession.run_sync`` (async engine mode)."""
    try:
        return bool(in_greenlet())
    except Exception:  # pragma: no cover
        return False


def resolve(value: Any) -> Any:
    """Return ``value``, waiting for it first if it is a coroutine (``async def`` closures)."""
    if not inspect.isawaitable(value):
        return value
    if in_async_session():
        return await_only(value)  # type: ignore[misc]
    import anyio.from_thread

    try:
        return anyio.from_thread.run(_await, value)
    except RuntimeError:
        # not in a worker thread (e.g. a script or the CLI): run a private loop
        import asyncio

        return asyncio.run(_await(value))


def blocking(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """Run slow sync work (password hashing, file writes) without blocking the event loop."""
    if not in_async_session():
        return fn(*args, **kwargs)
    import functools

    import anyio.to_thread

    return await_only(anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs)))  # type: ignore[misc]


def is_async_engine(obj: Any) -> bool:
    try:
        from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
    except ImportError:  # pragma: no cover
        return False
    return isinstance(obj, (AsyncEngine, async_sessionmaker))


__all__ = ["blocking", "in_async_session", "is_async_engine", "resolve"]
