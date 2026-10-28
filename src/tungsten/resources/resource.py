"""A :class:`Resource` turns one SQLAlchemy model into list/create/edit/view pages."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import select

from ..i18n import translate as __
from ..support.component import headline
from ..support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..forms.form import Form
    from ..tables.table import Table


@lru_cache(maxsize=1024)
def _plural(word: str) -> str:
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", word):
        return word + "es"
    return word + "s"


@lru_cache(maxsize=1024)
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
    #: a :class:`~tungsten.navigation.Cluster`: the resource then sits in that cluster's sub-menu
    cluster: ClassVar[Any] = None
    #: sub-menu on a record's pages: page names (``"view"``, ``"edit"``), relation manager slugs and/or
    #: ``NavigationItem``s. Empty: tabs for the record and its relations on separate pages, if any.
    record_sub_navigation: ClassVar[tuple] = ()
    #: where that sub-menu goes: ``"start"``, ``"end"`` or ``"top"`` (tabs). None: ``"start"`` when
    #: ``record_sub_navigation`` is set, else ``"top"``
    sub_navigation_position: ClassVar[str | None] = None

    # records
    record_title_attribute: ClassVar[str | None] = None
    global_search_attributes: ClassVar[list[str]] = []
    global_search_limit: ClassVar[int] = 5
    soft_delete_column: ClassVar[str | None] = "deleted_at"

    # pages: index, create, edit, view. A "simple" resource uses modals only.
    pages: ClassVar[tuple[str, ...]] = ("index", "create", "edit", "view")
    #: more pages under this resource's address, e.g. ``{"generate": GenerateProducts}`` for
    #: ``/products/generate`` (Filament's ``'generate' => Pages\GenerateThings::route('/generate')``).
    #: Each is a :class:`~tungsten.Page`; only users who may list this resource can open it.
    custom_pages: ClassVar[dict[str, Any]] = {}
    simple: ClassVar[bool] = False

    relations: ClassVar[list] = []
    widgets: ClassVar[list] = []

    # nested resources: records live under a parent record (``/courses/1/lessons/5/edit``).
    # The parent lists them with ``RelationManager(related_resource=...)``; set these so the
    # resource leaves the menu and links to its records (global search...) use the nested URLs.
    parent_resource: ClassVar[Any] = None
    #: the to-one relationship from this model to its parent (``"course"``)
    parent_relationship: ClassVar[str | None] = None

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
    def get_plural_label(cls, ctx: "Context | None" = None) -> str:
        """The plural label, translated (``Products``). Override with a ``ctx`` argument to change it per user."""
        return __(cls.plural_label or _plural(cls._raw_label()))

    @classmethod
    def plural_label_for(cls, ctx: "Context | None") -> str:
        """:meth:`get_plural_label` for this request (passes ``ctx`` when the override takes it)."""
        return str(call(cls.get_plural_label, ctx=ctx, user=getattr(ctx, "user", None)))

    @classmethod
    def get_description(cls, ctx: "Context | None" = None) -> str | None:
        """The line under the list (and create) page title: ``description``, or override per user."""
        return __(cls.description) if cls.description else None

    @classmethod
    def get_navigation_group(cls, ctx: "Context | None" = None) -> str | None:
        """The sidebar group: ``navigation_group``, or override to pick one per user."""
        return cls.navigation_group

    @classmethod
    def page_title(cls, ctx: "Context", page: str, record: Any = None) -> str | None:
        """Your own title for a page (``page`` is list, create, edit or view). None keeps the usual one."""
        return None

    @classmethod
    def page_subheading(cls, ctx: "Context", page: str, record: Any = None) -> str | None:
        """Your own line under a page's title. None keeps the usual one."""
        return None

    @classmethod
    def get_slug(cls) -> str:
        if cls.slug:
            return cls.slug
        return _plural(_kebab(cls.model.__name__)) if cls.model else _kebab(cls.__name__)

    @classmethod
    def get_navigation_label(cls, ctx: "Context | None" = None) -> str:
        """The menu label. Override with a ``ctx`` argument to change it per user."""
        return __(cls.navigation_label) if cls.navigation_label else cls.plural_label_for(ctx)

    @classmethod
    def navigation_badge(cls, ctx: "Context") -> Any:
        """Return a value (e.g. a count) to show next to the menu item."""
        return None

    @classmethod
    def navigation_badge_tooltip(cls, ctx: "Context") -> str | None:
        """Hover text for the menu badge (e.g. "3 waiting for you")."""
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
    def parent_manager(cls) -> Any:
        """The parent's relation manager that nests this resource."""
        parent = cls.parent_resource
        if parent is None:
            return None
        return next((m for m in parent.get_relations() if getattr(m, "related_resource", None) is cls), None)

    @classmethod
    def get_url(cls, ctx: "Context", page: str = "index", record: Any = None, **query: Any) -> str:
        if cls.parent_resource is not None and cls.parent_relationship and page in ("edit", "view") \
                and record is not None and not isinstance(record, (str, int)):
            owner = getattr(record, cls.parent_relationship, None)
            manager = cls.parent_manager()
            if owner is not None and manager is not None:
                return manager.get_url(ctx, cls.parent_resource, owner, page, record, **query)
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
    def get_record_sub_navigation(cls, ctx: "Context", record: Any) -> list:
        """The sub-menu on ``record``'s pages. Override to add links that depend on the record::

            @classmethod
            def get_record_sub_navigation(cls, ctx, record):
                return super().get_record_sub_navigation(ctx, record) + [
                    NavigationItem("Invoices", InvoiceResource.get_url(ctx, customer=record.id), icon="receipt"),
                ]
        """
        from ..hosts import RelationHost
        from ..navigation import NavigationItem
        from ..support.evaluate import call

        entries = list(cls.record_sub_navigation)
        if not entries:
            separate = [m.get_slug() for m in cls.get_relations() if m.separate_page]
            if not separate:
                return []
            entries = ["view" if cls.has_page("view") else "edit", *separate]
        names = {"view": ("View", "eye"), "edit": ("Edit", "pencil")}
        ability = {"view": "view", "edit": "update"}
        managers = {m.get_slug(): m for m in cls.get_relations()}
        out = []
        for entry in entries:
            if isinstance(entry, NavigationItem):
                out.append(entry)
            elif entry in names:
                if cls.has_page(entry) and cls.can(ctx, ability[entry], record):
                    label, icon = names[entry]
                    out.append(NavigationItem(__(label), cls.get_url(ctx, entry, record), icon=icon))
            else:
                manager = entry if isinstance(entry, type) else managers.get(entry)
                if manager is None or not RelationHost(cls, record, manager).can(ctx, "view_any"):
                    continue
                url = manager.get_url(ctx, cls, record) if manager.separate_page else cls.get_url(
                    ctx, "view" if cls.has_page("view") else "edit", record)
                out.append(NavigationItem(manager.get_title(), url, icon=manager.icon,
                                          badge=call(manager.badge, ctx=ctx, owner=record)))
        return out

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
