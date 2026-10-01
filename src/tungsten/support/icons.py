"""Server-side SVG icons (Lucide set, bundled as JSON)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from markupsafe import Markup

# Filament-style aliases so ``heroicon-o-users`` style names keep working.
ALIASES = {
    "home": "house",
    "cog": "settings",
    "cog-6-tooth": "settings",
    "pencil-square": "square-pen",
    "trash": "trash-2",
    "magnifying-glass": "search",
    "x-mark": "x",
    "check-circle": "circle-check",
    "x-circle": "circle-x",
    "exclamation-triangle": "triangle-alert",
    "exclamation-circle": "circle-alert",
    "information-circle": "info",
    "shopping-bag": "shopping-bag",
    "user-group": "users",
    "chart-bar": "chart-column",
    "document-text": "file-text",
    "arrow-down-tray": "download",
    "arrow-up-tray": "upload",
    "eye": "eye",
    "bars-3": "menu",
    "funnel": "funnel",
}


@lru_cache(maxsize=1)
def _icons() -> dict[str, str]:
    path = Path(__file__).with_name("icons.json")
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def normalize(name: str) -> str:
    for prefix in ("heroicon-o-", "heroicon-s-", "heroicon-m-", "lucide-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return ALIASES.get(name, name) if name not in _icons() else name


def exists(name: str | None) -> bool:
    return bool(name) and normalize(name) in _icons()


def icon(name: str | None, cls: str = "h-5 w-5", stroke: float = 2) -> Markup:
    """Return an inline ``<svg>`` for ``name`` (empty if unknown)."""
    if not name:
        return Markup("")
    if str(name).lstrip().startswith("<svg"):
        return Markup(name)
    body = _icons().get(normalize(name))
    if body is None:
        body = _icons().get("circle", "")
    return Markup(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" class="{cls}" '
        f'aria-hidden="true">{body}</svg>'
    )
