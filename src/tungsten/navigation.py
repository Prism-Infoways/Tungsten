"""Sidebar navigation: items, groups and badges."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class NavigationItem:
    label: str
    url: str = "#"
    icon: str | None = None
    group: str | None = None
    sort: int = 0
    badge: Any = None
    badge_color: str = "primary"
    active: bool = False
    parent: str | None = None
    #: path prefix that marks this item active (defaults to its url)
    active_prefix: str | None = None
    new_tab: bool = False
    visible: Callable | bool = True
    children: list["NavigationItem"] = field(default_factory=list)

    @property
    def expanded(self) -> bool:
        return self.active or any(c.active for c in self.children)


@dataclass
class NavigationGroup:
    label: str
    icon: str | None = None
    collapsible: bool = True
    collapsed: bool = False
    items: list[NavigationItem] = field(default_factory=list)
