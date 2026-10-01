"""Shared grid helpers for form components."""

from __future__ import annotations

from typing import Any

# Written out in full so the Tailwind build keeps these classes.
GRID_COLUMNS = {
    1: "grid-cols-1",
    2: "grid-cols-1 md:grid-cols-2",
    3: "grid-cols-1 md:grid-cols-3",
    4: "grid-cols-1 md:grid-cols-2 lg:grid-cols-4",
    5: "grid-cols-1 md:grid-cols-5",
    6: "grid-cols-1 md:grid-cols-3 lg:grid-cols-6",
    12: "grid-cols-1 md:grid-cols-12",
}
COLUMN_SPAN = {
    1: "md:col-span-1",
    2: "md:col-span-2",
    3: "md:col-span-3",
    4: "md:col-span-4",
    5: "md:col-span-5",
    6: "md:col-span-6",
    7: "md:col-span-7",
    8: "md:col-span-8",
    9: "md:col-span-9",
    10: "md:col-span-10",
    11: "md:col-span-11",
    12: "md:col-span-12",
    "full": "col-span-full",
}


def grid_class(columns: Any) -> str:
    return GRID_COLUMNS.get(columns, GRID_COLUMNS[2]) if isinstance(columns, int) else GRID_COLUMNS[2]


def span_class(span: Any) -> str:
    if span is None:
        return ""
    return COLUMN_SPAN.get(span, "")


class SchemaComponentMixin:
    """Default no-op lifecycle hooks shared by fields and layouts."""

    _column_span: Any = None

    def column_span(self, span: int | str):
        self._column_span = span
        return self

    def column_span_full(self):
        return self.column_span("full")

    def span_class(self) -> str:
        return span_class(self._column_span)
