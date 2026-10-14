"""Live push: send notifications to open browser tabs over a WebSocket.

Each signed-in tab opens ``/_tw/live``. :meth:`Notification.broadcast` and
:meth:`Notification.send_to_database` hand messages to the panel's
broadcaster, which forwards them to that user's open tabs straight away.

The default :class:`Broadcaster` keeps connections in memory, so it reaches
tabs served by the same process. When you run several workers or servers,
subclass it and pass messages through a shared channel (Redis pub/sub,
Postgres ``LISTEN/NOTIFY`` ...): override :meth:`Broadcaster.publish` to send
to the channel and call :meth:`Broadcaster.deliver` in every process when a
message arrives. Without live push the bell still updates by polling.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator


class Broadcaster:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        #: user id -> open connections, each its own queue on the loop that serves it
        self._subscribers: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}

    def publish(self, user_id: Any, message: dict[str, Any]) -> None:
        """Send ``message`` to every open tab of ``user_id``. Safe from any thread or event loop."""
        self.deliver(user_id, message)

    def deliver(self, user_id: Any, message: dict[str, Any]) -> None:
        """Put ``message`` on this process's connections for ``user_id``."""
        with self._lock:
            targets = list(self._subscribers.get(str(user_id), ()))
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(_put, queue, message)
            except RuntimeError:  # that loop has closed: the tab is gone
                pass

    def connected(self, user_id: Any) -> int:
        """How many tabs of ``user_id`` this process serves right now."""
        with self._lock:
            return len(self._subscribers.get(str(user_id), ()))

    @asynccontextmanager
    async def subscribe(self, user_id: Any) -> AsyncIterator[asyncio.Queue]:
        """A queue that receives the messages for ``user_id`` while the ``async with`` block runs."""
        entry = (asyncio.get_running_loop(), asyncio.Queue(maxsize=200))
        key = str(user_id)
        with self._lock:
            self._subscribers.setdefault(key, set()).add(entry)
        try:
            yield entry[1]
        finally:
            with self._lock:
                subs = self._subscribers.get(key)
                if subs is not None:
                    subs.discard(entry)
                    if not subs:
                        del self._subscribers[key]


def _put(queue: asyncio.Queue, message: dict[str, Any]) -> None:
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:  # a tab that stopped reading: drop rather than grow without end
        pass
