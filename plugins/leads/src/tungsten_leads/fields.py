"""The form section that draws the fields added on the "Lead fields" screen.

The fields are read from the database each time a form is built, and their
values are saved together in the lead's ``custom_fields`` JSON column.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Iterator

from markupsafe import Markup
from sqlalchemy import select
from tungsten.forms import CheckboxList, DatePicker, Section, Select, Textarea, TextInput, Toggle
from tungsten.forms.fields import DataRecord
from tungsten.support.state import join

from .models import LeadField

#: field types the admin can pick, with their labels
FIELD_TYPES = {
    "text": "Text",
    "textarea": "Long text",
    "number": "Number",
    "email": "Email",
    "phone": "Phone",
    "url": "Link",
    "date": "Date",
    "select": "Dropdown",
    "multiselect": "Checkboxes (pick many)",
    "checkbox": "Yes / No",
}
OPTION_TYPES = ("select", "multiselect")


def build_field(definition: LeadField) -> Any:
    """Turn one ``LeadField`` row into a Tungsten form field."""
    kind, key = definition.type, definition.key
    options = [str(o) for o in (definition.options or [])]
    if kind == "textarea":
        field = Textarea(key).rows(3).column_span("full")
    elif kind == "number":
        field = TextInput(key).numeric()
    elif kind == "email":
        field = TextInput(key).email()
    elif kind == "phone":
        field = TextInput(key).tel()
    elif kind == "url":
        field = TextInput(key).url()
    elif kind == "date":
        field = DatePicker(key)
    elif kind == "select":
        field = Select(key).options(options)
    elif kind == "multiselect":
        field = CheckboxList(key).options(options).columns(2)
    elif kind == "checkbox":
        field = Toggle(key)
    else:
        field = TextInput(key).max_length(255)
    field.label(definition.label)
    if definition.required and kind != "checkbox":
        field.required()
    if definition.help_text:
        field.helper_text(definition.help_text)
    return field


def active_fields(db: Any) -> list[LeadField]:
    return list(db.scalars(select(LeadField).where(LeadField.is_active.is_(True))
                           .order_by(LeadField.sort, LeadField.id)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral() else float(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


class CustomFields(Section):
    """``CustomFields()`` in a lead form: one input per active lead field.

    Its fields live under the ``custom_fields`` state path, so errors and
    values look like ``custom_fields.budget``.
    """

    def __init__(self, heading: Any = "More details", name: str = "custom_fields") -> None:
        super().__init__(heading)
        self.name = name
        self._built: list | None = None

    def _prepare(self, form: Any) -> list:
        if self._built is None:
            db = form.ctx.db if form.ctx is not None else None
            self._built = [build_field(d) for d in active_fields(db)] if db is not None else []
            model = form.get_model()
            for field in self._built:
                field._owner_model = model
        return self._built

    def child_components(self) -> list:
        return self._built or []

    def _base(self, base: str) -> str:
        return join(base, self.name)

    def fill_state(self, form: Any, base: str, record: Any) -> None:
        values = getattr(record, self.name, None) if record is not None else None
        source = DataRecord(values or {}) if record is not None else None
        for field in self._prepare(form):
            field.fill_state(form, self._base(base), source)

    def load_state(self, form: Any, formdata: Any, base: str) -> None:
        for field in self._prepare(form):
            field.load_state(form, formdata, self._base(base))

    def process(self, form: Any, base: str, data: dict, errors: dict) -> None:
        fields = self._prepare(form)
        if not fields or not self.is_layout_visible(form, base):
            return
        values: dict[str, Any] = {}
        for field in fields:
            field.process(form, self._base(base), values, errors)
        data[self.name] = {k: _jsonable(v) for k, v in values.items()}

    def fill_record(self, form: Any, record: Any, data: dict) -> None:
        if self.name in data:
            # keep values of fields that were switched off since
            merged = dict(getattr(record, self.name, None) or {})
            merged.update(data[self.name])
            setattr(record, self.name, merged)

    def save_relationships(self, form: Any, record: Any, data: dict) -> None:
        return None

    def walk(self, form: Any, base: str) -> Iterator[tuple[Any, str, str]]:
        for field in self._prepare(form):
            yield from field.walk(form, self._base(base))

    def view_data(self, form: Any, base: str) -> dict[str, Any]:
        return {**super().view_data(form, base), "base": self._base(base)}

    def render(self, form: Any, base: str) -> Markup:
        if not self._prepare(form):
            return Markup("")
        return super().render(form, base)
