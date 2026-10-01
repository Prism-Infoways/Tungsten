"""Base class shared by form fields, layouts, table columns, actions, etc."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from .evaluate import evaluate

T = TypeVar("T", bound="Component")


def headline(name: str) -> str:
    """``customer_id`` -> ``Customer``, ``created_at`` -> ``Created at``."""
    name = name.split(".")[-1]
    if name.endswith("_id"):
        name = name[:-3]
    words = name.replace("-", " ").replace("_", " ").strip()
    return words[:1].upper() + words[1:]


class Component:
    """Fluent, chainable configuration object. Options may be values or closures."""

    def __init__(self) -> None:
        self._visible: Any = True
        self._hidden: Any = False
        self._extra_attributes: dict[str, Any] = {}
        self._meta: dict[str, Any] = {}

    @classmethod
    def make(cls: type[T], *args: Any, **kwargs: Any) -> T:
        return cls(*args, **kwargs)

    def visible(self: T, condition: bool | Callable = True) -> T:
        self._visible = condition
        return self

    def hidden(self: T, condition: bool | Callable = True) -> T:
        self._hidden = condition
        return self

    def extra_attributes(self: T, attributes: dict[str, Any]) -> T:
        self._extra_attributes.update(attributes)
        return self

    def meta(self: T, key: str, value: Any) -> T:
        self._meta[key] = value
        return self

    def is_visible(self, **ev: Any) -> bool:
        if evaluate(self._hidden, **ev):
            return False
        return bool(evaluate(self._visible, **ev))

    def tap(self: T, fn: Callable[[T], Any]) -> T:
        fn(self)
        return self
