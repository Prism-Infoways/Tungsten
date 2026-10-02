"""Relation managers: manage related records inside a parent record's page."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from ..i18n import translate as __
from ..support.component import headline

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..forms.form import Form
    from ..tables.table import Table


class RelationManager:
    """Shown as a table under the edit/view page of the owner record::

        class OrdersRelationManager(RelationManager):
            relationship = "orders"

            @classmethod
            def table(cls, table):
                return table.columns([...]).header_actions([CreateAction()]).actions([EditAction(), DeleteAction()])
    """

    relationship: ClassVar[str] = ""
    title: ClassVar[str | None] = None
    label: ClassVar[str | None] = None
    icon: ClassVar[str | None] = None
    record_title_attribute: ClassVar[str | None] = None
    soft_delete_column: ClassVar[str | None] = "deleted_at"
    #: hide on the view page (read-only owners) unless True
    show_on_view: ClassVar[bool] = True

    @classmethod
    def form(cls, form: "Form") -> "Form":
        return form

    @classmethod
    def table(cls, table: "Table") -> "Table":
        return table

    @classmethod
    def infolist(cls, infolist: Any) -> Any:
        """Read-only layout for the View modal. ``None`` shows the form disabled."""
        return None

    @classmethod
    def get_name(cls) -> str:
        return cls.relationship

    @classmethod
    def get_title(cls) -> str:
        return __(cls.title or headline(cls.relationship))

    @classmethod
    def get_label(cls) -> str:
        if cls.label:
            return __(cls.label)
        title = cls.title or headline(cls.relationship)
        return __(title[:-1] if title.endswith("s") else title)

    @classmethod
    def get_record_title(cls, record: Any) -> str:
        if cls.record_title_attribute:
            return str(getattr(record, cls.record_title_attribute, ""))
        for attr in ("name", "title", "number", "email"):
            if getattr(record, attr, None):
                return str(getattr(record, attr))
        return str(record)

    @classmethod
    def can(cls, ctx: "Context", ability: str, record: Any = None, *, owner: Any = None, resource: Any = None) -> bool:
        """By default: allowed when the user can update the owner record."""
        if resource is None:
            return True
        if ability in ("view", "view_any"):
            return resource.can(ctx, "view", owner)
        return resource.can(ctx, "update", owner)

    @classmethod
    def badge(cls, ctx: "Context", owner: Any) -> Any:
        """Count shown on the relation tab. Default: number of related records."""
        try:
            return len(getattr(owner, cls.relationship))
        except TypeError:
            return None
