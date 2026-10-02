"""The :class:`Table`: builds the query from the URL state and renders the grid."""

from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlencode

from markupsafe import Markup
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import aliased, selectinload

from ..actions.action import Action, ActionGroup, BulkAction, flatten_actions
from ..forms.form import Form
from ..support.component import Component, headline
from ..support.evaluate import call, evaluate
from .columns import Column, read_path
from .filters import Filter, TrashedFilter

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..hosts import Host

_ids = itertools.count(1)


class Group(Component):
    """Group rows by an attribute: ``Group("status")`` or ``Group("category.name")``."""

    def __init__(self, attribute: str, label: str | None = None) -> None:
        super().__init__()
        self.attribute = attribute
        self._label = label
        self._title: Callable | None = None
        self._collapsible = True

    def label(self, label: str) -> "Group":
        self._label = label
        return self

    def title(self, fn: Callable) -> "Group":
        """``title(lambda record: ...)`` for the group heading."""
        self._title = fn
        return self

    def get_label(self) -> str:
        return self._label or headline(self.attribute.replace(".", " "))

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
        return self._label or headline(self.name)

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
        self._export: Any = None
        self._limit: int | None = None
        self._reorder_column: str | None = None
        self._tabs: list = []
        # runtime
        self.ctx: Context | None = None
        self.host: Host | None = None
        self.params: Any = {}
        self.id = f"tw-table-{next(_ids)}"
        self.model: Any = None
        self.filter_form: Form | None = None
        self.filter_data: dict[str, dict] = {}
        self._joins: dict[str, Any] = {}

    # ------------------------------------------------------------------ config
    def columns(self, columns: list[Column]) -> "Table":
        self._columns = list(columns)
        return self

    def filters(self, filters: list[Filter], layout: str | None = None) -> "Table":
        """``layout``: ``"panel"`` (side panel, default) or ``"above"`` (all inline)."""
        self._filters = list(filters)
        if layout:
            self._filters_layout = layout
        return self

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

    def paginated(self, options: list[int] | bool = True, default: int | None = None) -> "Table":
        if options is False:
            self._paginated = False
        elif isinstance(options, list):
            self._per_page_options = options
        if default:
            self._default_per_page = default
        elif isinstance(options, list) and options:
            self._default_per_page = options[0]
        return self

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
        self._load_filters()
        return self

    def ev(self) -> dict[str, Any]:
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

    def is_searchable(self) -> bool:
        if self._searchable is not None:
            return self._searchable
        return any(c._searchable for c in self._columns)

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

    def toggleable_columns(self) -> list[dict]:
        hidden = self.hidden_columns()
        return [{"name": c.name, "label": c.get_label(), "visible": c.name not in hidden}
                for c in self._columns if c._toggleable]

    # ---- filters
    def _load_filters(self) -> None:
        form = Form().columns(1)
        form.bind(self.ctx, operation="filter", refresh_url=None)
        form.id = self.id + "-filters"
        self.filter_form = form
        submitted = self.params.get("_f") is not None
        self.filter_data = {}
        for f in self._filters:
            base = f.base()
            if submitted:
                for field in f.get_fields():
                    field.load_state(form, self.params, base)
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
            self.filter_data[f.name] = data

    def active_indicators(self) -> list[dict]:
        out = []
        for f in self._filters:
            for label in f.indicators(self.filter_data.get(f.name, {}), self):
                out.append({"filter": f.name, "label": label})
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

    def _eager_loads(self, query):
        paths = set()
        for col in self._columns:
            if "." in col.name and col._state is None:
                paths.add(tuple(col.name.split(".")[:-1]))
        for path in paths:
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
            cond = self._search_condition(self.search, self._columns)
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

    def get_total(self, query) -> int:
        return int(self.ctx.db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0)

    def get_records(self) -> tuple[list, int]:
        query = self.filtered_query()
        total = self.get_total(query)
        query = self._eager_loads(self.sorted_query(query))
        if self._paginated:
            pages = max(1, math.ceil(total / self.per_page))
            page = min(self.page, pages)
            query = query.limit(self.per_page).offset((page - 1) * self.per_page)
        records = list(self.ctx.db.scalars(query).unique().all())
        return records, total

    def summaries(self, query) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        sub = None
        for col in self.visible_columns():
            if not col._summarizers or "." in col.name:
                continue
            if sub is None:
                sub = query.order_by(None).subquery()
            for s in col._summarizers:
                value = self.ctx.db.scalar(select(s.expression(sub.c[col.name])))
                out.setdefault(col.name, []).append({"label": s.get_label(), "value": s.format(value)})
        return out

    # ---- urls
    def state_params(self, **overrides: Any) -> list[tuple[str, Any]]:
        params: dict[str, Any] = {
            "tab": self.param("tab"),
            "reordering": self.param("reordering"),
            "search": self.search or None,
            "sort": self.param("sort"),
            "direction": self.param("direction"),
            "page": self.param("page"),
            "per_page": self.param("per_page") if str(self.param("per_page")) != str(self._default_per_page) else None,
            "group": self.param("group"),
        }
        params.update(overrides)
        items = [(k, v) for k, v in params.items() if v not in (None, "")]
        if self.params.get("_f") is not None:
            items.append(("_f", "1"))
            for key in self.params.keys():
                if key.startswith("filters."):
                    for v in self.params.getlist(key):
                        if v not in (None, ""):
                            items.append((key, v))
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
        total = self.get_total(query)
        sorted_q = self._eager_loads(self.sorted_query(query))
        per_page = self.per_page
        paginated = self._paginated and not self.is_reordering
        pages = max(1, math.ceil(total / per_page)) if paginated else 1
        page = min(self.page, pages)
        if paginated:
            sorted_q = sorted_q.limit(per_page).offset((page - 1) * per_page)
        elif self._limit:
            sorted_q = sorted_q.limit(self._limit)
        records = list(ctx.db.scalars(sorted_q).unique().all())
        columns = self.visible_columns()
        self._scoped(self._actions, "row")
        self._scoped(self._bulk_actions, "bulk")
        self._scoped(self._header_actions, "table")
        self._scoped(self._empty_actions, "empty")
        group = None if self.is_reordering else self.group
        rows = []
        last_group = object()
        start = (page - 1) * per_page if paginated else 0
        for i, record in enumerate(records):
            if group is not None:
                title = group.get_title(record)
                if title != last_group:
                    rows.append({"group": title})
                    last_group = title
            rows.append({
                "record": record,
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
            "heading": evaluate(self._heading, **self.ev()),
            "description": evaluate(self._description, **self.ev()),
            "empty_heading": evaluate(self._empty_heading, **self.ev()) or f"No {self.host.title().lower() or 'records'}",
            "empty_description": evaluate(self._empty_description, **self.ev()) or (
                "Try a different search or filter." if (self.search or self.active_indicators()) else "Create one to get started."),
            "empty_icon": self._empty_icon,
            "search_placeholder": self._search_placeholder or f"Search {self.host.title().lower() or 'records'}...",
        }

    def render(self) -> Markup:
        return self.renderer.render("tungsten/tables/table.html", **self.view_data())

    def __html__(self) -> str:
        return str(self.render())


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
