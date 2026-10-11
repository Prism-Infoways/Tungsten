"""Quick Create plugin for Tungsten: a "+ New" button in the top bar.

    from tungsten_quick_create import QuickCreatePlugin

    panel.plugin(QuickCreatePlugin())

The button lists every resource the signed-in user may create (your own and
those of other plugins: leads, tickets, employees, invoices, posts...). Picking
one opens its create form in a side panel, so a record can be added from any
page without losing your place.

Other plugins add their own entries with :meth:`QuickCreatePlugin.add_link`, and
a resource leaves the menu with ``quick_create = False``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from markupsafe import Markup

from tungsten import Notification, Plugin
from tungsten.forms.form import ValidationError
from tungsten.i18n import translate as __
from tungsten.routes import Forbidden, NotFound, Routes
from tungsten.support.evaluate import call

__version__ = "0.1.0"

log = logging.getLogger("tungsten.quick_create")

WIDTHS = ("sm", "md", "lg", "xl", "2xl", "3xl", "4xl", "5xl")
FORM_ID = "tw-quick-create-form"


@dataclass
class QuickLink:
    """An extra menu entry that is a plain link (another plugin's "New event", "Upload file"...)."""

    key: str
    label: str
    url: str | Callable[..., str]
    icon: str | None = None
    group: str | None = None
    sort: int = 0
    #: ``visible(ctx=..., user=...)``: hide the entry for some users
    visible: Callable[..., Any] | bool = True


class QuickCreatePlugin(Plugin):
    """``QuickCreatePlugin(include=None, exclude=(), label="New", ...)``.

    - ``include`` lists the resources (classes or slugs) to show, in that order. Default: every one.
    - ``exclude`` hides resources (classes or slugs).
    - ``label`` / ``icon`` style the top bar button. ``label=""`` shows the icon alone.
    - ``slide_over`` opens forms in a side panel (``False``: a centred popup); ``width`` is its size.
    - ``create_another`` adds a "Create & create another" button.
    - ``open_after_create`` goes to the new record after saving instead of staying on the page.
    - ``group`` splits the menu by navigation group; ``search_from`` shows a filter box once the
      menu has that many entries.
    - ``shortcut`` opens the menu from the keyboard, e.g. ``"mod+shift+n"``.
    """

    id = "quick-create"
    templates = Path(__file__).with_name("templates")

    def __init__(self, include: Iterable[Any] | None = None, exclude: Iterable[Any] = (), label: str = "New",
                 icon: str = "plus", slide_over: bool = True, width: str = "4xl", create_another: bool = True,
                 open_after_create: bool = False, group: bool = True, search_from: int = 8,
                 shortcut: str | None = None) -> None:
        if width not in WIDTHS:
            raise ValueError(f"width must be one of {', '.join(WIDTHS)}")
        self.include = list(include) if include is not None else None
        self.exclude = list(exclude)
        self.label = label
        self.icon = icon
        self.slide_over = slide_over
        self.width = width
        self.create_another = create_another
        self.open_after_create = open_after_create
        self.group = group
        self.search_from = search_from
        self.shortcut = shortcut
        self.links: dict[str, QuickLink] = {}
        self.panel: Any = None

    # ------------------------------------------------------------------ hooks for other code
    def add_link(self, key: str, label: str, url: str | Callable[..., str], icon: str | None = None,
                 group: str | None = None, sort: int = 0, visible: Callable[..., Any] | bool = True) -> None:
        """Add a menu entry that opens ``url`` (a string, or ``url(ctx=...)``). The same ``key`` replaces it."""
        self.links[key] = QuickLink(key, label, url, icon, group, sort, visible)

    def remove_link(self, key: str) -> None:
        self.links.pop(key, None)

    #: how many "New ..." shortcuts the installed app gets (phones show about four)
    pwa_shortcut_limit = 4

    def pwa_shortcuts(self, panel: Any) -> list[dict[str, str]]:
        """App shortcuts for tungsten-pwa: "New ..." for the first resources, then plain links.

        They open the normal create page, which checks the user's permissions as always.
        """
        out = [{"name": __("New :label", label=r.get_label()), "url": panel.url(r.get_slug(), "create")}
               for r in self.resources() if r.has_page("create")]
        out += [{"name": __(link.label), "url": link.url} for link in sorted(self.links.values(), key=lambda l: l.sort)
                if isinstance(link.url, str) and link.visible is True]
        return out[:self.pwa_shortcut_limit]

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        panel.render_hook("topbar.end", self._button)
        panel.routes(self._routes)

    # ------------------------------------------------------------------ which resources
    @staticmethod
    def _matches(resource: Any, ref: Any) -> bool:
        return resource is ref or (isinstance(ref, str) and resource.get_slug() == ref)

    def resources(self) -> list[Any]:
        """Resources that can be quick-created at all (before checking the user's permissions)."""
        found = [r for r in self.panel.get_resources()
                 if "create" in r.pages and getattr(r, "quick_create", True) is not False
                 and not any(self._matches(r, ref) for ref in self.exclude)]
        if self.include is None:
            return found
        ordered = []
        for ref in self.include:
            for r in found:
                if self._matches(r, ref) and r not in ordered:
                    ordered.append(r)
        return ordered

    def allowed(self, ctx: Any, resource: Any) -> bool:
        """The user may open the list (live form updates need it) and create."""
        try:
            return bool(resource.can(ctx, "view_any") and resource.can(ctx, "create"))
        except Exception:  # a broken policy hides one entry, not the whole top bar
            log.exception("Quick create: permission check failed for %s", resource.get_slug())
            return False

    def items(self, ctx: Any) -> list[dict[str, Any]]:
        """The menu entries for this user: ``{"label", "icon", "group", "url" | "modal_url"}``."""
        out: list[dict[str, Any]] = []
        for n, r in enumerate(self.resources()):
            if not self.allowed(ctx, r):
                continue
            sort = n if self.include is not None else r.navigation_sort
            out.append({"key": r.get_slug(), "label": r.get_label(), "icon": r.icon or "file-text",
                        "group": r.navigation_group, "sort": sort,
                        "modal_url": self.panel.url("_quick-create", r.get_slug())})
        for link in self.links.values():
            try:
                shown = call(link.visible, ctx=ctx, user=ctx.user) if callable(link.visible) else link.visible
                if not shown:
                    continue
                url = call(link.url, ctx=ctx, user=ctx.user) if callable(link.url) else link.url
            except Exception:
                log.exception("Quick create: link %r failed", link.key)
                continue
            if url:
                out.append({"key": link.key, "label": __(link.label), "icon": link.icon or "plus",
                            "group": link.group, "sort": link.sort, "url": url})
        if self.include is None:
            out.sort(key=lambda i: (i["sort"], i["label"].lower()))
        return out

    def grouped(self, items: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
        """Entries split by navigation group, in the order the sidebar shows the groups."""
        if not self.group:
            return [("", items)]
        order = [g.label for g in self.panel._nav_groups]
        groups: dict[str, list] = {}
        for item in items:
            groups.setdefault(item["group"] or "", []).append(item)
        if len(groups) < 2:
            return [("", items)]
        rank = {label: n for n, label in enumerate(order)}
        keys = sorted(groups, key=lambda g: (g != "", rank.get(g, len(rank)), g))
        return [(__(g) if g else "", groups[g]) for g in keys]

    # ------------------------------------------------------------------ top bar button
    def _button(self, ctx: Any) -> Markup:
        if ctx.user is None and self.panel.auth.enabled:
            return Markup("")
        try:
            items = self.items(ctx)
        except Exception:  # never break every page because of the menu
            log.exception("Quick create: could not build the menu")
            return Markup("")
        if not items:
            return Markup("")
        return Markup(self.panel.renderer.render(
            "tungsten_quick_create/button.html", plugin=self, groups=self.grouped(items), count=len(items),
            all_labels=[i["label"].lower() for i in items],
            label=__(self.label) if self.label else "", ctx=ctx, panel=self.panel))

    # ------------------------------------------------------------------ routes
    def _routes(self, app: Any, panel: Any) -> None:
        routes = Routes(panel)
        plugin = self

        @app.get("/_quick-create/{slug}")
        async def quick_create_open(request: Request, slug: str):
            return await routes.run(request, plugin.handle, slug=slug)

        @app.post("/_quick-create/{slug}")
        async def quick_create_save(request: Request, slug: str):
            return await routes.run(request, plugin.handle, read_form=True, slug=slug)

    def _resource(self, ctx: Any, slug: str) -> Any:
        resource = next((r for r in self.resources() if r.get_slug() == slug), None)
        if resource is None:
            raise NotFound()
        if not self.allowed(ctx, resource):
            raise Forbidden()
        return resource

    def _form(self, ctx: Any, resource: Any) -> Any:
        form = resource.host().form(ctx, "create")
        form.id = FORM_ID
        return form

    def handle(self, ctx: Any, fd: Any, slug: str) -> Response:
        resource = self._resource(ctx, slug)
        host = resource.host()
        form = self._form(ctx, resource)
        if fd is None:
            form.fill()
            return self._modal(ctx, resource, form)
        form.load(fd)
        try:
            data = form.validate()
        except ValidationError:
            return self._modal(ctx, resource, form)
        try:
            record = host.create(ctx, data, form)
            self.panel.log_activity(ctx, "created", record)
            ctx.db.commit()
        except ValidationError as exc:  # a resource hook refused the data
            ctx.db.rollback()
            form.errors = exc.errors
            return self._modal(ctx, resource, form)
        except (NotFound, Forbidden, PermissionError):
            raise
        except Exception:
            ctx.db.rollback()
            log.exception("Quick create: could not save %s", slug)
            Notification("Not saved").body("Something went wrong while saving. Please check the form and try again.") \
                .danger().send(ctx)
            return self._modal(ctx, resource, form)
        link = self._record_url(ctx, resource, record)
        note = Notification("Created").body(__(":label was created.", label=resource.get_label())).success()
        if link and not self.open_after_create:
            note.action(__("Open"), link)
        note.send(ctx)
        if self.open_after_create and link:
            return ctx.go(link)
        ctx.dispatch("tw-refresh")  # tables on the page behind show the new record
        if fd.get("_tw_another") and self.create_another:
            fresh = self._form(ctx, resource)
            fresh.fill()
            return self._modal(ctx, resource, fresh)
        ctx.dispatch("tw-close-modal")
        return ctx.html("")

    @staticmethod
    def _record_url(ctx: Any, resource: Any, record: Any) -> str | None:
        host = resource.host()
        try:
            if resource.has_page("view") and resource.can(ctx, "view", record):
                return host.view_url(ctx, record)
            if resource.has_page("edit") and resource.can(ctx, "update", record):
                return host.edit_url(ctx, record)
        except Exception:
            log.exception("Quick create: could not link to the new record")
        return None

    def _live_note(self, ctx: Any) -> str | None:
        """With the environment indicator plugin on live, say so in the form, so nobody adds test data there."""
        indicator = self.panel.get_plugin("environment-indicator")
        if indicator is None or not hasattr(indicator, "current"):
            return None
        try:
            env = indicator.current(ctx)
        except Exception:  # never break the form because of the note
            log.exception("Quick create: could not read the environment")
            return None
        if getattr(env, "is_production", False):
            return __("You are on :env. This record goes into real data.", env=env.label)
        return None

    def _modal(self, ctx: Any, resource: Any, form: Any) -> Response:
        m = {
            "endpoint": self.panel.url("_quick-create", resource.get_slug()),
            "heading": __("Create :label", label=resource.get_label().lower()),
            "description": self._live_note(ctx),
            "icon": resource.icon,
            "icon_color": "primary",
            "submit_label": __("Create"),
            "cancel_label": __("Cancel"),
            "color": "primary",
            "width": self.width,
            "slide_over": self.slide_over,
            "confirm_only": False,
            "content": None,
            "multipart": False,
            "create_another_label": __("Create & create another") if self.create_another else None,
        }
        html = self.panel.renderer.render("tungsten/actions/modal.html", m=m, form=form, hidden={}, records=[],
                                          ctx=ctx)
        return ctx.html(html)


__all__ = ["QuickCreatePlugin", "QuickLink"]
