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
            return __(":text :from and :to", text=text, **{"from": self.describe_value(rule["v"], table),
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
        if op == "between":
            low, high = sorted([v, rule["v2"]])
            return column.between(low, high)
        if op == "filled":
            return column.is_not(None)
        return column.is_(None)


class DateConstraint(Constraint):
    kind = "date"
    icon = "calendar"
    operators = {
        "on": ("Is on", "date"),
        "before": ("Is before", "date"),
        "after": ("Is after", "date"),
        "between": ("Is between", "between"),
        "last_days": ("Is in the last (days)", "count"),
        "filled": ("Is filled", None),
        "blank": ("Is blank", None),
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
        if op == "before":
            return column < start(rule["v"])
        if op == "after":
            return column >= next_day(rule["v"])
        if op == "between":
            low, high = sorted([rule["v"], rule["v2"]])
            return and_(column >= start(low), column < next_day(high))
        if op == "last_days":
            return column >= start(dt.date.today() - dt.timedelta(days=rule["v"]))
        if op == "filled":
            return column.is_not(None)
        return column.is_(None)

    def describe_value(self, value: Any, table: "Table") -> str:
        return value.strftime("%d %b %Y") if isinstance(value, dt.date) else str(value)

    def describe(self, rule: dict, table: "Table") -> str:
        if rule["op"] == "last_days":
            return __(":label is in the last :days days", label=self.get_label(), days=rule["v"])
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

    def get_operators(self) -> dict[str, tuple[str, str | None]]:
        ops: dict[str, tuple[str, str | None]] = {}
        if self._title:
            ops["in"] = ("Is any of", "multi")
            ops["not_in"] = ("Is none of", "multi")
        ops["has"] = ("Has any", None)
        ops["has_none"] = ("Has none", None)
        if self._multiple is not False:
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
        self._label = "Custom filters"  # translated by get_label

    def constraints(self, constraints: list[Constraint]) -> "QueryBuilder":
        self._constraints = list(constraints)
        return self

    def by_name(self) -> dict[str, Constraint]:
        return {c.name: c for c in self._constraints}

    def _build_fields(self) -> list:
        return [QueryBuilderField("rules", self)]

    @property
    def field(self) -> QueryBuilderField:
        return self.get_fields()[0]

    def default_data(self) -> dict[str, Any]:
        return {}

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
                except (KeyError, ValueError, AttributeError):
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
           "RelationshipConstraint", "SelectConstraint", "TextConstraint"]
