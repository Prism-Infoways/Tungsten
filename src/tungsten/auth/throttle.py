"""Counting failed sign-ins (and two-factor codes) per key, to refuse guessing."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Protocol


class ThrottleStore(Protocol):
    """Where failed attempts are counted. Swap it (``Auth(throttle=...)``) to share counts between processes."""

    def failures(self, key: str, seconds: float) -> int:
        """Failed attempts for ``key`` in the last ``seconds``."""

    def fail(self, key: str) -> None:
        """Record one failed attempt for ``key``."""

    def clear(self, key: str) -> None:
        """Forget ``key`` (after a successful sign-in)."""


class MemoryThrottle:
    """Counts in this process's memory.

    Keys without recent attempts are removed, and at most ``max_keys`` keys are kept (the oldest go first), so
    sign-ins with ever new emails cannot grow memory without limit. Each server process has its own counts: with
    several workers the real limit is ``max_login_attempts`` times the number of workers.
    """

    def __init__(self, window: float = 60, max_keys: int = 10_000) -> None:
        self.window = window
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float, seconds: float) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and hits[0] <= now - seconds:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def failures(self, key: str, seconds: float) -> int:
        with self._lock:
            hits = self._prune(key, time.monotonic(), seconds)
            return len(hits) if hits else 0

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.pop(key, None) or deque()
            hits.append(now)
            self._hits[key] = hits  # re-inserted, so the dict stays ordered by last attempt
            if len(self._hits) > self.max_keys:
                for k in list(self._hits):
                    if self._prune(k, now, self.window) is not None:
                        break  # the rest attempted more recently
                while len(self._hits) > self.max_keys:
                    del self._hits[next(iter(self._hits))]

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def __len__(self) -> int:
        return len(self._hits)
