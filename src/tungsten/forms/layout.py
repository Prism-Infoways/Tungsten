"""Layout components: Section, Grid, Fieldset, Group, Tabs and Wizard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

from markupsafe import Markup

from ..support.component import Component
from ..support.evaluate import evaluate
from .base import SchemaComponentMixin

if TYPE_CHECKING:  # pragma: no cover
    from .fields import Field
    from .form import Form


class Layout(SchemaComponentMixin, Component):
    """A container of other components. It holds no state of its own."""

    template = "tungsten/forms/layouts/group.html"

    def __init__(self, schema: list | None = None) -> None:
        super().__init__()
        self._schema: list[Component] = list(schema or [])
        self._columns: Any = 1

    def schema(self, components: list) -> "Layout":
        self._schema = list(components)
        return self

    def columns(self, columns: int) -> "Layout":
        self._columns = columns
        return self

    def child_components(self) -> list[Component]:
        return self._schema

    def is_layout_visible(self, form: "Form", base: str) -> bool:
        return self.is_visible(**form.ev(base))

    # lifecycle: delegate to children
    def fill_state(self, form: "Form", base: str, record: Any) -> None:
        for c in self.child_components():
            c.fill_state(form, base, record)

    def load_state(self, form: "Form", formdata: Any, base: str) -> None:
        for c in self.child_components():
            c.load_state(form, formdata, base)

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        if not self.is_layout_visible(form, base):
            return
        for c in self.child_components():
            c.process(form, base, data, errors)

    def fill_record(self, form: "Form", record: Any, data: dict) -> None:
        for c in self.child_components():
            c.fill_record(form, record, data)

    def save_relationships(self, form: "Form", record: Any, data: dict) -> None:
        for c in self.child_components():
            c.save_relationships(form, record, data)

    def walk(self, form: "Form", base: str) -> Iterator[tuple["Field", str, str]]:
        for c in self.child_components():
            yield from c.walk(form, base)

    def field_paths(self, form: "Form", base: str) -> list[str]:
        return [p for _, p, _ in self.walk(form, base)]

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        return {"base": base, "extra": self._extra_attributes}

    def render(self, form: "Form", base: str) -> Markup:
        if not self.is_layout_visible(form, base):
            return Markup("")
        return form.renderer.render(self.template, form=form, layout=self, v=self.view_data(form, base))


class Group(Layout):
    """Groups components without any visual wrapper (useful for visibility rules)."""

    def __init__(self, schema: list | None = None) -> None:
        super().__init__(schema)
        self._columns = 2


class Grid(Layout):
    """``Grid(3).schema([...])`` lays out children in columns."""

    template = "tungsten/forms/layouts/group.html"

    def __init__(self, columns: int = 2, schema: list | None = None) -> None:
        super().__init__(schema)
        self._columns = columns
        self._column_span = "full"


class Section(Layout):
    template = "tungsten/forms/layouts/section.html"

    def __init__(self, heading: Any = None, schema: list | None = None) -> None:
        super().__init__(schema)
        self._heading = heading
        self._description: Any = None
        self._icon: str | None = None
        self._collapsible = False
        self._collapsed = False
        self._aside = False
        self._compact = False
        self._columns = 2
        self._column_span = "full"

    def heading(self, heading: Any) -> "Section":
        self._heading = heading
        return self

    def description(self, text: Any) -> "Section":
        self._description = text
        return self

    def icon(self, icon: str) -> "Section":
        self._icon = icon
        return self

    def collapsible(self, condition: bool = True) -> "Section":
        self._collapsible = condition
        return self

    def collapsed(self, condition: bool = True) -> "Section":
        self._collapsed = condition
        self._collapsible = self._collapsible or condition
        return self

    def aside(self, condition: bool = True) -> "Section":
        """Show the heading and description in a column to the left."""
        self._aside = condition
        return self

    def compact(self, condition: bool = True) -> "Section":
        self._compact = condition
        return self

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        ev = form.ev(base)
        paths = set(self.field_paths(form, base))
        has_errors = any(p in form.errors for p in paths)
        return {
            "base": base,
            "heading": evaluate(self._heading, **ev),
            "description": evaluate(self._description, **ev),
            "icon": self._icon,
            "collapsible": self._collapsible,
            "collapsed": self._collapsed and not has_errors,
            "aside": self._aside,
            "compact": self._compact,
        }


class Fieldset(Layout):
    template = "tungsten/forms/layouts/fieldset.html"

    def __init__(self, label: Any = None, schema: list | None = None) -> None:
        super().__init__(schema)
        self._label = label
        self._columns = 2
        self._column_span = "full"

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        return {"base": base, "label": evaluate(self._label, **form.ev(base))}


class Tab(Layout):
    def __init__(self, label: Any, schema: list | None = None) -> None:
        super().__init__(schema)
        self._label = label
        self._icon: str | None = None
        self._badge: Any = None
        self._columns = 2

    def icon(self, icon: str) -> "Tab":
        self._icon = icon
        return self

    def badge(self, badge: Any) -> "Tab":
        self._badge = badge
        return self


class Tabs(Layout):
    """``Tabs().tabs([Tab("General").schema([...]), Tab("Media").schema([...])])``."""

    template = "tungsten/forms/layouts/tabs.html"

    def __init__(self, label: Any = None, tabs: list[Tab] | None = None) -> None:
        super().__init__(tabs)
        self._label = label
        self._column_span = "full"
        self._ui_key: str = ""
        self._ui_key_auto = True
        self._contained = True

    def tabs(self, tabs: list[Tab]) -> "Tabs":
        self._schema = list(tabs)
        return self

    def key(self, key: str) -> "Tabs":
        self._ui_key = key
        self._ui_key_auto = False
        return self

    def contained(self, condition: bool = True) -> "Tabs":
        self._contained = condition
        return self

    def on_errors(self, form: "Form") -> None:
        for i, tab in enumerate(self._schema):
            if any(p in form.errors for p in tab.field_paths(form, "")):
                form.ui[self._ui_key] = str(i)
                return

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        tabs = []
        for i, tab in enumerate(self._schema):
            if not tab.is_layout_visible(form, base):
                continue
            ev = form.ev(base)
            errors = sum(1 for p in tab.field_paths(form, base) if p in form.errors)
            tabs.append({"index": i, "tab": tab, "label": evaluate(tab._label, **ev), "icon": tab._icon,
                         "badge": evaluate(tab._badge, **ev), "errors": errors})
        active = form.ui.get(self._ui_key, str(tabs[0]["index"]) if tabs else "0")
        return {"base": base, "tabs": tabs, "key": self._ui_key, "active": active, "contained": self._contained}


class Step(Layout):
    def __init__(self, label: Any, schema: list | None = None) -> None:
        super().__init__(schema)
        self._label = label
        self._description: Any = None
        self._icon: str | None = None
        self._columns = 2

    def description(self, text: Any) -> "Step":
        self._description = text
        return self

    def icon(self, icon: str) -> "Step":
        self._icon = icon
        return self


class Wizard(Layout):
    """A step-by-step form. Each "Next" validates the current step on the server."""

    template = "tungsten/forms/layouts/wizard.html"

    def __init__(self, steps: list[Step] | None = None) -> None:
        super().__init__(steps)
        self._column_span = "full"
        self._ui_key = ""
        self._ui_key_auto = True
        self._skippable = False
        self._submit_label: Any = "Submit"
        self._vertical = True

    def steps(self, steps: list[Step]) -> "Wizard":
        self._schema = list(steps)
        return self

    def skippable(self, condition: bool = True) -> "Wizard":
        self._skippable = condition
        return self

    def submit_label(self, label: Any) -> "Wizard":
        self._submit_label = label
        return self

    def horizontal(self) -> "Wizard":
        self._vertical = False
        return self

    def key(self, key: str) -> "Wizard":
        self._ui_key = key
        self._ui_key_auto = False
        return self

    def current(self, form: "Form") -> int:
        try:
            return max(0, min(int(form.ui.get(self._ui_key, "0")), len(self._schema) - 1))
        except ValueError:
            return 0

    def handle_ui_action(self, form: "Form", kind: str, arg: str) -> None:
        from .form import ValidationError

        step = self.current(form)
        if kind == "next":
            try:
                form.validate(self._schema[step].child_components())
            except ValidationError:
                form.ui[self._ui_key] = str(step)
                return
            form.ui[self._ui_key] = str(min(step + 1, len(self._schema) - 1))
        elif kind == "previous":
            form.ui[self._ui_key] = str(max(step - 1, 0))
        elif kind == "goto" and arg.isdigit():
            target = int(arg)
            if self._skippable or target <= step:
                form.ui[self._ui_key] = str(target)

    def on_errors(self, form: "Form") -> None:
        for i, step in enumerate(self._schema):
            if any(p in form.errors for p in step.field_paths(form, "")):
                form.ui[self._ui_key] = str(i)
                return

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        ev = form.ev(base)
        current = self.current(form)
        steps = []
        for i, step in enumerate(self._schema):
            steps.append({
                "index": i,
                "step": step,
                "label": evaluate(step._label, **ev),
                "description": evaluate(step._description, **ev),
                "icon": step._icon,
                "errors": sum(1 for p in step.field_paths(form, base) if p in form.errors),
            })
        return {
            "base": base,
            "steps": steps,
            "key": self._ui_key,
            "current": current,
            "last": len(self._schema) - 1,
            "skippable": self._skippable,
            "submit_label": evaluate(self._submit_label, **ev),
            "vertical": self._vertical,
        }
