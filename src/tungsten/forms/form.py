"""The :class:`Form` container: holds the schema plus the live state of one form."""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from markupsafe import Markup

from ..support.component import Component
from ..support.state import Getter, Setter, get_path, join, set_path

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from .fields import Field

_ids = itertools.count(1)


class ValidationError(Exception):
    """Raised by :meth:`Form.validate`; ``errors`` maps state paths to messages."""

    def __init__(self, errors: dict[str, list[str]]):
        super().__init__("The given data was invalid.")
        self.errors = errors


class Form(Component):
    """A form schema bound to a record, operation and request.

    Resources build it in ``form(cls, form)``::

        def form(cls, form):
            return form.schema([TextInput("name").required()]).columns(2)
    """

    def __init__(self, schema: list | None = None) -> None:
        super().__init__()
        self._schema: list[Component] = list(schema or [])
        self._columns: int = 2
        self._model: Any = None
        self._disabled: Any = False
        # runtime
        self.ctx: Context | None = None
        self.operation: str = "create"
        self.record: Any = None
        self.state: dict[str, Any] = {}
        self.errors: dict[str, list[str]] = {}
        self.ui: dict[str, str] = {}
        self.id: str = f"tw-form-{next(_ids)}"
        self.source: dict[str, Any] = {}
        self.refresh_url: str | None = None

    # ------------------------------------------------------------------ config
    def schema(self, components: list) -> "Form":
        self._schema = list(components)
        return self

    def columns(self, columns: int) -> "Form":
        self._columns = columns
        return self

    def model(self, model: Any) -> "Form":
        self._model = model
        return self

    def disabled(self, condition: Any = True) -> "Form":
        self._disabled = condition
        return self

    def get_schema(self) -> list[Component]:
        return self._schema

    def get_model(self) -> Any:
        return self._model if self._model is not None else (type(self.record) if self.record is not None else None)

    def get_columns(self) -> int:
        return self._columns

    # ------------------------------------------------------------------ runtime
    def bind(
        self,
        ctx: "Context | None",
        *,
        operation: str = "create",
        record: Any = None,
        id: str | None = None,
        source: dict[str, Any] | None = None,
        refresh_url: str | None = None,
    ) -> "Form":
        self.ctx = ctx
        self.operation = operation
        self.record = record
        if id:
            self.id = id
        if source is not None:
            self.source = source
        if refresh_url is None and ctx is not None:
            refresh_url = ctx.panel.url("_tw", "form")
        self.refresh_url = refresh_url
        counters: dict[str, int] = {}
        for comp in self._walk_components(self._schema):
            key_attr = getattr(comp, "_ui_key", None)
            if key_attr is not None and getattr(comp, "_ui_key_auto", False):
                kind = comp.__class__.__name__.lower()
                n = counters.get(kind, 0)
                counters[kind] = n + 1
                comp._ui_key = f"{kind}{n}"
        return self

    def _walk_components(self, components: Iterable[Component]) -> Iterator[Component]:
        for comp in components:
            yield comp
            children = getattr(comp, "child_components", None)
            if children is not None:
                yield from self._walk_components(children())

    @property
    def is_disabled(self) -> bool:
        from ..support.evaluate import evaluate

        return bool(evaluate(self._disabled, **self.ev())) or self.operation == "view"

    def ev(self, base: str = "", **extra: Any) -> dict[str, Any]:
        """Arguments available to closures (``get``, ``set``, ``record`` ...)."""
        ctx = self.ctx
        data = {
            "get": Getter(self.state, base),
            "set": Setter(self.state, base),
            "record": self.record,
            "operation": self.operation,
            "form": self,
            "model": self.get_model(),
            "ctx": ctx,
            "request": ctx.request if ctx else None,
            "user": ctx.user if ctx else None,
            "db": ctx.db if ctx else None,
            "tenant": ctx.tenant if ctx else None,
        }
        data.update(extra)
        return data

    @property
    def renderer(self):
        from ..rendering import default_renderer

        if self.ctx is not None:
            return self.ctx.panel.renderer
        return default_renderer()

    # ------------------------------------------------------------------ state
    def fill(self, record: Any = None, data: dict[str, Any] | None = None) -> "Form":
        """Fill state from a record (edit/view) or from defaults (create)."""
        if record is not None:
            self.record = record
        self.state = {}
        for comp in self._schema:
            comp.fill_state(self, "", self.record if self.operation != "create" else None)
        if data:
            for key, value in data.items():
                set_path(self.state, key, value)
        return self

    def fill_from(self, data: Any) -> "Form":
        """Fill state from a dict (or any object) of Python values, ignoring defaults."""
        from .fields import DataRecord

        source = DataRecord(data) if isinstance(data, dict) else data
        self.state = {}
        for comp in self._schema:
            comp.fill_state(self, "", source)
        return self

    def load(self, formdata: Any) -> "Form":
        """Read state from submitted form data (a Starlette ``FormData``/MultiDict)."""
        self.state = {}
        for comp in self._schema:
            comp.load_state(self, formdata, "")
        for key in formdata.keys():
            if key.startswith("_tw_ui."):
                self.ui[key[len("_tw_ui."):]] = formdata.get(key)
        return self

    def get(self, path: str, default: Any = None) -> Any:
        return get_path(self.state, path, default)

    def set(self, path: str, value: Any) -> None:
        set_path(self.state, path, value)

    # ------------------------------------------------------------------ fields
    def walk_fields(self) -> Iterator[tuple["Field", str, str]]:
        """Yield ``(field, path, base)`` for every field, including repeater rows."""
        for comp in self._schema:
            yield from comp.walk(self, "")

    def find(self, path: str) -> tuple["Field", str, str] | None:
        for field, fpath, base in self.walk_fields():
            if fpath == path:
                return field, fpath, base
        return None

    # ------------------------------------------------------------------ validation
    def validate(self, components: list[Component] | None = None) -> dict[str, Any]:
        """Cast + validate visible fields. Returns clean data or raises ValidationError."""
        data: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}
        for comp in components if components is not None else self._schema:
            comp.process(self, "", data, errors)
        self.errors = errors
        if errors:
            self._focus_errors()
            raise ValidationError(errors)
        return data

    def _focus_errors(self) -> None:
        """Open the tab / wizard step that holds the first error."""
        for comp in self._walk_components(self._schema):
            on_errors = getattr(comp, "on_errors", None)
            if on_errors:
                on_errors(self)

    def add_error(self, path: str, message: str) -> None:
        self.errors.setdefault(path, []).append(message)

    # ------------------------------------------------------------------ saving
    def fill_record(self, record: Any, data: dict[str, Any]) -> Any:
        for comp in self._schema:
            comp.fill_record(self, record, data)
        return record

    def save_relationships(self, record: Any, data: dict[str, Any]) -> None:
        for comp in self._schema:
            comp.save_relationships(self, record, data)

    # ------------------------------------------------------------------ ui actions
    def handle_ui_action(self, action: str) -> None:
        """Run a server-side UI action such as ``repeater.add:items``."""
        if not action:
            return
        kind, _, rest = action.partition(":")
        target, _, arg = rest.partition(":")
        if kind.startswith("wizard."):
            for comp in self._walk_components(self._schema):
                if getattr(comp, "_ui_key", None) == target and hasattr(comp, "handle_ui_action"):
                    comp.handle_ui_action(self, kind.split(".", 1)[1], arg)
                    return
            return
        found = self.find(target)
        if found:
            field, path, base = found
            handler = getattr(field, "handle_ui_action", None)
            if handler:
                handler(self, path, base, kind.split(".", 1)[-1], arg)

    def state_updated(self, path: str) -> None:
        """Run ``after_state_updated`` hooks for the field that changed."""
        found = self.find(path)
        if found:
            field, fpath, base = found
            field.call_after_state_updated(self, fpath, base)

    # ------------------------------------------------------------------ render
    def render_schema(self, components: list[Component], base: str, columns: int | dict | None = None) -> Markup:
        return self.renderer.render(
            "tungsten/forms/grid.html",
            form=self,
            components=components,
            base=base,
            columns=self._columns if columns is None else columns,
        )

    def render(self) -> Markup:
        return self.renderer.render("tungsten/forms/form.html", form=self)

    def __html__(self) -> str:  # allows ``{{ form }}`` in templates
        return str(self.render())

    def path_id(self, path: str) -> str:
        return f"{self.id}-" + path.replace(".", "-")


def merge_paths(base: str, name: str) -> str:
    return join(base, name)


def _has_wizard(self: Form) -> bool:
    from .layout import Wizard

    return any(isinstance(c, Wizard) for c in self._schema)


Form.has_wizard = property(_has_wizard)  # type: ignore[attr-defined]
