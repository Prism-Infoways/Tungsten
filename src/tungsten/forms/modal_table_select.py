"""``ModalTableSelect``: pick records from a searchable, paged table in a modal."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from markupsafe import Markup

from ..i18n import translate as __
from ..support.component import headline
from ..support.evaluate import evaluate
from ..support.state import get_path, set_path
from .fields import Field, Select

if TYPE_CHECKING:  # pragma: no cover
    from .form import Form


class ModalTableSelect(Select):
    """Like a ``Select``, but the user picks from a table in a modal — handy for big
    lists where seeing more than a name helps::

        ModalTableSelect("customer_id").relationship("customer", "name")
            .table_columns(["name", "email", ("city", "Town")])
            .searchable_columns(["name", "email"])

    Add ``.multiple()`` (with a many-to-many relationship) to pick several.
    """

    template = "tungsten/forms/fields/modal-table-select.html"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._searchable = True
        self._preload = False
        self._native = False
        self._table_columns: list = []
        self._search_columns: list[str] | None = None
        self._per_page = 10
        self._select_label: Any = None
        self._modal_heading: Any = None
        self._modal_width = "3xl"

    def table_columns(self, columns: list) -> "ModalTableSelect":
        """Attribute names (``"email"``, ``"company.name"``) or ``(attribute, label)`` pairs."""
        self._table_columns = list(columns)
        return self

    def searchable_columns(self, columns: list[str]) -> "ModalTableSelect":
        """Columns the search box looks in (default: the title attribute)."""
        self._search_columns = list(columns)
        return self

    def per_page(self, n: int) -> "ModalTableSelect":
        self._per_page = max(1, int(n))
        return self

    def select_action_label(self, label: Any) -> "ModalTableSelect":
        self._select_label = label
        return self

    def modal_heading(self, heading: Any) -> "ModalTableSelect":
        self._modal_heading = heading
        return self

    def modal_width(self, width: str) -> "ModalTableSelect":
        self._modal_width = width
        return self

    # ---------------------------------------------------------------- actions
    def _option_actions(self) -> list:
        cached = getattr(self, "_option_actions_cache", None)
        if cached is not None:
            return cached
        out = super()._option_actions()
        from ..actions.action import Action

        picker = _TablePicker("pick", self)
        select = (Action("select_records").label(lambda: str(evaluate(self._select_label) or __("Select")))
                  .icon("table").color("gray").form([picker]).modal_width(self._modal_width)
                  .modal_heading(lambda: str(evaluate(self._modal_heading) or __("Select :label", label=self.get_label().lower())))
                  .modal_submit_label(__("Select"))
                  .fill_form(lambda state: {"pick": state})
                  .action(self._apply_pick))
        self._option_actions_cache = [select, *out]
        return self._option_actions_cache

    def form_actions(self, form: "Form", base: str) -> list:
        return Field.form_actions(self, form, base) + self._option_actions()

    def _apply_pick(self, data: dict, set: Any) -> None:
        picked = data.get("pick")
        if self._multiple:
            set(self.name, [str(k) for k in (picked or [])])
        else:
            set(self.name, str(picked) if picked not in (None, "", []) else "")

    def handle_ui_action(self, form: "Form", path: str, base: str, kind: str, arg: str) -> None:
        if kind == "remove" and not self.is_disabled(form, base):
            if self._multiple:
                set_path(form.state, path, [k for k in (get_path(form.state, path) or []) if str(k) != arg])
            else:
                set_path(form.state, path, "")
            self.call_after_state_updated(form, path, base)

    # ---------------------------------------------------------------- rows
    def columns_spec(self) -> list[tuple[str, str]]:
        out = []
        for col in self._table_columns or ([self._relationship["title"]] if self._relationship and
                                           self._relationship.get("title") else []):
            if isinstance(col, (tuple, list)):
                out.append((col[0], __(str(col[1]))))
            else:
                out.append((col, __(headline(col.replace(".", "_")))))
        return out or [("label", __("Name"))]

    def page_of_rows(self, form: "Form", search: str, page: int) -> tuple[list[dict], int]:
        """``([{"key", "cells"}], total)`` for one page of the table."""
        cols = self.columns_spec()
        if self._relationship and self._options is None and form.ctx is not None:
            from sqlalchemy import String, cast, func, or_, select

            _, target, pk = self._rel_info(form)
            query = self.relationship_query(form)
            if search:
                names = self._search_columns or [c for c, _ in cols if "." not in c]
                conds = [cast(getattr(target, n), String).ilike(f"%{search}%") for n in names if hasattr(target, n)]
                if conds:
                    query = query.where(or_(*conds))
            total = form.ctx.db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
            records = form.ctx.db.scalars(query.offset((page - 1) * self._per_page).limit(self._per_page)).all()
            rows = [{"key": str(getattr(r, pk.key)), "cells": [_cell(get_path(r, c)) for c, _ in cols]} for r in records]
            return rows, total
        options = self.get_options(form)
        if search:
            options = [o for o in options if search.lower() in o[1].lower()]
        chunk = options[(page - 1) * self._per_page: page * self._per_page]
        return [{"key": str(k), "cells": [label]} for k, label in chunk], len(options)

    def validate_value(self, form: "Form", base: str, value: Any) -> list[str]:
        keys = value if self._multiple else [value]
        if self._relationship and self._options is None and form.ctx is not None and keys:
            from sqlalchemy import func, select

            _, target, pk = self._rel_info(form)
            matched = {self._match_key(form, base, k) for k in keys}
            query = self.relationship_query(form).where(pk.in_(matched))
            count = form.ctx.db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
            if count < len(matched):
                return [__("The selected :attribute is invalid.", attribute=self.get_label(form, base).lower())]
            return []
        return super().validate_value(form, base, value)

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        v["selected"] = [o for o in v["options"] if o["selected"]]
        from .actions import render_action

        select = self._option_actions()[0]
        v["select_button"] = render_action(select, form, self, base, style="button") if not v["disabled"] else Markup("")
        v["suffix_actions"] = Markup("").join(render_action(a, form, self, base, style="icon")
                                              for a in self._suffix_actions)
        return v


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if hasattr(value, "value") and not isinstance(value, (str, int, float)):  # an Enum
        value = value.value
    return str(value)


class _TablePicker(Field):
    """The table shown in a ModalTableSelect's modal. Its value is the picked key(s)."""

    template = "tungsten/forms/fields/table-picker.html"
    live_typed = False

    def __init__(self, name: str, owner: ModalTableSelect) -> None:
        super().__init__(name)
        self.owner = owner
        self._hidden_label = True
        self._column_span = "full"

    def blank_state(self) -> Any:
        return [] if self.owner._multiple else ""

    def to_state(self, value: Any) -> Any:
        if self.owner._multiple:
            return [str(v) for v in (value or [])]
        return "" if value in (None, "") else str(value)

    def extract(self, formdata: Any, path: str) -> Any:
        if self.owner._multiple:
            return [v for v in formdata.getlist(path) if v != ""]
        return super().extract(formdata, path)

    def cast(self, state: Any) -> Any:
        if self.owner._multiple:
            return list(state or [])
        return super().cast(state)

    def _ui(self, form: "Form", path: str, key: str, default: str = "") -> str:
        return str(form.ui.get(f"{path}.{key}", default) or default)

    def handle_ui_action(self, form: "Form", path: str, base: str, kind: str, arg: str) -> None:
        if kind == "page" and arg.isdigit():
            form.ui[f"{path}.page"] = arg

    def view_data(self, form: "Form", base: str) -> dict[str, Any]:
        v = super().view_data(form, base)
        path = v["path"]
        owner_form = form.parent or form
        search = self._ui(form, path, "q").strip()[:200]
        if search != self._ui(form, path, "qprev"):
            form.ui[f"{path}.page"] = "1"  # a new search starts on page 1
        try:
            page = max(1, int(self._ui(form, path, "page", "1")))
        except ValueError:
            page = 1
        rows, total = self.owner.page_of_rows(owner_form, search, page)
        pages = max(1, math.ceil(total / self.owner._per_page))
        if page > pages:
            page = pages
            rows, total = self.owner.page_of_rows(owner_form, search, page)
        state = v["state"]
        selected = [str(s) for s in state] if isinstance(state, list) else ([str(state)] if state else [])
        on_page = {r["key"] for r in rows}
        v.update(rows=rows, total=total, page=page, pages=pages, search=search, multiple=self.owner._multiple,
                 columns=[label for _, label in self.owner.columns_spec()], selected=selected,
                 hidden=[k for k in selected if k not in on_page])
        return v
