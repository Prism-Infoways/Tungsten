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
    #: icon shown instead of ``icon`` while the item is the current page
    active_icon: str | None = None

    @property
    def current_icon(self) -> str | None:
        return self.active_icon if self.active and self.active_icon else self.icon

    @property
    def expanded(self) -> bool:
        return self.active or any(c.active for c in self.children)


@dataclass
class NavigationGroup:
    label: str
    icon: str | None = None
    #: users can fold the group by clicking its label
    collapsible: bool = True
    #: the group starts folded (only when collapsible); it opens by itself when it holds the current page
    collapsed: bool = False
    items: list[NavigationItem] = field(default_factory=list)

    @property
    def starts_open(self) -> bool:
        if not (self.collapsible and self.collapsed):
            return True
        return any(i.expanded for i in self.items)
