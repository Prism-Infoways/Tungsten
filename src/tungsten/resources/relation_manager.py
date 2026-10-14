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

    ``relationship`` can be:

    * a one-to-many (``"orders"``): use ``CreateAction``, ``AssociateAction``, ``DissociateAction``,
    * a many-to-many (``"tags"``): ``AttachAction`` (with extra link-table fields) and ``DetachAction``,
    * a polymorphic one (``tungsten.relations.morph_many`` / ``morph_to_many``),
    * a "has many through" path (``"teams.projects"``): listed, edited and deleted, never linked.

    ``separate_page = True`` moves the table to its own page (``/customers/1/orders``) with a
    link on the record page. ``related_resource = OrderResource`` reuses that resource's form,
    table and infolist and opens its records on nested pages (``/customers/1/orders/5/edit``).
    """

    relationship: ClassVar[str] = ""
    #: URL part of the relation's own page (default: the relationship, kebab-case)
    slug: ClassVar[str | None] = None
    #: show the table on its own page instead of under the record's form
    separate_page: ClassVar[bool] = False
    #: a nested resource: its form/table/infolist are used and its records get nested pages
    related_resource: ClassVar[Any] = None
    #: force linking on/off (default: off for "through" paths and read-only relationships)
    linkable: ClassVar[bool | None] = None
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
    def get_slug(cls) -> str:
        return cls.slug or cls.relationship.replace(".", "-").replace("_", "-")

    @classmethod
    def get_url(cls, ctx: "Context", resource: Any, owner: Any, page: str = "index", record: Any = None,
                **query: Any) -> str:
        """``index``: the relation's own page; ``create``/``edit``/``view``: nested record pages."""
        owner_key = resource.host().record_key(owner) if not isinstance(owner, (str, int)) else owner
        parts: list[Any] = [resource.get_slug(), owner_key, cls.get_slug()]
        if page == "create":
            parts.append("create")
        elif page in ("edit", "view"):
            from ..hosts import RelationHost

            key = record if isinstance(record, (str, int)) else RelationHost.key_of(record)
            parts.append(key)
            if page == "edit":
                parts.append("edit")
        return ctx.url(*parts, **query)
    @classmethod
    def get_title(cls) -> str:
        if cls.title is None and cls.related_resource is not None:
            return cls.related_resource.get_plural_label()
        return __(cls.title or headline(cls.relationship.split(".")[-1]))

    @classmethod
    def get_label(cls) -> str:
        if cls.label:
            return __(cls.label)
        if cls.related_resource is not None:
            return cls.related_resource.get_label()
        title = cls.title or headline(cls.relationship.split(".")[-1])
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
        """By default: allowed when the user can update the owner record.

        With a ``related_resource``, that resource's own permissions decide (the owner must be viewable).
        """
        if resource is None:
            return True
        if cls.related_resource is not None:
            if not resource.can(ctx, "view", owner):
                return False
            nested = {"view_any": "view_any", "view": "view", "create": "create", "update": "update",
                      "delete": "delete", "delete_any": "delete_any", "restore": "restore",
                      "restore_any": "restore_any", "force_delete": "force_delete",
                      "force_delete_any": "force_delete_any"}.get(ability)
            if nested is not None:
                return cls.related_resource.can(ctx, nested, record)
            return resource.can(ctx, "update", owner)
        if ability in ("view", "view_any"):
            return resource.can(ctx, "view", owner)
        return resource.can(ctx, "update", owner)

    @classmethod
    def badge(cls, ctx: "Context", owner: Any) -> Any:
        """Count shown on the relation tab. Default: number of related records."""
        if "." in cls.relationship or getattr(type(owner), cls.relationship, None) is None:
            from ..relations import RelationLink

            try:
                return RelationLink(type(owner), cls.relationship).count(ctx.db, owner)
            except Exception:  # noqa: BLE001
                return None
        try:
            return len(getattr(owner, cls.relationship))
        except TypeError:
            return None
