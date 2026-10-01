"""Table columns: ``TextColumn("name").searchable().sortable()``."""

from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable

from markupsafe import Markup, escape

from ..support import colors
from ..support.component import Component, headline
from ..support.evaluate import call, evaluate
from ..support.html import sanitize
from ..support.icons import icon

if TYPE_CHECKING:  # pragma: no cover
    from .table import Table

ALIGN = {"start": "text-start", "center": "text-center", "end": "text-end"}
JUSTIFY = {"start": "justify-start", "center": "justify-center", "end": "justify-end"}


def read_path(record: Any, path: str) -> Any:
    """Read ``customer.name`` style paths; to-many relations give a list."""
    values = [record]
    many = False
    for part in path.split("."):
        nxt = []
        for v in values:
            if v is None:
                continue
            if isinstance(v, dict):
                got = v.get(part)
            else:
                got = getattr(v, part, None)
            if isinstance(got, (list, tuple, set)) and not isinstance(got, str):
                many = True
                nxt.extend(got)
            else:
                nxt.append(got)
        values = nxt
    if many:
        return [v for v in values if v is not None]
    return values[0] if values else None


class Column(Component):
    template = "tungsten/tables/columns/text.html"

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self._label: Any = None
        self._sortable: Any = False
        self._sort_query: Callable | None = None
        self._searchable: Any = False
        self._search_query: Callable | None = None
        self._search_columns: list[str] | None = None
        self._global_searchable = False
        self._toggleable = False
        self._hidden_by_default = False
        self._alignment = "start"
        self._format: Callable | None = None
        self._state: Callable | None = None
        self._url: Callable | None = None
        self._new_tab = False
        self._description: Any = None
        self._description_position = "below"
        self._default: Any = None
        self._placeholder: Any = None
        self._summarizers: list = []
        self._width: str | None = None
        self._wrap = False
        self._tooltip: Any = None
        self._extra_classes: Any = None

    # ------------------------------------------------------------------ config
    def label(self, label: Any) -> "Column":
        self._label = label
        return self

    def sortable(self, condition: bool = True, query: Callable | None = None) -> "Column":
        """``query(query, direction)`` may customise the ORDER BY."""
        self._sortable = condition
        self._sort_query = query
        return self

    def searchable(self, condition: bool = True, query: Callable | None = None,
                   columns: list[str] | None = None, is_global: bool = True) -> "Column":
        """Include in the table search. ``columns`` searches other attributes instead."""
        self._searchable = condition
        self._search_query = query
        self._search_columns = columns
        self._global_searchable = is_global
        return self

    def toggleable(self, condition: bool = True, hidden_by_default: bool = False) -> "Column":
        self._toggleable = condition
        self._hidden_by_default = hidden_by_default
        return self

    def alignment(self, value: str) -> "Column":
        self._alignment = value
        return self

    def align_center(self) -> "Column":
        return self.alignment("center")

    def align_end(self) -> "Column":
        return self.alignment("end")

    def format_state_using(self, fn: Callable) -> "Column":
        self._format = fn
        return self

    formatted = format_state_using

    def state(self, fn: Callable) -> "Column":
        """Compute the value instead of reading an attribute: ``state(lambda record: ...)``."""
        self._state = fn
        return self

    get_state_using = state

    def url(self, fn: Callable | str, open_in_new_tab: bool = False) -> "Column":
        self._url = fn
        self._new_tab = open_in_new_tab
        return self

    def description(self, text: Any, position: str = "below") -> "Column":
        self._description = text
        self._description_position = position
        return self

    def default(self, value: Any) -> "Column":
        self._default = value
        return self

    def placeholder(self, text: Any) -> "Column":
        self._placeholder = text
        return self

    def summarize(self, *summarizers: Any) -> "Column":
        for s in summarizers:
            if isinstance(s, (list, tuple)):
                self._summarizers.extend(s)
            else:
                self._summarizers.append(s)
        return self

    def width(self, value: str) -> "Column":
        self._width = value
        return self

    def wrap(self, condition: bool = True) -> "Column":
        self._wrap = condition
        return self

    def tooltip(self, value: Any) -> "Column":
        self._tooltip = value
        return self

    def extra_classes(self, value: Any) -> "Column":
        self._extra_classes = value
        return self

    # ------------------------------------------------------------------ data
    def get_label(self) -> str:
        return str(self._label) if self._label is not None else headline(self.name.replace(".", " "))

    def is_relation(self) -> bool:
        return "." in self.name

    def get_state(self, record: Any, ev: dict | None = None) -> Any:
        ev = {**(ev or {}), "record": record}
        if self._state is not None:
            value = call(self._state, **ev)
        else:
            value = read_path(record, self.name)
        if value is None or value == []:
            value = evaluate(self._default, **ev)
        return value

    def format_value(self, value: Any, record: Any, ev: dict) -> Any:
        if self._format is not None:
            return call(self._format, **{**ev, "state": value, "record": record})
        return default_format(value)

    def cell_ev(self, table: "Table", record: Any) -> dict:
        return {**table.ev(), "record": record, "column": self}

    def get_url(self, table: "Table", record: Any) -> str | None:
        if self._url is None:
            return None
        return evaluate(self._url, **self.cell_ev(table, record))

    def view_data(self, table: "Table", record: Any) -> dict[str, Any]:
        ev = self.cell_ev(table, record)
        state = self.get_state(record, ev)
        ev["state"] = state
        return {
            "state": state,
            "description": evaluate(self._description, **ev),
            "description_position": self._description_position,
            "tooltip": evaluate(self._tooltip, **ev),
            "align": ALIGN.get(self._alignment, ""),
            "justify": JUSTIFY.get(self._alignment, ""),
            "classes": evaluate(self._extra_classes, **ev) or "",
            "placeholder": evaluate(self._placeholder, **ev),
            "ev": ev,
        }

    def render_cell(self, table: "Table", record: Any) -> Markup:
        return table.renderer.render(self.template, table=table, column=self, record=record,
                                     v=self.view_data(table, record))


def default_format(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        label = getattr(value, "label", None)
        if callable(label):
            return label()
        return label or headline(str(value.name).lower())
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dt.datetime):
        return value.strftime("%d %b %Y, %H:%M")
    if isinstance(value, dt.date):
        return value.strftime("%d %b %Y")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value == value.to_integral() else str(value)
    return value


class TextColumn(Column):
    template = "tungsten/tables/columns/text.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._badge = False
        self._color: Any = None
        self._colors: dict | None = None
        self._icon: Any = None
        self._icons: dict | None = None
        self._icon_position = "before"
        self._limit: int | None = None
        self._words: int | None = None
        self._weight: str | None = None
        self._size: str = "sm"
        self._copyable = False
        self._html = False
        self._list = False
        self._separator: str | None = None
        self._prefix: Any = None
        self._suffix: Any = None
        self._font_mono = False
        self._limit_list: int | None = None
        self._avatar: Any = None
        self._avatar_circular = True

    def badge(self, condition: bool = True) -> "TextColumn":
        self._badge = condition
        return self

    def color(self, color: Any) -> "TextColumn":
        """A color name or closure: ``color(lambda state: "success" if state == "paid" else "gray")``."""
        self._color = color
        return self

    def colors(self, mapping: dict[str, Any]) -> "TextColumn":
        """Filament style: ``{"success": "active", "danger": ["banned", "inactive"]}``."""
        self._colors = mapping
        return self

    def icon(self, icon: Any, position: str = "before") -> "TextColumn":
        self._icon = icon
        self._icon_position = position
        return self

    def icons(self, mapping: dict[str, Any]) -> "TextColumn":
        self._icons = mapping
        return self

    def limit(self, n: int) -> "TextColumn":
        self._limit = n
        return self

    def avatar(self, source: Any = True, circular: bool = True) -> "TextColumn":
        """Show an image before the text: an attribute name, a closure, or ``True`` for initials only."""
        self._avatar = source
        self._avatar_circular = circular
        return self

    def words(self, n: int) -> "TextColumn":
        self._words = n
        return self

    def weight(self, weight: str) -> "TextColumn":
        self._weight = weight
        return self

    def bold(self) -> "TextColumn":
        return self.weight("semibold")

    def size(self, size: str) -> "TextColumn":
        self._size = size
        return self

    def font_mono(self, condition: bool = True) -> "TextColumn":
        self._font_mono = condition
        return self

    def copyable(self, condition: bool = True) -> "TextColumn":
        self._copyable = condition
        return self

    def html(self, condition: bool = True) -> "TextColumn":
        self._html = condition
        return self

    def list(self, condition: bool = True) -> "TextColumn":
        """Show to-many values as a bulleted list."""
        self._list = condition
        return self

    def separator(self, sep: str = ",") -> "TextColumn":
        self._separator = sep
        return self

    def limit_list(self, n: int) -> "TextColumn":
        self._limit_list = n
        return self

    def prefix(self, text: Any) -> "TextColumn":
        self._prefix = text
        return self

    def suffix(self, text: Any) -> "TextColumn":
        self._suffix = text
        return self

    # formatting helpers
    def money(self, currency: str = "$", decimals: int = 2, divide_by: int = 1) -> "TextColumn":
        def fmt(state: Any) -> Any:
            if state is None or state == "":
                return None
            try:
                amount = float(state) / divide_by
            except (TypeError, ValueError):
                return state
            symbol = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}.get(currency, currency)
            return f"{'-' if amount < 0 else ''}{symbol}{abs(amount):,.{decimals}f}"

        self._format = fmt
        if self._alignment == "start":
            self._alignment = "start"
        return self

    def numeric(self, decimals: int = 0, thousands: bool = True) -> "TextColumn":
        def fmt(state: Any) -> Any:
            if state is None or state == "":
                return None
            try:
                return f"{float(state):,.{decimals}f}" if thousands else f"{float(state):.{decimals}f}"
            except (TypeError, ValueError):
                return state

        self._format = fmt
        return self

    def date(self, fmt: str = "%d %b %Y") -> "TextColumn":
        self._format = lambda state: state.strftime(fmt) if hasattr(state, "strftime") else state
        return self

    def datetime(self, fmt: str = "%d %b %Y, %H:%M") -> "TextColumn":
        return self.date(fmt)

    def time(self, fmt: str = "%H:%M") -> "TextColumn":
        return self.date(fmt)

    def since(self) -> "TextColumn":
        self._format = lambda state: humanize_since(state)
        return self

    # resolving
    def resolve_color(self, state: Any, ev: dict) -> str | None:
        raw = state.value if isinstance(state, enum.Enum) else state
        if isinstance(state, enum.Enum) and hasattr(state, "color") and self._color is None and self._colors is None:
            c = state.color
            return c() if callable(c) else c
        if self._colors:
            for color, cond in self._colors.items():
                if callable(cond):
                    if call(cond, **{**ev, "state": state}):
                        return color
                elif isinstance(cond, (list, tuple, set)):
                    if raw in cond or str(raw) in [str(c) for c in cond]:
                        return color
                elif str(cond) == str(raw):
                    return color
            return "gray" if self._badge else None
        if self._color is not None:
            return evaluate(self._color, **ev)
        return "gray" if self._badge else None

    def resolve_icon(self, state: Any, ev: dict) -> str | None:
        if self._icons:
            raw = state.value if isinstance(state, enum.Enum) else state
            for name, cond in self._icons.items():
                if callable(cond):
                    if call(cond, **{**ev, "state": state}):
                        return name
                elif isinstance(cond, (list, tuple, set)):
                    if raw in cond:
                        return name
                elif str(cond) == str(raw):
                    return name
            return None
        return evaluate(self._icon, **ev)

    def view_data(self, table: "Table", record: Any) -> dict[str, Any]:
        v = super().view_data(table, record)
        ev = v["ev"]
        state = v["state"]
        items = state if isinstance(state, list) else ([] if state is None or state == "" else [state])
        if self._separator and isinstance(state, str):
            items = [s.strip() for s in state.split(self._separator) if s.strip()]
        more = 0
        if self._limit_list and len(items) > self._limit_list:
            more = len(items) - self._limit_list
            items = items[: self._limit_list]
        out = []
        for item in items:
            iev = {**ev, "state": item}
            text = self.format_value(item, record, iev)
            full = None if text is None else str(text)
            if text is not None and not self._html:
                text = str(text)
                if self._words and len(text.split()) > self._words:
                    text = " ".join(text.split()[: self._words]) + "…"
                if self._limit and len(text) > self._limit:
                    text = text[: self._limit].rstrip() + "…"
            elif text is not None and self._html:
                text = Markup(sanitize(str(text)))
            prefix = evaluate(self._prefix, **iev)
            suffix = evaluate(self._suffix, **iev)
            out.append({
                "text": text,
                "full": full if (self._limit or self._words) else None,
                "color": self.resolve_color(item, iev),
                "icon": self.resolve_icon(item, iev),
                "prefix": prefix,
                "suffix": suffix,
            })
        v.update(
            entries=out,
            more=more,
            badge=self._badge,
            icon_position=self._icon_position,
            weight={"bold": "font-bold", "semibold": "font-semibold", "medium": "font-medium"}.get(self._weight or "", ""),
            size={"xs": "text-xs", "sm": "text-sm", "base": "text-base", "lg": "text-lg"}.get(self._size, "text-sm"),
            mono=self._font_mono,
            copyable=self._copyable,
            as_list=self._list,
            url=self.get_url(table, record),
            new_tab=self._new_tab,
            avatar=self._resolve_avatar(table, record, ev) if self._avatar is not None else None,
            avatar_circular=self._avatar_circular,
        )
        return v

    def _resolve_avatar(self, table: "Table", record: Any, ev: dict) -> dict:
        source = self._avatar
        url = None
        if isinstance(source, str):
            url = read_path(record, source)
        elif callable(source):
            url = call(source, **ev)
        if url and not str(url).startswith(("http://", "https://", "/", "data:")) and table.ctx is not None:
            url = table.ctx.panel.storage.url(str(url))
        text = str(read_path(record, self.name) or "")
        return {"url": url, "name": text}


class BadgeColumn(TextColumn):
    """Shortcut for ``TextColumn(name).badge()``."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._badge = True


class IconColumn(Column):
    template = "tungsten/tables/columns/icon.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._boolean = False
        self._icon: Any = None
        self._icons: dict | None = None
        self._color: Any = None
        self._colors: dict | None = None
        self._size = "h-5 w-5"
        self._true_icon = "circle-check"
        self._false_icon = "circle-x"
        self._true_color = "success"
        self._false_color = "danger"
        self._alignment = "center"

    def boolean(self, condition: bool = True) -> "IconColumn":
        self._boolean = condition
        return self

    def icon(self, icon: Any) -> "IconColumn":
        self._icon = icon
        return self

    def icons(self, mapping: dict) -> "IconColumn":
        self._icons = mapping
        return self

    def color(self, color: Any) -> "IconColumn":
        self._color = color
        return self

    def colors(self, mapping: dict) -> "IconColumn":
        self._colors = mapping
        return self

    def true_icon(self, icon: str, color: str = "success") -> "IconColumn":
        self._true_icon, self._true_color = icon, color
        return self

    def false_icon(self, icon: str, color: str = "danger") -> "IconColumn":
        self._false_icon, self._false_color = icon, color
        return self

    def size(self, size: str) -> "IconColumn":
        self._size = {"sm": "h-4 w-4", "md": "h-5 w-5", "lg": "h-6 w-6"}.get(size, size)
        return self

    def view_data(self, table: "Table", record: Any) -> dict[str, Any]:
        v = super().view_data(table, record)
        ev, state = v["ev"], v["state"]
        if self._boolean:
            if state is None:
                name, color = None, None
            else:
                name = self._true_icon if state else self._false_icon
                color = self._true_color if state else self._false_color
        else:
            helper = TextColumn(self.name)
            helper._icons, helper._colors, helper._color, helper._icon = self._icons, self._colors, self._color, self._icon
            name = helper.resolve_icon(state, ev)
            color = helper.resolve_color(state, ev)
        v.update(icon=name, color=color or "gray", size=self._size)
        return v


class ImageColumn(Column):
    template = "tungsten/tables/columns/image.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._circular = False
        self._square = False
        self._size = 40
        self._stacked = False
        self._limit: int | None = None
        self._default_url: Any = None

    def circular(self, condition: bool = True) -> "ImageColumn":
        self._circular = condition
        return self

    def square(self, condition: bool = True) -> "ImageColumn":
        self._square = condition
        return self

    def size(self, px: int) -> "ImageColumn":
        self._size = px
        return self

    def stacked(self, condition: bool = True) -> "ImageColumn":
        self._stacked = condition
        return self

    def limit(self, n: int) -> "ImageColumn":
        self._limit = n
        return self

    def default_image_url(self, url: Any) -> "ImageColumn":
        self._default_url = url
        return self

    def view_data(self, table: "Table", record: Any) -> dict[str, Any]:
        v = super().view_data(table, record)
        state = v["state"]
        paths = state if isinstance(state, list) else ([state] if state else [])
        if self._limit:
            paths = paths[: self._limit]
        storage = table.ctx.panel.storage if table.ctx else None

        def to_url(p: str) -> str:
            if p.startswith(("http://", "https://", "/", "data:")):
                return p
            return storage.url(p) if storage else p

        urls = [to_url(str(p)) for p in paths]
        if not urls and self._default_url:
            urls = [evaluate(self._default_url, **v["ev"])]
        v.update(urls=urls, circular=self._circular, size=self._size, stacked=self._stacked)
        return v


class ToggleColumn(Column):
    """An on/off switch that saves straight away."""

    template = "tungsten/tables/columns/toggle.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._disabled: Any = False
        self._before_save: Callable | None = None
        self._after_save: Callable | None = None
        self._alignment = "start"

    def disabled(self, condition: Any = True) -> "ToggleColumn":
        self._disabled = condition
        return self

    def before_state_updated(self, fn: Callable) -> "ToggleColumn":
        self._before_save = fn
        return self

    def after_state_updated(self, fn: Callable) -> "ToggleColumn":
        self._after_save = fn
        return self

    def update(self, table: "Table", record: Any, value: bool) -> None:
        ev = {**self.cell_ev(table, record), "state": value}
        if evaluate(self._disabled, **ev):
            raise PermissionError("Column is disabled")
        if self._before_save:
            call(self._before_save, **ev)
        setattr(record, self.name, value)
        if self._after_save:
            call(self._after_save, **ev)

    def view_data(self, table: "Table", record: Any) -> dict[str, Any]:
        v = super().view_data(table, record)
        v["disabled"] = bool(evaluate(self._disabled, **v["ev"])) or not table.can_update(record)
        v["record_key"] = table.host.record_key(record)
        return v


class ColorColumn(Column):
    template = "tungsten/tables/columns/color.html"


class ViewColumn(Column):
    """Render a custom template for the cell (``template`` receives ``record`` and ``state``)."""

    def __init__(self, name: str, template: str | None = None) -> None:
        super().__init__(name)
        if template:
            self.template = template


def humanize_since(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        value = dt.datetime.combine(value, dt.time())
    now = dt.datetime.now(value.tzinfo) if value.tzinfo else dt.datetime.now()
    seconds = int((now - value).total_seconds())
    future = seconds < 0
    seconds = abs(seconds)
    for unit, size in (("year", 31536000), ("month", 2592000), ("week", 604800), ("day", 86400),
                       ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            n = seconds // size
            text = f"{n} {unit}{'s' if n != 1 else ''}"
            return f"in {text}" if future else f"{text} ago"
    return "just now"


def text_color(color: str | None) -> str:
    return colors.pick(colors.TEXT, color) if color else "text-gray-950 dark:text-white"


def render_icon(name: str | None, cls: str) -> Markup:
    return icon(name, cls)


__all__ = [
    "BadgeColumn", "ColorColumn", "Column", "IconColumn", "ImageColumn", "TextColumn", "ToggleColumn",
    "ViewColumn", "read_path", "escape",
]
