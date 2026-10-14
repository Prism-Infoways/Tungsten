"""The :class:`Table`: builds the query from the URL state and renders the grid."""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import itertools
import json
import math
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import parse_qsl, urlencode

from markupsafe import Markup
from starlette.datastructures import QueryParams
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import aliased, selectinload

from ..actions.action import Action, ActionGroup, flatten_actions
from ..forms.form import Form
from ..i18n import maybe
from ..i18n import translate as __
from ..support.component import Component, headline
from ..support.evaluate import call, evaluate
from .columns import Column, ColumnGroup, read_path
from .filters import Filter, TrashedFilter

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..hosts import Host

_ids = itertools.count(1)

# written out in full so the Tailwind build finds every class
_GRID_COLS = {
    "default": ("grid-cols-1", "grid-cols-2", "grid-cols-3", "grid-cols-4", "grid-cols-5", "grid-cols-6"),
    "sm": ("sm:grid-cols-1", "sm:grid-cols-2", "sm:grid-cols-3", "sm:grid-cols-4", "sm:grid-cols-5", "sm:grid-cols-6"),
    "md": ("md:grid-cols-1", "md:grid-cols-2", "md:grid-cols-3", "md:grid-cols-4", "md:grid-cols-5", "md:grid-cols-6"),
    "lg": ("lg:grid-cols-1", "lg:grid-cols-2", "lg:grid-cols-3", "lg:grid-cols-4", "lg:grid-cols-5", "lg:grid-cols-6"),
    "xl": ("xl:grid-cols-1", "xl:grid-cols-2", "xl:grid-cols-3", "xl:grid-cols-4", "xl:grid-cols-5", "xl:grid-cols-6"),
    "2xl": ("2xl:grid-cols-1", "2xl:grid-cols-2", "2xl:grid-cols-3", "2xl:grid-cols-4", "2xl:grid-cols-5",
            "2xl:grid-cols-6"),
}

_PERSIST_LIMIT = 1200  # characters of remembered state per table

# query-string keys that hold table state (anything else is ignored when deciding to restore)
_STATE_KEYS = ("search", "sort", "direction", "_f", "page", "per_page", "cursor", "group", "tab", "reordering")


class Group(Component):
    """Group rows by an attribute: ``Group("status")`` or ``Group("category.name")``."""

    def __init__(self, attribute: str, label: str | None = None) -> None:
        super().__init__()
        self.attribute = attribute
        self._label = label
        self._title: Callable | None = None
        self._collapsible = False

    def label(self, label: str) -> "Group":
        self._label = label
        return self

    def title(self, fn: Callable) -> "Group":
        """``title(lambda record: ...)`` for the group heading."""
        self._title = fn
        return self

    def collapsible(self, condition: bool = True) -> "Group":
        """Let users click a group heading to hide or show its rows."""
        self._collapsible = condition
        return self

    def get_label(self) -> str:
        return __(self._label or headline(self.attribute.replace(".", " ")))

    def get_title(self, record: Any) -> str:
        if self._title:
            return str(call(self._title, record=record))
        from .columns import default_format

        value = read_path(record, self.attribute)
        return str(default_format(value)) if value not in (None, "") else "—"


class ListTab(Component):
    """A tab above the table that narrows the records: ``ListTab("active").query(lambda query, model: ...)``."""

    def __init__(self, name: str, label: str | None = None) -> None:
        super().__init__()
        self.name = name
        self._label = label
        self._icon: str | None = None
        self._query: Callable | None = None
        self._badge: Any = None
        self._badge_color = "gray"

    def label(self, label: str) -> "ListTab":
        self._label = label
        return self

    def icon(self, icon: str) -> "ListTab":
        self._icon = icon
        return self

    def query(self, fn: Callable) -> "ListTab":
        """``fn(query, model)`` returns the narrowed query."""
        self._query = fn
        return self

    def badge(self, value: Any = True, color: str = "gray") -> "ListTab":
        """``True`` shows the record count, or pass a value / closure."""
        self._badge = value
        self._badge_color = color
        return self

    def get_label(self) -> str:
        return __(self._label or headline(self.name))

    def apply(self, query: Any, table: "Table") -> Any:
        if self._query is None:
            return query
        return call(self._query, **{**table.ev(), "query": query})


class Table(Component):
    def __init__(self) -> None:
        super().__init__()
        self._columns: list[Column] = []
        self._filters: list[Filter] = []
        self._actions: list = []
        self._bulk_actions: list = []
        self._header_actions: list = []
        self._empty_actions: list = []
        self._default_sort: str | None = None
        self._default_direction = "asc"
        self._per_page_options = [10, 25, 50, 100]
        self._default_per_page = 10
        self._paginated = True
        self._searchable: bool | None = None
        self._search_placeholder: str | None = None
        self._groups: list[Group] = []
        self._default_group: str | None = None
        self._empty_heading: Any = None
        self._empty_description: Any = None
        self._empty_icon: Any = "inbox"
        self._striped = False
        self._record_url: Any = None
        self._modify_query: Callable | None = None
        self._poll: str | None = None
        self._heading: Any = None
        self._description: Any = None
        self._record_classes: Callable | None = None
        self._row_index = False
        self._filters_layout = "panel"
        self._selectable: bool | None = None
        self._toolbar = True
        self._limit: int | None = None
        self._reorder_column: str | None = None
        self._tabs: list = []
        self._deferred_filters: bool | None = None
        self._pagination_mode = "default"
        self._persist: set[str] = set()
        self._content_grid: dict[str, int] | None = None
        self._stacked_on_mobile = False
        self._column_groups: dict[str, ColumnGroup] = {}
        # runtime
        self.ctx: Context | None = None
        self.host: Host | None = None
        self.params: Any = {}
        self.id = f"tw-table-{next(_ids)}"
        self.model: Any = None
        self._ev_cache: tuple | None = None
        self._page_records: list = []
        self._relation_counts: dict[str, dict] = {}
        self.filter_form: Form | None = None
        self.filter_data: dict[str, dict] = {}
        self._state_form: Form | None = None
        self._joins: dict[str, Any] = {}
        self._has_more = False
        self._cursors: dict[str, str | None] = {}

    # ------------------------------------------------------------------ config
    def columns(self, columns: list[Column | ColumnGroup]) -> "Table":
        """The table's columns. A :class:`ColumnGroup` puts a shared heading over the columns in it."""
        self._columns = []
        self._column_groups = {}
        for item in columns:
            if isinstance(item, ColumnGroup):
                for col in item.columns:
                    self._column_groups[col.name] = item
                    self._columns.append(col)
            else:
                self._columns.append(item)
        return self

    FILTER_LAYOUTS = ("panel", "above", "modal", "dropdown")

    def filters(self, filters: list[Filter], layout: str | None = None) -> "Table":
        """``layout``: ``"panel"`` (side panel, default), ``"above"`` (all inline in the toolbar),
        ``"modal"`` (a pop-up window) or ``"dropdown"`` (a menu under the Filters button)."""
        self._filters = list(filters)
        if layout:
            self.filters_layout(layout)
        return self

    def filters_layout(self, layout: str) -> "Table":
        if layout not in self.FILTER_LAYOUTS:
            raise ValueError(f"Unknown filters layout {layout!r}; use one of {', '.join(self.FILTER_LAYOUTS)}")
        self._filters_layout = layout
        return self

    def deferred_filters(self, condition: bool = True) -> "Table":
        """Wait for the Apply button before running filters, instead of on every change.

        On by default for the ``"modal"`` and ``"dropdown"`` layouts.
        """
        self._deferred_filters = condition
        return self

    def has_deferred_filters(self) -> bool:
        if not self._filters:
            return False
        if self._deferred_filters is not None:
            return self._deferred_filters
        return self._filters_layout in ("modal", "dropdown")

    def persist_filters_in_session(self, condition: bool = True) -> "Table":
        """Remember the filters for this user, so they are still set on the next visit."""
        return self._set_persist("filters", condition)

    def persist_search_in_session(self, condition: bool = True) -> "Table":
        """Remember the search text (and the per-column searches) for this user."""
        return self._set_persist("search", condition)

    def persist_sort_in_session(self, condition: bool = True) -> "Table":
        """Remember the sort column and direction for this user."""
        return self._set_persist("sort", condition)

    def persist_in_session(self, condition: bool = True) -> "Table":
        """Remember filters, search and sort (shortcut for the three ``persist_*`` methods)."""
        for part in ("filters", "search", "sort"):
            self._set_persist(part, condition)
        return self

    def _set_persist(self, part: str, condition: bool) -> "Table":
        if condition:
            self._persist.add(part)
        else:
            self._persist.discard(part)
        return self

    def content_grid(self, columns: dict[str, int] | int = 3) -> "Table":
        """Show records as cards in a grid instead of rows. ``{"md": 2, "xl": 3}`` sets columns per screen width."""
        self._content_grid = {"default": columns} if isinstance(columns, int) else dict(columns)
        return self

    def stacked_on_mobile(self, condition: bool = True) -> "Table":
        """On phones, show each row as a card with the column labels next to the values."""
        self._stacked_on_mobile = condition
        return self

    def content_grid_classes(self) -> str:
        out = ["grid", "gap-4", "grid-cols-1"]
        for size, n in (self._content_grid or {}).items():
            if size in _GRID_COLS:
                out.append(_GRID_COLS[size][max(1, min(int(n), 6)) - 1])
        return " ".join(out)

    def actions(self, actions: list) -> "Table":
        """Row actions (shown at the end of every row)."""
        self._actions = list(actions)
        return self

    def bulk_actions(self, actions: list) -> "Table":
        self._bulk_actions = list(actions)
        return self

    def header_actions(self, actions: list) -> "Table":
        self._header_actions = list(actions)
        return self

    def empty_state_actions(self, actions: list) -> "Table":
        self._empty_actions = list(actions)
        return self

    def default_sort(self, column: str, direction: str = "asc") -> "Table":
        self._default_sort = column
        self._default_direction = direction
        return self

    PAGINATION_MODES = ("default", "simple", "cursor")

    def paginated(self, options: list[int] | bool = True, default: int | None = None,
                  mode: str | None = None) -> "Table":
        """Per-page choices, or ``False`` for one page. ``mode``: see :meth:`pagination_mode`."""
        if mode:
            self.pagination_mode(mode)
        if options is False:
            self._paginated = False
        elif isinstance(options, list):
            self._per_page_options = options
        if default:
            self._default_per_page = default
        elif isinstance(options, list) and options:
            self._default_per_page = options[0]
        return self

    def pagination_mode(self, mode: str) -> "Table":
        """``"default"`` (page numbers and a total), ``"simple"`` (Previous / Next, no row count) or
        ``"cursor"`` (Previous / Next that stays fast deep into very large tables)."""
        if mode not in self.PAGINATION_MODES:
            raise ValueError(f"Unknown pagination mode {mode!r}; use one of {', '.join(self.PAGINATION_MODES)}")
        self._pagination_mode = mode
        return self

    def simple_pagination(self) -> "Table":
        return self.pagination_mode("simple")

    def cursor_pagination(self) -> "Table":
        return self.pagination_mode("cursor")

    def limit(self, n: int) -> "Table":
        """Show only the first ``n`` rows, without pagination (good for widgets)."""
        self._paginated = False
        self._limit = n
        return self

    def tabs(self, tabs: list[ListTab]) -> "Table":
        """Tabs above the table (e.g. All / Active / Inactive). The first one is the default."""
        self._tabs = list(tabs)
        return self

    @property
    def active_tab(self) -> ListTab | None:
        if not self._tabs:
            return None
        wanted = self.param("tab")
        return next((t for t in self._tabs if t.name == wanted), self._tabs[0])

    def tab_data(self) -> list[dict]:
        out = []
        active = self.active_tab
        base = None
        for tab in self._tabs:
            badge = None
            if tab._badge is True:
                if base is None:
                    base = self._scoped_base_query()
                badge = self.get_total(tab.apply(base, self))
            elif tab._badge is not None:
                badge = evaluate(tab._badge, **self.ev())
            out.append({"name": tab.name, "label": tab.get_label(), "icon": tab._icon, "badge": badge,
                        "color": tab._badge_color, "active": tab is active,
                        "url": self.url(tab=tab.name, page=None)})
        return out

    def reorderable(self, column: str = "sort") -> "Table":
        """Let users drag rows to change their order (saved to ``column``)."""
        self._reorder_column = column
        return self

    def default_per_page(self, n: int) -> "Table":
        self._default_per_page = n
        return self

    def searchable(self, condition: bool = True) -> "Table":
        self._searchable = condition
        return self

    def search_placeholder(self, text: str) -> "Table":
        self._search_placeholder = text
        return self

    def groups(self, groups: list[Group | str], default: str | None = None) -> "Table":
        self._groups = [g if isinstance(g, Group) else Group(g) for g in groups]
        if default:
            self._default_group = default
        return self

    def default_group(self, attribute: str) -> "Table":
        self._default_group = attribute
        return self

    def empty_state(self, heading: Any = None, description: Any = None, icon: Any = None) -> "Table":
        self._empty_heading = heading
        self._empty_description = description
        if icon:
            self._empty_icon = icon
        return self

    def striped(self, condition: bool = True) -> "Table":
        self._striped = condition
        return self

    def record_url(self, fn: Any) -> "Table":
        """Where a row click goes: a closure, or ``False`` to disable."""
        self._record_url = fn
        return self

    def modify_query_using(self, fn: Callable) -> "Table":
        """``fn(query)`` returns a changed query (extra WHERE, joins, eager loads)."""
        self._modify_query = fn
        return self

    query = modify_query_using

    def poll(self, interval: str = "10s") -> "Table":
        self._poll = interval
        return self

    def heading(self, text: Any) -> "Table":
        self._heading = text
        return self

    def description(self, text: Any) -> "Table":
        self._description = text
        return self

    def record_classes(self, fn: Callable) -> "Table":
        self._record_classes = fn
        return self

    def row_index(self, condition: bool = True) -> "Table":
        """Show a ``#`` column with the row number."""
        self._row_index = condition
        return self

    def selectable(self, condition: bool = True) -> "Table":
        self._selectable = condition
        return self

    def toolbar(self, condition: bool = True) -> "Table":
        self._toolbar = condition
        return self

    # ------------------------------------------------------------------ runtime
    def bind(self, ctx: "Context", host: "Host", params: Any = None, id: str | None = None) -> "Table":
        self.ctx = ctx
        self.host = host
        self.model = host.model
        self.params = params if params is not None else ctx.request.query_params
        self.id = id or "tw-table-" + host.key.replace(":", "-").replace("_", "-")
        for f in self._filters:
            if hasattr(f, "bind_options"):
                f.bind_options(self)
        restored = self._restore_persisted()
        pending = None
        if self.has_deferred_filters() and "_applied" in self.params and not self.params.get("_apply"):
            # deferred filters: the query uses the last applied values, not what is typed in the form
            pending = self.params
            self.params = self._with_applied_filters(self.params)
        if not restored:
            self._remember_state()
        self.filter_form, self.filter_data = self._load_filters(self.params)
        self._state_form = self.filter_form
        if pending is not None and pending.get("_qb"):
            # a query-builder edit (add a rule, ...) keeps the unapplied rules on screen
            self.filter_form, _ = self._load_filters(pending)
        return self

    # ---- deferred filters
    def _with_applied_filters(self, params: Any) -> QueryParams:
        items = [(k, v) for k, v in params.multi_items()
                 if not k.startswith("filters.") and k not in ("_qb", "_applied", "_apply")]
        items += [(k, v) for k, v in parse_qsl(str(params.get("_applied") or ""), keep_blank_values=False)
                  if k.startswith("filters.")]
        return QueryParams(items)

    def applied_filters_value(self) -> str:
        """The applied filter values, sent back with each request while the form holds unapplied changes."""
        return urlencode(self.filter_state_items(include_marker=False))

    # ---- session persistence
    def persist_key(self) -> str:
        return f"tw_table:{self.host.key if self.host else self.id}"

    def _session(self) -> dict | None:
        if not self._persist or self.ctx is None:
            return None
        if "session" not in getattr(self.ctx.request, "scope", {}):
            return None
        return self.ctx.session

    def _has_state(self, params: Any) -> bool:
        return any(params.get(k) is not None for k in _STATE_KEYS) or any(
            k.startswith("col_search.") for k in params.keys())

    def _restore_persisted(self) -> bool:
        """With no table state in the URL, open the table as the user last left it."""
        session = self._session()
        if session is None or self._has_state(self.params):
            return False
        saved = session.get(self.persist_key()) or {}
        items = [tuple(i) for part in ("filters", "search", "sort") if part in self._persist
                 for i in saved.get(part, [])]
        if not items:
            return False
        self.params = QueryParams(list(self.params.multi_items()) + items)
        return True

    def _remember_state(self) -> None:
        session = self._session()
        if session is None or not self._has_state(self.params):
            return
        params = self.params
        saved: dict[str, list] = {}
        if "filters" in self._persist and params.get("_f") is not None:
            saved["filters"] = [("_f", "1")] + [
                (k, v) for k, v in params.multi_items() if k.startswith("filters.") and v not in (None, "")]
        if "search" in self._persist:
            saved["search"] = [(k, v) for k, v in params.multi_items()
                               if (k == "search" or k.startswith("col_search.")) and str(v).strip()]
        if "sort" in self._persist and params.get("sort") is not None:
            saved["sort"] = [("sort", params.get("sort")), ("direction", params.get("direction") or "")]
        saved = {k: [list(i) for i in v] for k, v in saved.items() if v}
        # the session lives in a cookie (about 4 KB for everything): big query-builder rules are not kept
        while saved and len(json.dumps(saved)) > _PERSIST_LIMIT:
            saved.pop("filters" if "filters" in saved else next(iter(saved)))
        if saved:
            session[self.persist_key()] = saved
        else:
            session.pop(self.persist_key(), None)

    def ev(self) -> dict[str, Any]:
        """Closure arguments for this table. Built once per request: every cell asks for them.

        Treat the returned dict as read-only; copy it (``{**table.ev(), ...}``) to add keys.
        """
        ctx = self.ctx
        key = (ctx, getattr(ctx, "user", None), getattr(ctx, "tenant", None), self.host, self.model)
        cached = getattr(self, "_ev_cache", None)
        if cached is not None and all(a is b for a, b in zip(cached[0], key)):
            return cached[1]
        ev = self._build_ev()
        self._ev_cache = (key, ev)
        return ev

    def _build_ev(self) -> dict[str, Any]:
        ctx = self.ctx
        return {
            "ctx": ctx,
            "request": ctx.request if ctx else None,
            "user": ctx.user if ctx else None,
            "db": ctx.db if ctx else None,
            "tenant": ctx.tenant if ctx else None,
            "table": self,
            "model": self.model,
            "host": self.host,
            "owner": getattr(self.host, "owner", None),
        }

    @property
    def renderer(self):
        from ..rendering import default_renderer

        return self.ctx.panel.renderer if self.ctx else default_renderer()

    def param(self, name: str, default: Any = None) -> Any:
        value = self.params.get(name)
        return default if value in (None, "") else value

    # ---- state
    @property
    def search(self) -> str:
        return (self.param("search") or "").strip()

    @property
    def sort(self) -> tuple[str | None, str]:
        column = self.param("sort")
        direction = self.param("direction", "asc")
        if column is None:
            return self._default_sort, self._default_direction
        if not any(c.name == column and c._sortable for c in self._columns):
            return self._default_sort, self._default_direction
        return column, "desc" if direction == "desc" else "asc"

    @property
    def per_page(self) -> int:
        try:
            n = int(self.param("per_page", self._default_per_page))
        except ValueError:
            n = self._default_per_page
        return n if n in self._per_page_options or n == self._default_per_page else self._default_per_page

    @property
    def page(self) -> int:
        try:
            return max(1, int(self.param("page", 1)))
        except ValueError:
            return 1

    @property
    def group(self) -> Group | None:
        name = self.param("group", self._default_group)
        if name == "none":
            return None
        for g in self._groups:
            if g.attribute == name:
                return g
        return None

    @property
    def column_searches(self) -> dict[str, str]:
        """Terms typed in the per-column search boxes (``searchable(is_individual=True)``)."""
        out = {}
        for c in self._columns:
            if c._searchable and c._individual_searchable:
                term = (self.param(f"col_search.{c.name}") or "").strip()
                if term:
                    out[c.name] = term
        return out

    def is_searchable(self) -> bool:
        if self._searchable is not None:
            return self._searchable
        return any(c._searchable and c._global_searchable for c in self._columns)

    def has_individual_search(self, columns: list[Column]) -> bool:
        return any(c._searchable and c._individual_searchable for c in columns)

    @property
    def is_reordering(self) -> bool:
        return bool(self._reorder_column) and self.param("reordering") == "1" and self.host is not None \
            and self.host.can(self.ctx, "update")

    def is_selectable(self) -> bool:
        if self.is_reordering:
            return False
        if self._selectable is not None:
            return self._selectable
        return bool(self.visible_bulk_actions())

    # ---- columns
    def column_toggle_key(self) -> str:
        return f"tw_cols:{self.host.key if self.host else self.id}"

    def hidden_columns(self) -> set[str]:
        toggleable = {c.name for c in self._columns if c._toggleable}
        if self.params.get("_cols") is not None and self.ctx is not None:
            visible = set(self.params.getlist("cols"))
            hidden = sorted(toggleable - visible)
            self.ctx.session[self.column_toggle_key()] = hidden
            return set(hidden)
        if self.ctx is not None and self.column_toggle_key() in self.ctx.session:
            return set(self.ctx.session[self.column_toggle_key()]) & toggleable
        return {c.name for c in self._columns if c._toggleable and c._hidden_by_default}

    def visible_columns(self) -> list[Column]:
        hidden = self.hidden_columns()
        ev = self.ev()
        return [c for c in self._columns if c.name not in hidden and c.is_visible(**ev)]

    def column_group_headers(self, columns: list[Column]) -> list[dict]:
        """The extra heading row over grouped columns: ``[{"group": ColumnGroup | None, "span": n}, ...]``."""
        if not self._column_groups or not any(c.name in self._column_groups for c in columns):
            return []
        out: list[dict] = []
        for col in columns:
            group = self._column_groups.get(col.name)
            if out and out[-1]["group"] is group:
                out[-1]["span"] += 1
            else:
                out.append({"group": group, "span": 1})
        return out

    def toggleable_columns(self) -> list[dict]:
        hidden = self.hidden_columns()
        return [{"name": c.name, "label": c.get_label(), "visible": c.name not in hidden}
                for c in self._columns if c._toggleable]

    # ---- filters
    def _load_filters(self, params: Any) -> tuple[Form, dict[str, dict]]:
        form = Form().columns(1)
        form.bind(self.ctx, operation="filter", refresh_url=None)
        form.id = self.id + "-filters"
        form.table = self  # type: ignore[attr-defined]  # the query builder renders table-aware buttons
        submitted = params.get("_f") is not None
        builder_action = str(params.get("_qb") or "")
        filter_data: dict[str, dict] = {}
        for f in self._filters:
            base = f.base()
            if submitted:
                for field in f.get_fields():
                    field.load_state(form, params, base)
                verb, _, rest = builder_action.partition(":")
                target, _, args = rest.partition(":")
                if target == f.name and hasattr(f, "field"):
                    f.field.handle(form, base, f"{verb}:{args}")
            else:
                for field in f.get_fields():
                    field.fill_state(form, base, None)
                defaults = f.default_data()
                for k, v in defaults.items():
                    form.set(f"{base}.{k}", v)
            data: dict[str, Any] = {}
            errors: dict[str, list] = {}
            for field in f.get_fields():
                field.process(form, base, data, errors)
            filter_data[f.name] = data
        return form, filter_data

    def active_indicators(self) -> list[dict]:
        out = []
        for f in self._filters:
            for label in f.indicators(self.filter_data.get(f.name, {}), self):
                out.append({"filter": f.name, "label": label})
        labels = {c.name: c.get_label() for c in self._columns}
        for name, term in self.column_searches.items():
            out.append({"filter": None, "label": f"{labels[name]}: “{term}”"})
        return out

    def inline_filters(self) -> list[Filter]:
        if self._filters_layout == "above":
            return list(self._filters)
        return [f for f in self._filters if f._inline]

    def panel_filters(self) -> list[Filter]:
        if self._filters_layout == "above":
            return []
        return [f for f in self._filters if not f._inline]

    def trashed_mode(self) -> str:
        for f in self._filters:
            if isinstance(f, TrashedFilter):
                return f.mode(self.filter_data.get(f.name, {}))
        return "without"

    # ---- query building
    def column_expression(self, path: str):
        """The SQL expression for a direct attribute (``status``)."""
        if "." in path:
            raise ValueError(f"Use a relationship filter for {path!r}")
        return getattr(self.model, path)

    def _relation_condition(self, model: Any, path: str, make: Callable) -> Any:
        """Build ``Model.rel.has(Target.attr ...)`` for dotted paths."""
        head, _, rest = path.partition(".")
        if not rest:
            return make(getattr(model, head))
        rel = sa_inspect(model).relationships[head]
        target = rel.mapper.class_
        inner = self._relation_condition(target, rest, make)
        attr = getattr(model, head)
        return attr.any(inner) if rel.uselist else attr.has(inner)

    def _search_condition(self, term: str, columns: list[Column]):
        conds = []
        like = f"%{term}%"
        for col in columns:
            if not col._searchable:
                continue
            if col._search_query is not None:
                conds.append(call(col._search_query, search=term, model=self.model))
                continue
            for path in col._search_columns or [col.name]:
                try:
                    conds.append(self._relation_condition(
                        self.model, path, lambda c: cast(c, String).ilike(like)))
                except (KeyError, AttributeError):
                    continue
        return or_(*conds) if conds else None

    def _sort_expression(self, query, path: str):
        if "." not in path:
            return query, getattr(self.model, path)
        parts = path.split(".")
        model = self.model
        current = self.model
        for part in parts[:-1]:
            rel = sa_inspect(model).relationships[part]
            alias = aliased(rel.mapper.class_)
            query = query.outerjoin(alias, getattr(current, part))
            model = rel.mapper.class_
            current = alias
        return query, getattr(current, parts[-1])

    def _eager_load_paths(self) -> set[tuple[str, ...]]:
        """Relationship paths the visible cells will read, so each is loaded in one query, not once per row.

        ``customer.name`` needs ``customer`` and ``tags`` needs ``tags``. A column with ``state()`` is
        computed, but a name that is itself a relationship (``TextColumn("items").state(lambda record:
        len(record.items))``) is almost always read by it, so that relationship is loaded too.
        """
        paths = set()
        for col in self._columns:
            if getattr(col, "_counts", None) is not None:  # counted with one GROUP BY, never loaded
                continue
            path: list[str] = []
            model = self.model
            for part in col.name.split("."):
                rels = sa_inspect(model).relationships
                if part not in rels:
                    break
                rel = rels[part]
                path.append(part)
                model = rel.mapper.class_
            if path:
                paths.add(tuple(path))
        return paths

    def _eager_loads(self, query):
        if self.model is None:
            return query
        for path in self._eager_load_paths():
            model = self.model
            loader = None
            try:
                for part in path:
                    rel = sa_inspect(model).relationships[part]
                    attr = getattr(model, part)
                    loader = selectinload(attr) if loader is None else loader.selectinload(attr)
                    model = rel.mapper.class_
            except KeyError:
                continue
            if loader is not None:
                query = query.options(loader)
        return query

    def relation_count(self, relationship: str, record: Any) -> int:
        """How many ``relationship`` rows ``record`` has. The first call counts the whole page in one query."""
        mapper = sa_inspect(self.model)
        if len(mapper.primary_key) != 1:
            return len(getattr(record, relationship) or [])
        pk = mapper.primary_key[0]
        cache = self._relation_counts.setdefault(relationship, {})
        key = getattr(record, pk.key)
        if key not in cache:
            keys = {getattr(r, pk.key) for r in getattr(self, "_page_records", None) or ()} | {key}
            keys = [k for k in keys if k not in cache]
            pk_attr = getattr(self.model, pk.key)
            for start in range(0, len(keys), 500):  # stay under the database's bound-parameter limit
                chunk = keys[start:start + 500]
                rows = self.ctx.db.execute(
                    select(pk_attr, func.count()).select_from(self.model).join(getattr(self.model, relationship))
                    .where(pk_attr.in_(chunk)).group_by(pk_attr))
                found = dict(rows.all())
                for k in chunk:
                    cache[k] = int(found.get(k, 0))
        return cache[key]

    def _scoped_base_query(self):
        query = self.host.base_query(self.ctx)
        sd = self.host.soft_delete_column
        if sd and self.trashed_mode() == "without":
            query = query.where(getattr(self.model, sd).is_(None))
        if self._modify_query is not None:
            query = call(self._modify_query, **{**self.ev(), "query": query})
        return query

    def filtered_query(self):
        query = self.host.base_query(self.ctx)
        tab = self.active_tab
        if tab is not None:
            query = tab.apply(query, self)
        sd = self.host.soft_delete_column
        if sd:
            mode = self.trashed_mode()
            column = getattr(self.model, sd)
            if mode == "without":
                query = query.where(column.is_(None))
            elif mode == "only":
                query = query.where(column.is_not(None))
        if self._modify_query is not None:
            query = call(self._modify_query, **{**self.ev(), "query": query})
        for f in self._filters:
            query = f.apply(query, self.filter_data.get(f.name, {}), self)
        if self.search:
            cond = self._search_condition(self.search, [c for c in self._columns if c._global_searchable])
            if cond is not None:
                query = query.where(cond)
        searches = self.column_searches
        for col in self._columns:
            if col.name in searches:
                cond = self._search_condition(searches[col.name], [col])
                if cond is not None:
                    query = query.where(cond)
        return query

    def sorted_query(self, query):
        if self.is_reordering:
            return query.order_by(getattr(self.model, self._reorder_column), self.host.primary_key())
        group = self.group
        if group is not None:
            query, expr = self._sort_expression(query, group.attribute)
            query = query.order_by(expr)
        column, direction = self.sort
        if column:
            col = next((c for c in self._columns if c.name == column), None)
            if col is not None and col._sort_query is not None:
                query = call(col._sort_query, query=query, direction=direction, model=self.model)
            else:
                query, expr = self._sort_expression(query, column)
                query = query.order_by(expr.desc() if direction == "desc" else expr.asc())
        query = query.order_by(self.host.primary_key().desc() if not column else self.host.primary_key())
        return query

    # ---- cursor pagination
    def _keyset(self, query) -> tuple[Any, list[tuple[Any, bool, Callable, bool]] | None]:
        """The sort keys as ``(expression, descending, read value, nullable)``, or ``None`` when the
        order cannot be paged by cursor (a custom sort, drag-to-reorder, or a composite key)."""
        mapper = sa_inspect(self.model)
        if self.is_reordering or len(mapper.primary_key) != 1:
            return query, None
        keys: list[tuple[Any, bool, Callable, bool]] = []
        group = self.group
        if group is not None:
            query, expr = self._sort_expression(query, group.attribute)
            keys.append((expr, False, lambda r, p=group.attribute: read_path(r, p), _nullable(expr)))
        column, direction = self.sort
        if column:
            col = next((c for c in self._columns if c.name == column), None)
            if col is not None and col._sort_query is not None:
                return query, None
            query, expr = self._sort_expression(query, column)
            keys.append((expr, direction == "desc", lambda r, p=column: read_path(r, p), _nullable(expr)))
        pk = mapper.primary_key[0]
        keys.append((self.host.primary_key(), not column, lambda r, k=pk.key: getattr(r, k), False))
        return query, keys

    @staticmethod
    def _keyset_order(keys: list, reverse: bool) -> list:
        order = []
        for expr, desc, _, nullable in keys:
            if nullable:  # empty values last (first when paging backwards), the same on every database
                order.append(expr.is_(None).desc() if reverse else expr.is_(None))
            order.append(expr.desc() if desc != reverse else expr.asc())
        return order

    @staticmethod
    def _keyset_after(keys: list, values: list, reverse: bool):
        """WHERE for the rows after ``values`` in the (possibly reversed) order."""
        from sqlalchemy import false

        parts: list[tuple[Any, Any]] = []  # (equal, after) for each sort component
        for (expr, desc, _, nullable), value in zip(keys, values):
            if nullable and value is None:
                parts.append((expr.is_(None), expr.is_not(None) if reverse else false()))
                continue
            if nullable:
                parts.append((expr.is_not(None), false() if reverse else expr.is_(None)))
            parts.append((expr == value, expr < value if desc != reverse else expr > value))
        return or_(*[and_(*[eq for eq, _ in parts[:i]], after) for i, (_, after) in enumerate(parts)])

    def encode_cursor(self, keys: list, record: Any, direction: str) -> str:
        values = [_cursor_value(read(record)) for _, _, read, _ in keys]
        raw = json.dumps({"d": direction, "v": values}, separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    def decode_cursor(self, keys: list) -> tuple[str, list] | None:
        token = self.param("cursor")
        if not token:
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(str(token) + "=" * (-len(str(token)) % 4)))
            values = [_cursor_load(v) for v in data["v"]]
            if data["d"] not in ("n", "p") or len(values) != len(keys):
                return None
            return data["d"], values
        except (ValueError, KeyError, TypeError):  # a stale or edited link opens the first page
            return None

    def _cursor_page(self, query, per_page: int) -> list | None:
        """One page by cursor. Sets ``self._cursors``; ``None`` when this order can't use cursors."""
        query, keys = self._keyset(query)
        if keys is None:
            return None
        cursor = self.decode_cursor(keys)
        reverse = cursor is not None and cursor[0] == "p"
        if cursor is not None:
            query = query.where(self._keyset_after(keys, cursor[1], reverse))
        query = self._eager_loads(query.order_by(*self._keyset_order(keys, reverse)).limit(per_page + 1))
        records = list(self.ctx.db.scalars(query).unique().all())
        more = len(records) > per_page
        records = records[:per_page]
        if reverse:
            records.reverse()
        has_next = more if not reverse else True
        has_prev = cursor is not None and (more if reverse else True)
        self._cursors = {
            "next": self.encode_cursor(keys, records[-1], "n") if records and has_next else None,
            "prev": self.encode_cursor(keys, records[0], "p") if records and has_prev else None,
        }
        return records

    def get_total(self, query) -> int:
        return int(self.ctx.db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0)

    def get_records(self) -> tuple[list, int | None]:
        """The current page and the total (``None`` with simple or cursor pagination, which skip the count)."""
        page = self._page(self.filtered_query())
        return page["records"], page["total"]

    def _page(self, query) -> dict[str, Any]:
        """Fetch the rows on screen, by the table's pagination mode."""
        per_page = self.per_page
        paginated = self._paginated and not self.is_reordering
        mode = self._pagination_mode if paginated else "default"
        self._cursors = {}
        out: dict[str, Any] = {"paginated": paginated, "mode": mode, "per_page": per_page, "total": None,
                               "page": 1, "pages": 1, "start": 0, "has_next": False}
        records = None
        if mode == "cursor":
            records = self._cursor_page(query, per_page)
            if records is None:
                mode = out["mode"] = "simple"  # this sort can't use cursors; page by number instead
            else:
                out["has_next"] = bool(self._cursors.get("next"))
        if mode == "simple":
            page = self.page
            rows = list(self.ctx.db.scalars(
                self._eager_loads(self.sorted_query(query)).limit(per_page + 1).offset((page - 1) * per_page)
            ).unique().all())
            if not rows and page > 1:  # past the end (rows were deleted): back to the first page
                page = 1
                rows = list(self.ctx.db.scalars(
                    self._eager_loads(self.sorted_query(query)).limit(per_page + 1)).unique().all())
            records = rows[:per_page]
            out.update(page=page, start=(page - 1) * per_page, has_next=len(rows) > per_page)
        if mode == "default":
            total = self.get_total(query)
            sorted_q = self._eager_loads(self.sorted_query(query))
            pages = max(1, math.ceil(total / per_page)) if paginated else 1
            page = min(self.page, pages)
            if paginated:
                sorted_q = sorted_q.limit(per_page).offset((page - 1) * per_page)
            elif self._limit:
                sorted_q = sorted_q.limit(self._limit)
            records = list(self.ctx.db.scalars(sorted_q).unique().all())
            out.update(total=total, page=page, pages=pages, start=(page - 1) * per_page if paginated else 0)
        self._prepare(records)
        self._page_records = records
        out["records"] = records
        return out

    def _prepare(self, records: list) -> None:
        """Let the host add data to the rows (a relation's link-table columns as ``record.pivot``)."""
        prepare = getattr(self.host, "prepare_records", None)
        if prepare is not None and records:
            prepare(self.ctx, records)

    def summaries(self, query) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        sub = None
        records = None
        in_sql: list[tuple[dict, Any, Any]] = []  # (footer entry, summarizer, expression): one query for all
        for col in self.visible_columns():
            if not col._summarizers or ("." in col.name and col._state is None):
                continue
            if sub is None:
                sub = query.order_by(None).subquery()
            if col._state is None and col.name in sub.c:
                for s in col._summarizers:
                    entry = {"label": s.get_label(), "value": None}
                    out.setdefault(col.name, []).append(entry)
                    in_sql.append((entry, s, s.expressions(sub.c[col.name])))
                continue
            # computed (``state()``) or non-column values: summarise in Python over every matching row
            if records is None:
                records = list(self.ctx.db.scalars(self._eager_loads(query)).unique().all())
                self._page_records = records  # ``counts()`` columns then count every row at once
            ev = self.ev()
            values = [col.get_state(r, ev) for r in records]
            values = [x for v in values for x in (v if isinstance(v, list) else [v])]
            for s in col._summarizers:
                try:
                    value = s.compute(values)
                except TypeError:  # e.g. a sum over text
                    value = None
                out.setdefault(col.name, []).append({"label": s.get_label(), "value": s.format(value)})
        if in_sql:
            row = list(self.ctx.db.execute(select(*[e for _, _, exprs in in_sql for e in exprs])).one())
            for entry, s, exprs in in_sql:
                values, row = row[:len(exprs)], row[len(exprs):]
                entry["value"] = s.format(s.combine(values))
        return out

    def reorder(self, keys: list[str]) -> None:
        """Save a dragged order. ``keys`` are the rows on screen, in their new order.

        The rows on screen may be only some of the records (a filter, search or tab is
        active), so every record is renumbered: the moved rows take the slots they held
        before, and the rows not on screen keep their place.
        """
        column = self._reorder_column
        query = self.host.scoped_query(self.ctx).order_by(getattr(self.model, column), self.host.primary_key())
        records = list(self.ctx.db.scalars(query).all())
        by_key = {self.host.record_key(r): r for r in records}
        moved = [by_key[k] for k in dict.fromkeys(keys) if k in by_key]
        moved_ids = {id(r) for r in moved}
        new_order = iter(moved)
        records = [next(new_order) if id(r) in moved_ids else r for r in records]
        for position, record in enumerate(records, start=1):
            if getattr(record, column) != position:
                setattr(record, column, position)

    # ---- urls
    def state_params(self, **overrides: Any) -> list[tuple[str, Any]]:
        params: dict[str, Any] = {
            "tab": self.param("tab"),
            "reordering": self.param("reordering"),
            "search": self.search or None,
            "sort": self.param("sort"),
            "direction": self.param("direction"),
            "page": self.param("page"),
            "cursor": self.param("cursor"),
            "per_page": self.param("per_page") if str(self.param("per_page")) != str(self._default_per_page) else None,
            "group": self.param("group"),
        }
        if "page" in overrides and "cursor" not in overrides:
            params["cursor"] = None  # a new page, sort, tab or filter starts again from the top
        params.update(overrides)
        items = [(k, v) for k, v in params.items() if v not in (None, "")]
        items.extend((f"col_search.{name}", term) for name, term in self.column_searches.items())
        if self.params.get("_f") is not None:
            items.extend(self.filter_state_items())
        return items

    def filter_state_items(self, include_marker: bool = True) -> list[tuple[str, Any]]:
        """The applied filter values as query-string pairs."""
        items: list[tuple[str, Any]] = [("_f", "1")] if include_marker else []
        builders = {f.name: f for f in self._filters if hasattr(f, "field")}
        for key in self.params.keys():
            if key.startswith("filters.") and key.split(".")[1] not in builders:
                for v in self.params.getlist(key):
                    if v not in (None, ""):
                        items.append((key, v))
        form = self._state_form or self.filter_form
        for f in builders.values():
            items.extend(f.field.url_items(form, f.base()))
        return items

    def url(self, **overrides: Any) -> str:
        items = [("host", self.host.key)] + self.state_params(**overrides)
        return self.ctx.panel.url("_tw", "table") + "?" + urlencode(items)

    def push_url(self, **overrides: Any) -> str | None:
        base = self.host.page_url(self.ctx)
        if not base:
            return None
        qs = urlencode(self.state_params(**overrides))
        return base + ("?" + qs if qs else "")

    def sort_url(self, column: Column) -> str:
        current, direction = self.sort
        if current == column.name:
            if direction == "asc":
                return self.url(sort=column.name, direction="desc", page=None)
            return self.url(sort="", direction="", page=None)
        return self.url(sort=column.name, direction="asc", page=None)

    # ---- actions
    def visible_bulk_actions(self) -> list:
        ctx, host = self.ctx, self.host
        out = []
        for a in self._bulk_actions:
            if isinstance(a, ActionGroup):
                if any(x.is_available(host, ctx) for x in a.flatten()):
                    out.append(a)
            elif a.is_available(host, ctx):
                out.append(a)
        return out

    def find_action(self, scope: str, name: str) -> Action | None:
        pools = {
            "row": self._actions,
            "bulk": self._bulk_actions,
            "table": self._header_actions,
            "empty": self._empty_actions,
        }
        for a in flatten_actions(pools.get(scope, [])):
            if a.name == name:
                a.scope = "bulk" if scope == "bulk" else ("row" if scope == "row" else "table")
                return a
        return None

    def _scoped(self, actions: list, scope: str) -> list:
        for a in flatten_actions(actions):
            a.scope = scope
        return actions

    def can_update(self, record: Any) -> bool:
        return self.host.can(self.ctx, "update", record) if self.host else True

    def get_record_url(self, record: Any) -> str | None:
        if self._record_url is False:
            return None
        if self._record_url is not None:
            return evaluate(self._record_url, **{**self.ev(), "record": record})
        host = self.host
        if host is None:
            return None
        if host.is_trashed(record):
            return None
        if host.can(self.ctx, "update", record):
            url = host.edit_url(self.ctx, record)
            if url:
                return url
        if host.can(self.ctx, "view", record):
            return host.view_url(self.ctx, record)
        return None

    # ------------------------------------------------------------------ render
    def view_data(self) -> dict[str, Any]:
        ctx = self.ctx
        query = self.filtered_query()
        paging = self._page(query)
        records = paging["records"]
        total, page, pages, per_page = paging["total"], paging["page"], paging["pages"], paging["per_page"]
        paginated = paging["paginated"]
        columns = self.visible_columns()
        self._scoped(self._actions, "row")
        self._scoped(self._bulk_actions, "bulk")
        self._scoped(self._header_actions, "table")
        self._scoped(self._empty_actions, "empty")
        group = None if self.is_reordering else self.group
        rows = []
        last_group = object()
        group_index = -1
        start = paging["start"]
        for i, record in enumerate(records):
            if group is not None:
                title = group.get_title(record)
                if title != last_group:
                    group_index += 1
                    rows.append({"group": title, "group_index": group_index})
                    last_group = title
            rows.append({
                "record": record,
                "group_index": group_index,
                "key": self.host.record_key(record),
                "index": start + i + 1,
                "url": self.get_record_url(record),
                "trashed": self.host.is_trashed(record),
                "classes": call(self._record_classes, record=record) if self._record_classes else "",
            })
        has_row_actions = bool(self._actions)
        return {
            "table": self,
            "ctx": ctx,
            "host": self.host,
            "columns": columns,
            "rows": rows,
            "total": total,
            "page": page,
            "pages": pages,
            "per_page": per_page,
            "from": start + 1 if records else 0,
            "to": start + len(records),
            "page_links": _page_links(page, pages),
            "summaries": self.summaries(query) if any(c._summarizers for c in columns) else {},
            "selectable": self.is_selectable(),
            "paginated": paginated,
            "pagination_mode": paging["mode"],
            "has_next": paging["has_next"],
            "cursors": self._cursors,
            "column_groups": self.column_group_headers(columns),
            "content_grid": self.content_grid_classes() if self._content_grid else None,
            "stacked": self._stacked_on_mobile and not self._content_grid,
            "deferred": self.has_deferred_filters(),
            "filters_layout": self._filters_layout,
            "reordering": self.is_reordering,
            "reorderable": bool(self._reorder_column) and self.host.can(ctx, "update"),
            "tabs": self.tab_data() if self._tabs else [],
            "bulk_actions": self.visible_bulk_actions(),
            "header_actions": self._header_actions,
            "row_actions": self._actions if has_row_actions else [],
            "empty_actions": self._empty_actions,
            "indicators": self.active_indicators(),
            "inline_filters": self.inline_filters(),
            "panel_filters": self.panel_filters(),
            "active_panel_count": sum(1 for f in self.panel_filters() if f.is_active(self.filter_data.get(f.name, {}))),
            "toggleable": self.toggleable_columns(),
            "groups": self._groups,
            "group": group,
            "individual_search": self.has_individual_search(columns),
            "column_searches": self.column_searches,
            "heading": maybe(evaluate(self._heading, **self.ev())),
            "description": maybe(evaluate(self._description, **self.ev())),
            "empty_heading": maybe(evaluate(self._empty_heading, **self.ev()))
            or __("No :records", records=self.host.title().lower() or __("records")),
            "empty_description": maybe(evaluate(self._empty_description, **self.ev())) or (
                __("Try a different search or filter.") if (self.search or self.column_searches or self.active_indicators())
                else __("Create one to get started.")),
            "empty_icon": self._empty_icon,
            "search_placeholder": maybe(self._search_placeholder)
            or __("Search :records...", records=self.host.title().lower() or __("records")),
        }

    def render(self) -> Markup:
        return self.renderer.render("tungsten/tables/table.html", **self.view_data())

    def __html__(self) -> str:
        return str(self.render())


def _nullable(expr: Any) -> bool:
    try:
        return bool(expr.property.columns[0].nullable)
    except (AttributeError, IndexError):
        return True


def _cursor_value(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, dt.date):
        return {"$d": value.isoformat()}
    if isinstance(value, dt.time):
        return {"$t": value.isoformat()}
    if isinstance(value, decimal.Decimal):
        return {"$n": str(value)}
    if hasattr(value, "value") and hasattr(type(value), "__members__"):  # an Enum
        return _cursor_value(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _cursor_load(value: Any) -> Any:
    if isinstance(value, dict):
        (tag, raw), = value.items()
        return {"$dt": dt.datetime.fromisoformat, "$d": dt.date.fromisoformat, "$t": dt.time.fromisoformat,
                "$n": decimal.Decimal}[tag](raw)
    return value


def _page_links(page: int, pages: int) -> list[int | None]:
    """Page numbers with ``None`` for gaps: 1 2 3 4 5 … 33."""
    if pages <= 7:
        return list(range(1, pages + 1))
    links: list[int | None] = []
    window = {1, pages, page - 1, page, page + 1}
    if page <= 4:
        window |= {2, 3, 4, 5}
    if page >= pages - 3:
        window |= {pages - 1, pages - 2, pages - 3, pages - 4}
    prev = 0
    for n in sorted(p for p in window if 1 <= p <= pages):
        if n - prev > 1:
            links.append(None)
        links.append(n)
        prev = n
    return links
