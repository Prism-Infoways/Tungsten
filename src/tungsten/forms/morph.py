"""``MorphToSelect``: pick a record from one of several models (a polymorphic relation).

The record is stored as two columns, a type and an id, like ``commentable_type`` and
``commentable_id``. Filament's ``MorphToSelect`` does the same.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ..i18n import maybe
from ..support.evaluate import call, evaluate
from .fields import Select
from .layout import Layout

if TYPE_CHECKING:  # pragma: no cover
    from .form import Form


class MorphType:
    """One model a :class:`MorphToSelect` can point at::

        MorphType(Product).title("name").label("Product")
        MorphType(Post, key="post").title(lambda record: record.title[:40]).modify_query(lambda query: query.where(...))
    """

    def __init__(self, model: type, key: str | None = None) -> None:
        self.model = model
        #: the value saved in the type column (the class name unless you pass ``key``)
        self.key = key or model.__name__
        self._title: Any = None
        self._label: Any = None
        self._modify_query: Callable | None = None
        self._searchable = False

    def title(self, attribute_or_fn: Any) -> "MorphType":
        """The attribute (or a closure ``lambda record: ...``) shown for each record."""
        self._title = attribute_or_fn
        return self

    title_attribute = title

    def label(self, label: Any) -> "MorphType":
        """The name shown in the type list (default: the model name)."""
        self._label = label
        return self

    def modify_query(self, fn: Callable) -> "MorphType":
        """Narrow the records: ``lambda query: query.where(Product.active == True)``."""
        self._modify_query = fn
        return self

    def searchable(self, condition: bool = True) -> "MorphType":
        self._searchable = condition
        return self

    def get_label(self) -> str:
        from ..support.component import headline

        return str(maybe(evaluate(self._label))) if self._label is not None else headline(self.model.__name__)

    def title_of(self, record: Any) -> str:
        if callable(self._title):
            return str(call(self._title, record=record))
        if self._title:
            return str(getattr(record, self._title))
        return str(record)

    def options(self, form: "Form") -> dict[Any, str]:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import select

        ctx = form.ctx
        if ctx is None or ctx.db is None:
            return {}
        query = select(self.model)
        query = ctx.panel.tenancy.scope(ctx, self.model, query)
        if self._modify_query is not None:
            query = call(self._modify_query, **{**form.ev(), "query": query})
        pk = sa_inspect(self.model).primary_key[0]
        from ..support.aio import resolve

        rows = resolve(ctx.db.execute(query))
        return {getattr(r, pk.key): self.title_of(r) for r in rows.scalars()}


class MorphToSelect(Layout):
    """Two selects that together point at one of several models::

        MorphToSelect("commentable").types([
            MorphType(Product).title("name"),
            MorphType(Post).title("title"),
        ])

    Saves ``commentable_type`` (the type key) and ``commentable_id``. The record list
    follows the chosen type without a page reload. Change the column names with
    ``.type_column()`` and ``.id_column()``.
    """

    template = "tungsten/forms/layouts/group.html"

    def __init__(self, name: str, types: list[MorphType] | None = None) -> None:
        super().__init__()
        self.name = name
        self._types: list[MorphType] = list(types or [])
        self._label: Any = None
        self._required: Any = False
        self._type_column = f"{name}_type"
        self._id_column = f"{name}_id"
        self._searchable = False
        self._native = True
        self._columns = 2
        self._column_span = "full"
        self._built: list | None = None

    def types(self, types: list[MorphType]) -> "MorphToSelect":
        self._types = list(types)
        self._built = None
        return self

    def label(self, label: Any) -> "MorphToSelect":
        self._label = label
        self._built = None
        return self

    def required(self, condition: Any = True) -> "MorphToSelect":
        self._required = condition
        self._built = None
        return self

    def type_column(self, column: str) -> "MorphToSelect":
        self._type_column = column
        self._built = None
        return self

    def id_column(self, column: str) -> "MorphToSelect":
        self._id_column = column
        self._built = None
        return self

    def searchable(self, condition: bool = True) -> "MorphToSelect":
        """A searchable record list (useful with many records)."""
        self._searchable = condition
        self._built = None
        return self

    def native(self, condition: bool = True) -> "MorphToSelect":
        self._native = condition
        self._built = None
        return self

    def type_for(self, key: Any) -> MorphType | None:
        return next((t for t in self._types if t.key == key), None)

    def _record_label(self, key: Any) -> str:
        t = self.type_for(key)
        return t.get_label() if t else "Record"

    def record_options(self, form: "Form", get: Any) -> dict[Any, str]:
        t = self.type_for(get(self._type_column))
        return t.options(form) if t else {}

    def child_components(self) -> list:
        if self._built is None:
            from ..support.component import headline

            label = self._label if self._label is not None else headline(self.name.replace("_", " "))
            type_select = (Select(self._type_column).label(label).options({t.key: t.get_label() for t in self._types})
                           .placeholder("Select a type").required(self._required).live()
                           .after_state_updated(lambda set: set(self._id_column, None)))
            record_select = (Select(self._id_column)
                             .label(lambda get: self._record_label(get(self._type_column)))
                             .options(lambda get, form: self.record_options(form, get))
                             .placeholder("Select a record").required(self._required)
                             .disabled(lambda get: not get(self._type_column)))
            if not self._native or self._searchable:
                record_select.native(False)
            if self._searchable:
                record_select.searchable()
            self._built = [type_select, record_select]
        return self._built
