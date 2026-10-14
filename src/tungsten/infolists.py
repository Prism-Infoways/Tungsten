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

Entries can carry action buttons, next to the label (``hint_action``), before or
after the value (``prefix_action`` / ``suffix_action``) or under it (``actions``)::

    TextEntry("email").suffix_action(
        Action("mail").icon("mail").url(lambda record: f"mailto:{record.email}"))
    TextEntry("status").badge().actions([
        Action("approve").requires_confirmation().action(lambda record: record.approve()),
    ])

They run like page actions: ``record`` is the record the infolist shows.

``CodeEntry`` shows code or JSON with colours, ``ViewEntry`` renders your own template.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Iterator

from markupsafe import Markup, escape

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

    def entry_actions(self) -> list:
        """Every action placed on an entry (``hint_action``, ``suffix_action``, ``actions``...)."""
        from .actions.action import flatten_actions

        out: list = []

        def visit(components: list) -> None:
            for comp in components:
                for field, _, _ in comp.walk(self, ""):
                    if isinstance(field, Entry):
                        out.extend(flatten_actions(field.all_actions()))
                    if isinstance(field, RepeatableEntry):
                        visit(field._schema)

        visit(self._schema)
        return out


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
        self._entry_actions: dict[str, list] = {"hint": [], "prefix": [], "suffix": [], "below": []}

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

    # ------------------------------------------------------------------ actions
    def hint_action(self, action: Any) -> "Entry":
        """A small action button next to the label."""
        return self.hint_actions([action])

    def hint_actions(self, actions: list) -> "Entry":
        self._entry_actions["hint"].extend(actions)
        return self

    def prefix_action(self, action: Any) -> "Entry":
        """An icon button before the value."""
        return self.prefix_actions([action])

    def prefix_actions(self, actions: list) -> "Entry":
        self._entry_actions["prefix"].extend(actions)
        return self

    def suffix_action(self, action: Any) -> "Entry":
        """An icon button after the value."""
        return self.suffix_actions([action])

    def suffix_actions(self, actions: list) -> "Entry":
        self._entry_actions["suffix"].extend(actions)
        return self

    def actions(self, actions: list) -> "Entry":
        """Buttons under the value."""
        self._entry_actions["below"].extend(actions)
        return self

    def all_actions(self) -> list:
        return [a for group in self._entry_actions.values() for a in group]

    def render_actions(self, form: Form, place: str) -> Markup:
        from .actions.action import ActionGroup, flatten_actions

        actions = self._entry_actions[place]
        if not actions or form.ctx is None:
            return Markup("")
        host = getattr(form, "_host", None)
        for a in flatten_actions(actions):
            a.scope = "infolist"
        style = None if place == "below" else "icon"
        out = []
        for a in actions:
            if isinstance(a, ActionGroup):
                out.append(a.render(form.ctx, host, form.record))
            else:
                out.append(a.render(form.ctx, host, form.record, style=a._style or style))
        return Markup("").join(out)

    def action_slots(self, form: Form) -> dict[str, Markup]:
        return {place: self.render_actions(form, place) for place in self._entry_actions}

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
            "actions": self.action_slots(form),
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


# ---------------------------------------------------------------------- code
_KEYWORDS = {
    "python": "and as assert async await break class continue def del elif else except finally for from global "
              "if import in is lambda nonlocal not or pass raise return try while with yield match case",
    "js": "async await break case catch class const continue default delete do else export extends finally for "
          "function if import in instanceof let new of return static super switch this throw try typeof var "
          "void while yield",
    "sql": "select from where and or not insert into values update set delete create table alter drop index on "
           "join left right inner outer group by order having limit offset as distinct union all null is in "
           "like between case when then else end primary key foreign references default",
    "bash": "if then else elif fi for while do done case esac function return in export local echo",
    "php": "abstract and array as break case catch class clone const continue declare default do echo else "
           "elseif empty enddeclare endfor endforeach endif endswitch endwhile extends final finally fn for "
           "foreach function global if implements include instanceof interface isset list match namespace new "
           "or print private protected public readonly require return static switch throw trait try unset use "
           "var while yield",
}
_KEYWORDS.update({"javascript": _KEYWORDS["js"], "ts": _KEYWORDS["js"], "typescript": _KEYWORDS["js"],
                  "py": _KEYWORDS["python"], "sh": _KEYWORDS["bash"], "shell": _KEYWORDS["bash"]})
_LITERALS = {"true", "false", "null", "None", "True", "False", "undefined", "NULL", "TRUE", "FALSE"}
_COMMENTS = {"python": r"#[^\n]*", "py": r"#[^\n]*", "bash": r"#[^\n]*", "sh": r"#[^\n]*", "shell": r"#[^\n]*",
             "yaml": r"#[^\n]*", "toml": r"#[^\n]*", "sql": r"--[^\n]*", "html": r"<!--[\s\S]*?-->",
             "xml": r"<!--[\s\S]*?-->"}
_TOKEN_CLASSES = {
    "comment": "italic text-gray-400 dark:text-gray-500",
    "key": "text-info-700 dark:text-info-300",
    "string": "text-success-700 dark:text-success-400",
    "number": "text-warning-700 dark:text-warning-400",
    "keyword": "font-medium text-purple-700 dark:text-purple-400",
    "literal": "text-danger-600 dark:text-danger-400",
    "tag": "text-info-700 dark:text-info-300",
}


def highlight(code: str, language: str | None) -> Markup:
    """Colour ``code`` with a small, dependency-free tokenizer (strings, numbers, keywords, comments)."""
    lang = (language or "").lower()
    if lang in ("html", "xml"):
        pattern = rf"(?P<comment>{_COMMENTS[lang]})|(?P<tag></?[A-Za-z][\w:-]*|/?>)|(?P<string>\"[^\"]*\"|'[^']*')"
    else:
        comment = _COMMENTS.get(lang, r"//[^\n]*|/\*[\s\S]*?\*/" if lang not in ("json", "") else None)
        parts = []
        if comment:
            parts.append(rf"(?P<comment>{comment})")
        parts += [
            r"(?P<key>\"(?:\\.|[^\"\\])*\"(?=\s*:))" if lang in ("json", "js", "javascript", "ts", "typescript") else "",
            r"(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)",
            r"(?P<number>\b-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)",
            r"(?P<word>\b[A-Za-z_][\w]*\b)",
        ]
        pattern = "|".join(p for p in parts if p)
    keywords = set(_KEYWORDS.get(lang, "").split())
    if lang == "sql":
        keywords |= {k.upper() for k in keywords}
    out: list[str] = []
    last = 0
    for m in re.finditer(pattern, code):
        kind = m.lastgroup
        text = m.group(0)
        if kind == "word":
            kind = "literal" if text in _LITERALS else ("keyword" if text in keywords else None)
        out.append(str(escape(code[last:m.start()])))
        if kind:
            out.append(f'<span class="{_TOKEN_CLASSES[kind]}">{escape(text)}</span>')
        else:
            out.append(str(escape(text)))
        last = m.end()
    out.append(str(escape(code[last:])))
    return Markup("".join(out))


class CodeEntry(Entry):
    """Show code or JSON in a monospaced, coloured block::

        CodeEntry("payload")                      # dicts and lists are shown as pretty JSON
        CodeEntry("script").language("python").line_numbers()
    """

    template = "tungsten/infolists/code-entry.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._language: Any = None
        self._line_numbers = False
        self._copy = True
        self._max_height: int | None = 384
        self._wrap = False

    def language(self, language: Any) -> "CodeEntry":
        """``json``, ``python``, ``js``, ``sql``, ``bash``, ``php``, ``html``, ``yaml``... (colours only)."""
        self._language = language
        return self

    def line_numbers(self, condition: bool = True) -> "CodeEntry":
        self._line_numbers = condition
        return self

    def copyable(self, condition: bool = True) -> "CodeEntry":  # type: ignore[override]
        """Show a copy button (on by default)."""
        self._copy = condition
        return self

    def max_height(self, pixels: int | None) -> "CodeEntry":
        """Scroll inside the block above this height (``None``: never)."""
        self._max_height = pixels
        return self

    def wrap(self, condition: bool = True) -> "CodeEntry":
        """Wrap long lines instead of scrolling sideways."""
        self._wrap = condition
        return self

    def get_code(self, form: Form, base: str) -> tuple[str, str | None]:
        record = self.current_record(form)
        state = read_path(record, self.name) if record is not None else None
        ev = {**form.ev(base), "record": record, "state": state}
        if self.column._state is not None:
            state = evaluate(self.column._state, **ev)
        language = evaluate(self._language, **ev)
        if isinstance(state, (bytes, bytearray)):
            state = state.decode("utf-8", "replace")
        if isinstance(state, (dict, list, tuple)):
            return json.dumps(state, indent=2, ensure_ascii=False, default=str), language or "json"
        if isinstance(state, str) and language == "json":
            try:  # pretty-print stored JSON text
                return json.dumps(json.loads(state), indent=2, ensure_ascii=False), language
            except ValueError:
                pass
        return ("" if state is None else str(state)), language

    def render(self, form: Form, base: str) -> Markup:
        if not self.is_field_visible(form, base):
            return Markup("")
        code, language = self.get_code(form, base)
        lines = code.split("\n")
        ev = {**form.ev(base), "record": self.current_record(form)}
        return form.renderer.render(self.template, entry=self, code=code, v={
            "label": self.get_label(form, base), "show_label": not self._hidden_label,
            "html": highlight(code, language) if code else Markup(""),
            "language": language, "line_numbers": self._line_numbers, "lines": len(lines),
            "copyable": self._copy, "max_height": self._max_height, "wrap": self._wrap,
            "placeholder": evaluate(self.column._placeholder, **ev),
            "helper_text": evaluate(self._helper_text, **ev),
            "hint": evaluate(self._hint, **ev), "hint_icon": self._hint_icon,
            "actions": self.action_slots(form)})


class ViewEntry(Entry):
    """Render your own Jinja template for an entry::

        ViewEntry("location").view("admin/map-entry.html").view_data({"zoom": 12})

    The template gets ``state`` (the value), ``record``, ``entry``, ``label`` and your ``view_data``.
    Put the template in a folder passed to ``Panel(template_dirs=[...])``.
    """

    def __init__(self, name: str, view: str | None = None) -> None:
        super().__init__(name)
        self._view = view
        self._view_data: Any = {}
        self._wrapped = True

    def view(self, template: str) -> "ViewEntry":
        self._view = template
        return self

    def view_data(self, data: Any) -> "ViewEntry":
        """Extra variables for the template (a dict, or a function returning one)."""
        self._view_data = data
        return self

    def without_label_wrapper(self, condition: bool = True) -> "ViewEntry":
        """Render only your template: no label, hint or helper text around it."""
        self._wrapped = not condition
        return self

    def render(self, form: Form, base: str) -> Markup:
        if not self.is_field_visible(form, base):
            return Markup("")
        if not self._view:
            raise ValueError(f"ViewEntry({self.name!r}) needs a template: .view('path/to/template.html')")
        record = self.current_record(form)
        state = read_path(record, self.name) if record is not None else None
        ev = {**form.ev(base), "record": record, "state": state}
        if self.column._state is not None:
            state = ev["state"] = evaluate(self.column._state, **ev)
        label = self.get_label(form, base)
        extra = evaluate(self._view_data, **ev) or {}
        cell = form.renderer.render(self._view, **{**extra, "state": state, "record": record, "entry": self,
                                                   "label": label, "ctx": form.ctx, "form": form})
        if not self._wrapped:
            return cell
        return form.renderer.render(Entry.template, form=form, entry=self, cell=cell, v={
            "label": label, "show_label": not self._hidden_label,
            "helper_text": evaluate(self._helper_text, **ev), "hint": evaluate(self._hint, **ev),
            "hint_icon": self._hint_icon, "inline": self._inline_label, "actions": self.action_slots(form)})


__all__ = ["CodeEntry", "ColorEntry", "Entry", "IconEntry", "ImageEntry", "Infolist", "KeyValueEntry", "RepeatableEntry",
           "TextEntry", "ViewEntry", "highlight"]
