"""Advanced filters: one column, an operator and a value, right in the filter panel.

::

    table.filters([
        AdvancedFilter.text("name"),                    # contains / starts with / is blank ...
        AdvancedFilter.number("price"),                 # >, <, between ...
        AdvancedFilter.date("created_at"),              # today, this month, in the last 7 days ...
        AdvancedFilter.boolean("is_featured"),
        AdvancedFilter.select("status", OrderStatus),
        AdvancedFilter.relationship("tags", "name"),
        AdvancedFilter("stock"),                        # type guessed from the model column
    ])

Each filter uses the same constraints as the :class:`~tungsten.tables.QueryBuilder`, so the
operators, chips and saved URLs match. ``Table.advanced_filters()`` adds one per column.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from markupsafe import Markup

from ..forms.fields import Field
from ..i18n import translate as __
from ..support.state import get_path, set_path
from .filters import Filter
from .query_builder import (
    BooleanConstraint,
    Constraint,
    DateConstraint,
    NumberConstraint,
    RelationshipConstraint,
    SelectConstraint,
    TextConstraint,
    constraint_for,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..forms.form import Form
    from .table import Table

BLANK_RULE = {"op": "", "v": "", "v2": "", "vs": []}


class AdvancedFilterField(Field):
    """Operator select + value input(s). Reads ``filters.<name>.op|v|v2|vs``."""

    template = "tungsten/tables/advanced-filter.html"

    def __init__(self, name: str, owner: "AdvancedFilter") -> None:
        super().__init__(name)
        self.owner = owner

    def blank_state(self) -> Any:
        return dict(BLANK_RULE)

    def fill_state(self, form: "Form", base: str, record: Any) -> None:
        set_path(form.state, self.path(base), dict(BLANK_RULE))

    def load_state(self, form: "Form", formdata: Any, base: str) -> None:
        rule = {key: str(formdata.get(f"{base}.{key}") or "") for key in ("op", "v", "v2")}
        rule["vs"] = [str(v) for v in formdata.getlist(f"{base}.vs") if str(v).strip()]
        set_path(form.state, self.path(base), rule)

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        rule = self.owner.parse(get_path(form.state, self.path(base)) or {})
        if rule:
            data.update(rule)

    def render(self, form: "Form", base: str) -> Markup:
        table: Table = form.table  # type: ignore[attr-defined]
        f = self.owner
        c = f.get_constraint()
        state = get_path(form.state, self.path(base)) or BLANK_RULE
        op = state.get("op") or ""
        shown = op or f.default_operator()
        needs = c.input_for(shown) if shown else None
        r = {
            "constraint": c,
            "prefix": base,
            "op": op,
            "needs": needs,
            "v": state.get("v", ""),
            "v2": state.get("v2", ""),
            "vs": [str(v) for v in state.get("vs") or []],
            "options": [(str(k), lbl) for k, lbl in c.option_list(table)] if needs in ("select", "multi") else [],
        }
        return form.renderer.render(self.template, filter=f, r=r, operators=f.get_operators(),
                                    complete=bool(f.parse(state)), ctx=table.ctx)


class AdvancedFilter(Filter):
    """A filter on one column with an operator picker.

    Pass a constraint (``AdvancedFilter(NumberConstraint("stock").integer())``), or a column
    name to guess the type from the model (``AdvancedFilter("stock")``).
    """

    def __init__(self, constraint: Constraint | str, name: str | None = None) -> None:
        path = constraint if isinstance(constraint, str) else constraint.name
        super().__init__(name or path.replace(".", "__"))
        self._path = path
        self._constraint: Constraint | None = None if isinstance(constraint, str) else constraint
        self._only: list[str] | None = None
        self._default_op: str | None = None

    # ---- shortcuts
    @classmethod
    def text(cls, name: str, attribute: str | None = None) -> "AdvancedFilter":
        return cls(TextConstraint(name, attribute))

    @classmethod
    def number(cls, name: str, attribute: str | None = None, integer: bool = False) -> "AdvancedFilter":
        return cls(NumberConstraint(name, attribute).integer(integer))

    @classmethod
    def date(cls, name: str, attribute: str | None = None) -> "AdvancedFilter":
        return cls(DateConstraint(name, attribute))

    @classmethod
    def boolean(cls, name: str, attribute: str | None = None) -> "AdvancedFilter":
        return cls(BooleanConstraint(name, attribute))

    @classmethod
    def select(cls, name: str, options: Any, attribute: str | None = None) -> "AdvancedFilter":
        return cls(SelectConstraint(name, attribute).options(options))

    @classmethod
    def relationship(cls, name: str, title_attribute: str | None = None,
                     modify_query: Callable | None = None) -> "AdvancedFilter":
        c = RelationshipConstraint(name)
        return cls(c.selectable(title_attribute, modify_query) if title_attribute else c)

    # ---- options
    def operators(self, operators: list[str]) -> "AdvancedFilter":
        """Offer only these operators (keys like ``"contains"``, ``"between"``, ``"this_month"``)."""
        self._only = list(operators)
        return self

    def default_operator(self, op: str | None = None) -> Any:
        """Set the operator used when users only type a value. Called with no argument, returns it."""
        if op is not None:
            self._default_op = op
            return self
        ops = self.get_operators()
        if self._default_op in ops:
            return self._default_op
        return next((k for k, (_, needs) in ops.items() if needs is not None), "")

    def get_constraint(self) -> Constraint:
        if self._constraint is None:
            raise RuntimeError(f"AdvancedFilter({self._path!r}) is not bound to a table yet")
        return self._constraint

    def bind_options(self, table: "Table") -> None:
        if self._constraint is None:
            guessed = constraint_for(table.model, self._path)
            if guessed is None:
                raise ValueError(f"Can't guess a filter for {self._path!r}; pass a constraint, "
                                 f"like AdvancedFilter(TextConstraint({self._path!r}))")
            self._constraint = guessed
        if isinstance(self._constraint, RelationshipConstraint):
            self._constraint._model = table.model

    def get_operators(self) -> dict[str, tuple[str, str | None]]:
        ops = self.get_constraint().get_operators()
        if self._only is None:
            return ops
        return {k: ops[k] for k in self._only if k in ops}

    def get_label(self) -> str:
        if self._label is not None:
            return __(str(self._label))
        return self.get_constraint().get_label()

    # ---- state
    def _build_fields(self) -> list:
        return [AdvancedFilterField("rule", self)]

    def parse(self, state: dict) -> dict | None:
        """The typed rule for ``state`` (``{"op", "v", "v2", "vs"}``), or None when not set."""
        op = state.get("op") or ""
        if not op:
            has_value = any(str(state.get(k) or "").strip() for k in ("v", "v2")) or state.get("vs")
            if not has_value:
                return None
            op = self.default_operator()
        if op not in self.get_operators():
            return None
        return self.get_constraint().parse({**state, "op": op})

    def default_data(self) -> dict[str, Any]:
        """``default("today")`` (an operator) or ``default({"op": "gt", "v": 100})``."""
        default = self.get_default()
        if not default:
            return {}
        if isinstance(default, str):
            default = {"op": default}
        rule = dict(BLANK_RULE)
        for key in ("op", "v", "v2"):
            value = default.get(key)
            if hasattr(value, "isoformat"):
                value = value.isoformat()[:10]
            rule[key] = "" if value is None else str(value)
        rule["vs"] = [str(v) for v in default.get("vs") or []]
        return {"rule": rule}

    def is_active(self, data: dict[str, Any]) -> bool:
        return bool(data.get("op"))

    def apply(self, query: Any, data: dict[str, Any], table: "Table") -> Any:
        if not self.is_active(data):
            return query
        if self._query is not None:
            return super().apply(query, data, table)
        try:
            cond = self.get_constraint().condition(table, data)
        except (KeyError, ValueError, AttributeError, OverflowError):
            return query
        return query if cond is None else query.where(cond)

    def indicators(self, data: dict[str, Any], table: "Table") -> list[str]:
        if not self.is_active(data):
            return []
        if self._indicator is not None:
            return super().indicators(data, table)
        c = self.get_constraint()
        if self._label is not None:
            original, c._label = c._label, self._label
            try:
                return [c.describe(data, table)]
            finally:
                c._label = original
        return [c.describe(data, table)]


def advanced_filters_for(table: "Table", columns: list[str] | None = None,
                         exclude: list[str] | None = None) -> list[AdvancedFilter]:
    """An :class:`AdvancedFilter` for each table column whose type can be guessed."""
    skip = set(exclude or ())
    names = columns if columns is not None else [getattr(c, "name", None) for c in table._columns]
    labels = {c.name: c._label for c in table._columns if isinstance(getattr(c, "_label", None), str)}
    out = []
    for name in names:
        if not name or name in skip:
            continue
        c = constraint_for(table.model, name) if table.model is not None else None
        if c is None:
            continue
        f = AdvancedFilter(c)
        if labels.get(name):
            c.label(labels[name])
        out.append(f)
    return out


__all__ = ["AdvancedFilter", "AdvancedFilterField", "advanced_filters_for"]
