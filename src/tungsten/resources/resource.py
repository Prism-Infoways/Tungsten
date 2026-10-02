"""A :class:`Resource` turns one SQLAlchemy model into list/create/edit/view pages."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import select

from ..i18n import translate as __
from ..support.component import headline

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..forms.form import Form
    from ..tables.table import Table


def _plural(word: str) -> str:
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", word):
        return word + "es"
    return word + "s"


def _kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


_POLICY_ARGS = {"user", "record", "ctx", "db", "ability", "tenant"}


def _call_policy(fn: Any, ctx: "Context", ability: str, record: Any) -> Any:
    """Call a policy method by parameter name (``user``, ``record``, ``ctx``...), awaiting ``async def``.

    Methods with other parameter names get ``(user, record)`` / ``(user)`` by position, as before.
    """
    from ..support.aio import resolve
    from ..support.evaluate import _signature, call

    try:
        names, var_kw = _signature(fn)
    except TypeError:  # unhashable callable
        names, var_kw = _signature.__wrapped__(fn)
    if var_kw or set(names) <= _POLICY_ARGS:
        return call(fn, user=ctx.user, record=record, ctx=ctx, db=ctx.db, ability=ability, tenant=ctx.tenant)
    return resolve(fn(ctx.user, record) if record is not None else fn(ctx.user))


class Resource:
    """Describe how a model is managed. Minimal example::

        class ProductResource(Resource):
            model = Product
            icon = "package"

            @classmethod
            def form(cls, form):
                return form.schema([TextInput("name").required()])

            @classmethod
            def table(cls, table):
                return table.columns([TextColumn("name").searchable().sortable()])
    """

    model: ClassVar[Any] = None
    slug: ClassVar[str | None] = None
    label: ClassVar[str | None] = None
    plural_label: ClassVar[str | None] = None
    description: ClassVar[str | None] = None

    # navigation
    icon: ClassVar[str | None] = "file-text"
    active_icon: ClassVar[str | None] = None
    navigation_group: ClassVar[str | None] = None
    navigation_label: ClassVar[str | None] = None
    navigation_sort: ClassVar[int] = 0
    navigation_parent: ClassVar[str | None] = None
    show_in_navigation: ClassVar[bool] = True

    # records
    record_title_attribute: ClassVar[str | None] = None
    global_search_attributes: ClassVar[list[str]] = []
    global_search_limit: ClassVar[int] = 5
    soft_delete_column: ClassVar[str | None] = "deleted_at"

    # pages: index, create, edit, view. A "simple" resource uses modals only.
    pages: ClassVar[tuple[str, ...]] = ("index", "create", "edit", "view")
    simple: ClassVar[bool] = False

    relations: ClassVar[list] = []
    widgets: ClassVar[list] = []

    # tenancy: the column or relationship that links a record to the current tenant
    # (default: the panel's ``Tenancy(ownership=...)``); ``tenant_scoped = False`` shares
    # this resource's records between all tenants
    tenant_ownership: ClassVar[str | None] = None
    tenant_scoped: ClassVar[bool] = True

    #: optional policy object with methods like ``update(user, record)``
    policy: ClassVar[Any] = None

    # ------------------------------------------------------------------ definition
    @classmethod
    def form(cls, form: "Form") -> "Form":
        return form

    @classmethod
    def table(cls, table: "Table") -> "Table":
        return table

    @classmethod
    def infolist(cls, infolist: Any) -> Any:
        """Read-only layout for the view page. Return ``None`` to show the form disabled."""
        return None

    @classmethod
    def query(cls, ctx: "Context"):
        """The base query for every page (override to scope records)."""
        return select(cls.model)

    @classmethod
    def header_actions(cls, ctx: "Context", page: str, record: Any = None) -> list:
        """Buttons in the page header. ``page`` is index/list, create, edit or view."""
        from ..actions import CreateAction, DeleteAction, EditAction, ForceDeleteAction, RestoreAction

        if page in ("list", "index"):
            return [CreateAction().label(lambda: __("Create :label", label=cls.get_label().lower()))]
        if page == "edit":
            return [DeleteAction().outlined(), RestoreAction().button(), ForceDeleteAction().outlined()]
        if page == "view":
            return [DeleteAction().outlined(), EditAction().button().color("primary")]
        return []

    @classmethod
    def header_widgets(cls, ctx: "Context", page: str) -> list:
        return list(cls.widgets) if page in ("list", "index") else []

    # ------------------------------------------------------------------ naming
    @classmethod
    def get_label(cls) -> str:
        """The singular label, translated (``Product``)."""
        return __(cls._raw_label())

    @classmethod
    def _raw_label(cls) -> str:
        if cls.label:
            return cls.label
        return headline(_kebab(cls.model.__name__).replace("-", "_")).lower().capitalize() if cls.model else "Record"

    @classmethod
    def get_plural_label(cls) -> str:
        """The plural label, translated (``Products``)."""
        return __(cls.plural_label or _plural(cls._raw_label()))

    @classmethod
    def get_slug(cls) -> str:
        if cls.slug:
            return cls.slug
        return _plural(_kebab(cls.model.__name__)) if cls.model else _kebab(cls.__name__)

    @classmethod
    def get_navigation_label(cls) -> str:
        return __(cls.navigation_label) if cls.navigation_label else cls.get_plural_label()

    @classmethod
    def navigation_badge(cls, ctx: "Context") -> Any:
        """Return a value (e.g. a count) to show next to the menu item."""
        return None

    navigation_badge_color: ClassVar[str] = "primary"

    @classmethod
    def get_record_title(cls, record: Any) -> str:
        if record is None:
            return ""
        if cls.record_title_attribute:
            return str(getattr(record, cls.record_title_attribute, "") or "")
        for attr in ("name", "title", "label", "email"):
            if hasattr(record, attr) and getattr(record, attr):
                return str(getattr(record, attr))
        return f"{cls.get_label()} #{cls.host().record_key(record)}"

    # ------------------------------------------------------------------ search
    @classmethod
    def global_search_title(cls, record: Any) -> str:
        return cls.get_record_title(record)

    @classmethod
    def global_search_details(cls, record: Any) -> dict[str, Any]:
        return {}

    @classmethod
    def global_search_image(cls, record: Any) -> str | None:
        return None

    # ------------------------------------------------------------------ pages / urls
    @classmethod
    def has_page(cls, page: str) -> bool:
        if cls.simple and page in ("create", "edit", "view"):
            return False
        return page in cls.pages

    @classmethod
    def get_url(cls, ctx: "Context", page: str = "index", record: Any = None, **query: Any) -> str:
        slug = cls.get_slug()
        if page == "index":
            return ctx.url(slug, **query)
        if page == "create":
            return ctx.url(slug, "create", **query)
        key = cls.host().record_key(record) if record is not None and not isinstance(record, (str, int)) else record
        if page == "edit":
            return ctx.url(slug, key, "edit", **query)
        if page == "view":
            return ctx.url(slug, key, **query)
        return ctx.url(slug, page, **query)

    @classmethod
    def host(cls):
        from ..hosts import ResourceHost

        return ResourceHost(cls)

    @classmethod
    def get_soft_delete_column(cls) -> str | None:
        from ..hosts import detect_soft_delete

        return detect_soft_delete(cls.model, cls.soft_delete_column)

    @classmethod
    def get_relations(cls) -> list:
        return list(cls.relations)

    # ------------------------------------------------------------------ authorization
    @classmethod
    def permission_prefix(cls) -> str:
        return cls.get_slug()

    @classmethod
    def can(cls, ctx: "Context", ability: str, record: Any = None) -> bool:
        """Policy first (``policy.update(user, record)``), then the panel's RBAC/gate."""
        tenancy = ctx.panel.tenancy
        if ability == "create" and tenancy.enabled and ctx.tenant is None \
                and tenancy.ownership_for(ctx, cls.model, cls) is not None:
            return False  # without a current tenant there is nobody to own the new record
        if cls.policy is not None:
            fn = getattr(cls.policy, ability, None)
            if fn is not None:
                return bool(_call_policy(fn, ctx, ability, record))
        return ctx.can(f"{cls.permission_prefix()}.{ability}", record)

    @classmethod
    def abilities(cls) -> list[str]:
        base = ["view_any", "view", "create", "update", "delete", "delete_any"]
        if cls.get_soft_delete_column():
            base += ["restore", "restore_any", "force_delete", "force_delete_any"]
        return base + list(getattr(cls, "extra_permissions", []))
