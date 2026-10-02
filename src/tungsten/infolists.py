"""Infolists: read-only layouts for view pages.

An infolist uses the same layouts as forms (Section, Grid, Tabs...) and
entries that format values like table columns::

    @classmethod
    def infolist(cls, infolist):
        return infolist.schema([
            Section("Product").schema([
                TextEntry("name").weight("semibold"),
                TextEntry("category.name").badge(),
                TextEntry("price").money("INR"),
                IconEntry("is_featured").boolean(),
                ImageEntry("images").stacked(),
            ]),
        ])

Every TextColumn option (``badge``, ``money``, ``date``, ``colors``, ``icon``,
``copyable``, ``limit``, ``list``...) works on ``TextEntry`` too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

from markupsafe import Markup

from .forms.fields import DataRecord, Field
from .forms.form import Form
from .support.component import Component
from .support.evaluate import evaluate
from .tables.columns import ColorColumn, Column, IconColumn, ImageColumn, TextColumn, read_path

if TYPE_CHECKING:  # pragma: no cover
    pass


class Infolist(Form):
    """A read-only :class:`Form`. Entries read straight from the record."""

    def bind(self, ctx, **kwargs):  # type: ignore[override]
        kwargs["operation"] = "view"
        kwargs.setdefault("refresh_url", "")
        return super().bind(ctx, **kwargs)

    @property
    def is_disabled(self) -> bool:
        return True

    def render(self) -> Markup:
        return self.renderer.render("tungsten/infolists/infolist.html", form=self)


class _EntryTable:
    """The small part of the Table API that columns need, backed by a form."""

    def __init__(self, form: Form, record: Any) -> None:
        self.form = form
        self.ctx = form.ctx
        self.host = None
        self.model = form.get_model()
        self.record = record

    def ev(self) -> dict[str, Any]:
        ev = self.form.ev()
        ev.pop("get", None)
        ev.pop("set", None)
        return ev

    @property
    def renderer(self):
        return self.form.renderer

    def can_update(self, record: Any) -> bool:
        return False


class Entry(Field):
    """Base entry. Unknown options are passed on to the column that formats the value."""

    template = "tungsten/infolists/entry.html"
    column_class: type[Column] = TextColumn

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.column = self.column_class(name)
        self._dehydrated = False
        self._inline_label = False

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_") or "column" not in self.__dict__:
            raise AttributeError(item)
        attr = getattr(self.column, item)
        if not callable(attr):
            return attr

        def proxy(*args: Any, **kwargs: Any) -> Any:
            result = attr(*args, **kwargs)
            return self if result is self.column else result

        return proxy

    # options that exist on both Field and Column go to the column
    def placeholder(self, text: Any) -> "Entry":
        self.column.placeholder(text)
        return self

    def default(self, value: Any) -> "Entry":
        self.column.default(value)
        return self

    def format_state_using(self, fn: Any) -> "Entry":
        """Change how the value is displayed (same as ``formatted()``)."""
        self.column.format_state_using(fn)
        return self

    def inline_label(self, condition: bool = True) -> "Entry":
        """Put the label to the left of the value instead of above it."""
        self._inline_label = condition
        return self

    # entries hold no form state
    def fill_state(self, form: Form, base: str, record: Any) -> None:
        return None

    def load_state(self, form: Form, formdata: Any, base: str) -> None:
        return None

    def process(self, form: Form, base: str, data: dict, errors: dict) -> None:
        return None

    def fill_record(self, form: Form, record: Any, data: dict) -> None:
        return None

    def save_relationships(self, form: Form, record: Any, data: dict) -> None:
        return None

    @staticmethod
    def current_record(form: Form) -> Any:
        return getattr(form, "_entry_record", None) or form.record

    def is_field_visible(self, form: Form, base: str) -> bool:
        record = self.current_record(form)
        return self.is_visible(**{**form.ev(base), "record": record,
                                  "state": read_path(record, self.name) if record is not None else None})

    def render(self, form: Form, base: str) -> Markup:
        if not self.is_field_visible(form, base):
            return Markup("")
        record = self.current_record(form)
        table = _EntryTable(form, record)
        cell = self.column.render_cell(table, record) if record is not None else Markup("")
        ev = {**form.ev(base), "record": record}
        return form.renderer.render(self.template, form=form, entry=self, cell=cell, v={
            "label": self.get_label(form, base),
            "show_label": not self._hidden_label,
            "helper_text": evaluate(self._helper_text, **ev),
            "hint": evaluate(self._hint, **ev),
            "hint_icon": self._hint_icon,
            "inline": self._inline_label,
        })


class TextEntry(Entry):
    column_class = TextColumn

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.column.placeholder("—")


class IconEntry(Entry):
    column_class = IconColumn

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.column.alignment("start")


class ImageEntry(Entry):
    column_class = ImageColumn

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.column.size(80)


class ColorEntry(Entry):
    column_class = ColorColumn


class KeyValueEntry(Entry):
    """Show a dict as a two-column table."""

    template = "tungsten/infolists/key-value-entry.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._key_label = "Key"
        self._value_label = "Value"

    def key_label(self, label: str) -> "KeyValueEntry":
        self._key_label = label
        return self

    def value_label(self, label: str) -> "KeyValueEntry":
        self._value_label = label
        return self

    def render(self, form: Form, base: str) -> Markup:
        if not self.is_field_visible(form, base):
            return Markup("")
        record = self.current_record(form)
        data = read_path(record, self.name) if record is not None else None
        return form.renderer.render(self.template, entry=self, rows=list((data or {}).items()), v={
            "label": self.get_label(form, base), "show_label": not self._hidden_label,
            "key_label": self._key_label, "value_label": self._value_label})


class RepeatableEntry(Entry):
    """Show each item of a list (a to-many relationship or a JSON list) with its own entries."""

    template = "tungsten/infolists/repeatable-entry.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._schema: list[Component] = []
        self._columns = 2
        self._grid = 1

    def schema(self, components: list) -> "RepeatableEntry":
        self._schema = list(components)
        return self

    def columns(self, n: int) -> "RepeatableEntry":
        self._columns = n
        return self

    def grid(self, n: int) -> "RepeatableEntry":
        """How many items per row."""
        self._grid = n
        return self

    def walk(self, form: Form, base: str) -> Iterator:
        yield self, self.path(base), base

    def render(self, form: Form, base: str) -> Markup:
        from .forms.base import GRID_COLUMNS

        if not self.is_field_visible(form, base):
            return Markup("")
        record = self.current_record(form)
        items = read_path(record, self.name) if record is not None else None
        if items is not None and not isinstance(items, list):
            items = list(items)
        rendered = []
        previous = getattr(form, "_entry_record", None)
        for item in items or []:
            form._entry_record = DataRecord(item) if isinstance(item, dict) else item  # type: ignore[attr-defined]
            rendered.append(form.render_schema(self._schema, base, self._columns))
        form._entry_record = previous  # type: ignore[attr-defined]
        return form.renderer.render(self.template, entry=self, items=rendered, v={
            "label": self.get_label(form, base), "show_label": not self._hidden_label,
            "grid": GRID_COLUMNS.get(self._grid, "grid-cols-1")})


__all__ = ["ColorEntry", "Entry", "IconEntry", "ImageEntry", "Infolist", "KeyValueEntry", "RepeatableEntry",
           "TextEntry"]
