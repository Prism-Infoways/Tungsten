"""Code and Markdown editors: :class:`CodeEditor` and :class:`MarkdownEditor`.

Both are plain textareas with extra behaviour and no heavy JavaScript library, so
they load fast and work offline. The code editor adds line numbers, Tab indenting and a
language chip; the Markdown editor adds a toolbar, a live preview and keyboard shortcuts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from markupsafe import Markup

from ..i18n import __
from ..support.evaluate import evaluate
from ..support.markdown import markdown_to_html
from .fields import Textarea

if TYPE_CHECKING:  # pragma: no cover
    from .form import Form

#: the toolbar of the Markdown editor: name, Lucide icon, label, shortcut
MARKDOWN_TOOLBAR = [
    ("bold", "bold", "Bold", "Ctrl+B"),
    ("italic", "italic", "Italic", "Ctrl+I"),
    ("strike", "strikethrough", "Strikethrough", ""),
    ("heading", "heading", "Heading", ""),
    ("quote", "quote", "Quote", ""),
    ("code", "code", "Code", "Ctrl+E"),
    ("codeBlock", "square-code", "Code block", ""),
    ("link", "link", "Link", "Ctrl+K"),
    ("image", "image", "Image", ""),
    ("bulletList", "list", "Bullet list", ""),
    ("orderedList", "list-ordered", "Numbered list", ""),
    ("taskList", "list-checks", "Task list", ""),
    ("table", "table", "Table", ""),
    ("hr", "minus", "Divider", ""),
]


class CodeEditor(Textarea):
    """A monospaced editor for code, JSON, YAML, SQL or HTML::

        CodeEditor("script").language("python").line_numbers()
        CodeEditor("settings").language("json").json()        # pretty JSON in, a dict out

    Tab indents (Shift+Tab outdents), Enter keeps the indent, and the language is shown
    as a small chip. ``json()`` checks the text is valid JSON and saves it as data.
    """

    template = "tungsten/forms/fields/code-editor.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._language: Any = None
        self._line_numbers = True
        self._indent = 2
        self._min_height: int | None = 160
        self._max_height: int | None = 480
        self._wrap = False
        self._json = False
        self._rows = 8

    def language(self, language: Any) -> "CodeEditor":
        """``json``, ``python``, ``js``, ``sql``, ``bash``, ``php``, ``html``, ``css``, ``yaml``... (a label; Tab size follows it)."""
        self._language = language
        return self

    def line_numbers(self, condition: bool = True) -> "CodeEditor":
        self._line_numbers = condition
        return self

    def indent(self, spaces: int) -> "CodeEditor":
        """How many spaces Tab inserts (default 2; 4 for Python)."""
        self._indent = spaces
        return self

    def min_height(self, pixels: int | None) -> "CodeEditor":
        self._min_height = pixels
        return self

    def max_height(self, pixels: int | None) -> "CodeEditor":
        """Scroll inside the editor above this height (``None``: grow forever)."""
        self._max_height = pixels
        return self

    def wrap(self, condition: bool = True) -> "CodeEditor":
        """Wrap long lines instead of scrolling sideways."""
        self._wrap = condition
        return self

    def json(self, condition: bool = True) -> "CodeEditor":
        """Treat the text as JSON: shown pretty-printed, checked on save, stored as data (a dict or list)."""
        self._json = condition
        if condition and self._language is None:
            self._language = "json"
        return self

    def to_state(self, value: Any) -> Any:
        import json as _json

        if self._json and isinstance(value, (dict, list, tuple)):
            return _json.dumps(value, indent=2, ensure_ascii=False, default=str)
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", "replace")
        return super().to_state(value)

    def cast(self, state: Any) -> Any:
        value = super().cast(state)
        if self._json and isinstance(value, str) and value.strip():
            import json as _json

            try:
                return _json.loads(value)
            except ValueError as exc:
                raise ValueError(__("The :attribute must be valid JSON (:error).", attribute=self.get_label().lower(),
                                    error=str(exc))) from exc
        return value

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        language = evaluate(self._language, **self.field_ev(form, base))
        indent = self._indent
        if language in ("python", "py") and indent == 2:
            indent = 4
        v.update(language=language, line_numbers=self._line_numbers, indent=indent, min_height=self._min_height,
                 max_height=self._max_height, wrap=self._wrap)
        return v


class MarkdownEditor(Textarea):
    """Write Markdown with a toolbar and a live preview::

        MarkdownEditor("body").toolbar_buttons(["bold", "italic", "link", "bulletList"]).preview()

    The value is the Markdown text. Show it with :func:`tungsten.support.markdown.markdown_to_html`,
    or save the HTML next to it with ``.html_column("body_html")``.
    """

    template = "tungsten/forms/fields/markdown-editor.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._rows = 10
        self._toolbar: list[str] | None = None
        self._preview = True
        self._html_column: str | None = None
        self._min_height: int | None = 200
        self._max_height: int | None = 600

    def toolbar_buttons(self, buttons: list[str] | None) -> "MarkdownEditor":
        """Which buttons to show, in order: ``bold``, ``italic``, ``strike``, ``heading``, ``quote``, ``code``,
        ``codeBlock``, ``link``, ``image``, ``bulletList``, ``orderedList``, ``taskList``, ``table``, ``hr``.
        ``None`` shows them all, ``[]`` hides the toolbar."""
        self._toolbar = None if buttons is None else list(buttons)
        return self

    def disable_toolbar_buttons(self, buttons: list[str]) -> "MarkdownEditor":
        keep = [b[0] for b in MARKDOWN_TOOLBAR] if self._toolbar is None else self._toolbar
        self._toolbar = [b for b in keep if b not in set(buttons)]
        return self

    def preview(self, condition: bool = True) -> "MarkdownEditor":
        """Show a Preview tab (on by default)."""
        self._preview = condition
        return self

    def html_column(self, column: str) -> "MarkdownEditor":
        """Also save the rendered HTML into this attribute of the record."""
        self._html_column = column
        return self

    def min_height(self, pixels: int | None) -> "MarkdownEditor":
        self._min_height = pixels
        return self

    def max_height(self, pixels: int | None) -> "MarkdownEditor":
        self._max_height = pixels
        return self

    def fill_record(self, form: "Form", record: Any, data: dict) -> None:
        super().fill_record(form, record, data)
        if self._html_column and self.name in data:
            setattr(record, self._html_column, str(markdown_to_html(data.get(self.name))))

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        names = [b[0] for b in MARKDOWN_TOOLBAR] if self._toolbar is None else self._toolbar
        by_name = {b[0]: b for b in MARKDOWN_TOOLBAR}
        toolbar = [{"name": n, "icon": by_name[n][1], "label": __(by_name[n][2]), "shortcut": by_name[n][3]}
                   for n in names if n in by_name]
        state = v.get("state")
        v.update(toolbar=toolbar, preview=self._preview, min_height=self._min_height, max_height=self._max_height,
                 preview_html=markdown_to_html(state if isinstance(state, str) else None) if self._preview else Markup(""))
        return v
