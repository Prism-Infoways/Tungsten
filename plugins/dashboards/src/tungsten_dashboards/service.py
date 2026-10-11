"""Who sees and edits which dashboard, the widget catalog, and the changes the screens make."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import false, or_, select

from .models import CustomDashboard, DashboardHome, DashboardItem

if TYPE_CHECKING:  # pragma: no cover
    from tungsten.context import Context

log = logging.getLogger("tungsten.dashboards")

#: widths, in quarters of a row
SPANS = (1, 2, 3, 4)
SPAN_LABELS = {1: "Quarter", 2: "Half", 3: "Three quarters", 4: "Full width"}
MAX_DASHBOARDS = 50
MAX_ITEMS = 40
MAX_NOTE = 4000
MAX_NAME = 120

#: permission to make dashboards for everyone (shared, or the home page for all)
SHARE = "dashboards.share"
#: permission to build your own dashboards (only checked when the panel uses roles)
CREATE = "dashboards.create"


class DashboardError(ValueError):
    """A change that can't be made; the message is shown to the user."""


# ---------------------------------------------------------------------- who
def user_key(ctx: "Context") -> str:
    if ctx.user is None:
        return ""
    try:
        return str(ctx.panel.auth.user_id(ctx.user))
    except Exception:
        return ""


def tenant_key(ctx: "Context") -> str | None:
    tenancy = ctx.panel.tenancy
    tenant = getattr(ctx, "tenant", None)
    if not getattr(tenancy, "enabled", False) or tenant is None:
        return None
    return str(tenancy.key_of(tenant))


def _tenant_clause(ctx: "Context", column: Any) -> Any:
    tenancy = ctx.panel.tenancy
    key = tenant_key(ctx)
    if key is not None:
        return column == key
    if getattr(tenancy, "enabled", False):  # tenancy on but no team picked: nothing to show
        return false()
    return column.is_(None)


def can_create(ctx: "Context") -> bool:
    return ctx.can(CREATE)


def can_share(ctx: "Context") -> bool:
    return ctx.can(SHARE)


def can_edit(ctx: "Context", dashboard: CustomDashboard) -> bool:
    if dashboard.owner_id == user_key(ctx):
        return True
    return dashboard.shared and can_share(ctx)


def visible(ctx: "Context"):
    """Query of the dashboards this person can open: their own, and the shared ones."""
    return (select(CustomDashboard)
            .where(_tenant_clause(ctx, CustomDashboard.tenant_key),
                   or_(CustomDashboard.owner_id == user_key(ctx), CustomDashboard.shared.is_(True)))
            .order_by(CustomDashboard.shared, CustomDashboard.sort, CustomDashboard.id))


def dashboards(ctx: "Context") -> list[CustomDashboard]:
    return list(ctx.db.scalars(visible(ctx)).all())


def find(ctx: "Context", dashboard_id: Any) -> CustomDashboard | None:
    try:
        key = int(dashboard_id)
    except (TypeError, ValueError):
        return None
    return ctx.db.scalars(visible(ctx).where(CustomDashboard.id == key)).first()


def find_editable(ctx: "Context", dashboard_id: Any) -> CustomDashboard:
    from tungsten.routes import Forbidden, NotFound

    dashboard = find(ctx, dashboard_id)
    if dashboard is None:
        raise NotFound()
    if not can_edit(ctx, dashboard):
        raise Forbidden()
    return dashboard


# ---------------------------------------------------------------------- home page
def home_for(ctx: "Context") -> CustomDashboard | None:
    """This person's home dashboard: the one they picked, else a shared one marked for everyone."""
    me = user_key(ctx)
    if ctx.user is not None:
        pick = ctx.db.scalars(select(DashboardHome).where(DashboardHome.user_id == me,
                                                          _tenant_clause(ctx, DashboardHome.tenant_key))).first()
        if pick is not None:
            dashboard = find(ctx, pick.dashboard_id)
            if dashboard is not None:
                return dashboard
    return ctx.db.scalars(visible(ctx).where(CustomDashboard.shared.is_(True),
                                             CustomDashboard.home_for_all.is_(True))).first()


def personal_home_id(ctx: "Context") -> int | None:
    if ctx.user is None:
        return None
    pick = ctx.db.scalars(select(DashboardHome).where(DashboardHome.user_id == user_key(ctx),
                                                      _tenant_clause(ctx, DashboardHome.tenant_key))).first()
    return pick.dashboard_id if pick is not None else None


def set_home(ctx: "Context", dashboard: CustomDashboard | None) -> None:
    """Make ``dashboard`` this person's home page (``None``: back to the normal one)."""
    if ctx.user is None:
        raise DashboardError("Log in to pick a home page.")
    me, key = user_key(ctx), tenant_key(ctx)
    for row in ctx.db.scalars(select(DashboardHome).where(DashboardHome.user_id == me,
                                                          _tenant_clause(ctx, DashboardHome.tenant_key))).all():
        ctx.db.delete(row)
    if dashboard is not None:
        ctx.db.add(DashboardHome(user_id=me, tenant_key=key, dashboard_id=dashboard.id))


# ---------------------------------------------------------------------- catalog
@dataclass
class CatalogEntry:
    key: str
    label: str
    group: str
    description: str | None = None
    icon: str | None = None
    span: int = 2
    #: the panel widget class; ``None`` for the plugin's own widgets
    widget: Any = None
    #: form fields the built-in widget asks for
    fields: list[str] = field(default_factory=list)


def humanize(name: str) -> str:
    """``HRStats`` -> ``HR stats``, ``LatestOrdersWidget`` -> ``Latest orders``."""
    name = re.sub(r"Widget$", "", name) or name
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).replace("_", " ").split()
    out = [w if w.isupper() and len(w) > 1 else w.lower() for w in words]
    text = " ".join(out)
    return text[:1].upper() + text[1:]


def span_of(widget: Any) -> int:
    span = getattr(widget, "dashboard_span", None) or getattr(widget, "column_span", 2)
    if span == "full":
        return 4
    try:
        return max(1, min(4, int(span)))
    except (TypeError, ValueError):
        return 2


def widget_label(widget: Any) -> str:
    from tungsten.i18n import translate as __

    label = getattr(widget, "dashboard_label", None) or getattr(widget, "heading", None)
    return __(label) if label else humanize(widget.__name__)


def group_of(panel: Any, widget: Any, groups: dict[str, str] | None = None) -> str:
    """The plugin a widget comes from ("HR", "Finance"...), "General" for Tungsten's own, else "App"."""
    explicit = getattr(widget, "dashboard_group", None)
    if explicit:
        return explicit
    top = (widget.__module__ or "").split(".")[0]
    groups = groups if groups is not None else plugin_groups(panel)
    if top in groups:
        return groups[top]
    return "General" if top == "tungsten" else "App"


def plugin_groups(panel: Any) -> dict[str, str]:
    """Top-level package -> nice plugin name, for every installed plugin."""
    out: dict[str, str] = {}
    for plugin in getattr(panel, "_plugins", []):
        top = type(plugin).__module__.split(".")[0]
        name = getattr(plugin, "dashboard_group", None) or getattr(plugin, "label", None)
        if not name:
            cls = type(plugin).__name__.removesuffix("Plugin")
            name = cls if cls.isupper() else humanize(cls)
        out.setdefault(top, name)
    return out


def safe_can_view(widget: Any, ctx: "Context") -> bool:
    try:
        return bool(widget.can_view(ctx))
    except Exception:
        log.exception("can_view of widget %s failed", getattr(widget, "__name__", widget))
        return False


#: widgets this plugin brings itself: key -> (label, description, icon, span, fields)
BUILTINS: dict[str, tuple[str, str, str, int, list[str]]] = {
    "dashboards.counts": ("Record counts", "How many records there are in the lists you pick.", "hash", 4,
                          ["title", "resources"]),
    "dashboards.links": ("Quick links", "Buttons that open the lists and pages you use most.", "link", 2,
                         ["title", "links"]),
    "dashboards.note": ("Note", "A short note or to-do list for everyone who sees this dashboard.", "sticky-note", 2,
                        ["title", "text"]),
}


def catalog(ctx: "Context", plugin: Any) -> list[CatalogEntry]:
    """Every widget this person may put on a dashboard, grouped by the plugin it comes from."""
    from tungsten.i18n import translate as __

    panel = ctx.panel
    groups = plugin_groups(panel)
    entries: list[CatalogEntry] = []
    seen: set[str] = set()
    for widget in [*panel.all_widgets(), *plugin.extra_widgets]:
        try:
            key = widget.get_id()
        except Exception:
            continue
        if key in seen or widget in plugin.hidden_widgets or key in plugin.hidden_widgets \
                or getattr(widget, "dashboard_hidden", False) or not safe_can_view(widget, ctx):
            continue
        seen.add(key)
        description = getattr(widget, "dashboard_description", None) or getattr(widget, "description", None)
        entries.append(CatalogEntry(key, widget_label(widget), group_of(panel, widget, groups),
                                    __(description) if description else None, getattr(widget, "icon", None),
                                    span_of(widget), widget))
    if plugin.builtin_widgets:
        for key, (label, description, icon, span, fields) in BUILTINS.items():
            entries.append(CatalogEntry(key, __(label), __("Dashboards"), __(description), icon, span, None, fields))
    return entries


def entry_for(ctx: "Context", plugin: Any, key: str) -> CatalogEntry | None:
    return next((e for e in catalog(ctx, plugin) if e.key == key), None)


def resource_options(ctx: "Context") -> dict[str, str]:
    out: dict[str, str] = {}
    for resource in ctx.panel.get_resources():
        try:
            if resource.can(ctx, "view_any"):
                out[resource.get_slug()] = resource.get_plural_label()
        except Exception:
            continue
    return out


def link_options(ctx: "Context") -> dict[str, str]:
    out = {f"resource:{slug}": label for slug, label in resource_options(ctx).items()}
    for page in ctx.panel.get_pages():
        try:
            if page.can_access(ctx) and page.show_in_navigation:
                out[f"page:{page.get_slug()}"] = page.get_navigation_label()
        except Exception:
            continue
    return out


def clean_settings(ctx: "Context", key: str, data: Any) -> tuple[str | None, dict[str, Any] | None]:
    """Check the fields of a built-in widget. Returns ``(title, settings)``."""
    if key not in BUILTINS:
        return None, None
    title = (_get(data, "title") or "").strip()[:MAX_NAME] or None
    if key == "dashboards.note":
        text = (_get(data, "text") or "").strip()
        if not text:
            raise DashboardError("Write something in the note.")
        if len(text) > MAX_NOTE:
            raise DashboardError(f"Keep the note under {MAX_NOTE} letters.")
        return title, {"text": text}
    if key == "dashboards.counts":
        allowed = resource_options(ctx)
        picked = [s for s in dict.fromkeys(_getlist(data, "resources")) if s in allowed][:12]
        if not picked:
            raise DashboardError("Pick at least one list to count.")
        return title, {"resources": picked}
    allowed = link_options(ctx)
    picked = [s for s in dict.fromkeys(_getlist(data, "links")) if s in allowed][:20]
    if not picked:
        raise DashboardError("Pick at least one link.")
    return title, {"links": picked}


def _get(data: Any, name: str) -> Any:
    if data is None:
        return None
    return data.get(name)


def _getlist(data: Any, name: str) -> list[str]:
    if data is None:
        return []
    if hasattr(data, "getlist"):
        values = data.getlist(name)
    else:
        values = data.get(name) or []
        values = [values] if isinstance(values, str) else list(values)
    return [str(v) for v in values if v not in (None, "")]


def parse_span(value: Any, default: int = 2) -> int:
    try:
        span = int(value)
    except (TypeError, ValueError):
        return default
    return span if span in SPANS else default


# ---------------------------------------------------------------------- changes
def clean_name(name: Any) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise DashboardError("Give the dashboard a name.")
    return name[:MAX_NAME]


def create(ctx: "Context", plugin: Any, name: Any, *, shared: bool = False, start: str | None = None,
           description: str | None = None) -> CustomDashboard:
    """Make a dashboard. ``start`` fills it: ``"home"`` (the panel's home widgets), a plugin group
    name ("HR") for all its widgets, the name of a template from ``plugin.add_template()``, or nothing."""
    if not can_create(ctx):
        raise DashboardError("You can't make dashboards.")
    name = clean_name(name)
    if shared and not can_share(ctx):
        raise DashboardError("You can't share dashboards with everyone.")
    count = len([d for d in dashboards(ctx) if d.owner_id == user_key(ctx)])
    if count >= MAX_DASHBOARDS:
        raise DashboardError(f"You already have {MAX_DASHBOARDS} dashboards. Delete one first.")
    dashboard = CustomDashboard(name=name, owner_id=user_key(ctx), tenant_key=tenant_key(ctx), shared=bool(shared),
                                description=(description or "").strip()[:255] or None)
    ctx.db.add(dashboard)
    for i, (key, span) in enumerate(starter_widgets(ctx, plugin, start)):
        dashboard.items.append(DashboardItem(widget=key, span=span, position=i))
    ctx.db.flush()
    return dashboard


def starter_options(ctx: "Context", plugin: Any) -> dict[str, str]:
    from tungsten.i18n import translate as __

    out = {"": __("Empty"), "home": __("Same widgets as the home page")}
    for name in plugin.templates_by_name:
        out[f"template:{name}"] = __(name)
    groups: dict[str, int] = {}
    for entry in catalog(ctx, plugin):
        if entry.widget is not None:
            groups[entry.group] = groups.get(entry.group, 0) + 1
    for group in groups:
        out[f"group:{group}"] = __("All :group widgets", group=group)
    return out


def starter_widgets(ctx: "Context", plugin: Any, start: str | None) -> list[tuple[str, int]]:
    if not start:
        return []
    entries = {e.key: e for e in catalog(ctx, plugin) if e.widget is not None}
    if start == "home":
        home = ctx.panel.dashboard
        widgets = list(home.widgets or ctx.panel.get_widgets()) if home is not None else ctx.panel.get_widgets()
        keys = [w.get_id() for w in sorted(widgets, key=lambda w: getattr(w, "sort", 0))]
    elif start.startswith("template:"):
        keys = [w if isinstance(w, str) else w.get_id() for w in plugin.templates_by_name.get(start[9:], [])]
    elif start.startswith("group:"):
        keys = [k for k, e in entries.items() if e.group == start[6:]]
    else:
        return []
    keys = [k for k in dict.fromkeys(keys) if k in entries]  # skip widgets this person can't see
    return [(k, entries[k].span) for k in keys[:MAX_ITEMS]]


def update(ctx: "Context", dashboard: CustomDashboard, data: Any) -> None:
    dashboard.name = clean_name(_get(data, "name"))
    dashboard.description = (_get(data, "description") or "").strip()[:255] or None
    wants_shared = _get(data, "shared") in ("1", "on", "true", True)
    wants_all = wants_shared and _get(data, "home_for_all") in ("1", "on", "true", True)
    if (wants_shared != dashboard.shared or wants_all != dashboard.home_for_all) and not can_share(ctx):
        raise DashboardError("You can't share dashboards with everyone.")
    if dashboard.shared and not wants_shared and dashboard.owner_id != user_key(ctx):
        # un-sharing someone else's dashboard would lock everyone out of it but its owner: make it yours
        dashboard.owner_id = user_key(ctx)
    dashboard.shared = wants_shared
    dashboard.home_for_all = wants_all
    if wants_all:  # only one home page for everyone
        for other in ctx.db.scalars(visible(ctx).where(CustomDashboard.home_for_all.is_(True),
                                                       CustomDashboard.id != dashboard.id)).all():
            other.home_for_all = False
    if "my_home" in data or _get(data, "_my_home_shown"):
        mine = _get(data, "my_home") in ("1", "on", "true", True)
        current = personal_home_id(ctx)
        if mine and current != dashboard.id:
            set_home(ctx, dashboard)
        elif not mine and current == dashboard.id:
            set_home(ctx, None)


def delete(ctx: "Context", dashboard: CustomDashboard) -> None:
    for row in ctx.db.scalars(select(DashboardHome).where(DashboardHome.dashboard_id == dashboard.id)).all():
        ctx.db.delete(row)
    ctx.db.delete(dashboard)


def duplicate(ctx: "Context", dashboard: CustomDashboard) -> CustomDashboard:
    """A private copy of a dashboard this person can see."""
    from tungsten.i18n import translate as __

    if not can_create(ctx):
        raise DashboardError("You can't make dashboards.")
    copy = CustomDashboard(name=clean_name(__(":name (copy)", name=dashboard.name)), owner_id=user_key(ctx),
                           tenant_key=tenant_key(ctx), icon=dashboard.icon, description=dashboard.description)
    ctx.db.add(copy)
    for item in dashboard.items:
        copy.items.append(DashboardItem(widget=item.widget, title=item.title, span=item.span,
                                        position=item.position, settings=dict(item.settings or {})))
    ctx.db.flush()
    return copy


def add_item(ctx: "Context", plugin: Any, dashboard: CustomDashboard, key: str, data: Any = None) -> DashboardItem:
    entry = entry_for(ctx, plugin, key or "")
    if entry is None:
        raise DashboardError("That widget isn't available.")
    if len(dashboard.items) >= MAX_ITEMS:
        raise DashboardError(f"A dashboard can hold {MAX_ITEMS} widgets. Make another dashboard for more.")
    if entry.widget is not None and any(i.widget == key for i in dashboard.items):
        raise DashboardError("This widget is already on the dashboard.")
    title, settings = clean_settings(ctx, key, data)
    span = parse_span(_get(data, "span"), entry.span)
    position = max((i.position for i in dashboard.items), default=-1) + 1
    item = DashboardItem(widget=key, title=title, settings=settings, span=span, position=position)
    dashboard.items.append(item)
    ctx.db.flush()
    return item


def find_item(dashboard: CustomDashboard, item_id: Any) -> DashboardItem:
    from tungsten.routes import NotFound

    item = next((i for i in dashboard.items if str(i.id) == str(item_id)), None)
    if item is None:
        raise NotFound()
    return item


def update_item(ctx: "Context", item: DashboardItem, data: Any) -> None:
    if _get(data, "span") is not None:
        item.span = parse_span(_get(data, "span"), item.span)
    if item.widget in BUILTINS and any(_get(data, f) is not None or _getlist(data, f)
                                       for f in ("title", "text", "resources", "links")):
        item.title, item.settings = clean_settings(ctx, item.widget, data)


def reorder(dashboard: CustomDashboard, keys: list[str]) -> None:
    """Put the items in the order of ``keys`` (item ids); unknown ids are skipped, missing ones go last."""
    by_id = {str(i.id): i for i in dashboard.items}
    order = [by_id[k] for k in dict.fromkeys(keys) if k in by_id]
    order += [i for i in sorted(dashboard.items, key=lambda i: i.position) if i not in order]
    for position, item in enumerate(order):
        item.position = position
