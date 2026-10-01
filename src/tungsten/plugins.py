"""Plugins bundle resources, pages, widgets, routes and render hooks.

    class BlogPlugin(Plugin):
        id = "blog"

        def register(self, panel):
            panel.resources([PostResource, CategoryResource])
            panel.navigation_group("Blog", icon="newspaper")

        def boot(self, panel):
            panel.render_hook("sidebar.footer", lambda: Markup("<p>Blog v1</p>"))

    panel.plugin(BlogPlugin())
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .panel import Panel


class Plugin:
    id: str = "plugin"

    def register(self, panel: "Panel") -> None:
        """Called when the plugin is added: register resources, pages, widgets."""

    def boot(self, panel: "Panel") -> None:
        """Called once before the panel starts serving requests."""

    def permissions(self) -> list[tuple[str, str]]:
        """Extra ``(permission, label)`` pairs shown in the Roles screen."""
        return []
