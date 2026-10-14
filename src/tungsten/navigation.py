"""Sidebar navigation: items, groups, badges and clusters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar


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


class Cluster:
    """A group of resources and pages behind one menu item, with their own sub-menu::

        class Settings(Cluster):
            icon = "settings"
            navigation_group = "Admin"

        class TaxResource(Resource):
            model = Tax
            cluster = Settings

    The menu shows one "Settings" item. It opens the first page of the cluster, and every page
    of the cluster shows the cluster's sub-menu (on the side, or as tabs with
    ``sub_navigation_position = "top"``). ``/admin/settings`` also opens the first page.
    """

    slug: ClassVar[str | None] = None
    label: ClassVar[str | None] = None
    icon: ClassVar[str | None] = "squares-2x2"
    active_icon: ClassVar[str | None] = None
    navigation_group: ClassVar[str | None] = None
    navigation_label: ClassVar[str | None] = None
    navigation_sort: ClassVar[int] = 0
    #: ``"start"`` (beside the page), ``"end"`` or ``"top"`` (tabs above it)
    sub_navigation_position: ClassVar[str] = "start"
    #: a short line under the cluster's name in the sub-menu
    description: ClassVar[str | None] = None

    @classmethod
    def get_slug(cls) -> str:
        return cls.slug or re.sub(r"(?<!^)(?=[A-Z])", "-", cls.__name__).lower()

    @classmethod
    def get_label(cls) -> str:
        from .i18n import translate as __
        from .support.component import headline

        return __(cls.label or headline(cls.get_slug().replace("-", "_")))

    @classmethod
    def get_navigation_label(cls) -> str:
        from .i18n import translate as __

        return __(cls.navigation_label) if cls.navigation_label else cls.get_label()
