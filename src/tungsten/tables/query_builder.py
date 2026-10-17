"""The query builder filter: users build their own conditions in the filter panel.

::

    QueryBuilder().constraints([
        TextConstraint("name"),
        NumberConstraint("price"),
        DateConstraint("created_at"),
        BooleanConstraint("is_visible"),
        SelectConstraint("status").options(OrderStatus),
        RelationshipConstraint("tags").selectable("name"),
        TextConstraint("category.name").label("Category name"),
    ])

Rules inside a group must all match (AND). Groups are joined with OR.
"""

from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Callable

from markupsafe import Markup
from sqlalchemy import Date, DateTime, String, and_, cast, false, func, not_, or_, select
from sqlalchemy import inspect as sa_inspect

from ..forms.fields import Field, normalize_options
from ..i18n import translate as __
from ..support.component import headline
from ..support.evaluate import call, evaluate
from ..support.state import get_path, set_path
from .filters import Filter

if TYPE_CHECKING:  # pragma: no cover
    from ..forms.form import Form
    from .table import Table

MAX_GROUPS = 10
MAX_RULES = 20


class Constraint:
    """One thing users can filter on. Subclasses list operators and build SQL."""

    kind = "text"
    icon = "text-cursor"
    #: operator -> (label, value input: None / "text" / "number" / "date" / "between" / "select" / "multi")
    operators: dict[str, tuple[str, str | None]] = {}

    def __init__(self, name: str, attribute: str | None = None) -> None:
        self.name = name
        self.attribute = attribute or name
        self._label: Any = None
        self._icon: str | None = None

    def label(self, label: Any) -> "Constraint":
        self._label = label
        return self

    def icon_name(self, icon: str) -> "Constraint":
        self._icon = icon
        return self

    def get_label(self) -> str:
        if self._label is not None:
            return __(str(self._label))
        return __(headline(self.name.replace(".", " ")))

    def get_icon(self) -> str:
        return self._icon or self.icon

    def get_operators(self) -> dict[str, tuple[str, str | None]]:
        return self.operators

    def input_for(self, op: str) -> str | None:
        return self.get_operators().get(op, ("", None))[1]

    def input_type(self) -> str:
        return {"number": "number", "date": "date"}.get(self.kind, "text")

    # ---- values
    def parse_value(self, raw: Any) -> Any:
        """Convert one raw value; raise ``ValueError`` for bad input."""
        raw = str(raw).strip()
        if raw == "":
            raise ValueError("empty")
        return raw

    def parse(self, rule: dict) -> dict | None:
        """A typed copy of ``rule``, or None when it is incomplete or invalid."""
        op = rule.get("op")
        if op not in self.get_operators():
            return None
        needs = self.input_for(op)
        out = {"c": self.name, "op": op}
        try:
            if needs in ("text", "number", "date", "select"):
                out["v"] = self.parse_value(rule.get("v", ""))
            elif needs == "between":
                out["v"] = self.parse_value(rule.get("v", ""))
                out["v2"] = self.parse_value(rule.get("v2", ""))
            elif needs == "multi":
                values = [self.parse_value(v) for v in rule.get("vs") or [] if str(v).strip()]
                if not values:
                    return None
                out["vs"] = values
            elif needs == "count":
                out["v"] = int(str(rule.get("v", "")).strip())
                if out["v"] < 0:
                    return None
        except (ValueError, TypeError, InvalidOperation):
            return None
        return out

    # ---- sql
    def condition(self, table: "Table", rule: dict) -> Any:
        return table._relation_condition(table.model, self.attribute, lambda col: self.compare(col, rule))

    def compare(self, column: Any, rule: dict) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    # ---- labels
    def describe_value(self, value: Any, table: "Table") -> str:
        return f"“{value}”" if self.kind == "text" else str(value)

    def describe(self, rule: dict, table: "Table") -> str:
        label, needs = self.get_operators()[rule["op"]]
        text = f"{self.get_label()} {__(label).lower()}"
        if needs == "between":
            return __(":rule :from and :to", rule=text, **{"from": self.describe_value(rule["v"], table),
                                                          "to": self.describe_value(rule["v2"], table)})
        if needs == "multi":
            return f"{text} " + ", ".join(self.describe_value(v, table) for v in rule["vs"])
        if needs == "count":
            return f"{text} {rule['v']}"
        if needs is not None:
            return f"{text} {self.describe_value(rule['v'], table)}"
        return text

    def option_list(self, table: "Table") -> list[tuple[Any, str]]:
        return []


class TextConstraint(Constraint):
    kind = "text"
    icon = "text-cursor"
    operators = {
        "contains": ("Contains", "text"),
        "not_contains": ("Does not contain", "text"),
        "starts_with": ("Starts with", "text"),
        "ends_with": ("Ends with", "text"),
        "equals": ("Equals", "text"),
        "not_equals": ("Does not equal", "text"),
        "filled": ("Is filled", None),
        "blank": ("Is blank", None),
    }

    def compare(self, column: Any, rule: dict) -> Any:
        op, v = rule["op"], rule.get("v")
        text = cast(column, String)
        if op == "contains":
            return text.icontains(v, autoescape=True)
        if op == "not_contains":
            return or_(column.is_(None), not_(text.icontains(v, autoescape=True)))
        if op == "starts_with":
            return text.istartswith(v, autoescape=True)
        if op == "ends_with":
            return text.iendswith(v, autoescape=True)
        if op == "equals":
            return func.lower(text) == str(v).lower()
        if op == "not_equals":
            return or_(column.is_(None), func.lower(text) != str(v).lower())
        if op == "filled":
            return and_(column.is_not(None), text != "")
        return or_(column.is_(None), text == "")


class NumberConstraint(Constraint):
    kind = "number"
    icon = "hash"
    operators = {
        "eq": ("Equals", "number"),
        "ne": ("Does not equal", "number"),
        "gt": ("Is greater than", "number"),
        "gte": ("Is at least", "number"),
        "lt": ("Is less than", "number"),
        "lte": ("Is at most", "number"),
        "between": ("Is between", "between"),
        "not_between": ("Is not between", "between"),
        "filled": ("Is filled", None),
        "blank": ("Is blank", None),
    }

    def __init__(self, name: str, attribute: str | None = None) -> None:
        super().__init__(name, attribute)
        self._integer = False

    def integer(self, condition: bool = True) -> "NumberConstraint":
        self._integer = condition
        return self

    def parse_value(self, raw: Any) -> Any:
        raw = str(raw).strip()
        if raw == "":
            raise ValueError("empty")
        return int(raw) if self._integer else Decimal(raw)

    def compare(self, column: Any, rule: dict) -> Any:
        op, v = rule["op"], rule.get("v")
        if op == "eq":
            return column == v
        if op == "ne":
            return or_(column.is_(None), column != v)
        if op == "gt":
            return column > v
        if op == "gte":
            return column >= v
        if op == "lt":
            return column < v
        if op == "lte":
            return column <= v
        if op in ("between", "not_between"):
            low, high = sorted([v, rule["v2"]])
            inside = column.between(low, high)
            return inside if op == "between" else or_(column.is_(None), not_(inside))
        if op == "filled":
            return column.is_not(None)
        return column.is_(None)


def _add_months(day: dt.date, months: int) -> dt.date:
    """``day`` moved by ``months`` calendar months (the 31st becomes the month's last day)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    last = (dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(year, month, min(day.day, last))


def date_range(op: str, n: int = 0, today: dt.date | None = None) -> tuple[dt.date | None, dt.date | None]:
    """``(first day, day after the last)`` for a relative date operator. ``None`` means open-ended.

    Weeks start on Monday. "In the last 7 days" runs from 7 days ago up to the end of today.
    """
    today = today or dt.date.today()
    one = dt.timedelta(days=1)
    week = today - dt.timedelta(days=today.weekday())
    month = today.replace(day=1)
    year = today.replace(month=1, day=1)
    ranges = {
        "today": lambda: (today, today + one),
        "yesterday": lambda: (today - one, today),
        "tomorrow": lambda: (today + one, today + 2 * one),
        "this_week": lambda: (week, week + 7 * one),
        "last_week": lambda: (week - 7 * one, week),
        "next_week": lambda: (week + 7 * one, week + 14 * one),
        "this_month": lambda: (month, _add_months(month, 1)),
        "last_month": lambda: (_add_months(month, -1), month),
        "next_month": lambda: (_add_months(month, 1), _add_months(month, 2)),
        "this_year": lambda: (year, year.replace(year=year.year + 1)),
        "last_year": lambda: (year.replace(year=year.year - 1), year),
        "next_year": lambda: (year.replace(year=year.year + 1), year.replace(year=year.year + 2)),
        "last_days": lambda: (today - n * one, today + one),
        "last_weeks": lambda: (today - dt.timedelta(weeks=n), today + one),
        "last_months": lambda: (_add_months(today, -n), today + one),
        "last_years": lambda: (_add_months(today, -12 * n), today + one),
        "next_days": lambda: (today, today + n * one),
        "next_weeks": lambda: (today, today + dt.timedelta(weeks=n)),
        "next_months": lambda: (today, _add_months(today, n)),
        "past": lambda: (None, today),
        "future": lambda: (today + one, None),
    }
    return ranges[op]()


class DateConstraint(Constraint):
    kind = "date"
    icon = "calendar"
    operators = {
        "on": ("Is on", "date"),
        "not_on": ("Is not on", "date"),
        "before": ("Is before", "date"),
        "after": ("Is after", "date"),
        "between": ("Is between", "between"),
        "not_between": ("Is not between", "between"),
        "today": ("Is today", None),
        "yesterday": ("Is yesterday", None),
        "tomorrow": ("Is tomorrow", None),
        "this_week": ("Is this week", None),
        "last_week": ("Is last week", None),
        "next_week": ("Is next week", None),
        "this_month": ("Is this month", None),
        "last_month": ("Is last month", None),
        "next_month": ("Is next month", None),
        "this_year": ("Is this year", None),
        "last_year": ("Is last year", None),
        "next_year": ("Is next year", None),
        "last_days": ("Is in the last (days)", "count"),
        "last_weeks": ("Is in the last (weeks)", "count"),
        "last_months": ("Is in the last (months)", "count"),
        "last_years": ("Is in the last (years)", "count"),
        "next_days": ("Is in the next (days)", "count"),
        "next_weeks": ("Is in the next (weeks)", "count"),
        "next_months": ("Is in the next (months)", "count"),
        "past": ("Is in the past", None),
        "future": ("Is in the future", None),
        "filled": ("Is filled", None),
        "blank": ("Is blank", None),
    }
    #: count operators -> the sentence used for chips
    count_phrases = {
        "last_days": ":label is in the last :n days",
        "last_weeks": ":label is in the last :n weeks",
        "last_months": ":label is in the last :n months",
        "last_years": ":label is in the last :n years",
        "next_days": ":label is in the next :n days",
        "next_weeks": ":label is in the next :n weeks",
        "next_months": ":label is in the next :n months",
    }

    def parse_value(self, raw: Any) -> Any:
        return dt.date.fromisoformat(str(raw).strip())

    def compare(self, column: Any, rule: dict) -> Any:
        op = rule["op"]
        is_datetime = isinstance(getattr(column, "type", None), DateTime) or not isinstance(
            getattr(column, "type", None), Date)

        def start(day: dt.date) -> Any:
            return dt.datetime.combine(day, dt.time.min) if is_datetime else day

        def next_day(day: dt.date) -> Any:
            return start(day + dt.timedelta(days=1))

        if op == "on":
            return and_(column >= start(rule["v"]), column < next_day(rule["v"]))
        if op == "not_on":
            return or_(column.is_(None), column < start(rule["v"]), column >= next_day(rule["v"]))
        if op == "before":
            return column < start(rule["v"])
        if op == "after":
            return column >= next_day(rule["v"])
        if op == "between":
            low, high = sorted([rule["v"], rule["v2"]])
            return and_(column >= start(low), column < next_day(high))
        if op == "not_between":
            low, high = sorted([rule["v"], rule["v2"]])
            return or_(column.is_(None), column < start(low), column >= next_day(high))
        if op not in ("filled", "blank"):
            try:
                low, high = date_range(op, int(rule.get("v") or 0))
            except (OverflowError, ValueError):  # a huge N runs past year 1 or 9999: open-ended
                today = dt.date.today()
                low, high = (None, today + dt.timedelta(days=1)) if op.startswith("last") else (today, None)
            parts = []
            if low is not None:
                parts.append(column >= start(low))
            if high is not None:
                parts.append(column < start(high))
            return and_(*parts)
        if op == "filled":
            return column.is_not(None)
        return column.is_(None)

    def describe_value(self, value: Any, table: "Table") -> str:
        return value.strftime("%d %b %Y") if isinstance(value, dt.date) else str(value)

    def describe(self, rule: dict, table: "Table") -> str:
        phrase = self.count_phrases.get(rule["op"])
        if phrase:
            return __(phrase, label=self.get_label(), n=rule["v"])
        return super().describe(rule, table)


class BooleanConstraint(Constraint):
    kind = "boolean"
    icon = "toggle-right"
    operators = {"true": ("Is true", None), "false": ("Is false", None)}

    def compare(self, column: Any, rule: dict) -> Any:
        return column.is_(True) if rule["op"] == "true" else or_(column.is_(None), column.is_(False))


class SelectConstraint(Constraint):
    kind = "select"
    icon = "list"
    operators = {
        "is": ("Is", "select"),
        "is_not": ("Is not", "select"),
        "in": ("Is any of", "multi"),
        "not_in": ("Is none of", "multi"),
        "filled": ("Is filled", None),
        "blank": ("Is blank", None),
    }

    def __init__(self, name: str, attribute: str | None = None) -> None:
        super().__init__(name, attribute)
        self._options: Any = None
        self._table: Table | None = None

    def options(self, options: Any) -> "SelectConstraint":
        """A dict, a list, list of pairs, an Enum class, or a closure returning one."""
        self._options = options
        return self

    def option_list(self, table: "Table") -> list[tuple[Any, str]]:
        return normalize_options(evaluate(self._options, **table.ev()))

    def _typed(self, value: Any, table: "Table") -> Any:
        lookup = {str(k): k for k, _ in self.option_list(table)}
        if str(value) not in lookup:
            raise ValueError("unknown option")
        key = lookup[str(value)]
        if isinstance(self._options, type) and issubclass(self._options, enum.Enum):
            return self._options(key)
        return key

    def condition(self, table: "Table", rule: dict) -> Any:
        self._table = table
        return super().condition(table, rule)

    def compare(self, column: Any, rule: dict) -> Any:
        op = rule["op"]
        table = self._table
        if op in ("is", "is_not"):
            value = self._typed(rule["v"], table)  # type: ignore[arg-type]
            return column == value if op == "is" else or_(column.is_(None), column != value)
        if op in ("in", "not_in"):
            values = [self._typed(v, table) for v in rule["vs"]]  # type: ignore[arg-type]
            return column.in_(values) if op == "in" else or_(column.is_(None), column.not_in(values))
        if op == "filled":
            return column.is_not(None)
        return column.is_(None)

    def describe_value(self, value: Any, table: "Table") -> str:
        labels = {str(k): lbl for k, lbl in self.option_list(table)}
        return labels.get(str(value), str(value))


class RelationshipConstraint(Constraint):
    """Filter on a relationship: has any / has none / how many / which records."""

    kind = "relationship"
    icon = "link"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._title: str | None = None
        self._modify_query: Callable | None = None
        self._multiple: bool | None = None
        self._model: Any = None  # set by the QueryBuilder when the table binds

    def selectable(self, title_attribute: str, modify_query: Callable | None = None) -> "RelationshipConstraint":
        """Let users pick related records by ``title_attribute``."""
        self._title = title_attribute
        self._modify_query = modify_query
        return self

    def multiple(self, condition: bool = True) -> "RelationshipConstraint":
        """Treat as to-many (counts are offered). Detected from the relationship when not set."""
        self._multiple = condition
        return self

    def _rel(self, model: Any) -> Any:
        return sa_inspect(model).relationships[self.name]

    def is_multiple(self) -> bool:
        """To-many? ``multiple()`` wins; otherwise read ``uselist`` from the relationship."""
        if self._multiple is not None:
            return self._multiple
        if self._model is None:
            return True
        try:
            return bool(self._rel(self._model).uselist)
        except KeyError:
            return True

    def get_operators(self) -> dict[str, tuple[str, str | None]]:
        ops: dict[str, tuple[str, str | None]] = {}
        if self._title:
            ops["in"] = ("Is any of", "multi")
            ops["not_in"] = ("Is none of", "multi")
        ops["has"] = ("Has any", None)
        ops["has_none"] = ("Has none", None)
        if self.is_multiple():
            ops["count_gte"] = ("Has at least", "count")
            ops["count_lte"] = ("Has at most", "count")
            ops["count_eq"] = ("Has exactly", "count")
        return ops

    def option_list(self, table: "Table") -> list[tuple[Any, str]]:
        if not self._title or table.ctx is None:
            return []
        target = self._rel(table.model).mapper.class_
        pk = sa_inspect(target).primary_key[0]
        title = getattr(target, self._title)
        query = select(target).order_by(title).limit(500)
        if self._modify_query is not None:
            query = call(self._modify_query, query=query)
        return [(getattr(r, pk.key), str(getattr(r, self._title))) for r in table.ctx.db.scalars(query)]

    def parse_value(self, raw: Any) -> Any:
        raw = str(raw).strip()
        if raw == "":
            raise ValueError("empty")
        return raw

    def condition(self, table: "Table", rule: dict) -> Any:
        model = table.model
        rel = self._rel(model)
        attr = getattr(model, self.name)
        op = rule["op"]
        if op in ("in", "not_in"):
            target = rel.mapper.class_
            pk = sa_inspect(target).primary_key[0]
            keys = {str(k): k for k, _ in self.option_list(table)}
            values = [keys[str(v)] for v in rule["vs"] if str(v) in keys]
            if not values:
                return false() if op == "in" else None
            cond = pk.in_(values)
            matched = attr.any(cond) if rel.uselist else attr.has(cond)
            return matched if op == "in" else not_(matched)
        if op in ("has", "has_none"):
            matched = attr.any() if rel.uselist else attr.has()
            return matched if op == "has" else not_(matched)
        source = rel.secondary if rel.secondary is not None else rel.mapper.local_table
        count = select(func.count()).select_from(source).where(rel.primaryjoin).correlate(model).scalar_subquery()
        v = rule["v"]
        return {"count_gte": count >= v, "count_lte": count <= v, "count_eq": count == v}[op]

    def describe_value(self, value: Any, table: "Table") -> str:
        labels = {str(k): lbl for k, lbl in self.option_list(table)}
        return labels.get(str(value), str(value))


# ---------------------------------------------------------------------- picking a constraint from the model
TITLE_ATTRIBUTES = ("name", "title", "label", "email", "code")


def constraint_for(model: Any, path: str) -> Constraint | None:
    """Guess the constraint for ``path`` from the model's column type, or None when it can't be filtered.

    ``String``/``Text`` → text, ``Integer`` → whole number, ``Numeric``/``Float`` → number,
    ``Date``/``DateTime`` → date, ``Boolean`` → yes/no, ``Enum`` → select, a relationship → relationship.
    Dotted paths (``category.name``) follow relationships.
    """
    from sqlalchemy import Boolean, Enum, Float, Integer, Numeric, Text

    current = model
    parts = path.split(".")
    for i, part in enumerate(parts):
        try:
            mapper = sa_inspect(current)
        except Exception:  # noqa: BLE001 - not a mapped class
            return None
        rel = mapper.relationships.get(part)
        last = i == len(parts) - 1
        if rel is not None:
            if last:
                if i:  # a relationship of a relationship: not supported
                    return None
                target = sa_inspect(rel.mapper.class_)
                constraint = RelationshipConstraint(part)
                title = next((t for t in TITLE_ATTRIBUTES if t in target.columns), None)
                return constraint.selectable(title) if title else constraint
            current = rel.mapper.class_
            continue
        if not last:
            return None
        column = mapper.columns.get(part)
        if column is None:
            return None
        kind = column.type
        if isinstance(kind, Enum):
            options = kind.enum_class if kind.enum_class is not None else list(kind.enums)
            return SelectConstraint(path).options(options)
        if isinstance(kind, Boolean):
            return BooleanConstraint(path)
        if isinstance(kind, (Date, DateTime)):
            return DateConstraint(path)
        if isinstance(kind, Integer):
            return NumberConstraint(path).integer()
        if isinstance(kind, (Numeric, Float)):
            return NumberConstraint(path)
        if isinstance(kind, (String, Text)):
            return TextConstraint(path)
        return None
    return None  # pragma: no cover - the loop always returns


# ---------------------------------------------------------------------- the field + filter
class QueryBuilderField(Field):
    """Holds the rule groups in form state and renders the builder UI."""

    template = "tungsten/tables/query-builder.html"

    def __init__(self, name: str, builder: "QueryBuilder") -> None:
        super().__init__(name)
        self.builder = builder

    def blank_state(self) -> Any:
        return []

    def fill_state(self, form: "Form", base: str, record: Any) -> None:
        set_path(form.state, self.path(base), [])

    def load_state(self, form: "Form", formdata: Any, base: str) -> None:
        """Read ``filters.<name>.g.<group>.<rule>.<key>`` params into ``[[rule, ...], ...]``."""
        prefix = self.path(base).rsplit(".", 1)[0] + ".g."
        groups: dict[int, dict[int, dict]] = {}
        for key in formdata.keys():
            if not key.startswith(prefix):
                continue
            parts = key[len(prefix):].split(".")
            try:
                g = int(parts[0])
            except ValueError:
                continue
            if g >= MAX_GROUPS:
                continue
            rules = groups.setdefault(g, {})
            if len(parts) != 3:
                continue
            try:
                r = int(parts[1])
            except ValueError:
                continue
            if r >= MAX_RULES:
                continue
            rule = rules.setdefault(r, {})
            if parts[2] == "vs":
                rule["vs"] = [str(v) for v in formdata.getlist(key)]
            elif parts[2] in ("c", "op", "v", "v2"):
                rule[parts[2]] = str(formdata.get(key) or "")
        state = []
        for g in sorted(groups):
            state.append([groups[g][r] for r in sorted(groups[g]) if groups[g][r].get("c") in self.builder.by_name()])
        set_path(form.state, self.path(base), state)

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        constraints = self.builder.by_name()
        out = []
        for group in get_path(form.state, self.path(base)) or []:
            rules = []
            for rule in group:
                c = constraints.get(rule.get("c"))
                parsed = c.parse(rule) if c is not None else None
                if parsed is not None:
                    rules.append(parsed)
            if rules:
                out.append(rules)
        data[self.name] = out

    def handle(self, form: "Form", base: str, action: str) -> None:
        """Apply a builder button: ``add:<group|new>:<constraint>``, ``remove:<group>:<rule>``, ``group``."""
        path = self.path(base)
        groups = [list(g) for g in (get_path(form.state, path) or [])]
        verb, _, rest = action.partition(":")
        if verb == "add":
            where, _, cname = rest.partition(":")
            constraint = self.builder.by_name().get(cname)
            if constraint is None:
                return
            rule = {"c": cname, "op": next(iter(constraint.get_operators()), ""), "v": "", "v2": "", "vs": []}
            if where == "new" or not groups:
                if len(groups) < MAX_GROUPS:
                    groups.append([rule])
            elif where.isdigit() and int(where) < len(groups) and len(groups[int(where)]) < MAX_RULES:
                groups[int(where)].append(rule)
        elif verb == "remove":
            g, _, r = rest.partition(":")
            if g.isdigit() and r.isdigit() and int(g) < len(groups) and int(r) < len(groups[int(g)]):
                groups[int(g)].pop(int(r))
                if not groups[int(g)]:
                    groups.pop(int(g))
        set_path(form.state, path, groups)

    def url_items(self, form: "Form", base: str) -> list[tuple[str, str]]:
        prefix = self.path(base).rsplit(".", 1)[0] + ".g"
        items: list[tuple[str, str]] = []
        for g, group in enumerate(get_path(form.state, self.path(base)) or []):
            for r, rule in enumerate(group):
                key = f"{prefix}.{g}.{r}"
                for part in ("c", "op", "v", "v2"):
                    if rule.get(part) not in (None, ""):
                        items.append((f"{key}.{part}", str(rule[part])))
                for v in rule.get("vs") or []:
                    items.append((f"{key}.vs", str(v)))
        return items

    def render(self, form: "Form", base: str) -> Markup:
        table: Table = form.table  # type: ignore[attr-defined]
        constraints = self.builder.by_name()
        groups = []
        prefix = self.path(base).rsplit(".", 1)[0] + ".g"
        for g, group in enumerate(get_path(form.state, self.path(base)) or []):
            rules = []
            for r, rule in enumerate(group):
                c = constraints[rule["c"]]
                op = rule.get("op") or ""
                rules.append({
                    "constraint": c,
                    "prefix": f"{prefix}.{g}.{r}",
                    "op": op,
                    "needs": c.input_for(op),
                    "v": rule.get("v", ""),
                    "v2": rule.get("v2", ""),
                    "vs": [str(v) for v in rule.get("vs") or []],
                    "operators": c.get_operators(),
                    "options": [(str(k), lbl) for k, lbl in c.option_list(table)]
                    if c.input_for(op) in ("select", "multi") else [],
                    "complete": c.parse(rule) is not None,
                    "remove": f"remove:{self.builder.name}:{g}:{r}",
                })
            groups.append({"index": g, "rules": rules})
        return form.renderer.render(self.template, table=table, builder=self.builder, groups=groups,
                                    constraints=list(constraints.values()), ctx=table.ctx, host=table.host)


class QueryBuilder(Filter):
    """A filter where users build conditions from the constraints you allow."""

    def __init__(self, name: str = "query") -> None:
        super().__init__(name)
        self._constraints: list[Constraint] = []
        self._auto: tuple[bool, set[str]] | None = None
        self._auto_constraints: list[Constraint] = []
        self._label = "Custom filters"  # translated by get_label

    def constraints(self, constraints: list[Constraint]) -> "QueryBuilder":
        self._constraints = list(constraints)
        return self

    def auto_constraints(self, condition: bool = True, exclude: list[str] | None = None) -> "QueryBuilder":
        """Add a constraint for every table column, guessed from its database type.

        Constraints you list with ``constraints()`` win over the guessed ones. Columns that
        are not real model attributes (computed values, JSON) are skipped.
        """
        self._auto = (condition, set(exclude or ())) if condition else None
        return self

    def all_constraints(self) -> list[Constraint]:
        return self._constraints + self._auto_constraints

    def by_name(self) -> dict[str, Constraint]:
        return {c.name: c for c in self.all_constraints()}

    def bind_options(self, table: "Table") -> None:
        """Called when the table binds: tell relationship constraints the model, guess auto constraints."""
        if self._auto is not None:
            _, exclude = self._auto
            taken = {c.name for c in self._constraints} | exclude
            guessed = []
            for column in table._columns:
                name = getattr(column, "name", None)
                if not name or name in taken:
                    continue
                c = constraint_for(table.model, name)
                if c is None:
                    continue
                label = getattr(column, "_label", None)
                if isinstance(label, str) and label:
                    c.label(label)
                taken.add(name)
                guessed.append(c)
            self._auto_constraints = guessed
        for c in self.all_constraints():
            if isinstance(c, RelationshipConstraint):
                c._model = table.model

    def _build_fields(self) -> list:
        return [QueryBuilderField("rules", self)]

    @property
    def field(self) -> QueryBuilderField:
        return self.get_fields()[0]

    def default_data(self) -> dict[str, Any]:
        """``default([[rule, ...], ...])``: groups of rules like ``{"c": "price", "op": "gt", "v": 100}``.

        A flat list of rules is one group.
        """
        default = self.get_default()
        if not default:
            return {}
        groups = [default] if all(isinstance(r, dict) for r in default) else default
        constraints = self.by_name()
        state = []
        for group in groups[:MAX_GROUPS]:
            rules = []
            for rule in list(group)[:MAX_RULES]:
                if rule.get("c") not in constraints:
                    continue
                rules.append({
                    "c": rule["c"], "op": str(rule.get("op") or ""),
                    "v": "" if rule.get("v") is None else str(rule["v"]),
                    "v2": "" if rule.get("v2") is None else str(rule["v2"]),
                    "vs": [str(v) for v in rule.get("vs") or []],
                })
            if rules:
                state.append(rules)
        return {"rules": state} if state else {}

    def is_active(self, data: dict[str, Any]) -> bool:
        return bool(data.get("rules"))

    def apply(self, query: Any, data: dict[str, Any], table: "Table") -> Any:
        if self._query is not None:
            return super().apply(query, data, table)
        constraints = self.by_name()
        ors = []
        for group in data.get("rules") or []:
            ands = []
            for rule in group:
                try:
                    cond = constraints[rule["c"]].condition(table, rule)
                except (KeyError, ValueError, AttributeError, OverflowError):
                    cond = None
                if cond is not None:
                    ands.append(cond)
            if ands:
                ors.append(and_(*ands))
        return query.where(or_(*ors)) if ors else query

    def indicators(self, data: dict[str, Any], table: "Table") -> list[str]:
        constraints = self.by_name()
        out = []
        groups = data.get("rules") or []
        for i, group in enumerate(groups):
            text = f" {__('and')} ".join(constraints[r["c"]].describe(r, table) for r in group)
            out.append((__("or") + " " if i else "") + text)
        return out


__all__ = ["BooleanConstraint", "Constraint", "DateConstraint", "NumberConstraint", "QueryBuilder",
           "RelationshipConstraint", "SelectConstraint", "TextConstraint", "constraint_for", "date_range"]
