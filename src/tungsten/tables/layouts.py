"""Layout columns: arrange a row's columns as a card instead of plain cells.

``Split`` puts columns side by side, ``Stack`` one under the other, ``Panel`` wraps them in
a box that can collapse, and ``Grid`` lays them out in a grid. They nest, and work in the
normal table and in ``content_grid()`` cards. The table header is hidden when a layout
is used, like Filament. Inner columns keep their search, toggle and visibility settings.
"""

from __future__ import annotations

import itertools
from typing import Any, Iterator

from markupsafe import Markup

from ..support.evaluate import evaluate
from .columns import Column

_ids = itertools.count(1)

FROM = {"sm": "sm:flex-row", "md": "md:flex-row", "lg": "lg:flex-row", "xl": "xl:flex-row", "2xl": "2xl:flex-row"}
ITEMS = {"start": "items-start", "center": "items-center", "end": "items-end"}
SPACE = {1: "gap-1", 2: "gap-2", 3: "gap-3", 4: "gap-4", 6: "gap-6", 8: "gap-8"}
GRID_COLS = {1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-3", 4: "grid-cols-4", 5: "grid-cols-5", 6: "grid-cols-6"}
GRID_FROM = {
    "sm": {1: "sm:grid-cols-1", 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "sm:grid-cols-4", 5: "sm:grid-cols-5", 6: "sm:grid-cols-6"},
    "md": {1: "md:grid-cols-1", 2: "md:grid-cols-2", 3: "md:grid-cols-3", 4: "md:grid-cols-4", 5: "md:grid-cols-5", 6: "md:grid-cols-6"},
    "lg": {1: "lg:grid-cols-1", 2: "lg:grid-cols-2", 3: "lg:grid-cols-3", 4: "lg:grid-cols-4", 5: "lg:grid-cols-5", 6: "lg:grid-cols-6"},
    "xl": {1: "xl:grid-cols-1", 2: "xl:grid-cols-2", 3: "xl:grid-cols-3", 4: "xl:grid-cols-4", 5: "xl:grid-cols-5", 6: "xl:grid-cols-6"},
}
VISIBLE_FROM = {"sm": "max-sm:hidden", "md": "max-md:hidden", "lg": "max-lg:hidden", "xl": "max-xl:hidden", "2xl": "max-2xl:hidden"}


class LayoutColumn(Column):
    """Base of the layout columns. Holds other columns and draws them together in one cell."""

    is_layout = True
    template = "tungsten/tables/layouts/stack.html"

    def __init__(self, schema: list | None = None) -> None:
        super().__init__(f"_layout_{next(_ids)}")
        self.schema_items: list[Column] = list(schema or [])
        self._label = ""
        self._visible_from: str | None = None

    def schema(self, columns: list) -> "LayoutColumn":
        self.schema_items = list(columns)
        return self

    def visible_from(self, breakpoint: str) -> "LayoutColumn":
        """Only show this part from a screen size up (sm, md, lg, xl, 2xl)."""
        self._visible_from = breakpoint
        return self

    def get_label(self) -> str:
        return ""

    def flatten(self) -> Iterator[Column]:
        """Every real (non-layout) column inside, at any depth."""
        for c in self.schema_items:
            if isinstance(c, LayoutColumn):
                yield from c.flatten()
            else:
                yield c

    def get_state(self, record: Any, ev: dict | None = None) -> Any:
        return None

    def render_children(self, table: Any, record: Any) -> list[dict]:
        hidden = table.hidden_columns()
        ev = table.ev()
        out = []
        for c in self.schema_items:
            if c.name in hidden or not c.is_visible(**{**ev, "record": record}):
                continue
            html = c.render_cell(table, record)
            if not html:
                continue
            url = None
            if not isinstance(c, LayoutColumn) and not c.editable and not c._url:
                url = table.get_record_url(record)
            out.append({"html": html, "grow": getattr(c, "_grow", True), "url": url,
                        "classes": VISIBLE_FROM.get(getattr(c, "_visible_from", None) or "", "")})
        return out

    def view_data(self, table: Any, record: Any) -> dict[str, Any]:
        return {"children": self.render_children(table, record), "classes": evaluate(self._extra_classes, **self.cell_ev(table, record)) or ""}

    def render_cell(self, table: Any, record: Any) -> Markup:
        return table.renderer.render(self.template, table=table, column=self, record=record, v=self.view_data(table, record))


class Split(LayoutColumn):
    """Columns side by side in a row, like a card: ``Split([ImageColumn("avatar").circular(), Stack([...])])``.

    A child takes the free space unless it is ``.grow(False)``. Below ``from_breakpoint`` (default ``md``)
    the children stack on small screens.
    """

    template = "tungsten/tables/layouts/split.html"

    def __init__(self, schema: list | None = None) -> None:
        super().__init__(schema)
        self._from = "md"
        self._align = "center"

    def from_breakpoint(self, breakpoint: str) -> "Split":
        self._from = breakpoint
        return self

    def vertical_alignment(self, value: str) -> "Split":
        """start, center or end"""
        self._align = value
        return self

    def view_data(self, table: Any, record: Any) -> dict[str, Any]:
        v = super().view_data(table, record)
        v.update(row=FROM.get(self._from, FROM["md"]), items=ITEMS.get(self._align, ITEMS["center"]))
        return v


class Stack(LayoutColumn):
    """Columns one under the other: ``Stack([TextColumn("name").weight("bold"), TextColumn("email")]).space(1)``."""

    template = "tungsten/tables/layouts/stack.html"

    def __init__(self, schema: list | None = None) -> None:
        super().__init__(schema)
        self._space = 1
        self._align = "start"

    def space(self, n: int) -> "Stack":
        """The gap between items: 1, 2, 3, 4, 6 or 8"""
        self._space = n
        return self

    def alignment(self, value: str) -> "Stack":  # type: ignore[override]
        """start, center or end"""
        self._align = value
        return self

    def view_data(self, table: Any, record: Any) -> dict[str, Any]:
        v = super().view_data(table, record)
        v.update(gap=SPACE.get(self._space, "gap-1"), items=ITEMS.get(self._align, ITEMS["start"]))
        return v


class Panel(LayoutColumn):
    """A box around columns, which can collapse: ``Panel([Stack([...])]).collapsible()``."""

    template = "tungsten/tables/layouts/panel.html"

    def __init__(self, schema: list | None = None) -> None:
        super().__init__(schema)
        self._collapsible = False
        self._collapsed = True

    def collapsible(self, condition: bool = True) -> "Panel":
        self._collapsible = condition
        return self

    def collapsed(self, condition: bool = True) -> "Panel":
        """Start closed (the default when collapsible)."""
        self._collapsed = condition
        return self

    def view_data(self, table: Any, record: Any) -> dict[str, Any]:
        v = super().view_data(table, record)
        v.update(collapsible=self._collapsible, collapsed=self._collapsed and self._collapsible)
        return v


class Grid(LayoutColumn):
    """Columns in a grid: ``Grid([...]).columns({"md": 2, "xl": 4})`` or ``Grid([...]).columns(3)``."""

    template = "tungsten/tables/layouts/grid.html"

    def __init__(self, schema: list | None = None) -> None:
        super().__init__(schema)
        self._columns: dict[str, int] = {"default": 1, "md": 2}
        self._space = 3

    def columns(self, columns: int | dict[str, int]) -> "Grid":
        self._columns = {"default": 1, "md": columns} if isinstance(columns, int) else dict(columns)
        return self

    def space(self, n: int) -> "Grid":
        self._space = n
        return self

    def grid_classes(self) -> str:
        out = [GRID_COLS.get(self._columns.get("default", 1), "grid-cols-1")]
        for size, n in self._columns.items():
            if size in GRID_FROM:
                out.append(GRID_FROM[size].get(n, ""))
        return " ".join(c for c in out if c)

    def view_data(self, table: Any, record: Any) -> dict[str, Any]:
        v = super().view_data(table, record)
        v.update(grid=self.grid_classes(), gap=SPACE.get(self._space, "gap-3"))
        return v
