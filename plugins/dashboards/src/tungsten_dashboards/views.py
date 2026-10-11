"""The Dashboards page, the home page override, and the small routes the editor posts to."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from markupsafe import Markup
from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import Response

from tungsten import Page, Stat, StatsOverviewWidget
from tungsten.actions import Action
from tungsten.forms import Select, TextInput, Toggle
from tungsten.i18n import translate as __
from tungsten.notifications import Notification

from . import service as svc
from .models import CustomDashboard, DashboardItem

if TYPE_CHECKING:  # pragma: no cover
    from tungsten.context import Context

log = logging.getLogger("tungsten.dashboards")

SPAN_CLASS = {1: "md:col-span-1", 2: "md:col-span-2", 3: "md:col-span-3", 4: "md:col-span-4"}


# ---------------------------------------------------------------------- drawing widgets
def error_card(message: str) -> Markup:
    return Markup(
        '<div class="tw-card flex h-full items-center gap-3 p-6 text-sm text-gray-500 dark:text-gray-400">'
        '<span class="text-danger-600">&#9888;</span><span>{}</span></div>').format(__(message))


def widget_class(ctx: "Context", plugin: Any, key: str) -> Any:
    widget = ctx.panel.widget(key)
    if widget is None:
        widget = next((w for w in plugin.extra_widgets if w.get_id() == key), None)
    return widget


def render_item(ctx: "Context", plugin: Any, item: DashboardItem) -> Markup:
    """Draw one widget of a dashboard. A broken widget shows a short message, never an error page."""
    try:
        if item.widget in svc.BUILTINS:
            return render_builtin(ctx, item)
        widget = widget_class(ctx, plugin, item.widget)
        if widget is None:
            return error_card("This widget is no longer available. Its plugin may have been removed.")
        if not svc.safe_can_view(widget, ctx):
            return error_card("You don't have access to this widget.")
        return Markup(widget.render(ctx))
    except Exception:
        log.exception("Dashboard widget %s (item %s) failed", item.widget, item.id)
        try:
            ctx.db.rollback()
        except Exception:
            pass
        return error_card("This widget could not load. Try again later.")


def render_builtin(ctx: "Context", item: DashboardItem) -> Markup:
    settings = item.settings or {}
    renderer = ctx.panel.renderer
    if item.widget == "dashboards.counts":
        stats = []
        for slug in settings.get("resources", []):
            resource = ctx.panel.resource(slug)
            if resource is None or not resource.can(ctx, "view_any"):
                continue
            query = resource.host().scoped_query(ctx, with_trashed=False)
            count = ctx.db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
            stats.append(Stat(resource.get_plural_label(), f"{count:,}").icon(resource.icon or "hash")
                         .url(resource.get_url(ctx)))
        if not stats:
            return error_card("None of the picked lists can be shown.")
        widget = type("DashboardCounts", (StatsOverviewWidget,), {
            "id": f"dash-item-{item.id}", "columns": max(2, min(4, len(stats))),
            "stats": classmethod(lambda cls, ctx: stats)})
        body = widget.render(ctx)
        return renderer.render("tungsten_dashboards/builtin.html", item=item, body=body, ctx=ctx)
    if item.widget == "dashboards.links":
        options = svc.link_options(ctx)
        links = []
        for target in settings.get("links", []):
            if target not in options:
                continue
            kind, _, slug = target.partition(":")
            thing = ctx.panel.resource(slug) if kind == "resource" else ctx.panel.page(slug)
            if thing is None:
                continue
            links.append({"label": options[target], "url": thing.get_url(ctx), "icon": getattr(thing, "icon", None)})
        return renderer.render("tungsten_dashboards/builtin.html", item=item, links=links, ctx=ctx)
    return renderer.render("tungsten_dashboards/builtin.html", item=item, text=settings.get("text", ""), ctx=ctx)


def is_lazy(ctx: "Context", plugin: Any, item: DashboardItem) -> bool:
    if item.widget in svc.BUILTINS:
        return False
    widget = widget_class(ctx, plugin, item.widget)
    return bool(widget is not None and getattr(widget, "lazy", True))


def polling(ctx: "Context", plugin: Any, item: DashboardItem) -> str | None:
    widget = None if item.widget in svc.BUILTINS else widget_class(ctx, plugin, item.widget)
    return getattr(widget, "polling_interval", None) if widget is not None else None


def item_label(ctx: "Context", plugin: Any, item: DashboardItem) -> str:
    if item.title:
        return item.title
    if item.widget in svc.BUILTINS:
        return __(svc.BUILTINS[item.widget][0])
    widget = widget_class(ctx, plugin, item.widget)
    return svc.widget_label(widget) if widget is not None else item.widget


def board(ctx: "Context", plugin: Any, dashboard: CustomDashboard, editing: bool = False) -> Markup:
    """The widget grid of a dashboard (with the edit tools when ``editing``)."""
    items = sorted(dashboard.items, key=lambda i: i.position)
    if not editing:
        items = [i for i in items if i.widget in svc.BUILTINS or _viewable(ctx, plugin, i.widget)]
    return ctx.panel.renderer.render(
        "tungsten_dashboards/board.html", ctx=ctx, plugin=plugin, dashboard=dashboard, items=items,
        editing=editing, span_class=SPAN_CLASS, spans=svc.SPAN_LABELS, render_item=render_item,
        is_lazy=is_lazy, polling=polling, item_label=item_label, url=lambda *p, **q: plugin.url(ctx, *p, **q),
        **(_choices(ctx) if editing else {}))


def _choices(ctx: "Context") -> dict[str, Any]:
    return {"resources": svc.resource_options(ctx), "links": svc.link_options(ctx), "max_note": svc.MAX_NOTE}


def _viewable(ctx: "Context", plugin: Any, key: str) -> bool:
    widget = widget_class(ctx, plugin, key)
    return widget is not None and svc.safe_can_view(widget, ctx)


# ---------------------------------------------------------------------- the Dashboards page
def new_dashboard_action(plugin: Any) -> Action:
    def form(ctx):
        return [
            TextInput("name").label("Name").required().max_length(svc.MAX_NAME).placeholder("Sales this month"),
            Select("start").label("Start with").options(svc.starter_options(ctx, plugin)).default("").native(),
            Toggle("shared").label("Share with everyone").helper_text("Everyone who logs in can see it.")
            .visible(svc.can_share(ctx)),
        ]

    def run(ctx, data):
        try:
            dashboard = svc.create(ctx, plugin, data.get("name"), shared=bool(data.get("shared")),
                                   start=data.get("start") or None)
        except svc.DashboardError as exc:
            ctx.db.rollback()
            Notification(str(exc)).danger().send(ctx)
            return False
        ctx.db.commit()
        Notification("Dashboard made").body("Add widgets and drag them where you like.").success().send(ctx)
        return ctx.go(plugin.url(ctx, d=dashboard.id, edit=1))

    return (Action("new_dashboard").label("New dashboard").icon("plus").form(form).action(run)
            .modal_heading("New dashboard").modal_submit_action_label("Make dashboard")
            .authorize(lambda ctx: svc.can_create(ctx)))


class DashboardsPage(Page):
    """Lists the dashboards a person can open and shows the picked one."""

    slug = "dashboards"
    title = "Dashboards"
    icon = "layout-grid"
    navigation_sort = -90
    template = "tungsten_dashboards/page.html"
    #: set by the plugin
    plugin: ClassVar[Any] = None
    #: widgets offered only on custom dashboards (kept here so the panel can find and refresh them)
    widgets: ClassVar[list] = []

    @classmethod
    def get_widgets(cls, ctx: "Context") -> list:
        return []  # this page draws its own grid

    @classmethod
    def header_actions(cls, ctx: "Context") -> list:
        return [new_dashboard_action(cls.plugin)]

    @classmethod
    def view(cls, ctx: "Context") -> dict[str, Any]:
        plugin = cls.plugin
        all_dashboards = svc.dashboards(ctx)
        wanted = ctx.request.query_params.get("d")
        current, missing = None, False
        if wanted:
            current = next((d for d in all_dashboards if str(d.id) == wanted), None)
            missing = current is None
        if current is None:
            home = svc.home_for(ctx)
            current = home if home is not None else (all_dashboards[0] if all_dashboards else None)
        editable = current is not None and svc.can_edit(ctx, current)
        editing = editable and ctx.request.query_params.get("edit") in ("1", "true")
        data: dict[str, Any] = {
            "plugin": plugin, "dashboards": all_dashboards, "current": current, "editable": editable,
            "editing": editing, "can_create": svc.can_create(ctx), "can_share": svc.can_share(ctx),
            "my_home": svc.personal_home_id(ctx), "signed_in": ctx.user is not None, "missing": missing,
            "url": lambda *p, **q: plugin.url(ctx, *p, **q),
        }
        if current is not None:
            data["board"] = board(ctx, plugin, current, editing)
        if editing:
            entries = svc.catalog(ctx, plugin)
            placed = {i.widget for i in current.items}
            groups: dict[str, list] = {}
            for entry in entries:
                groups.setdefault(entry.group, []).append(entry)
            data.update(catalog=groups, placed=placed, **_choices(ctx))
        return data


def home_page(base: type[Page], plugin: Any) -> type[Page]:
    """The panel's home page, showing the person's own dashboard when they picked one."""

    def _home(ctx: "Context") -> CustomDashboard | None:
        cache = ctx.__dict__.setdefault("_tw_dash_home", {})
        if "home" not in cache:
            try:
                cache["home"] = svc.home_for(ctx)
            except Exception:
                log.exception("Could not load the home dashboard")
                ctx.db.rollback()
                cache["home"] = None
        return cache["home"]

    class HomeDashboard(base):  # type: ignore[valid-type, misc]
        @classmethod
        def get_widgets(cls, ctx):
            return [] if _home(ctx) is not None else super().get_widgets(ctx)

        @classmethod
        def content(cls, ctx):
            dashboard = _home(ctx)
            if dashboard is None:
                return super().content(ctx)
            return ctx.panel.renderer.render("tungsten_dashboards/home.html", ctx=ctx, dashboard=dashboard,
                                             board=board(ctx, plugin, dashboard),
                                             editable=svc.can_edit(ctx, dashboard),
                                             url=lambda *p, **q: plugin.url(ctx, *p, **q))

    HomeDashboard.__name__ = base.__name__
    HomeDashboard.__qualname__ = base.__qualname__
    return HomeDashboard


# ---------------------------------------------------------------------- routes
def add_routes(app: Any, panel: Any, plugin: Any) -> None:
    from tungsten.routes import Routes

    routes = Routes(panel)
    base = f"/{DashboardsPage.get_slug()}"

    def guarded(fn):
        """Run a change; a :class:`DashboardError` becomes a red toast and nothing is saved."""
        def handler(ctx, fd, **kw):
            try:
                result = fn(ctx, fd, **kw)
            except svc.DashboardError as exc:
                ctx.db.rollback()
                Notification(str(exc)).danger().send(ctx)
                return ctx.finalize(Response(status_code=204))
            ctx.db.commit()
            return result
        return handler

    def show_item(ctx, fd, item_id: str):
        try:
            key = int(item_id)
        except ValueError:
            return ctx.html(error_card("This widget is no longer available."))
        item = ctx.db.get(DashboardItem, key)
        if item is None or svc.find(ctx, item.dashboard_id) is None:
            return ctx.html(error_card("This widget is no longer available."))
        return ctx.html(render_item(ctx, plugin, item))

    def add(ctx, fd, dashboard_id: str):
        dashboard = svc.find_editable(ctx, dashboard_id)
        item = svc.add_item(ctx, plugin, dashboard, fd.get("widget") or "", fd)
        Notification(__("Added: :widget", widget=item_label(ctx, plugin, item))).success().send(ctx)
        return ctx.refresh()

    def change_item(ctx, fd, dashboard_id: str, item_id: str):
        dashboard = svc.find_editable(ctx, dashboard_id)
        item = svc.find_item(dashboard, item_id)
        svc.update_item(ctx, item, fd)
        if fd.get("_reload"):
            Notification("Saved").success().send(ctx)
            return ctx.refresh()
        return ctx.finalize(Response(status_code=204))

    def remove_item(ctx, fd, dashboard_id: str, item_id: str):
        dashboard = svc.find_editable(ctx, dashboard_id)
        item = svc.find_item(dashboard, item_id)
        dashboard.items.remove(item)
        return ctx.finalize(Response(status_code=200, headers={"X-Dash-Removed": "1"}))

    def order(ctx, fd, dashboard_id: str):
        dashboard = svc.find_editable(ctx, dashboard_id)
        svc.reorder(dashboard, fd.getlist("keys"))
        return ctx.finalize(Response(status_code=204))

    def settings(ctx, fd, dashboard_id: str):
        dashboard = svc.find_editable(ctx, dashboard_id)
        svc.update(ctx, dashboard, fd)
        Notification("Saved").success().send(ctx)
        return ctx.refresh()

    def remove(ctx, fd, dashboard_id: str):
        dashboard = svc.find_editable(ctx, dashboard_id)
        name = dashboard.name
        svc.delete(ctx, dashboard)
        Notification(__("Deleted: :name", name=name)).success().send(ctx)
        return ctx.go(plugin.url(ctx))

    def copy(ctx, fd, dashboard_id: str):
        dashboard = svc.find(ctx, dashboard_id)
        if dashboard is None:
            from tungsten.routes import NotFound

            raise NotFound()
        new = svc.duplicate(ctx, dashboard)
        Notification("Copy made").body("This copy is yours to change.").success().send(ctx)
        return ctx.go(plugin.url(ctx, d=new.id, edit=1))

    def home(ctx, fd, dashboard_id: str):
        dashboard = svc.find(ctx, dashboard_id)
        if dashboard is None:
            from tungsten.routes import NotFound

            raise NotFound()
        on = fd.get("on") in ("1", "true")
        svc.set_home(ctx, dashboard if on else None)
        Notification("Home page set" if on else "Home page back to normal").success().send(ctx)
        return ctx.refresh()

    @app.get(base + "/_w/{item_id}")
    async def dashboards_item(request: Request, item_id: str):
        return await routes.run(request, show_item, item_id=item_id)

    posts = {"add": add, "order": order, "settings": settings, "delete": remove, "copy": copy, "home": home}
    for name, fn in posts.items():
        def make(fn=fn, name=name):
            async def endpoint(request: Request, dashboard_id: str):
                return await routes.run(request, guarded(fn), read_form=True, dashboard_id=dashboard_id)
            endpoint.__name__ = f"dashboards_{name}"
            return endpoint
        app.post(base + "/{dashboard_id}/" + name)(make())

    @app.post(base + "/{dashboard_id}/items/{item_id}")
    async def dashboards_item_change(request: Request, dashboard_id: str, item_id: str):
        return await routes.run(request, guarded(change_item), read_form=True, dashboard_id=dashboard_id,
                                item_id=item_id)

    @app.post(base + "/{dashboard_id}/items/{item_id}/remove")
    async def dashboards_item_remove(request: Request, dashboard_id: str, item_id: str):
        return await routes.run(request, guarded(remove_item), read_form=True, dashboard_id=dashboard_id,
                                item_id=item_id)

