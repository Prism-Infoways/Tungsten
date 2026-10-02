"""Table filters. Each filter owns a few form fields and a query callback."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ..forms.fields import Checkbox, CheckboxList, DatePicker, Select, normalize_options
from ..i18n import translate as __
from ..support.component import Component, headline
from ..support.evaluate import call, evaluate

if TYPE_CHECKING:  # pragma: no cover
    from .table import Table


class Filter(Component):
    """A custom filter. By default it is a single checkbox::

        Filter("featured").query(lambda query, model: query.where(model.is_featured))

    or give it a form::

        Filter("price").form([TextInput("min").numeric(), TextInput("max").numeric()])
            .query(lambda query, data, model: ...)
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self._label: Any = None
        self._fields: list | None = None
        self._query: Callable | None = None
        self._indicator: Callable | None = None
        self._default: Any = None
        self._inline = False
        self._columns = 1

    def label(self, label: Any) -> "Filter":
        self._label = label
        return self

    def form(self, fields: list) -> "Filter":
        self._fields = fields
        return self

    def query(self, fn: Callable) -> "Filter":
        """``fn(query, data, model)`` returns the filtered query."""
        self._query = fn
        return self

    def indicate_using(self, fn: Callable) -> "Filter":
        """``fn(data)`` returns a label (or list of labels) for the active filter chips."""
        self._indicator = fn
        return self

    def default(self, value: Any = True) -> "Filter":
        self._default = value
        return self

    def inline(self, condition: bool = True) -> "Filter":
        """Show the filter in the toolbar instead of the filter panel."""
        self._inline = condition
        return self

    def columns(self, n: int) -> "Filter":
        self._columns = n
        return self

    def get_label(self) -> str:
        return __(str(self._label) if self._label is not None else headline(self.name))

    def get_fields(self) -> list:
        """The filter's form fields (built once, then reused)."""
        if not hasattr(self, "_field_cache"):
            self._field_cache = self._build_fields()
        return self._field_cache

    def _build_fields(self) -> list:
        if self._fields is not None:
            return self._fields
        return [Checkbox("isActive").label(self.get_label())]

    def base(self) -> str:
        return f"filters.{self.name}"

    def default_data(self) -> dict[str, Any]:
        if self._default is None:
            return {}
        if self._fields is None:
            return {"isActive": bool(self._default)}
        return dict(self._default) if isinstance(self._default, dict) else {}

    def is_active(self, data: dict[str, Any]) -> bool:
        return any(v not in (None, "", [], False) for v in data.values())

    def apply(self, query: Any, data: dict[str, Any], table: "Table") -> Any:
        if not self.is_active(data):
            return query
        if self._fields is None and self._query is not None:
            return call(self._query, **{**table.ev(), "query": query, "data": data, "model": table.model})
        if self._query is not None:
            return call(self._query, **{**table.ev(), "query": query, "data": data, "model": table.model})
        return query

    def indicators(self, data: dict[str, Any], table: "Table") -> list[str]:
        if not self.is_active(data):
            return []
        if self._indicator:
            result = call(self._indicator, **{**table.ev(), "data": data})
            return [result] if isinstance(result, str) else list(result or [])
        if self._fields is None:
            return [self.get_label()]
        parts = [f"{__(headline(k))}: {v}" for k, v in data.items() if v not in (None, "", [], False)]
        return [f"{self.get_label()} — " + ", ".join(parts)]


class SelectFilter(Filter):
    """``SelectFilter("status").options({...})`` or ``.relationship("category", "name")``."""

    def __init__(self, name: str, attribute: str | None = None) -> None:
        super().__init__(name)
        self._attribute = attribute or name
        self._options: Any = None
        self._multiple = False
        self._relationship: dict | None = None
        self._searchable = False
        self._inline = True
        self._placeholder: str | None = None

    def attribute(self, attribute: str) -> "SelectFilter":
        self._attribute = attribute
        return self

    def options(self, options: Any) -> "SelectFilter":
        self._options = options
        return self

    def multiple(self, condition: bool = True) -> "SelectFilter":
        self._multiple = condition
        if condition:
            self._inline = False
        return self

    def searchable(self, condition: bool = True) -> "SelectFilter":
        self._searchable = condition
        return self

    def placeholder(self, text: str) -> "SelectFilter":
        self._placeholder = text
        return self

    def relationship(self, name: str, title_attribute: str, modify_query: Callable | None = None) -> "SelectFilter":
        self._relationship = {"name": name, "title": title_attribute, "modify_query": modify_query}
        return self

    def get_options(self, table: "Table") -> list[tuple[Any, str]]:
        if self._options is not None:
            return normalize_options(evaluate(self._options, **table.ev()))
        if self._relationship and table.ctx is not None:
            from sqlalchemy import inspect as sa_inspect
            from sqlalchemy import select

            rel = sa_inspect(table.model).relationships[self._relationship["name"]]
            target = rel.mapper.class_
            pk = sa_inspect(target).primary_key[0]
            title = getattr(target, self._relationship["title"])
            query = select(target).order_by(title)
            if self._relationship.get("modify_query"):
                query = call(self._relationship["modify_query"], query=query)
            rows = table.ctx.db.scalars(query).all()
            return [(getattr(r, pk.key), str(getattr(r, self._relationship["title"]))) for r in rows]
        return []

    def _build_fields(self) -> list:
        if self._fields is not None:
            return self._fields
        if self._multiple:
            return [CheckboxList("values").label(self.get_label())]
        return [Select("value").label(self.get_label())]

    def bind_options(self, table: "Table") -> None:
        """Push the evaluated options into the generated field."""
        if self._fields is not None:
            return
        opts = self.get_options(table)
        for f in self.get_fields():
            f.options(opts)
            if isinstance(f, Select):
                f.placeholder(self._placeholder or self.get_label())
                if self._searchable:
                    f.searchable()
        self._bound_options = opts

    def default_data(self) -> dict[str, Any]:
        if self._default is None:
            return {}
        if self._multiple:
            values = self._default if isinstance(self._default, (list, tuple)) else [self._default]
            return {"values": [str(v) for v in values]}
        return {"value": str(self._default)}

    def apply(self, query: Any, data: dict[str, Any], table: "Table") -> Any:
        if self._query is not None:
            return super().apply(query, data, table)
        values = data.get("values") if self._multiple else ([data.get("value")] if data.get("value") not in (None, "") else [])
        values = [v for v in (values or []) if v not in (None, "")]
        if not values:
            return query
        keys = self._typed(values, table)
        if self._relationship:
            from sqlalchemy import inspect as sa_inspect

            rel_attr = getattr(table.model, self._relationship["name"])
            rel = sa_inspect(table.model).relationships[self._relationship["name"]]
            pk = sa_inspect(rel.mapper.class_).primary_key[0]
            cond = pk.in_(keys)
            return query.where(rel_attr.any(cond) if rel.uselist else rel_attr.has(cond))
        column = table.column_expression(self._attribute)
        return query.where(column.in_(keys))

    def _typed(self, values: list, table: "Table") -> list:
        import enum

        options = getattr(self, "_bound_options", None) or self.get_options(table)
        lookup = {str(k): k for k, _ in options}
        enum_cls = self._options if isinstance(self._options, type) and issubclass(self._options, enum.Enum) else None
        out = []
        for v in values:
            key = lookup.get(str(v), v)
            out.append(enum_cls(key) if enum_cls is not None else key)
        return out

    def indicators(self, data: dict[str, Any], table: "Table") -> list[str]:
        if self._indicator or self._fields is not None:
            return super().indicators(data, table)
        values = data.get("values") if self._multiple else [data.get("value")]
        values = [v for v in (values or []) if v not in (None, "")]
        if not values:
            return []
        labels = dict((str(k), lbl) for k, lbl in (getattr(self, "_bound_options", None) or self.get_options(table)))
        return [f"{self.get_label()}: " + ", ".join(labels.get(str(v), str(v)) for v in values)]


class TernaryFilter(Filter):
    """Three states: all / yes / no. With ``.nullable()`` checks NULL instead of a boolean."""

    def __init__(self, name: str, attribute: str | None = None) -> None:
        super().__init__(name)
        self._attribute = attribute or name
        self._true_label = "Yes"
        self._false_label = "No"
        self._placeholder: str | None = None
        self._nullable = False
        self._true_query: Callable | None = None
        self._false_query: Callable | None = None
        self._inline = True

    def true_label(self, label: str) -> "TernaryFilter":
        self._true_label = label
        return self

    def false_label(self, label: str) -> "TernaryFilter":
        self._false_label = label
        return self

    def placeholder(self, label: str) -> "TernaryFilter":
        self._placeholder = label
        return self

    def nullable(self, condition: bool = True) -> "TernaryFilter":
        self._nullable = condition
        return self

    def queries(self, true: Callable, false: Callable) -> "TernaryFilter":
        self._true_query, self._false_query = true, false
        return self

    def _build_fields(self) -> list:
        return [
            Select("value").label(self.get_label()).placeholder(self._placeholder or self.get_label())
            .options({"1": self._true_label, "0": self._false_label})
        ]

    def default_data(self) -> dict[str, Any]:
        if self._default is None:
            return {}
        return {"value": "1" if self._default else "0"}

    def apply(self, query: Any, data: dict[str, Any], table: "Table") -> Any:
        value = data.get("value")
        if value not in ("1", "0"):
            return query
        truthy = value == "1"
        if truthy and self._true_query:
            return call(self._true_query, query=query, model=table.model)
        if not truthy and self._false_query:
            return call(self._false_query, query=query, model=table.model)
        column = table.column_expression(self._attribute)
        if self._nullable:
            return query.where(column.is_not(None) if truthy else column.is_(None))
        return query.where(column.is_(True) if truthy else column.is_not(True))

    def indicators(self, data: dict[str, Any], table: "Table") -> list[str]:
        value = data.get("value")
        if value not in ("1", "0"):
            return []
        return [f"{self.get_label()}: {__(self._true_label if value == '1' else self._false_label)}"]


class TrashedFilter(TernaryFilter):
    """For soft-deleting resources: without trashed (default) / with / only trashed."""

    def __init__(self, name: str = "trashed") -> None:
        super().__init__(name)
        self._label = "Deleted records"
        self._inline = False

    def _build_fields(self) -> list:
        return [
            Select("value").label(self.get_label()).placeholder("Without deleted records")
            .options({"with": "With deleted records", "only": "Only deleted records"})
        ]

    def apply(self, query: Any, data: dict[str, Any], table: "Table") -> Any:
        return query  # handled by the table, which knows the soft-delete column

    def mode(self, data: dict[str, Any]) -> str:
        return data.get("value") or "without"

    def indicators(self, data: dict[str, Any], table: "Table") -> list[str]:
        mode = self.mode(data)
        return [] if mode == "without" else [__("With deleted records") if mode == "with" else __("Only deleted records")]


class DateFilter(Filter):
    """``DateFilter("created_at")`` — from / until date range."""

    def __init__(self, name: str, attribute: str | None = None) -> None:
        super().__init__(name)
        self._attribute = attribute or name

    def _build_fields(self) -> list:
        return [DatePicker("from").label(lambda: __(":label from", label=self.get_label())),
                DatePicker("until").label(lambda: __(":label until", label=self.get_label()))]

    def apply(self, query: Any, data: dict[str, Any], table: "Table") -> Any:
        import datetime as dt

        column = table.column_expression(self._attribute)
        if data.get("from"):
            query = query.where(column >= data["from"])
        if data.get("until"):
            until = data["until"]
            if isinstance(until, dt.date) and not isinstance(until, dt.datetime):
                until = dt.datetime.combine(until, dt.time.max)
            query = query.where(column <= until)
        return query

    def indicators(self, data: dict[str, Any], table: "Table") -> list[str]:
        out = []
        if data.get("from"):
            out.append(__(":label from :date", label=self.get_label(), date=data["from"]))
        if data.get("until"):
            out.append(__(":label until :date", label=self.get_label(), date=data["until"]))
        return out
