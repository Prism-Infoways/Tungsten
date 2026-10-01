"""Helpers for nested form state addressed by dotted paths (``items.0.name``)."""

from __future__ import annotations

from typing import Any

_MISSING = object()


def split(path: str) -> list[str]:
    return [p for p in path.split(".") if p != ""]


def join(*parts: Any) -> str:
    return ".".join(str(p) for p in parts if p not in (None, ""))


def get_path(data: Any, path: str, default: Any = None) -> Any:
    cur = data
    for part in split(path):
        if isinstance(cur, dict):
            cur = cur.get(part, _MISSING)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                cur = _MISSING
        else:
            cur = getattr(cur, part, _MISSING)
        if cur is _MISSING:
            return default
    return cur


def set_path(data: dict, path: str, value: Any) -> None:
    parts = split(path)
    cur: Any = data
    for i, part in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        if isinstance(cur, list):
            idx = int(part)
            while len(cur) <= idx:
                cur.append({})
            if not isinstance(cur[idx], (dict, list)):
                cur[idx] = [] if nxt.isdigit() else {}
            cur = cur[idx]
        else:
            if part not in cur or not isinstance(cur[part], (dict, list)):
                cur[part] = [] if nxt.isdigit() else {}
            cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        idx = int(last)
        while len(cur) <= idx:
            cur.append(None)
        cur[idx] = value
    else:
        cur[last] = value


class Getter:
    """The ``get`` callable passed to closures: ``get("state")`` reads a sibling.

    Paths are relative to the current container (e.g. a repeater row). Use
    ``get("../field")`` to go up a level, or a leading ``/`` for absolute.
    """

    def __init__(self, data: dict, base: str = "") -> None:
        self._data = data
        self._base = base

    def resolve(self, path: str) -> str:
        if path.startswith("/"):
            return path.lstrip("/").replace("/", ".")
        base = split(self._base)
        for part in path.split("/"):
            if part == "..":
                # leave a repeater row: drop the row index and the repeater name
                if base and base[-1].isdigit():
                    base.pop()
                if base:
                    base.pop()
            elif part:
                base.extend(split(part))
        return ".".join(base)

    def __call__(self, path: str, default: Any = None) -> Any:
        return get_path(self._data, self.resolve(path), default)


class Setter:
    """The ``set`` callable passed to closures: ``set("slug", slugify(state))``."""

    def __init__(self, data: dict, base: str = "") -> None:
        self._data = data
        self._getter = Getter(data, base)

    def __call__(self, path: str, value: Any) -> None:
        set_path(self._data, self._getter.resolve(path), value)
