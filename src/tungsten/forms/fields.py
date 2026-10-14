"""Form fields. Every field is chainable: ``TextInput("email").email().required()``."""

from __future__ import annotations

import datetime as dt
import enum
import mimetypes
import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Callable, Iterator

from markupsafe import Markup

from ..i18n import maybe
from ..i18n import translate as __
from ..support.component import Component, headline
from ..support.evaluate import call, evaluate
from ..support.html import attrs
from ..support.state import get_path, join, set_path
from .base import SchemaComponentMixin

if TYPE_CHECKING:  # pragma: no cover
    from .form import Form

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.I)
HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}){1,2}$")
TAG_RE = re.compile(r"<[^>]*>")


def is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


class Field(SchemaComponentMixin, Component):
    """Base class for all form fields."""

    template = "tungsten/forms/fields/text-input.html"
    #: the user types the value (text, dates): ``live(on_blur=True)`` and ``debounce`` apply
    live_typed = True

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self._label: Any = None
        self._default: Any = None
        self._required: Any = False
        self._disabled: Any = False
        self._helper_text: Any = None
        self._hint: Any = None
        self._hint_icon: str | None = None
        self._placeholder: Any = None
        self._live = False
        self._live_debounce: int | None = None
        self._live_on_blur = False
        self._after_state_updated: list[Callable] = []
        self._rules: list[tuple[Callable, Any]] = []
        self._dehydrated: Any = True
        self._format_state: Callable | None = None
        self._dehydrate_state: Callable | None = None
        self._save_relationships_using: Callable | None = None
        self._autofocus = False
        self._inline_label = False
        self._unique: dict | None = None
        self._hidden_label = False
        self._hint_color: Any = None
        self._hint_actions: list = []
        self._prefix_actions: list = []
        self._suffix_actions: list = []

    # ------------------------------------------------------------------ config
    def label(self, label: Any) -> "Field":
        self._label = label
        return self

    def hidden_label(self, condition: bool = True) -> "Field":
        self._hidden_label = condition
        return self

    def default(self, value: Any) -> "Field":
        self._default = value
        return self

    def required(self, condition: Any = True) -> "Field":
        self._required = condition
        return self

    def disabled(self, condition: Any = True) -> "Field":
        self._disabled = condition
        return self

    def helper_text(self, text: Any) -> "Field":
        self._helper_text = text
        return self

    def hint(self, text: Any, icon: str | None = None) -> "Field":
        self._hint = text
        self._hint_icon = icon
        return self

    def hint_color(self, color: Any) -> "Field":
        self._hint_color = color
        return self

    def hint_action(self, action: Any) -> "Field":
        """A button next to the hint, e.g. ``Action("copy").icon("copy").action(...)``."""
        self._hint_actions.append(action)
        return self

    def hint_actions(self, actions: list) -> "Field":
        self._hint_actions.extend(actions)
        return self

    def prefix_action(self, action: Any) -> "Field":
        """A button before the input. Its closure gets ``get``/``set``/``state`` of the form."""
        self._prefix_actions.append(action)
        return self

    def prefix_actions(self, actions: list) -> "Field":
        self._prefix_actions.extend(actions)
        return self

    def suffix_action(self, action: Any) -> "Field":
        """A button after the input, e.g. to generate or copy the value."""
        self._suffix_actions.append(action)
        return self

    def suffix_actions(self, actions: list) -> "Field":
        self._suffix_actions.extend(actions)
        return self

    def form_actions(self, form: "Form", base: str) -> list:
        """Every action this field shows (see :mod:`tungsten.forms.actions`)."""
        return [*self._hint_actions, *self._prefix_actions, *self._suffix_actions]

    def placeholder(self, text: Any) -> "Field":
        self._placeholder = text
        return self

    def autofocus(self, condition: bool = True) -> "Field":
        self._autofocus = condition
        return self

    def live(self, debounce: int | None = None, on_blur: bool = False) -> "Field":
        """Re-render the form on the server when this field changes (dependent fields)."""
        self._live = True
        self._live_debounce = debounce
        self._live_on_blur = on_blur
        return self

    reactive = live

    def after_state_updated(self, fn: Callable) -> "Field":
        """Run ``fn(state, get, set, ...)`` after a live update of this field."""
        self._after_state_updated.append(fn)
        if not self._live:
            self._live = True
        return self

    def rule(self, fn: Callable, message: Any = None) -> "Field":
        """Custom rule. ``fn`` gets ``value`` (+ get/record/...) and returns
        ``True``/``None`` when valid, ``False`` or an error string when not."""
        self._rules.append((fn, message))
        return self

    def rules(self, rules: list[Callable]) -> "Field":
        for r in rules:
            self.rule(r)
        return self

    def dehydrated(self, condition: Any = True) -> "Field":
        """Whether the value is saved. May be a closure, e.g. ``lambda state: bool(state)``."""
        self._dehydrated = condition
        return self

    def format_state_using(self, fn: Callable) -> "Field":
        """Change how a record value is shown in the field (``fn(state, record)``)."""
        self._format_state = fn
        return self

    def dehydrate_state_using(self, fn: Callable) -> "Field":
        """Change the value before it is saved (``fn(state)``), e.g. hash a password."""
        self._dehydrate_state = fn
        return self

    mutate_dehydrated_state_using = dehydrate_state_using

    def save_relationships_using(self, fn: Callable) -> "Field":
        """Custom save logic run after the record is stored (``fn(record, state)``)."""
        self._save_relationships_using = fn
        self._dehydrated = False
        return self

    def unique(self, column: str | None = None, model: Any = None, ignore_record: bool = True) -> "Field":
        self._unique = {"column": column or self.name, "model": model, "ignore_record": ignore_record}
        return self

    # ------------------------------------------------------------------ getters
    def get_label(self, form: "Form | None" = None, base: str = "") -> str:
        if self._label is None:
            return __(headline(self.name))
        if form is None:
            return __(str(self._label) if not callable(self._label) else headline(self.name))
        return __(str(evaluate(self._label, **form.ev(base))))

    def is_required(self, form: "Form", base: str = "") -> bool:
        return bool(evaluate(self._required, **form.ev(base)))

    def is_disabled(self, form: "Form", base: str = "") -> bool:
        return form.is_disabled or bool(evaluate(self._disabled, **form.ev(base)))

    def path(self, base: str) -> str:
        return join(base, self.name)

    def get_state(self, form: "Form", base: str) -> Any:
        return get_path(form.state, self.path(base))

    def field_ev(self, form: "Form", base: str, **extra: Any) -> dict[str, Any]:
        return form.ev(base, state=self.get_state(form, base), component=self, **extra)

    def is_field_visible(self, form: "Form", base: str) -> bool:
        return self.is_visible(**self.field_ev(form, base))

    # ------------------------------------------------------------------ lifecycle
    def blank_state(self) -> Any:
        return ""

    def default_state(self, form: "Form", base: str) -> Any:
        value = evaluate(self._default, **form.ev(base))
        if value is None:
            return self.blank_state()
        return self.to_state(value)

    def to_state(self, value: Any) -> Any:
        """Convert a Python value (from a model) into form state."""
        if value is None:
            return self.blank_state()
        if isinstance(value, enum.Enum):
            return str(value.value)
        if isinstance(value, Decimal):
            return format(value.normalize(), "f") if value == value.to_integral() else str(value)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        return value

    def hydrate(self, form: "Form", record: Any) -> Any:
        value = getattr(record, self.name, None)
        if self._format_state is not None:
            return call(self._format_state, **{**form.ev(), "state": value, "record": record})
        return self.to_state(value)

    def fill_state(self, form: "Form", base: str, record: Any) -> None:
        if record is not None:
            state = self.hydrate(form, record)
        else:
            state = self.default_state(form, base)
        set_path(form.state, self.path(base), state)

    def extract(self, formdata: Any, path: str) -> Any:
        value = formdata.get(path)
        return "" if value is None else value

    def load_state(self, form: "Form", formdata: Any, base: str) -> None:
        set_path(form.state, self.path(base), self.extract(formdata, self.path(base)))

    def cast(self, state: Any) -> Any:
        """Convert form state into a Python value. Raise ``ValueError`` with a message on bad input."""
        if isinstance(state, str):
            state = state.strip()
            return state if state != "" else None
        return state

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        return []

    def run_rules(self, form: "Form", base: str, value: Any) -> list[str]:
        errors: list[str] = []
        label = self.get_label(form, base)
        for fn, message in self._rules:
            result = call(fn, **{**self.field_ev(form, base), "value": value, "attribute": label})
            if result is True or result is None:
                continue
            if isinstance(result, str):
                errors.append(__(result, attribute=label.lower()))
            else:
                errors.append(str(evaluate(message, **form.ev(base))) if message else __("The :attribute is invalid.", attribute=label.lower()))
        if self._unique and not is_blank(value):
            err = self._check_unique(form, value)
            if err:
                errors.append(err)
        return errors

    def _check_unique(self, form: "Form", value: Any) -> str | None:
        if form.ctx is None:
            return None
        from sqlalchemy import func, select
        from sqlalchemy import inspect as sa_inspect

        model = self._unique["model"] or getattr(self, "_owner_model", None) or form.get_model()
        if model is None:
            return None
        column = getattr(model, self._unique["column"])
        query = select(func.count()).select_from(model).where(column == value)
        query = form.ctx.panel.tenancy.scope(form.ctx, model, query)  # unique within the current tenant
        if self._unique["ignore_record"] and form.record is not None and form.operation != "create" \
                and isinstance(form.record, model):
            pk = sa_inspect(model).primary_key[0]
            query = query.where(pk != getattr(form.record, pk.key))
        if form.ctx.db.scalar(query):
            return __("The :attribute has already been taken.", attribute=self.get_label(form).lower())
        return None

    def is_dehydrated(self, form: "Form", base: str) -> bool:
        return bool(evaluate(self._dehydrated, **self.field_ev(form, base)))

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        """Cast + validate this field and write the clean value into ``data``."""
        if not self.is_field_visible(form, base):
            return
        path = self.path(base)
        state = get_path(form.state, path)
        label = self.get_label(form, base)
        try:
            value = self.cast(state)
        except ValueError as exc:
            errors.setdefault(path, []).append(__(str(exc), attribute=label.lower()))
            return
        if is_blank(value):
            if self.is_required(form, base) and not self.is_disabled(form, base):
                errors.setdefault(path, []).append(__("The :attribute field is required.", attribute=label.lower()))
                return
        else:
            msgs = self.validate_value(form, base, value)
            msgs += self.run_rules(form, base, value)
            if msgs:
                errors.setdefault(path, []).extend(msgs)
                return
        if self.is_disabled(form, base) and not getattr(self, "_dehydrate_when_disabled", False):
            return
        if not self.is_dehydrated(form, base):
            return
        if self._dehydrate_state is not None:
            value = call(self._dehydrate_state, **{**form.ev(base), "state": value})
        data[self.name] = value

    def fill_record(self, form: "Form", record: Any, data: dict) -> None:
        if self.name in data and self._save_relationships_using is None and not getattr(self, "_is_relation_many", False):
            setattr(record, self.name, data[self.name])

    def save_relationships(self, form: "Form", record: Any, data: dict) -> None:
        if self._save_relationships_using is not None and self.is_field_visible(form, ""):
            state = self.cast(self.get_state(form, ""))
            call(self._save_relationships_using, **{**form.ev(), "record": record, "state": state})

    def walk(self, form: "Form", base: str) -> Iterator[tuple["Field", str, str]]:
        yield self, self.path(base), base

    def call_after_state_updated(self, form: "Form", path: str, base: str) -> None:
        for fn in self._after_state_updated:
            call(fn, **self.field_ev(form, base))

    # ------------------------------------------------------------------ render
    def live_trigger(self) -> str:
        """The htmx trigger for ``live()``. Typed inputs can refresh on blur or while
        typing; inputs that are picked (``live_typed = False``) refresh on change."""
        delay = f" delay:{self._live_debounce}ms" if self._live_debounce else ""
        if not self.live_typed:
            # checkboxes and radios keep the same value, so "input changed" never fires
            return "change" + delay
        if self._live_on_blur:
            return "blur" + delay
        if self._live_debounce:
            return "input changed" + delay
        return "change"

    def live_attrs(self, form: "Form", trigger: str | None = None) -> Markup:
        if not self._live or form.is_disabled:
            return Markup("")
        if trigger is None:
            trigger = self.live_trigger()
        return attrs({
            "hx-post": form.refresh_url,
            "hx-trigger": trigger,
            "hx-target": f"#{form.id}",
            "hx-swap": "outerHTML",
            "hx-include": "closest form",
            "hx-sync": "closest form:replace",
        })

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        from .actions import render_actions

        path = self.path(base)
        ev = self.field_ev(form, base)
        return {
            "hint_color": evaluate(self._hint_color, **ev),
            "hint_actions": render_actions(self._hint_actions, form, self, base, style="link", size="sm")
            if self._hint_actions else Markup(""),
            "prefix_actions": render_actions(self._prefix_actions, form, self, base, style="icon")
            if self._prefix_actions else Markup(""),
            "suffix_actions": render_actions(self._suffix_actions, form, self, base, style="icon")
            if self._suffix_actions else Markup(""),
            "path": path,
            "id": form.path_id(path),
            "state": get_path(form.state, path),
            "label": self.get_label(form, base),
            "show_label": not self._hidden_label,
            "required": self.is_required(form, base),
            "disabled": self.is_disabled(form, base),
            "errors": form.errors.get(path, []),
            "helper_text": maybe(evaluate(self._helper_text, **ev)),
            "hint": maybe(evaluate(self._hint, **ev)),
            "hint_icon": self._hint_icon,
            "placeholder": maybe(evaluate(self._placeholder, **ev)),
            "live": self.live_attrs(form),
            "autofocus": self._autofocus,
            "extra": attrs(self._extra_attributes),
            "base": base,
        }

    def render(self, form: "Form", base: str) -> Markup:
        if not self.is_field_visible(form, base):
            return Markup("")
        return form.renderer.render(self.template, form=form, field=self, v=self.view_data(form, base))


# ---------------------------------------------------------------------- inputs
class TextInput(Field):
    template = "tungsten/forms/fields/text-input.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._type = "text"
        self._numeric = False
        self._integer = False
        self._min_length: int | None = None
        self._max_length: int | None = None
        self._min_value: Any = None
        self._max_value: Any = None
        self._step: Any = None
        self._regex: tuple[str, str | None] | None = None
        self._prefix: Any = None
        self._suffix: Any = None
        self._prefix_icon: str | None = None
        self._suffix_icon: str | None = None
        self._revealable = False
        self._autocomplete: str | None = None
        self._datalist: Any = None
        self._same: str | None = None
        self._mask: Any = None
        self._strip: list[str] = []

    def type(self, value: str) -> "TextInput":
        self._type = value
        return self

    def email(self) -> "TextInput":
        self._type = "email"
        return self

    def password(self) -> "TextInput":
        self._type = "password"
        return self

    def revealable(self, condition: bool = True) -> "TextInput":
        self._revealable = condition
        return self

    def tel(self) -> "TextInput":
        self._type = "tel"
        return self

    def url(self) -> "TextInput":
        self._type = "url"
        return self

    def numeric(self) -> "TextInput":
        self._numeric = True
        self._type = "number"
        if self._step is None:
            self._step = "any"
        return self

    def integer(self) -> "TextInput":
        self._integer = True
        self._numeric = True
        self._type = "number"
        self._step = 1
        return self

    def min_length(self, n: int) -> "TextInput":
        self._min_length = n
        return self

    def max_length(self, n: int) -> "TextInput":
        self._max_length = n
        return self

    def length(self, n: int) -> "TextInput":
        self._min_length = self._max_length = n
        return self

    def min_value(self, n: Any) -> "TextInput":
        self._min_value = n
        return self

    def max_value(self, n: Any) -> "TextInput":
        self._max_value = n
        return self

    min = min_value
    max = max_value

    def step(self, n: Any) -> "TextInput":
        self._step = n
        return self

    def regex(self, pattern: str, message: str | None = None) -> "TextInput":
        self._regex = (pattern, message)
        return self

    def prefix(self, text: Any) -> "TextInput":
        self._prefix = text
        return self

    def suffix(self, text: Any) -> "TextInput":
        self._suffix = text
        return self

    def prefix_icon(self, icon: str) -> "TextInput":
        self._prefix_icon = icon
        return self

    def suffix_icon(self, icon: str) -> "TextInput":
        self._suffix_icon = icon
        return self

    def autocomplete(self, value: str | bool) -> "TextInput":
        self._autocomplete = "off" if value is False else str(value)
        return self

    def datalist(self, options: Any) -> "TextInput":
        self._datalist = options
        return self

    def mask(self, pattern: Any) -> "TextInput":
        """Format the value while typing. ``9`` is a digit, ``a`` a letter, ``*`` either;
        anything else is typed for the user: ``mask("99999-99999")``, ``mask("aa-99-aa-9999")``.
        A list of patterns picks the first that fits the length. A closure works too."""
        self._mask = pattern
        return self

    def money_mask(self, prefix: str = "", thousands: str = ",", decimal: str = ".", precision: int = 2,
                   indian: bool = False) -> "TextInput":
        """Group digits while typing (``1,23,456.00`` with ``indian=True``). The saved value has
        the separators and prefix removed and is a number."""
        self._mask = {"money": True, "prefix": prefix, "thousands": thousands, "decimal": decimal,
                      "precision": precision, "indian": indian}
        self._strip = [c for c in (prefix, thousands) if c]
        if decimal != ".":
            self._strip.append(decimal)  # swapped for "." in cast()
        self._money_decimal = decimal
        self._numeric = True
        return self

    def strip_characters(self, characters: Any) -> "TextInput":
        """Remove these characters before saving, e.g. the dashes a mask adds."""
        self._strip = [characters] if isinstance(characters, str) else list(characters)
        return self

    def same(self, other_field: str) -> "TextInput":
        """Value must equal another field (e.g. password confirmation)."""
        self._same = other_field
        return self

    def hydrate(self, form: "Form", record: Any) -> Any:
        if self._type == "password" and self._format_state is None:
            return ""
        return super().hydrate(form, record)

    def cast(self, state: Any) -> Any:
        if self._type == "password":
            return state if state not in (None, "") else None
        if self._strip and isinstance(state, str):
            decimal = getattr(self, "_money_decimal", ".")
            for ch in self._strip:
                state = state.replace(ch, "." if ch == decimal and decimal != "." else "")
        value = super().cast(state)
        if value is None or not self._numeric:
            return value
        try:
            if self._integer:
                return int(Decimal(str(value)))
            dec = Decimal(str(value))
            return int(dec) if dec == dec.to_integral() and "." not in str(value) else dec
        except (InvalidOperation, ValueError):
            raise ValueError("The :attribute must be a number.") from None

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        label = self.get_label(form, base).lower()
        errors = []
        if self._type == "email" and not EMAIL_RE.match(str(value)):
            errors.append(__("The :attribute must be a valid email address.", attribute=label))
        if self._type == "url" and not URL_RE.match(str(value)):
            errors.append(__("The :attribute must be a valid URL.", attribute=label))
        if not self._numeric:
            n = len(str(value))
            if self._min_length is not None and n < self._min_length:
                errors.append(__("The :attribute must be at least :min characters.", attribute=label, min=self._min_length))
            if self._max_length is not None and n > self._max_length:
                errors.append(__("The :attribute may not be greater than :max characters.", attribute=label, max=self._max_length))
        else:
            lo = evaluate(self._min_value, **form.ev(base))
            hi = evaluate(self._max_value, **form.ev(base))
            if lo is not None and value < Decimal(str(lo)):
                errors.append(__("The :attribute must be at least :min.", attribute=label, min=lo))
            if hi is not None and value > Decimal(str(hi)):
                errors.append(__("The :attribute may not be greater than :max.", attribute=label, max=hi))
        if self._regex and not re.search(self._regex[0], str(value)):
            errors.append(self._regex[1] or __("The :attribute format is invalid.", attribute=label))
        if self._same:
            other = form.ev(base)["get"](self._same)
            if other != value:
                errors.append(__("The :attribute confirmation does not match.", attribute=label))
        return errors

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        ev = form.ev(base)
        v.update({
            "type": self._type,
            "prefix": evaluate(self._prefix, **ev),
            "suffix": evaluate(self._suffix, **ev),
            "prefix_icon": self._prefix_icon,
            "suffix_icon": self._suffix_icon,
            "revealable": self._revealable,
            "input_attrs": attrs({
                "minlength": self._min_length,
                "maxlength": self._max_length,
                "min": evaluate(self._min_value, **ev),
                "max": evaluate(self._max_value, **ev),
                "step": self._step,
                "autocomplete": self._autocomplete,
                "inputmode": "decimal" if self._numeric and not self._integer else ("numeric" if self._integer else None),
            }),
            "datalist": normalize_options(evaluate(self._datalist, **ev)) if self._datalist else None,
        })
        mask = evaluate(self._mask, **ev)
        if mask is not None:
            import json

            v["type"] = "text" if v["type"] == "number" else v["type"]  # a masked number has separators
            v["mask"] = json.dumps(mask)
        return v


class Hidden(Field):
    template = "tungsten/forms/fields/hidden.html"


class Textarea(Field):
    template = "tungsten/forms/fields/textarea.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._rows = 3
        self._autosize = False
        self._min_length: int | None = None
        self._max_length: int | None = None

    def rows(self, n: int) -> "Textarea":
        self._rows = n
        return self

    def autosize(self, condition: bool = True) -> "Textarea":
        self._autosize = condition
        return self

    def min_length(self, n: int) -> "Textarea":
        self._min_length = n
        return self

    def max_length(self, n: int) -> "Textarea":
        self._max_length = n
        return self

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        label = self.get_label(form, base).lower()
        n = len(str(value))
        if self._min_length is not None and n < self._min_length:
            return [__("The :attribute must be at least :min characters.", attribute=label, min=self._min_length)]
        if self._max_length is not None and n > self._max_length:
            return [__("The :attribute may not be greater than :max characters.", attribute=label, max=self._max_length)]
        return []

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        v.update({"rows": self._rows, "autosize": self._autosize, "maxlength": self._max_length})
        return v


# ---------------------------------------------------------------------- options
def normalize_options(options: Any) -> list[tuple[Any, str]]:
    """Accept a dict, a list of values, a list of pairs or an Enum class."""
    if options is None:
        return []
    if isinstance(options, type) and issubclass(options, enum.Enum):
        out = []
        for member in options:
            label = getattr(member, "label", None)
            if callable(label):
                label = label()
            out.append((member.value, str(label or headline(member.name.lower()))))
        return out
    if isinstance(options, dict):
        return [(k, str(v)) for k, v in options.items()]
    out = []
    for item in options:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            out.append((item[0], str(item[1])))
        elif isinstance(item, enum.Enum):
            out.append((item.value, headline(item.name.lower())))
        else:
            out.append((item, str(item)))
    return out


class HasOptions(Field):
    """Shared logic for fields that pick from a list of options."""

    live_typed = False

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._options: Any = None
        self._relationship: dict | None = None
        self._multiple = False
        self._descriptions: Any = None
        self._disable_option: Callable | None = None

    def options(self, options: Any) -> "HasOptions":
        """A dict, list, Enum class, or closure (``lambda get: {...}``) for dependent options."""
        self._options = options
        return self

    def descriptions(self, descriptions: Any) -> "HasOptions":
        self._descriptions = descriptions
        return self

    def disable_option_when(self, fn: Callable) -> "HasOptions":
        self._disable_option = fn
        return self

    def relationship(
        self,
        name: str,
        title_attribute: str | None = None,
        modify_query: Callable | None = None,
        title: Callable | None = None,
    ) -> "HasOptions":
        """Load options from a SQLAlchemy relationship.

        ``Select("customer_id").relationship("customer", "name")`` for a many-to-one,
        or ``Select("tags").multiple().relationship("tags", "name")`` for many-to-many.
        """
        self._relationship = {"name": name, "title": title_attribute, "modify_query": modify_query, "title_fn": title}
        return self

    # ---- relationship helpers
    def _rel_info(self, form: "Form"):
        from sqlalchemy import inspect as sa_inspect

        model = getattr(self, "_owner_model", None) or form.get_model()
        if model is None:
            raise RuntimeError(f"Field {self.name!r} uses a relationship but the form has no model.")
        rel = sa_inspect(model).relationships[self._relationship["name"]]
        target = rel.mapper.class_
        pk = sa_inspect(target).primary_key[0]
        return rel, target, pk

    @property
    def _is_relation_many(self) -> bool:
        return bool(self._relationship) and self._relationship["name"] == self.name and self._multiple

    def _title_of(self, obj: Any) -> str:
        fn = self._relationship.get("title_fn")
        if fn:
            return str(call(fn, record=obj))
        attr = self._relationship.get("title")
        return str(getattr(obj, attr)) if attr else str(obj)

    def relationship_query(self, form: "Form", search: str | None = None, limit: int | None = None):
        from sqlalchemy import select

        rel, target, pk = self._rel_info(form)
        query = select(target)
        if form.ctx is not None:  # only the current tenant's records
            query = form.ctx.panel.tenancy.scope(form.ctx, target, query)
        attr = self._relationship.get("title")
        if attr:
            if search:
                query = query.where(getattr(target, attr).ilike(f"%{search}%"))
            query = query.order_by(getattr(target, attr))
        if self._relationship.get("modify_query"):
            query = call(self._relationship["modify_query"], **{**form.ev(), "query": query})
        if limit:
            query = query.limit(limit)
        return query

    def get_options(self, form: "Form", base: str = "") -> list[tuple[Any, str]]:
        if self._options is not None:
            return normalize_options(evaluate(self._options, **form.ev(base)))
        if self._relationship and form.ctx is not None:
            _, _, pk = self._rel_info(form)
            if getattr(self, "_searchable", False) and not getattr(self, "_preload", True):
                # only the selected options; the rest load while typing
                state = self.get_state(form, base)
                keys = state if isinstance(state, list) else ([state] if state not in (None, "") else [])
                if not keys:
                    return []
                from sqlalchemy import select

                _, target, pk = self._rel_info(form)
                query = form.ctx.panel.tenancy.scope(form.ctx, target, select(target).where(pk.in_(keys)))
                rows = form.ctx.db.scalars(query).all()
            else:
                rows = form.ctx.db.scalars(self.relationship_query(form)).all()
            return [(getattr(r, pk.key), self._title_of(r)) for r in rows]
        return []

    def search_options(self, form: "Form", search: str, limit: int = 50) -> list[tuple[Any, str]]:
        if self._relationship and form.ctx is not None:
            _, _, pk = self._rel_info(form)
            rows = form.ctx.db.scalars(self.relationship_query(form, search, limit)).all()
            return [(getattr(r, pk.key), self._title_of(r)) for r in rows]
        s = search.lower()
        return [o for o in self.get_options(form) if s in o[1].lower()][:limit]

    def _match_key(self, form: "Form", base: str, raw: Any) -> Any:
        """Find the original (typed) option key that matches a submitted string."""
        if self._relationship and self._options is None:
            _, _, pk = self._rel_info(form)
            try:
                py = pk.type.python_type
            except NotImplementedError:
                py = str
            try:
                return py(raw)
            except (TypeError, ValueError):
                return raw
        for key, _ in self.get_options(form, base):
            if str(key) == str(raw):
                if isinstance(self._options, type) and issubclass(self._options, enum.Enum):
                    return self._options(key)
                return key
        return raw

    # ---- state
    def to_state(self, value: Any) -> Any:
        if self._multiple:
            if value is None:
                return []
            return [str(v.value) if isinstance(v, enum.Enum) else str(v) for v in value]
        if isinstance(value, bool):
            return "1" if value else "0"
        return super().to_state(value)

    def blank_state(self) -> Any:
        return [] if self._multiple else ""

    def hydrate(self, form: "Form", record: Any) -> Any:
        if self._is_relation_many:
            _, _, pk = self._rel_info(form)
            return [str(getattr(o, pk.key)) for o in getattr(record, self.name) or []]
        return super().hydrate(form, record)

    def extract(self, formdata: Any, path: str) -> Any:
        if self._multiple:
            return [v for v in formdata.getlist(path) if v != ""]
        return super().extract(formdata, path)

    def cast(self, state: Any) -> Any:
        if self._multiple:
            return list(state or [])
        return super().cast(state)

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        super().process(form, base, data, errors)
        if self.name in data and self._dehydrate_state is None:
            value = data[self.name]
            if self._multiple:
                data[self.name] = [self._match_key(form, base, v) for v in value]
            elif value is not None:
                data[self.name] = self._match_key(form, base, value)

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        label = self.get_label(form, base).lower()
        if self._relationship and self._options is None and getattr(self, "_searchable", False):
            if form.ctx is not None and form.ctx.panel.tenancy.enabled:  # refuse another tenant's records
                from sqlalchemy import func, select

                _, target, pk = self._rel_info(form)
                keys = {self._match_key(form, base, v) for v in (value if self._multiple else [value])}
                query = select(func.count()).select_from(target).where(pk.in_(keys))
                if form.ctx.db.scalar(form.ctx.panel.tenancy.scope(form.ctx, target, query)) < len(keys):
                    return [__("The selected :attribute is invalid.", attribute=label)]
            return []
        allowed = {str(k) for k, _ in self.get_options(form, base)}
        values = value if self._multiple else [value]
        if any(str(v) not in allowed for v in values):
            return [__("The selected :attribute is invalid.", attribute=label)]
        return []

    def fill_record(self, form: "Form", record: Any, data: dict) -> None:
        if self._is_relation_many:
            return
        super().fill_record(form, record, data)

    def save_relationships(self, form: "Form", record: Any, data: dict) -> None:
        if self._is_relation_many and self.name in data:
            from sqlalchemy import select

            _, target, pk = self._rel_info(form)
            keys = data[self.name]
            query = form.ctx.panel.tenancy.scope(form.ctx, target, select(target).where(pk.in_(keys)))
            objs = form.ctx.db.scalars(query).all() if keys else []
            setattr(record, self.name, list(objs))
        super().save_relationships(form, record, data)

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        state = v["state"]
        selected = {str(s) for s in state} if isinstance(state, list) else {str(state)}
        ev = form.ev(base)
        descriptions = evaluate(self._descriptions, **ev) or {}
        options = []
        for key, label in self.get_options(form, base):
            disabled = bool(call(self._disable_option, **{**ev, "value": key, "label": label})) if self._disable_option else False
            options.append({
                "value": str(key),
                "label": maybe(label),
                "selected": str(key) in selected,
                "description": maybe(descriptions.get(key)) if isinstance(descriptions, dict) else None,
                "disabled": disabled,
            })
        v["options"] = options
        v["multiple"] = self._multiple
        return v


class Select(HasOptions):
    template = "tungsten/forms/fields/select.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._searchable = False
        self._native = True
        self._preload = True
        self._placeholder = "Select an option"

    def multiple(self, condition: bool = True) -> "Select":
        self._multiple = condition
        if condition:
            self._native = False
        return self

    def searchable(self, condition: bool = True) -> "Select":
        self._searchable = condition
        if condition:
            self._native = False
        return self

    def native(self, condition: bool = True) -> "Select":
        self._native = condition
        return self

    def preload(self, condition: bool = True) -> "Select":
        """With a searchable relationship: load all options up-front (default) or search on the server."""
        self._preload = condition
        return self

    def boolean(self, true_label: str = "Yes", false_label: str = "No") -> "Select":
        self._boolean = True
        self._options = {"1": true_label, "0": false_label}
        return self

    # ---- create / edit an option in a modal
    def create_option_form(self, schema: Any, columns: int = 1) -> "Select":
        """A "+" button that opens a form to add a new option, which is then selected::

            Select("customer_id").relationship("customer", "name")
                .create_option_form([TextInput("name").required(), TextInput("email").email()])

        With a relationship the new record is saved for you (in the current tenant);
        otherwise give :meth:`create_option_using`.
        """
        self._create_option_form = (schema, columns)
        return self

    def create_option_using(self, fn: Callable) -> "Select":
        """Save the new option yourself: ``fn(data, ...)`` returns its key."""
        self._create_option_using = fn
        return self

    def create_option_action(self, fn: Callable) -> "Select":
        """Change the "+" button: ``lambda action: action.label("New").modal_width("2xl")``."""
        self._create_option_modifier = fn
        return self

    def edit_option_form(self, schema: Any, columns: int = 1) -> "Select":
        """A pencil button that opens a form to change the selected option's record."""
        self._edit_option_form = (schema, columns)
        return self

    def update_option_using(self, fn: Callable) -> "Select":
        """Save the changes yourself: ``fn(record, data, ...)``."""
        self._update_option_using = fn
        return self

    def edit_option_action(self, fn: Callable) -> "Select":
        self._edit_option_modifier = fn
        return self

    def form_actions(self, form: "Form", base: str) -> list:
        actions = super().form_actions(form, base)
        return actions + self._option_actions()

    def _option_actions(self) -> list:
        cached = getattr(self, "_option_actions_cache", None)
        if cached is not None:
            return cached
        from ..actions.action import Action

        out = []
        create = getattr(self, "_create_option_form", None)
        if create is not None:
            action = (Action("create_option").label(__("Create")).icon("plus").color("gray")
                      .form(create[0], create[1]).modal_heading(lambda: __("Create :label", label=self.get_label().lower()))
                      .modal_submit_label(__("Create"))
                      .authorize(lambda form, ctx: self._can_option(form, ctx, "create"))
                      .action(self._create_option))
            action._modal_model_fn = self._option_model
            modifier = getattr(self, "_create_option_modifier", None)
            out.append(modifier(action) or action if modifier else action)
        edit = getattr(self, "_edit_option_form", None)
        if edit is not None:
            action = (Action("edit_option").label(__("Edit")).icon("pencil").color("gray")
                      .form(edit[0], edit[1]).modal_heading(lambda: __("Edit :label", label=self.get_label().lower()))
                      .modal_submit_label(__("Save changes"))
                      .visible(lambda state: not self._multiple and state not in (None, "", []))
                      .authorize(lambda form, ctx, state: self._can_option(form, ctx, "update", state))
                      .action(self._update_option))
            action._modal_model_fn = self._option_model
            action._prepare_modal = self._prepare_edit_modal
            modifier = getattr(self, "_edit_option_modifier", None)
            out.append(modifier(action) or action if modifier else action)
        self._suffix_actions = [a for a in self._suffix_actions if a.name not in ("create_option", "edit_option")] + out
        self._option_actions_cache = out
        return out

    def _option_model(self, form: "Form") -> Any:
        if self._relationship and (getattr(self, "_owner_model", None) or form.get_model()) is not None:
            return self._rel_info(form)[1]
        return None

    def _can_option(self, form: "Form", ctx: Any, ability: str, state: Any = None) -> bool:
        target = self._option_model(form)
        if ctx is None or target is None:
            return True
        resource = ctx.panel.resource_for_model(target)
        if resource is None:
            return True
        record = self._selected_record(form, ctx, state) if ability == "update" else None
        return resource.can(ctx, ability, record)

    def _selected_record(self, form: "Form", ctx: Any, state: Any) -> Any:
        if ctx is None or not self._relationship or state in (None, "", []) or isinstance(state, list):
            return None
        from sqlalchemy import select

        _, target, pk = self._rel_info(form)
        key = self._match_key(form, "", state)
        query = ctx.panel.tenancy.scope(ctx, target, select(target).where(pk == key))
        return ctx.db.scalars(query).first()

    def _prepare_edit_modal(self, form: "Form", field: Any, base: str) -> None:
        action = next(a for a in self._option_actions() if a.name == "edit_option")
        record = self._selected_record(form, form.ctx, self.get_state(form, base))
        action._modal_operation = "edit" if record is not None else "create"
        action._modal_record = record

    def _create_option(self, data: dict, form: "Form", set: Callable, state: Any, ctx: Any) -> Any:
        fn = getattr(self, "_create_option_using", None)
        if fn is not None:
            key = call(fn, **{**form.ev(), "data": data})
        else:
            if not self._relationship or ctx is None:
                raise RuntimeError(f"Select {self.name!r}: give create_option_using() or a relationship().")
            _, target, pk = self._rel_info(form)
            record = target()
            for k, v in data.items():
                setattr(record, k, v)
            ctx.panel.tenancy.assign(ctx, target, record)
            ctx.db.add(record)
            ctx.db.flush()
            key = getattr(record, pk.key)
        if key is None:
            return False
        if self._multiple:
            set(self.name, [*(state or []), str(key)])
        else:
            set(self.name, str(key))
        return None

    def _update_option(self, data: dict, form: "Form", ctx: Any, get: Callable) -> Any:
        action = next(a for a in self._option_actions() if a.name == "edit_option")
        record = getattr(action, "_modal_record", None)
        if record is None:
            return False
        fn = getattr(self, "_update_option_using", None)
        if fn is not None:
            call(fn, **{**form.ev(), "record": record, "data": data})
        else:
            for k, v in data.items():
                setattr(record, k, v)
            if ctx is not None:
                ctx.db.flush()
        return None

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        super().process(form, base, data, errors)
        if getattr(self, "_boolean", False) and data.get(self.name) is not None:
            data[self.name] = str(data[self.name]) == "1"

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        self._option_actions()  # adds the create/edit buttons to the suffix actions
        v = super().view_data(form, base)
        v["native"] = self._native
        v["searchable"] = self._searchable
        remote = bool(self._relationship and self._options is None and self._searchable and not self._preload)
        v["search_url"] = form.ctx.panel.url("_tw", "form", "options") if remote and form.ctx else None
        return v


class CheckboxList(HasOptions):
    template = "tungsten/forms/fields/checkbox-list.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._multiple = True
        self._columns = 1
        self._bulk_toggleable = False
        self._grouped: Callable | None = None

    def columns(self, n: int) -> "CheckboxList":
        self._columns = n
        return self

    def bulk_toggleable(self, condition: bool = True) -> "CheckboxList":
        self._bulk_toggleable = condition
        return self

    def grouped(self, fn: Callable) -> "CheckboxList":
        """Show the options under group headings. ``fn`` gets ``value`` and ``label``
        and returns the group name. Options given as ``{"Group": {value: label}}``
        are grouped without this."""
        self._grouped = fn
        return self

    def get_option_groups(self, form: "Form", base: str = "") -> list[tuple[str | None, list[tuple[Any, str]]]] | None:
        """The options as ``[(group, [(value, label), ...]), ...]``, or ``None`` when not grouped."""
        raw = evaluate(self._options, **form.ev(base)) if self._options is not None else None
        if isinstance(raw, dict) and any(isinstance(o, dict) for o in raw.values()):
            groups: list[tuple[str | None, list[tuple[Any, str]]]] = []
            for key, value in raw.items():
                if isinstance(value, dict):
                    groups.append((str(key), normalize_options(value)))
                elif groups and groups[-1][0] is None:
                    groups[-1][1].append((key, str(value)))
                else:  # a plain option between groups
                    groups.append((None, [(key, str(value))]))
            return groups
        if self._grouped is not None:
            by_group: dict[Any, list[tuple[Any, str]]] = {}
            for key, label in super().get_options(form, base):
                group = call(self._grouped, **{**form.ev(base), "value": key, "label": label})
                by_group.setdefault(group, []).append((key, label))
            return [(None if g in (None, "") else str(g), opts) for g, opts in by_group.items()]
        return None

    def get_options(self, form: "Form", base: str = "") -> list[tuple[Any, str]]:
        groups = self.get_option_groups(form, base)
        if groups is None:
            return super().get_options(form, base)
        return [option for _, options in groups for option in options]

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        from .base import GRID_COLUMNS

        v = super().view_data(form, base)
        v["grid"] = GRID_COLUMNS.get(self._columns, "grid-cols-1")
        v["bulk"] = self._bulk_toggleable
        groups = self.get_option_groups(form, base)
        if groups is not None:
            # v["options"] holds the same options in the same order: cut it into groups
            options, v["groups"] = iter(v["options"]), []
            for label, items in groups:
                v["groups"].append({"label": maybe(label) if label else None,
                                    "options": [next(options) for _ in items]})
        return v


class Radio(HasOptions):
    template = "tungsten/forms/fields/radio.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._inline = False
        self._boolean = False

    def inline(self, condition: bool = True) -> "Radio":
        self._inline = condition
        return self

    def boolean(self, true_label: str = "Yes", false_label: str = "No") -> "Radio":
        self._boolean = True
        self._options = {"1": true_label, "0": false_label}
        return self

    def cast(self, state: Any) -> Any:
        value = super().cast(state)
        if self._boolean and value is not None:
            return value == "1"
        return value

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        if self._boolean:
            Field.process(self, form, base, data, errors)
        else:
            super().process(form, base, data, errors)

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        if self._boolean:
            return []
        return super().validate_value(form, base, value)

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        v["inline"] = self._inline
        return v


class ToggleButtons(HasOptions):
    """Options shown as a row of buttons (one or many can be picked)::

        ToggleButtons("status").options({"draft": "Draft", "published": "Published"})
            .icons({"draft": "pencil", "published": "circle-check"})
            .colors({"draft": "warning", "published": "success"})
    """

    template = "tungsten/forms/fields/toggle-buttons.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._icons: Any = None
        self._colors: Any = None
        self._grouped = True
        self._boolean = False

    def icons(self, icons: Any) -> "ToggleButtons":
        self._icons = icons
        return self

    def colors(self, colors: Any) -> "ToggleButtons":
        self._colors = colors
        return self

    def multiple(self, condition: bool = True) -> "ToggleButtons":
        self._multiple = condition
        return self

    def grouped(self, condition: bool = True) -> "ToggleButtons":
        """Join the buttons into one bar (default) or space them apart."""
        self._grouped = condition
        return self

    def boolean(self, true_label: str = "Yes", false_label: str = "No") -> "ToggleButtons":
        self._boolean = True
        self._options = {"1": true_label, "0": false_label}
        self._icons = self._icons or {"1": "check", "0": "x"}
        self._colors = self._colors or {"1": "success", "0": "danger"}
        return self

    def to_state(self, value: Any) -> Any:
        if self._boolean and isinstance(value, bool):
            return "1" if value else "0"
        return super().to_state(value)

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        super().process(form, base, data, errors)
        if self._boolean and data.get(self.name) is not None:
            data[self.name] = str(data[self.name]) == "1"

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        ev = form.ev(base)
        icons = evaluate(self._icons, **ev) or {}
        colors_ = evaluate(self._colors, **ev) or {}
        for o in v["options"]:
            key = next((k for k in list(icons) + list(colors_) if str(k) == o["value"]), o["value"])
            o["icon"] = icons.get(key) if isinstance(icons, dict) else None
            o["color"] = (colors_.get(key) if isinstance(colors_, dict) else None) or "primary"
        v["grouped"] = self._grouped
        return v


# ---------------------------------------------------------------------- booleans
class Checkbox(Field):
    template = "tungsten/forms/fields/checkbox.html"
    live_typed = False

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._inline_label = True

    def blank_state(self) -> Any:
        return False

    def to_state(self, value: Any) -> Any:
        return bool(value)

    def extract(self, formdata: Any, path: str) -> Any:
        return formdata.get(path) in ("1", "on", "true", "yes")

    def cast(self, state: Any) -> Any:
        return bool(state)

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        if not self.is_field_visible(form, base):
            return
        value = bool(get_path(form.state, self.path(base)))
        if self.is_required(form, base) and not value:
            label = self.get_label(form, base).lower()
            errors.setdefault(self.path(base), []).append(__("The :attribute must be accepted.", attribute=label))
            return
        msgs = self.run_rules(form, base, value)
        if msgs:
            errors.setdefault(self.path(base), []).extend(msgs)
            return
        if self.is_disabled(form, base) or not self.is_dehydrated(form, base):
            return
        if self._dehydrate_state is not None:
            value = call(self._dehydrate_state, **{**form.ev(base), "state": value})
        data[self.name] = value


class Toggle(Checkbox):
    template = "tungsten/forms/fields/toggle.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._on_color = "primary"
        self._off_color = "gray"
        self._on_icon: str | None = None
        self._off_icon: str | None = None
        self._on_label: Any = None
        self._off_label: Any = None

    def on_color(self, color: str) -> "Toggle":
        self._on_color = color
        return self

    def off_color(self, color: str) -> "Toggle":
        self._off_color = color
        return self

    def on_icon(self, icon: str) -> "Toggle":
        self._on_icon = icon
        return self

    def off_icon(self, icon: str) -> "Toggle":
        self._off_icon = icon
        return self

    def state_labels(self, on: Any, off: Any) -> "Toggle":
        """Text shown next to the switch, e.g. ``("Active", "Inactive")``."""
        self._on_label = on
        self._off_label = off
        return self

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        v.update(on_color=self._on_color, off_color=self._off_color, on_label=self._on_label,
                 off_label=self._off_label, on_icon=self._on_icon, off_icon=self._off_icon)
        return v


# ---------------------------------------------------------------------- dates
class DatePicker(Field):
    template = "tungsten/forms/fields/date-picker.html"
    input_type = "date"

    #: the timezone naive datetimes are stored in (like Laravel's ``app.timezone``)
    storage_timezone = "UTC"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._min_date: Any = None
        self._max_date: Any = None
        self._seconds = False
        self._timezone: Any = None
        self._show_timezone = True

    def min_date(self, value: Any) -> "DatePicker":
        self._min_date = value
        return self

    def max_date(self, value: Any) -> "DatePicker":
        self._max_date = value
        return self

    def timezone(self, tz: Any, show: bool = True) -> "DatePicker":
        """Show and type times in ``tz`` (e.g. ``"Asia/Kolkata"`` or ``lambda user: user.timezone``)
        and save them in :attr:`storage_timezone` (UTC by default)."""
        self._timezone = tz
        self._show_timezone = show
        return self

    def get_timezone(self, form: "Form", base: str = ""):
        """The ``ZoneInfo`` values are shown in, or None when no timezone is set."""
        tz = evaluate(self._timezone, **form.ev(base))
        if not tz or self.input_type == "date":
            return None
        from zoneinfo import ZoneInfo

        return tz if isinstance(tz, dt.tzinfo) else ZoneInfo(str(tz))

    def _storage_tz(self):
        from zoneinfo import ZoneInfo

        return ZoneInfo(self.storage_timezone)

    def to_display(self, value: Any, tz: Any) -> Any:
        """A stored datetime in the display timezone (naive, ready for the input)."""
        if tz is None or not isinstance(value, dt.datetime):
            return value
        aware = value if value.tzinfo else value.replace(tzinfo=self._storage_tz())
        return aware.astimezone(tz).replace(tzinfo=None)

    def to_storage(self, value: Any, tz: Any) -> Any:
        """A typed datetime (display timezone) in the storage timezone, naive."""
        if tz is None or not isinstance(value, dt.datetime):
            return value
        return value.replace(tzinfo=tz).astimezone(self._storage_tz()).replace(tzinfo=None)

    def hydrate(self, form: "Form", record: Any) -> Any:
        tz = self.get_timezone(form)
        if tz is not None and self._format_state is None:
            return self.to_state(self.to_display(getattr(record, self.name, None), tz))
        return super().hydrate(form, record)

    def default_state(self, form: "Form", base: str) -> Any:
        tz = self.get_timezone(form, base)
        if tz is not None:
            value = evaluate(self._default, **form.ev(base))
            if isinstance(value, dt.datetime):
                return self.to_state(self.to_display(value, tz))
        return super().default_state(form, base)

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        super().process(form, base, data, errors)
        tz = self.get_timezone(form, base)
        if tz is not None and self.name in data and self._dehydrate_state is None:
            data[self.name] = self.to_storage(data[self.name], tz)

    def to_state(self, value: Any) -> Any:
        if isinstance(value, dt.datetime):
            return value.date().isoformat() if self.input_type == "date" else value.strftime(self._fmt())
        if isinstance(value, (dt.date, dt.time)):
            return value.isoformat() if not isinstance(value, dt.time) else value.strftime(self._fmt())
        return super().to_state(value)

    def _fmt(self) -> str:
        if self.input_type == "datetime-local":
            return "%Y-%m-%dT%H:%M:%S" if self._seconds else "%Y-%m-%dT%H:%M"
        if self.input_type == "time":
            return "%H:%M:%S" if self._seconds else "%H:%M"
        return "%Y-%m-%d"

    def parse(self, value: str) -> Any:
        return dt.date.fromisoformat(value[:10])

    def cast(self, state: Any) -> Any:
        value = super().cast(state)
        if value is None or not isinstance(value, str):
            return value
        try:
            return self.parse(value)
        except ValueError:
            raise ValueError("The :attribute is not a valid date.") from None

    def _bound(self, form: "Form", base: str, bound: Any, upper: bool = False) -> Any:
        value = evaluate(bound, **form.ev(base))
        if value is None or value == "":
            return None  # e.g. a closure reading an empty field: no limit
        if isinstance(value, str):
            value = self.parse(value)
        return self.coerce_bound(value, upper)

    def coerce_bound(self, value: Any, upper: bool) -> Any:
        """Make a min/max value comparable with this field's values."""
        if isinstance(value, dt.datetime):
            return value.date()
        return value

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        label = self.get_label(form, base).lower()
        lo = self._bound(form, base, self._min_date)
        hi = self._bound(form, base, self._max_date, upper=True)
        if lo is not None and value < lo:
            return [__("The :attribute must be a date after or equal to :date.", attribute=label, date=self.to_state(lo))]
        if hi is not None and value > hi:
            return [__("The :attribute must be a date before or equal to :date.", attribute=label, date=self.to_state(hi))]
        return []

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        lo = self._bound(form, base, self._min_date)
        hi = self._bound(form, base, self._max_date, upper=True)
        v.update(input_type=self.input_type, min=self.to_state(lo) if lo else None,
                 max=self.to_state(hi) if hi else None, step=1 if self._seconds else None)
        tz = self.get_timezone(form, base)
        v["timezone"] = str(tz) if tz is not None and self._show_timezone else None
        return v


class DateTimePicker(DatePicker):
    input_type = "datetime-local"

    def seconds(self, condition: bool = True) -> "DateTimePicker":
        self._seconds = condition
        return self

    def parse(self, value: str) -> Any:
        if len(value) == 10:  # a plain date such as "2024-01-31"
            return dt.date.fromisoformat(value)
        return dt.datetime.fromisoformat(value)

    def cast(self, state: Any) -> Any:
        value = super().cast(state)
        if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
            value = dt.datetime.combine(value, dt.time.min)
        return value

    def coerce_bound(self, value: Any, upper: bool) -> Any:
        # a plain date as min means the start of that day, as max the end of it
        if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
            return dt.datetime.combine(value, dt.time.max if upper else dt.time.min)
        return value


class TimePicker(DatePicker):
    input_type = "time"

    def seconds(self, condition: bool = True) -> "TimePicker":
        self._seconds = condition
        return self

    def parse(self, value: str) -> Any:
        return dt.time.fromisoformat(value)


# ---------------------------------------------------------------------- misc inputs
class ColorPicker(Field):
    template = "tungsten/forms/fields/color-picker.html"

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        if not HEX_RE.match(str(value)):
            return [__("The :attribute must be a valid hex color.", attribute=self.get_label(form, base).lower())]
        return []


class Slider(Field):
    """Pick a number by dragging: ``Slider("discount").range(0, 50).step(5).suffix("%")``.

    ``.dual()`` shows two handles; the value is then a ``[low, high]`` list.
    """

    template = "tungsten/forms/fields/slider.html"
    live_typed = False

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._min: Any = 0
        self._max: Any = 100
        self._step: Any = 1
        self._dual = False
        self._pips: Any = None
        self._prefix: Any = None
        self._suffix: Any = None
        self._decimal_places: int | None = None
        self._show_value = True

    def range(self, minimum: Any, maximum: Any) -> "Slider":
        self._min, self._max = minimum, maximum
        return self

    def min_value(self, n: Any) -> "Slider":
        self._min = n
        return self

    def max_value(self, n: Any) -> "Slider":
        self._max = n
        return self

    def step(self, n: Any) -> "Slider":
        self._step = n
        return self

    def dual(self, condition: bool = True) -> "Slider":
        """Two handles: pick a range. The state is ``[low, high]``."""
        self._dual = condition
        return self

    def pips(self, every: Any = None) -> "Slider":
        """Marks under the track, every ``every`` units (default: 4 equal parts)."""
        self._pips = every if every is not None else True
        return self

    def prefix(self, text: Any) -> "Slider":
        self._prefix = text
        return self

    def suffix(self, text: Any) -> "Slider":
        self._suffix = text
        return self

    def decimal_places(self, n: int) -> "Slider":
        self._decimal_places = n
        return self

    def show_value(self, condition: bool = True) -> "Slider":
        self._show_value = condition
        return self

    def _bounds(self, form: "Form", base: str) -> tuple[Decimal, Decimal, Decimal]:
        ev = form.ev(base)
        lo, hi, step = (Decimal(str(evaluate(x, **ev))) for x in (self._min, self._max, self._step))
        return lo, hi, step

    def _number(self, raw: Any) -> Any:
        if raw is None or raw == "":
            return None
        try:
            dec = Decimal(str(raw).strip())
        except InvalidOperation:
            raise ValueError("The :attribute must be a number.") from None
        if not dec.is_finite():
            raise ValueError("The :attribute must be a number.")
        if self._decimal_places is not None:
            dec = round(dec, self._decimal_places)
        return int(dec) if dec == dec.to_integral() and self._decimal_places is None else dec

    def blank_state(self) -> Any:
        return [] if self._dual else ""

    def default_state(self, form: "Form", base: str) -> Any:
        value = evaluate(self._default, **form.ev(base))
        if value is None:  # start at the low end (or the whole range) like a browser slider
            lo, hi, _ = self._bounds(form, base)
            value = [lo, hi] if self._dual else lo
        return self.to_state(value)

    def to_state(self, value: Any) -> Any:
        if self._dual:
            return [super(Slider, self).to_state(v) for v in (value or [])]
        return super().to_state(value)

    def extract(self, formdata: Any, path: str) -> Any:
        if self._dual:
            return [v for v in formdata.getlist(path)]
        return super().extract(formdata, path)

    def cast(self, state: Any) -> Any:
        if self._dual:
            values = [self._number(v) for v in (state or [])]
            if not values or all(v is None for v in values):
                return None
            if len(values) != 2 or None in values:
                raise ValueError("The :attribute must be a range.")
            return sorted(values)
        return self._number(state)

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        label = self.get_label(form, base).lower()
        lo, hi, step = self._bounds(form, base)
        for v in value if self._dual else [value]:
            if Decimal(str(v)) < lo:
                return [__("The :attribute must be at least :min.", attribute=label, min=lo)]
            if Decimal(str(v)) > hi:
                return [__("The :attribute may not be greater than :max.", attribute=label, max=hi)]
            if step > 0 and (Decimal(str(v)) - lo) % step != 0:
                return [__("The :attribute is invalid.", attribute=label)]
        return []

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        ev = form.ev(base)
        lo, hi, step = self._bounds(form, base)
        state = v["state"]
        if self._dual:
            values = list(state) if isinstance(state, list) and len(state) == 2 else [str(lo), str(hi)]
        else:
            values = [state if state not in (None, "") else str(lo)]
        pips = []
        if self._pips:
            every = Decimal(str(self._pips)) if self._pips is not True else (hi - lo) / 4
            if every > 0 and (hi - lo) / every <= 50:
                n = lo
                while n <= hi:
                    pct = float((n - lo) / (hi - lo) * 100) if hi != lo else 0
                    pips.append({"value": format(n.normalize(), "f"), "pct": round(pct, 3)})
                    n += every
        v.update(min=format(lo, "f"), max=format(hi, "f"), step=format(step, "f"), dual=self._dual, values=values,
                 pips=pips, prefix=evaluate(self._prefix, **ev), suffix=evaluate(self._suffix, **ev),
                 show_value=self._show_value)
        return v


class TagsInput(Field):
    template = "tungsten/forms/fields/tags-input.html"
    live_typed = False  # a hidden input gets "change" when a tag is added or removed

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._separator: str | None = None
        self._suggestions: Any = None
        self._placeholder = "New tag"
        self._color = "primary"

    def separator(self, sep: str = ",") -> "TagsInput":
        """Store tags as one string joined by ``sep`` instead of a JSON list."""
        self._separator = sep
        return self

    def suggestions(self, values: Any) -> "TagsInput":
        self._suggestions = values
        return self

    def color(self, color: str) -> "TagsInput":
        self._color = color
        return self

    def blank_state(self) -> Any:
        return []

    def to_state(self, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [t.strip() for t in value.split(self._separator or ",") if t.strip()]
        return [str(v) for v in value]

    def extract(self, formdata: Any, path: str) -> Any:
        return [v.strip() for v in formdata.getlist(path) if v.strip()]

    def cast(self, state: Any) -> Any:
        tags = list(dict.fromkeys(state or []))
        if not tags:
            return None if self._separator else []
        return self._separator.join(tags) if self._separator else tags

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        v["suggestions"] = [str(s) for s in (evaluate(self._suggestions, **form.ev(base)) or [])]
        v["color"] = self._color
        return v


class FileUpload(Field):
    """Upload files. Files are stored right away (to the panel storage) and the
    field state holds the stored path(s)."""

    template = "tungsten/forms/fields/file-upload.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._directory: str = ""
        self._multiple = False
        self._image = False
        self._accepted: list[str] | None = None
        self._max_size: int | None = None  # kilobytes
        self._max_files: int | None = None
        self._avatar = False

    def directory(self, path: str) -> "FileUpload":
        self._directory = path
        return self

    def multiple(self, condition: bool = True) -> "FileUpload":
        self._multiple = condition
        return self

    def image(self) -> "FileUpload":
        self._image = True
        if self._accepted is None:
            self._accepted = ["image/*"]
        return self

    def avatar(self) -> "FileUpload":
        self._avatar = True
        return self.image()

    def accepted_file_types(self, types: list[str]) -> "FileUpload":
        self._accepted = types
        return self

    def max_size(self, kilobytes: int) -> "FileUpload":
        self._max_size = kilobytes
        return self

    def max_files(self, n: int) -> "FileUpload":
        self._max_files = n
        return self

    def blank_state(self) -> Any:
        return [] if self._multiple else ""

    def to_state(self, value: Any) -> Any:
        if self._multiple:
            return list(value or [])
        return value or ""

    def extract(self, formdata: Any, path: str) -> Any:
        if self._multiple:
            return [v for v in formdata.getlist(path) if isinstance(v, str) and v]
        value = formdata.get(path)
        return value if isinstance(value, str) else ""

    def cast(self, state: Any) -> Any:
        if self._multiple:
            return list(state or [])
        return state or None

    def check_upload(self, filename: str, content_type: str, size: int) -> str | None:
        if self._max_size is not None and size > self._max_size * 1024:
            return __("The file may not be greater than :max kilobytes.", max=self._max_size)
        if self._accepted:
            ok = False
            for t in self._accepted:
                if t.endswith("/*") and content_type.startswith(t[:-1]):
                    ok = True
                elif t.startswith(".") and filename.lower().endswith(t.lower()):
                    ok = True
                elif t == content_type:
                    ok = True
            if not ok:
                return __("The file type is not allowed.")
        return None

    def accept_upload(self, form: "Form", path: str, stored: str) -> None:
        if self._multiple:
            current = list(get_path(form.state, path) or [])
            if self._max_files and len(current) >= self._max_files:
                form.add_error(path, __("You may not upload more than :max files.", max=self._max_files))
                return
            current.append(stored)
            set_path(form.state, path, current)
        else:
            set_path(form.state, path, stored)

    def handle_ui_action(self, form: "Form", path: str, base: str, kind: str, arg: str) -> None:
        if kind == "pick":  # an already stored file, e.g. from a media library (see Panel.on_file_pick)
            if self.is_disabled(form, base) or not arg:
                return
            ctx = form.ctx
            if ctx is None or not ctx.panel.can_pick_file(ctx, arg, self):
                form.add_error(path, __("This file can't be used here."))
                return
            content_type = mimetypes.guess_type(arg)[0] or ""
            error = self.check_upload(arg, content_type, 0)
            if error:
                form.add_error(path, error)
                return
            if self._multiple and arg in (get_path(form.state, path) or []):
                return
            self.accept_upload(form, path, arg)
            self.call_after_state_updated(form, path, base)
            return
        if kind == "remove":
            if self._multiple:
                current = list(get_path(form.state, path) or [])
                if arg.isdigit() and int(arg) < len(current):
                    current.pop(int(arg))
                set_path(form.state, path, current)
            else:
                set_path(form.state, path, "")

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        state = v["state"]
        files = state if isinstance(state, list) else ([state] if state else [])
        storage = form.ctx.panel.storage if form.ctx else None
        names = form.ctx.panel.file_names(form.ctx, files) if form.ctx and form.ctx.panel.file_name_lookups else {}
        v["files"] = [
            {"path": f, "url": storage.url(f) if storage else f, "name": names.get(f) or str(f).rsplit("/", 1)[-1]}
            for f in files
        ]
        v.update(multiple=self._multiple, image=self._image, avatar=self._avatar,
                 accept=",".join(self._accepted or []), max_size=self._max_size)
        return v


class Placeholder(Field):
    """Read-only text inside a form (not saved). ``Placeholder("created").content(fn)``."""

    template = "tungsten/forms/fields/placeholder.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._content: Any = None
        self._dehydrated = False

    def content(self, content: Any) -> "Placeholder":
        self._content = content
        return self

    def hydrate(self, form: "Form", record: Any) -> Any:
        return None

    def load_state(self, form: "Form", formdata: Any, base: str) -> None:
        return None

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        return None

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        content = evaluate(self._content, **form.ev(base))
        v["content"] = content if content not in (None, "") else "—"
        return v


# ---------------------------------------------------------------------- nested
class Repeater(Field):
    """A list of rows, each with its own schema. Saved as a JSON list, or as
    related records with ``.relationship("items")``."""

    template = "tungsten/forms/fields/repeater.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._schema: list[Component] = []
        self._columns = 1
        self._default_items = 1
        self._min_items: int | None = None
        self._max_items: int | None = None
        self._add_label: Any = None
        self._reorderable = True
        self._addable: Any = True
        self._deletable: Any = True
        self._collapsible = False
        self._item_label: Callable | None = None
        self._rel: str | None = None
        self._order_column: str | None = None
        self._table = False

    def schema(self, components: list) -> "Repeater":
        self._schema = list(components)
        return self

    def child_components(self) -> list[Component]:
        return []  # rows are walked through state, not statically

    def columns(self, n: int) -> "Repeater":
        self._columns = n
        return self

    def default_items(self, n: int) -> "Repeater":
        self._default_items = n
        return self

    def min_items(self, n: int) -> "Repeater":
        self._min_items = n
        return self

    def max_items(self, n: int) -> "Repeater":
        self._max_items = n
        return self

    def add_action_label(self, label: Any) -> "Repeater":
        self._add_label = label
        return self

    def reorderable(self, condition: bool = True) -> "Repeater":
        self._reorderable = condition
        return self

    def addable(self, condition: Any = True) -> "Repeater":
        self._addable = condition
        return self

    def deletable(self, condition: Any = True) -> "Repeater":
        self._deletable = condition
        return self

    def collapsible(self, condition: bool = True) -> "Repeater":
        self._collapsible = condition
        return self

    def item_label(self, fn: Callable) -> "Repeater":
        self._item_label = fn
        return self

    def table(self, condition: bool = True) -> "Repeater":
        """Show rows as a compact table (one line per row)."""
        self._table = condition
        return self

    def relationship(self, name: str | None = None, order_column: str | None = None) -> "Repeater":
        self._rel = name or self.name
        self._order_column = order_column
        return self

    orderable = reorderable

    # ---- helpers
    def _prepare(self, form: "Form") -> None:
        """Tell row fields which model they belong to (for relationship options)."""
        if not self._rel or getattr(self, "_prepared", False):
            return
        from sqlalchemy import inspect as sa_inspect

        model = getattr(self, "_owner_model", None) or form.get_model()
        if model is None:
            return
        target = sa_inspect(model).relationships[self._rel].mapper.class_

        def assign(components):
            for c in components:
                c._owner_model = target
                children = getattr(c, "child_components", None)
                if children:
                    assign(children())
                if isinstance(c, Repeater):
                    assign(c._schema)

        assign(self._schema)
        self._prepared = True

    def _row_fields(self):
        from .layout import Layout

        def flatten(components):
            for c in components:
                if isinstance(c, Layout):
                    yield from flatten(c.child_components())
                else:
                    yield c

        return list(flatten(self._schema))

    # ---- hooks (overridden by Builder)
    def _schema_for(self, row: Any) -> list[Component]:
        """The schema used for one row."""
        return self._schema

    def _split_value(self, row: Any) -> tuple[dict, dict]:
        """A stored row -> (row meta such as ``__type``, field data)."""
        return {}, (row if isinstance(row, dict) else {})

    def _join_value(self, row_state: dict, row_data: dict) -> Any:
        """Clean row data -> the value stored for that row."""
        return row_data

    def _blank_row(self, form: "Form", path: str, index: int, block: str | None = None) -> dict:
        row: dict[str, Any] = {"__type": block} if block else {}
        set_path(form.state, join(path, index), row)
        for comp in self._schema_for(row):
            comp.fill_state(form, join(path, index), None)
        return get_path(form.state, join(path, index))

    def default_state(self, form: "Form", base: str) -> Any:
        value = evaluate(self._default, **form.ev(base))
        if value is not None:
            return self.to_state(value)
        path = self.path(base)
        set_path(form.state, path, [])
        for i in range(self._default_items):
            self._blank_row(form, path, i)
        return get_path(form.state, path)

    def to_state(self, value: Any) -> Any:
        return [dict(r) for r in (value or [])]

    def blank_state(self) -> Any:
        return []

    def hydrate(self, form: "Form", record: Any) -> Any:
        return None  # handled in fill_state

    def fill_state(self, form: "Form", base: str, record: Any) -> None:
        self._prepare(form)
        path = self.path(base)
        if record is None:
            set_path(form.state, path, self.default_state(form, base))
            return
        set_path(form.state, path, [])
        if self._rel:
            from sqlalchemy import inspect as sa_inspect

            items = list(getattr(record, self._rel) or [])
            if self._order_column:
                items.sort(key=lambda o: getattr(o, self._order_column) or 0)
            for i, item in enumerate(items):
                row_base = join(path, i)
                set_path(form.state, row_base, {})
                for comp in self._schema:
                    comp.fill_state(form, row_base, item)
                pk = sa_inspect(type(item)).primary_key[0]
                set_path(form.state, join(row_base, "__key"), str(getattr(item, pk.key)))
        else:
            rows = getattr(record, self.name, None) or []
            for i, row in enumerate(rows):
                row_base = join(path, i)
                meta, data = self._split_value(row)
                set_path(form.state, row_base, dict(meta))
                obj = DataRecord(data)
                for comp in self._schema_for(meta):
                    comp.fill_state(form, row_base, obj)

    def load_state(self, form: "Form", formdata: Any, base: str) -> None:
        self._prepare(form)
        path = self.path(base)
        prefix = path + "."
        indexes = set()
        for key in formdata.keys():
            if key.startswith(prefix):
                head = key[len(prefix):].split(".", 1)[0]
                if head.isdigit():
                    indexes.add(int(head))
        set_path(form.state, path, [])
        for new_i, old_i in enumerate(sorted(indexes)):
            row_base = join(path, new_i)
            row_type = formdata.get(join(path, old_i, "__type"))
            set_path(form.state, row_base, {"__type": row_type} if row_type else {})
            src = _ReindexedForm(formdata, join(path, old_i), row_base) if old_i != new_i else formdata
            for comp in self._schema_for(get_path(form.state, row_base)):
                comp.load_state(form, src, row_base)
            key = formdata.get(join(path, old_i, "__key"))
            if key:
                set_path(form.state, join(row_base, "__key"), key)

    def rows(self, form: "Form", base: str) -> list[dict]:
        return get_path(form.state, self.path(base)) or []

    def walk(self, form: "Form", base: str) -> Iterator[tuple["Field", str, str]]:
        self._prepare(form)
        yield self, self.path(base), base
        for i, row in enumerate(self.rows(form, base)):
            for comp in self._schema_for(row):
                yield from comp.walk(form, join(self.path(base), i))

    def process(self, form: "Form", base: str, data: dict, errors: dict) -> None:
        if not self.is_field_visible(form, base):
            return
        path = self.path(base)
        rows = self.rows(form, base)
        label = self.get_label(form, base).lower()
        out = []
        for i, row in enumerate(rows):
            row_data: dict[str, Any] = {}
            for comp in self._schema_for(row):
                comp.process(form, join(path, i), row_data, errors)
            if isinstance(row, dict) and row.get("__key"):
                row_data["__key"] = row["__key"]
            out.append(self._join_value(row if isinstance(row, dict) else {}, row_data))
        if self.is_required(form, base) and not out:
            errors.setdefault(path, []).append(__("The :attribute field is required.", attribute=label))
        if self._min_items is not None and len(out) < self._min_items:
            errors.setdefault(path, []).append(__("The :attribute must have at least :min items.", attribute=label, min=self._min_items))
        if self._max_items is not None and len(out) > self._max_items:
            errors.setdefault(path, []).append(__("The :attribute may not have more than :max items.", attribute=label, max=self._max_items))
        msgs = self.run_rules(form, base, out)
        if msgs:
            errors.setdefault(path, []).extend(msgs)
        if self.is_disabled(form, base) or not self.is_dehydrated(form, base):
            return
        if self._dehydrate_state is not None:
            out = call(self._dehydrate_state, **{**form.ev(base), "state": out})
        data[self.name] = out

    def fill_record(self, form: "Form", record: Any, data: dict) -> None:
        if self._rel or self.name not in data:
            return
        setattr(record, self.name, [_jsonable({k: v for k, v in row.items() if k != "__key"}) for row in data[self.name]])

    def save_relationships(self, form: "Form", record: Any, data: dict) -> None:
        if not self._rel or self.name not in data:
            return
        from sqlalchemy import inspect as sa_inspect

        rel = sa_inspect(type(record)).relationships[self._rel]
        target = rel.mapper.class_
        pk = sa_inspect(target).primary_key[0]
        existing = {str(getattr(o, pk.key)): o for o in getattr(record, self._rel)}
        keep = []
        for i, row in enumerate(data[self.name]):
            obj = existing.get(str(row.get("__key"))) if row.get("__key") else None
            if obj is None:
                obj = target()
            for comp in self._schema:
                comp.fill_record(form, obj, row)
            if self._order_column:
                setattr(obj, self._order_column, i)
            keep.append(obj)
        setattr(record, self._rel, keep)
        form.ctx.db.flush()
        for obj, row in zip(keep, data[self.name]):
            for comp in self._schema:
                comp.save_relationships(form, obj, row)

    def handle_ui_action(self, form: "Form", path: str, base: str, kind: str, arg: str) -> None:
        rows = list(get_path(form.state, path) or [])
        if kind == "add":
            if self._max_items is None or len(rows) < self._max_items:
                self._blank_row(form, path, len(rows), arg or None)
            return
        if not arg.isdigit() or int(arg) >= len(rows):
            return
        i = int(arg)
        if kind == "remove":
            rows.pop(i)
        elif kind == "up" and i > 0:
            rows[i - 1], rows[i] = rows[i], rows[i - 1]
        elif kind == "down" and i < len(rows) - 1:
            rows[i + 1], rows[i] = rows[i], rows[i + 1]
        elif kind == "clone":
            import copy

            clone = copy.deepcopy(rows[i])
            clone.pop("__key", None)
            rows.insert(i + 1, clone)
        set_path(form.state, path, rows)
        # move errors with rows is not worth it: clear row errors after a structural change
        form.errors = {k: v for k, v in form.errors.items() if not k.startswith(path + ".")}

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        path = v["path"]
        ev = form.ev(base)
        rows = []
        for i, row in enumerate(self.rows(form, base)):
            row_base = join(path, i)
            label = call(self._item_label, **{**form.ev(row_base), "state": row}) if self._item_label else None
            rows.append({"index": i, "base": row_base, "label": label, "key": (row or {}).get("__key"),
                         "schema": self._schema_for(row), "type": (row or {}).get("__type"),
                         **self._row_extra(row)})
        count = len(rows)
        v.update(
            rows=rows,
            schema=self._schema,
            columns=self._columns,
            add_label=maybe(evaluate(self._add_label, **ev)) or __("Add to :label", label=v["label"].lower()),
            can_add=bool(evaluate(self._addable, **ev)) and (self._max_items is None or count < self._max_items),
            can_delete=bool(evaluate(self._deletable, **ev)) and (self._min_items is None or count > self._min_items),
            reorderable=self._reorderable,
            collapsible=self._collapsible,
            table=self._table,
            row_fields=self._row_fields() if self._table else [],
            blocks=[],
        )
        return v

    def _row_extra(self, row: Any) -> dict:
        return {}


class Block(Component):
    """One block type of a :class:`Builder`: ``Block("heading").icon("heading").schema([...])``."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self._label: Any = None
        self._icon: str | None = None
        self._schema: list[Component] = []
        self._columns = 1

    def label(self, label: Any) -> "Block":
        self._label = label
        return self

    def icon(self, icon: str) -> "Block":
        self._icon = icon
        return self

    def schema(self, components: list) -> "Block":
        self._schema = list(components)
        return self

    def columns(self, n: int) -> "Block":
        self._columns = n
        return self

    def get_label(self) -> str:
        return __(str(self._label) if self._label is not None else headline(self.name))

    # ---- in a RichEditor (``RichEditor.blocks([...])``)
    def preview(self, fn: Callable) -> "Block":
        """What the block looks like inside the editor: ``fn(config)`` returns HTML (cleaned before use)."""
        self._preview = fn
        return self

    def render_using(self, fn: Callable) -> "Block":
        """The block's HTML on your site, used by ``render_rich_content``: ``fn(config)`` returns HTML."""
        self._render = fn
        return self

    def summary(self, config: dict) -> str:
        parts = [f"{headline(k)}: {v}" for k, v in (config or {}).items() if v not in (None, "", [], {})]
        return " · ".join(str(p) for p in parts)[:200]


class Builder(Repeater):
    """Rows of different block types (a page builder). Saved as
    ``[{"type": "heading", "data": {...}}, ...]``::

        Builder("content").blocks([
            Block("heading").icon("heading").schema([TextInput("text").required()]),
            Block("paragraph").icon("pilcrow").schema([RichEditor("body")]),
        ])
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._blocks: list[Block] = []
        self._default_items = 0
        self._add_label = None

    def blocks(self, blocks: list[Block]) -> "Builder":
        self._blocks = list(blocks)
        return self

    def relationship(self, *args: Any, **kwargs: Any) -> "Builder":
        raise NotImplementedError("Builder stores JSON; use Repeater for related records.")

    def block(self, name: str | None) -> Block | None:
        return next((b for b in self._blocks if b.name == name), None)

    def _schema_for(self, row: Any) -> list[Component]:
        block = self.block((row or {}).get("__type") if isinstance(row, dict) else None)
        return block._schema if block else []

    def _split_value(self, row: Any) -> tuple[dict, dict]:
        if isinstance(row, dict) and "type" in row:
            return {"__type": row["type"]}, dict(row.get("data") or {})
        return {}, {}

    def _join_value(self, row_state: dict, row_data: dict) -> Any:
        return {"type": row_state.get("__type"), "data": {k: v for k, v in row_data.items() if k != "__key"}}

    def _row_extra(self, row: Any) -> dict:
        block = self.block((row or {}).get("__type")) if isinstance(row, dict) else None
        return {"block_label": block.get_label() if block else "Unknown block",
                "block_icon": block._icon if block else None, "columns": block._columns if block else 1}

    def _blank_row(self, form: "Form", path: str, index: int, block: str | None = None) -> dict:
        if self.block(block) is None:
            block = self._blocks[0].name if self._blocks else None
        return super()._blank_row(form, path, index, block)

    def to_state(self, value: Any) -> Any:
        return []

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        v["blocks"] = [{"name": b.name, "label": b.get_label(), "icon": b._icon} for b in self._blocks]
        v["add_label"] = maybe(evaluate(self._add_label, **form.ev(base))) or __("Add block")
        v["table"] = False
        return v


class KeyValue(Field):
    """Edit a dict as key/value rows (saved as JSON)."""

    template = "tungsten/forms/fields/key-value.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._key_label = "Key"
        self._value_label = "Value"
        self._add_label = "Add row"
        self._addable = True
        self._deletable = True
        self._editable_keys = True

    def key_label(self, label: str) -> "KeyValue":
        self._key_label = label
        return self

    def value_label(self, label: str) -> "KeyValue":
        self._value_label = label
        return self

    def add_action_label(self, label: str) -> "KeyValue":
        self._add_label = label
        return self

    def addable(self, condition: bool = True) -> "KeyValue":
        self._addable = condition
        return self

    def deletable(self, condition: bool = True) -> "KeyValue":
        self._deletable = condition
        return self

    def editable_keys(self, condition: bool = True) -> "KeyValue":
        self._editable_keys = condition
        return self

    def blank_state(self) -> Any:
        return []

    def to_state(self, value: Any) -> Any:
        if not value:
            return []
        return [{"key": str(k), "value": "" if v is None else str(v)} for k, v in dict(value).items()]

    def extract(self, formdata: Any, path: str) -> Any:
        prefix = path + "."
        idx = sorted({int(k[len(prefix):].split(".")[0]) for k in formdata.keys()
                      if k.startswith(prefix) and k[len(prefix):].split(".")[0].isdigit()})
        return [{"key": formdata.get(f"{path}.{i}.key", ""), "value": formdata.get(f"{path}.{i}.value", "")} for i in idx]

    def cast(self, state: Any) -> Any:
        out = {}
        for row in state or []:
            key = str(row.get("key", "")).strip()
            if key:
                out[key] = row.get("value", "")
        return out

    def handle_ui_action(self, form: "Form", path: str, base: str, kind: str, arg: str) -> None:
        rows = list(get_path(form.state, path) or [])
        if kind == "add":
            rows.append({"key": "", "value": ""})
        elif kind == "remove" and arg.isdigit() and int(arg) < len(rows):
            rows.pop(int(arg))
        set_path(form.state, path, rows)

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        v.update(key_label=__(self._key_label), value_label=__(self._value_label), add_label=__(self._add_label),
                 addable=self._addable, deletable=self._deletable, editable_keys=self._editable_keys,
                 rows=v["state"] or [])
        return v


# ---------------------------------------------------------------------- helpers
class DataRecord:
    """Lets fields ``getattr`` into a plain dict (JSON repeater rows)."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return self._data.get(name)


class _ReindexedForm:
    """View of a MultiDict where ``old`` prefix is read as ``new`` prefix."""

    def __init__(self, formdata: Any, old: str, new: str) -> None:
        self._fd, self._old, self._new = formdata, old, new

    def _map(self, key: str) -> str:
        return self._old + key[len(self._new):] if key.startswith(self._new) else key

    def get(self, key: str, default: Any = None) -> Any:
        return self._fd.get(self._map(key), default)

    def getlist(self, key: str) -> list:
        return self._fd.getlist(self._map(key))

    def keys(self):
        return [self._new + k[len(self._old):] if k.startswith(self._old) else k for k in self._fd.keys()]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value
