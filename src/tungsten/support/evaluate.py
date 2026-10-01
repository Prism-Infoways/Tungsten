"""Call user closures with arguments injected by parameter name.

Like Filament, any option can be a plain value or a function. When it is a
function, Tungsten looks at the parameter names and passes in what it asks
for, e.g. ``lambda get, record: ...``.
"""

from __future__ import annotations

import inspect
from functools import lru_cache
from typing import Any, Callable


@lru_cache(maxsize=4096)
def _signature(fn: Callable) -> tuple[tuple[str, ...], bool]:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return (), True
    names: list[str] = []
    var_kw = False
    for p in sig.parameters.values():
        if p.kind is p.VAR_KEYWORD:
            var_kw = True
        elif p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY):
            names.append(p.name)
    return tuple(names), var_kw


def call(fn: Callable, **available: Any) -> Any:
    """Call ``fn`` passing only the keyword arguments it declares."""
    try:
        names, var_kw = _signature(fn)
    except TypeError:  # unhashable callable
        names, var_kw = _signature.__wrapped__(fn)
    if var_kw:
        return fn(**available)
    kwargs = {}
    for name in names:
        if name in available:
            kwargs[name] = available[name]
    return fn(**kwargs)


def evaluate(value: Any, **available: Any) -> Any:
    """Return ``value``, or the result of calling it if it is callable."""
    if callable(value) and not isinstance(value, type):
        return call(value, **available)
    return value
