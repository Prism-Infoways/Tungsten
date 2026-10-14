"""Failed sign-in counting does not grow memory without limit and can be shared (issue #72)."""

from __future__ import annotations

from tungsten import Auth
from tungsten.auth.throttle import MemoryThrottle


def test_empty_keys_are_removed(monkeypatch):
    t = MemoryThrottle()
    now = [1000.0]
    monkeypatch.setattr("tungsten.auth.throttle.time.monotonic", lambda: now[0])
    for i in range(500):
        t.fail(f"1.2.3.4|u{i}@x.com")
    assert len(t) == 500
    now[0] += 61
    for i in range(500):
        assert t.failures(f"1.2.3.4|u{i}@x.com", 60) == 0
    assert len(t) == 0


def test_key_count_is_bounded(monkeypatch):
    t = MemoryThrottle(max_keys=100)
    now = [0.0]
    monkeypatch.setattr("tungsten.auth.throttle.time.monotonic", lambda: now[0])
    for i in range(5000):
        now[0] += 0.001
        t.fail(f"ip|u{i}")
    assert len(t) <= 100
    assert t.failures("ip|u4999", 60) == 1  # the newest are kept


def test_limit_and_clear():
    auth = Auth(object(), max_login_attempts=3)
    for _ in range(2):
        auth.failed_attempt("k")
    assert not auth.throttled("k")
    auth.failed_attempt("k")
    assert auth.throttled("k")
    auth.throttle.clear("k")
    assert not auth.throttled("k")


def test_store_is_pluggable():
    class Shared:
        def __init__(self):
            self.counts = {}

        def failures(self, key, seconds):
            return self.counts.get(key, 0)

        def fail(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1

        def clear(self, key):
            self.counts.pop(key, None)

    store = Shared()
    a, b = Auth(object(), throttle=store, max_login_attempts=2), Auth(object(), throttle=store, max_login_attempts=2)
    a.failed_attempt("k")
    b.failed_attempt("k")
    assert a.throttled("k") and b.throttled("k")


def test_reset_attempts_for_one_email():
    auth = Auth(object(), max_login_attempts=1)
    auth.failed_attempt("1.1.1.1|ann@x.com")
    auth.failed_attempt("2.2.2.2|ann@x.com")
    auth.failed_attempt("1.1.1.1|bob@x.com")
    auth.reset_attempts("Ann@x.com")
    assert not auth.throttled("1.1.1.1|ann@x.com") and not auth.throttled("2.2.2.2|ann@x.com")
    assert auth.throttled("1.1.1.1|bob@x.com")
