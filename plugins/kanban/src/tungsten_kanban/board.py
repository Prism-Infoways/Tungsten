"""A board: the records of one resource, in columns by a status field, moved by drag and drop."""

from __future__ import annotations

import datetime as dt
import decimal
import enum
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from tungsten.i18n import translate as __
from tungsten.support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from tungsten.context import Context

#: colors a column or badge may have (the panel's own palette)
COLORS = ("gray", "primary", "info", "success", "warning", "danger", "indigo", "pink", "purple", "teal")
#: most cards one column shows before "Load more"
MAX_LIMIT = 200
#: cards a move may renumber in one go (the ones on screen in the target column)
MAX_ORDER_KEYS = 1000
#: longest search text we look for
MAX_SEARCH = 100


class MoveRefused(Exception):
    """Raise this from ``on_move`` or ``can_move`` to stop a move. The message is shown to the user."""


def key_of(value: Any) -> str:
    """The text form of a column value, as it travels in HTML and forms."""
    if isinstance(value, enum.Enum):
        value = value.value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _kebab(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "board"


@dataclass
class Column:
    key: str           # text form, used in HTML
    value: Any         # the real value stored in the record
    label: str
    color: str = "gray"
    #: soft work-in-progress limit: the count turns red above it
    limit: int | None = None
    #: False: cards can't be dropped here (the "Other" column)
    accepts: bool = True


@dataclass
class Card:
    key: str
    title: str
    url: str | None
    description: str | None = None
    fields: list[tuple[str, str]] = field(default_factory=list)
    badges: list[tuple[str, str]] = field(default_factory=list)
    color: str | None = None
    #: columns this card may move to from its own (None: every column)
    targets: list[str] | None = None
    can_move: bool = True


def _get(record: Any, path: str) -> Any:
    value = record
    for part in path.split("."):
        if value is None:
            return None
        value = getattr(value, part, None)
    return value


def _text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, enum.Enum):
        value = value.value
    if isinstance(value, dt.datetime):
        return value.strftime("%d %b %Y, %H:%M")
    if isinstance(value, dt.date):
        return value.strftime("%d %b %Y")
    if isinstance(value, bool):
        return __("Yes") if value else __("No")
    if isinstance(value, decimal.Decimal):
        return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:,.0f}"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value) or None
    return str(value)


def _short(text: str | None, size: int = 140) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Board:
    """Show a resource's records as a drag-and-drop board::

        Board(TaskResource, column="status", columns={
            "todo": ("To do", "gray"), "doing": ("Doing", "primary"), "done": ("Done", "success"),
        }, description="notes", fields={"Due": "due_date"}, order_column="sort")

    - ``column`` is the field that says which column a record is in (a status, a stage...).
    - ``columns`` maps each value to a label or ``(label, color)``. It can be a function that
      gets ``ctx``, so the columns follow settings that change at runtime.
    - ``title``, ``description``, ``color`` and each value of ``fields`` / ``badges`` are an
      attribute name (``"employee.name"`` works) or a function of ``record`` (and ``ctx``).
    - ``order_column`` (an integer field) lets people drag cards up and down inside a column.
    - ``transitions`` limits moves: ``{"pending": ["approved", "rejected"]}``. ``can_move`` is a
      function of ``record``, ``old``, ``new`` and ``ctx`` that returns False or a reason.
    - ``on_move`` does the move itself (``record``, ``old``, ``new``, ``db``, ``ctx``, ``user``),
      for example through a service that logs and emails. Default: set the field.
    """

    def __init__(self, resource: Any, column: str = "status", columns: Any = None, *,
                 slug: str | None = None, label: str | None = None, subheading: str | None = None,
                 icon: str = "square-kanban", navigation_group: Any = "inherit", navigation_sort: int | None = None,
                 show_in_navigation: bool = True, permission: str | None = None,
                 title: Any = None, description: Any = None, fields: Any = None, badges: Any = None,
                 color: Any = None, order_column: str | None = None, sort_by: Any = None,
                 query: Callable | None = None, search: list[str] | None = None, assignee: str | None = None,
                 limit: int = 50, wip_limits: dict[Any, int] | None = None, hidden: list[Any] | None = None,
                 transitions: dict[Any, list[Any]] | None = None, can_move: Callable | None = None,
                 on_move: Callable | None = None, card_url: Any = None, show_other: bool = True,
                 empty_text: str = "No cards here") -> None:
        if resource is None or getattr(resource, "model", None) is None:
            raise ValueError("Board needs a resource with a model")
        try:
            getattr(resource.model, column)
        except AttributeError:
            raise ValueError(f"{resource.model.__name__} has no field {column!r} for the board columns") from None
        if order_column is not None and not hasattr(resource.model, order_column):
            raise ValueError(f"{resource.model.__name__} has no field {order_column!r} to keep the card order")
        if assignee is not None and not hasattr(resource.model, assignee):
            raise ValueError(f"{resource.model.__name__} has no field {assignee!r} for 'only mine'")
        for name in search or []:
            if not hasattr(resource.model, name):
                raise ValueError(f"{resource.model.__name__} has no field {name!r} to search")
        self.resource = resource
        self.column = column
        self._columns = columns
        self.slug = slug or f"{resource.get_slug()}-board"
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.slug):
            raise ValueError(f"Board slug {self.slug!r} may only have small letters, digits and dashes")
        self.label = label
        self.subheading = subheading
        self.icon = icon
        self.navigation_group = resource.navigation_group if navigation_group == "inherit" else navigation_group
        self.navigation_sort = resource.navigation_sort if navigation_sort is None else navigation_sort
        self.show_in_navigation = show_in_navigation
        self.permission = permission
        self.title = title
        self.description = description
        self.fields = fields
        self.badges = badges
        self.color = color
        self.order_column = order_column
        self.sort_by = sort_by
        self.query = query
        self.search = list(search or [])
        self.assignee = assignee
        self.limit = max(1, min(int(limit), MAX_LIMIT))
        self.wip_limits = {key_of(k): int(v) for k, v in (wip_limits or {}).items()}
        self.hidden = {key_of(k) for k in (hidden or [])}
        self.transitions = None if transitions is None else \
            {key_of(k): {key_of(v) for v in vs} for k, vs in transitions.items()}
        self.can_move = can_move
        self.on_move = on_move
        self.card_url = card_url
        self.show_other = show_other
        self.empty_text = empty_text
        #: set by the plugin: functions that add badges to every card, by key
        self.plugin: Any = None
        self.page: Any = None

    # ------------------------------------------------------------------ naming
    def get_label(self) -> str:
        return __(self.label) if self.label else __(":things board", things=self.resource.get_plural_label())

    def model_column(self) -> Any:
        return getattr(self.resource.model, self.column)

    # ------------------------------------------------------------------ columns
    def get_columns(self, ctx: Context) -> list[Column]:
        raw = self._columns
        if callable(raw):
            raw = call(raw, ctx=ctx, db=ctx.db, user=ctx.user, board=self)
        if raw is None:
            raw = self._columns_from_model()
        out: list[Column] = []
        seen: set[str] = set()
        for value, spec in dict(raw).items():
            key = key_of(value)
            if key in seen or key in self.hidden:
                continue
            seen.add(key)
            if isinstance(spec, (tuple, list)):
                label = str(spec[0]) if spec else key
                color = str(spec[1]) if len(spec) > 1 and spec[1] else "gray"
            else:
                label, color = (str(spec) if spec is not None else key), "gray"
            if color not in COLORS:
                color = "gray"
            out.append(Column(key, value, __(label), color, self.wip_limits.get(key)))
        return out

    def _columns_from_model(self) -> dict:
        """Columns from an Enum field, when ``columns`` is not given."""
        col = self.model_column()
        enum_class = getattr(getattr(col, "type", None), "enum_class", None)
        if enum_class is not None:
            return {m: m.name.replace("_", " ").capitalize() for m in enum_class}
        raise ValueError(f"Give Board(columns=...) for {self.resource.__name__}.{self.column}")

    # ------------------------------------------------------------------ access
    def can_view(self, ctx: Context) -> bool:
        if ctx.user is None and ctx.panel.auth.enabled:
            return False
        if self.permission and not ctx.can(self.permission):
            return False
        return bool(self.resource.can(ctx, "view_any"))

    def can_update(self, ctx: Context, record: Any) -> bool:
        return bool(self.resource.can(ctx, "update", record))

    # ------------------------------------------------------------------ queries
    def host(self) -> Any:
        return self.resource.host()

    def base_query(self, ctx: Context, q: str = "", mine: bool = False) -> Any:
        """Every record this user may see on the board (tenancy, soft delete, the board's own filter)."""
        host = self.host()
        query = host.scoped_query(ctx, with_trashed=False)
        model = self.resource.model
        if self.query is not None:
            query = call(self.query, query=query, model=model, ctx=ctx, user=ctx.user, db=ctx.db) or query
        q = (q or "").strip()[:MAX_SEARCH]
        if q and self.search:
            like = f"%{_escape_like(q.lower())}%"
            query = query.where(or_(*[func.lower(getattr(model, name)).like(like, escape="\\")
                                      for name in self.search]))
        if mine and self.assignee and ctx.user is not None:
            query = query.where(getattr(model, self.assignee) == str(ctx.panel.auth.user_id(ctx.user)))
        return query

    def _ordered(self, query: Any) -> Any:
        model = self.resource.model
        pk = self.host().primary_key()
        query = query.order_by(None)  # the board decides the order, not the resource's own query
        if self.order_column:
            return query.order_by(getattr(model, self.order_column).is_(None), getattr(model, self.order_column), pk)
        if self.sort_by is not None:
            order = self.sort_by if isinstance(self.sort_by, (list, tuple)) else [self.sort_by]
            return query.order_by(*[getattr(model, o[1:]).desc() if isinstance(o, str) and o.startswith("-")
                                    else getattr(model, o) if isinstance(o, str) else o for o in order], pk)
        return query.order_by(pk.desc())

    def counts(self, ctx: Context, columns: list[Column], q: str = "", mine: bool = False) -> dict[str, int]:
        """Cards per column, with "" for records whose value is in no column."""
        sub = self.base_query(ctx, q, mine).subquery()
        col = sub.c[self.model_column().key]
        rows = ctx.db.execute(select(col, func.count()).group_by(col)).all()
        known = {c.key for c in columns}
        out = {c.key: 0 for c in columns}
        other = 0
        for value, n in rows:
            key = key_of(value)
            if key in known:
                out[key] += n
            elif key not in self.hidden:
                other += n
        out[""] = other
        return out

    def records(self, ctx: Context, column: Column | None, columns: list[Column], q: str = "",
                mine: bool = False, offset: int = 0) -> tuple[list, bool]:
        """One page of a column's records, and whether there are more."""
        query = self.base_query(ctx, q, mine)
        col = self.model_column()
        if column is not None:
            query = query.where(col == column.value)
        else:  # "Other": values no column has (and no hidden one)
            values = [c.value for c in columns] + [v for v in self._hidden_values(ctx)]
            query = query.where(or_(col.is_(None), col.notin_(values))) if values else query.where(col.is_(None))
        rows = list(ctx.db.scalars(self._ordered(query).offset(max(0, offset)).limit(self.limit + 1)).unique().all())
        return rows[: self.limit], len(rows) > self.limit

    def _hidden_values(self, ctx: Context) -> list:
        if not self.hidden:
            return []
        raw = self._columns
        if callable(raw):
            raw = call(raw, ctx=ctx, db=ctx.db, user=ctx.user, board=self)
        values = [v for v in dict(raw or {}) if key_of(v) in self.hidden]
        return values or list(self.hidden)

    # ------------------------------------------------------------------ cards
    def _value(self, spec: Any, record: Any, ctx: Context) -> Any:
        if spec is None:
            return None
        if callable(spec):
            return call(spec, record=record, ctx=ctx, db=ctx.db, user=ctx.user, board=self)
        return _get(record, str(spec))

    def _url(self, ctx: Context, record: Any) -> str | None:
        if self.card_url is not None:
            return self._value(self.card_url, record, ctx)
        resource = self.resource
        for page, ability in (("view", "view"), ("edit", "update")):
            if resource.has_page(page) and resource.can(ctx, ability, record):
                return resource.get_url(ctx, page, record)
        return None

    def targets(self, ctx: Context, record: Any, columns: list[Column]) -> list[str] | None:
        """Columns this record may be dropped in (None: all)."""
        current = key_of(getattr(record, self.column, None))
        if self.transitions is None:
            return None
        allowed = self.transitions.get(current)
        if allowed is None:
            return None
        return [c.key for c in columns if c.key in allowed or c.key == current]

    def card(self, ctx: Context, record: Any, columns: list[Column]) -> Card:
        host = self.host()
        title = self._value(self.title, record, ctx) if self.title is not None \
            else self.resource.get_record_title(record)
        fields_spec = self.fields or {}
        if isinstance(fields_spec, (list, tuple)):
            fields_spec = {str(name).split(".")[-1].replace("_", " ").capitalize(): name for name in fields_spec}
        fields = []
        for label, spec in dict(fields_spec).items():
            text = _text(self._value(spec, record, ctx))
            if text:
                fields.append((__(label), _short(text, 60) or ""))
        badges = []
        for spec in (self.badges or []):
            value = self._value(spec, record, ctx)
            badges.extend(_badges(value))
        if self.plugin is not None:
            for fn in list(self.plugin.badge_providers.values()):
                try:
                    badges.extend(_badges(call(fn, record=record, board=self, ctx=ctx, db=ctx.db, user=ctx.user)))
                except Exception:  # a broken add-on must not break the board
                    import logging

                    logging.getLogger("tungsten.kanban").exception("Card badge function failed")
        color = self._value(self.color, record, ctx)
        movable = self.can_update(ctx, record)
        targets = self.targets(ctx, record, columns) if movable else []
        if movable and targets is not None and len(targets) <= 1 and not self.order_column:
            movable = False  # nowhere to go from here (a final status)
        return Card(
            key=host.record_key(record), title=_short(str(title or ""), 120) or __("(no title)"),
            url=self._url(ctx, record), description=_short(_text(self._value(self.description, record, ctx))),
            fields=fields, badges=badges[:6], color=color if color in COLORS else None,
            targets=targets if movable else [], can_move=movable,
        )


def _badges(value: Any) -> list[tuple[str, str]]:
    """Badge specs: text, ``(text, color)`` or a list of them."""
    if value is None or value == "":
        return []
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], str) and value[1] in COLORS:
        text = _text(value[0])
        return [(text, value[1])] if text else []
    if isinstance(value, (list, tuple, set)):
        out: list[tuple[str, str]] = []
        for v in value:
            out.extend(_badges(v))
        return out
    text = _text(value)
    return [(_short(text, 30) or "", "gray")] if text else []


def slug_for(text: str) -> str:
    return _kebab(text)
