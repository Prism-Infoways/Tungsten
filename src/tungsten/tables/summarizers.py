"""Column summaries shown in the table footer: ``.summarize(Sum().money("INR"))``."""

from __future__ import annotations

from typing import Any, Callable

from ..i18n import translate as __
from ..support.component import Component
from ..support.evaluate import call


class Summarizer(Component):
    function = "sum"
    default_label = "Sum"

    def __init__(self, label: str | None = None) -> None:
        super().__init__()
        self._label = label
        self._format: Callable | None = None

    def label(self, label: str) -> "Summarizer":
        self._label = label
        return self

    def format_state_using(self, fn: Callable) -> "Summarizer":
        self._format = fn
        return self

    def money(self, currency: str = "$", decimals: int = 2) -> "Summarizer":
        from .columns import TextColumn

        self._format = TextColumn("x").money(currency, decimals)._format
        return self

    def numeric(self, decimals: int = 0) -> "Summarizer":
        from .columns import TextColumn

        self._format = TextColumn("x").numeric(decimals)._format
        return self

    def get_label(self) -> str:
        return __(self._label or self.default_label)

    def expression(self, column: Any) -> Any:
        from sqlalchemy import func

        return getattr(func, {"average": "avg"}.get(self.function, self.function))(column)

    def compute(self, values: list) -> Any:
        """The same summary in Python, for columns without a database column (``state()``)."""
        values = [v for v in values if v is not None]
        if self.function == "count":
            return len(values)
        if not values:
            return None
        if self.function == "sum":
            return sum(values)
        if self.function == "average":
            return sum(values) / len(values)
        return min(values) if self.function == "min" else max(values)

    def format(self, value: Any) -> Any:
        if self._format is not None:
            return call(self._format, state=value)
        if isinstance(value, float):
            return f"{value:,.2f}"
        if isinstance(value, int):
            return f"{value:,}"
        return value


class Sum(Summarizer):
    function = "sum"
    default_label = "Sum"


class Average(Summarizer):
    function = "average"
    default_label = "Average"


class Count(Summarizer):
    function = "count"
    default_label = "Count"


class Min(Summarizer):
    function = "min"
    default_label = "Min"


class Max(Summarizer):
    function = "max"
    default_label = "Max"
