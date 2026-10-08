"""Plugins bundle resources, pages, widgets, routes and render hooks.

    class BlogPlugin(Plugin):
        id = "blog"

        def register(self, panel):
            panel.resources([PostResource, CategoryResource])
            panel.navigation_group("Blog", icon="newspaper")

        def boot(self, panel):
            panel.render_hook("sidebar.footer", lambda: Markup("<p>Blog v1</p>"))

    panel.plugin(BlogPlugin())

A plugin shipped as its own package can also bring templates, static files,
language files and database tables::

    class BlogPlugin(Plugin):
        id = "blog"
        templates = Path(__file__).with_name("templates")   # render "blog/post.html"
        static = Path(__file__).with_name("static")         # served at panel.plugin_asset("blog", "blog.css")
        lang = Path(__file__).with_name("lang")             # en.json, hi.json ...
        metadata = BlogBase.metadata                        # created by panel.create_tables()
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .panel import Panel


class Plugin:
    id: str = "plugin"
    #: folder of Jinja templates; the panel looks there after your own ``template_dirs``
    templates: str | Path | None = None
    #: folder of static files, served at ``<panel>/plugins/<id>/...``
    static: str | Path | None = None
    #: folder of language files (``en.json``, ``hi.json``...)
    lang: str | Path | None = None
    #: SQLAlchemy ``MetaData`` of the plugin's own tables, created by ``panel.create_tables()``
    metadata: Any = None

    def register(self, panel: "Panel") -> None:
        """Called when the plugin is added: register resources, pages, widgets."""

    def boot(self, panel: "Panel") -> None:
        """Called once before the panel starts serving requests."""

    def mount(self, app: Any, panel: "Panel") -> None:
        """Called by ``panel.mount(app)`` with your main app, before the panel is mounted.

        For routes that must live outside the panel's path, such as ``/.well-known/...``.
        """

    def permissions(self) -> list[tuple[str, str]]:
        """Extra ``(permission, label)`` pairs shown in the Roles screen."""
        return []
