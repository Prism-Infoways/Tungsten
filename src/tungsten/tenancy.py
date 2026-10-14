"""Multi-tenancy: scope records to the current team/company.

    panel = Panel(..., tenancy=Tenancy(Team, ownership="team_id",
                                      tenants=lambda user, db: user.teams))

Every resource whose model has the ``ownership`` column is filtered by the
current tenant, and new records get it set automatically. Users switch tenant
from the user menu. A user without any tenant sees no tenant-owned records.

A resource can name another column or relationship with ``tenant_ownership``,
or opt out (a model shared by all tenants) with ``tenant_scoped = False``.

With ``url=True`` the tenant sits in every link (``/admin/{tenant}/products``),
so two browser tabs can show two tenants. ``registration`` and ``profile`` add
"new team" and "team settings" pages, and ``billing`` plugs in a subscription
check (see :class:`BillingProvider`).
"""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy import event, false
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, with_loader_criteria

from .support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context

#: slug of the tenant in the current request's URL; ``Panel.url`` puts it in every link
_url_slug: contextvars.ContextVar[str | None] = contextvars.ContextVar("tungsten_tenant_slug", default=None)


def current_url_slug() -> str | None:
    return _url_slug.get()


def set_url_slug(slug: str | None) -> Any:
    return _url_slug.set(slug)


def reset_url_slug(token: Any) -> None:
    _url_slug.reset(token)


#: set inside ``with tenancy.unscoped():`` so session-level scoping steps aside on purpose
_unscoped: contextvars.ContextVar[bool] = contextvars.ContextVar("tungsten_tenant_unscoped", default=False)
#: key in ``Session.info`` holding the current tenant's scope (set by :meth:`Tenancy.bind`)
SCOPE_INFO = "tungsten_tenant_scope"
_listening = False


def _install_listeners() -> None:
    """Hook every ORM session once; sessions without a bound tenant scope are left alone."""
    global _listening
    if _listening:
        return
    _listening = True
    event.listen(Session, "do_orm_execute", _filter_statement)
    event.listen(Session, "before_flush", _set_ownership)


def _filter_statement(state: Any) -> None:
    scope = state.session.info.get(SCOPE_INFO)
    if scope is None or _unscoped.get() or state.execution_options.get("tungsten_unscoped"):
        return
    if not (state.is_select or state.is_update or state.is_delete) or state.is_column_load:
        return
    key = scope["key"]
    options = []
    for model, column in scope["models"].items():
        criteria = false() if key is None else (column == key)
        options.append(with_loader_criteria(model, criteria, include_aliases=True))
    if options:
        state.statement = state.statement.options(*options)


def _set_ownership(session: Any, flush_context: Any, instances: Any) -> None:
    scope = session.info.get(SCOPE_INFO)
    if scope is None or scope["key"] is None or _unscoped.get():
        return
    for obj in session.new:
        column = scope["models"].get(type(obj))
        if column is not None and getattr(obj, column.key, None) is None:
            setattr(obj, column.key, scope["key"])


class BillingProvider:
    """Hooks for tenant subscriptions (Stripe, Paddle, Razorpay...). Subclass it::

        class StripeBilling(BillingProvider):
            def is_subscribed(self, ctx, tenant):
                return tenant.subscription_status == "active"

            def billing_url(self, ctx, tenant):
                return stripe.billing_portal.Session.create(customer=tenant.stripe_id,
                                                            return_url=ctx.panel.absolute_url(ctx, ctx.url())).url

        Tenancy(Team, ..., billing=StripeBilling(), require_subscription=True)

    The tenant menu gets a "Billing" link (``/{tenant}/tenant/billing``) that sends the user to
    :meth:`billing_url`. With ``require_subscription=True`` every panel page sends users of an
    unsubscribed tenant there first.
    """

    label: str = "Billing"
    icon: str = "credit-card"

    def is_subscribed(self, ctx: "Context", tenant: Any) -> bool:
        return True

    def billing_url(self, ctx: "Context", tenant: Any) -> str | None:
        """Where the Billing link goes (an external portal). ``None`` shows :meth:`content` instead."""
        return None

    def content(self, ctx: "Context", tenant: Any) -> Any:
        """HTML for a billing page inside the panel, used when :meth:`billing_url` returns ``None``."""
        return None

    def can_manage(self, ctx: "Context", tenant: Any) -> bool:
        """Who may open the billing page (everyone in the tenant by default)."""
        return True


class NoTenancy:
    enabled = False
    in_url = False
    registration = None
    profile = None
    billing = None

    def resolve(self, ctx: "Context") -> Any:
        return None

    def ownership_for(self, ctx: "Context | None", model: Any, resource: Any = None) -> str | None:
        return None

    def scope(self, ctx: "Context", model: Any, query: Any, resource: Any = None) -> Any:
        return query

    def assign(self, ctx: "Context", model: Any, record: Any, resource: Any = None) -> None:
        return None

    def tenants(self, ctx: "Context") -> list:
        return []


class Tenancy(NoTenancy):
    enabled = True

    def __init__(
        self,
        model: Any,
        *,
        ownership: str = "tenant_id",
        tenants: Callable,
        label_attribute: str = "name",
        session_key: str = "tw_tenant",
        url: bool = False,
        slug_attribute: str | None = None,
        registration: Any = None,
        on_register: Callable | None = None,
        profile: Any = None,
        can_edit_profile: Callable | None = None,
        billing: BillingProvider | None = None,
        require_subscription: bool = False,
        avatar_attribute: str | None = None,
        label: str | None = None,
        scope_session: bool = False,
    ) -> None:
        self.model = model
        self.ownership = ownership
        self._tenants = tenants
        self.label_attribute = label_attribute
        self.session_key = session_key
        #: put the tenant in the URL: ``/admin/{tenant}/products``
        self.in_url = url
        #: attribute used in the URL (default: the primary key)
        self.slug_attribute = slug_attribute
        #: fields (a list, or ``fn(form) -> form``) of the "Register new team" page; None hides it
        self.registration = registration
        #: ``fn(tenant, user, db, ctx)`` after a tenant is registered: link the user to it here
        self.on_register = on_register
        #: fields (a list, or ``fn(form) -> form``) of the tenant's settings page; None hides it
        self.profile = profile
        self.can_edit_profile = can_edit_profile
        self.billing = billing
        self.require_subscription = require_subscription
        self.avatar_attribute = avatar_attribute
        #: what a tenant is called in the menu ("Team", "Company"); defaults to the model's name
        self.tenant_label = label
        #: filter every ORM query on the panel's sessions (custom pages, widgets, routes, jobs, MCP tools),
        #: not only the queries Tungsten builds, like a Laravel global scope; see :meth:`unscoped`
        self.scope_session = scope_session
        if scope_session:
            _install_listeners()

    # ------------------------------------------------------------------ session-level scope
    def owned_columns(self, panel: Any) -> dict[Any, Any]:
        """``{model: column}`` for every model of the app that belongs to a tenant by a column (or a
        many-to-one relationship's column), after the resources' ``tenant_scoped`` / ``tenant_ownership``."""
        cache = getattr(self, "_owned_columns", None)
        if cache is not None and cache[0] is panel:
            return cache[1]
        out: dict[Any, Any] = {}
        for mapper in self.model.registry.mappers:
            model = mapper.class_
            attribute = self.ownership_for(None, model, panel.resource_for_model(model) if panel else None)
            if attribute is None:
                continue
            if attribute in mapper.columns:
                out[model] = getattr(model, attribute)
            elif attribute in mapper.relationships:
                rel = mapper.relationships[attribute]
                if not rel.uselist and len(rel.local_columns) == 1:
                    out[model] = getattr(model, mapper.get_property_by_column(next(iter(rel.local_columns))).key)
        self._owned_columns = (panel, out)
        return out

    def bind(self, ctx: "Context") -> None:
        """Filter ``ctx.db`` by ``ctx.tenant`` (called when the tenant is set). Without a signed-in user the
        session stays unfiltered, so sign-in can find the user."""
        db = getattr(ctx, "db", None)
        if db is None:
            return
        info = db.info
        if ctx.user is None:
            info.pop(SCOPE_INFO, None)
            return
        key = self._tenant_key(ctx.tenant) if ctx.tenant is not None else None
        info[SCOPE_INFO] = {"key": key, "models": self.owned_columns(ctx.panel)}

    @staticmethod
    @contextlib.contextmanager
    def unscoped() -> Iterator[None]:
        """Step outside the session-level scope on purpose (super-admin screens, reports over all tenants)::

            with Tenancy.unscoped():
                total = db.scalar(select(func.count()).select_from(Order))

        One statement can also opt out with ``.execution_options(tungsten_unscoped=True)``.
        """
        token = _unscoped.set(True)
        try:
            yield
        finally:
            _unscoped.reset(token)

    def get_label(self) -> str:
        from .i18n import translate as __
        from .support.component import headline

        return __(self.tenant_label or headline(self.model.__name__))

    def register(self, ctx: "Context", data: dict, form: Any) -> Any:
        """Create a tenant from the registration form, link the user to it and make it current."""
        tenant = self.model()
        form.fill_record(tenant, data)
        ctx.db.add(tenant)
        ctx.db.flush()
        form.record = tenant
        form.save_relationships(tenant, data)
        if self.on_register is not None:
            call(self.on_register, tenant=tenant, user=ctx.user, db=ctx.db, ctx=ctx)
        ctx.db.commit()
        self.forget(ctx)
        ctx.session[self.session_key] = self.key_of(tenant)
        ctx.tenant = tenant
        return tenant

    def update_profile(self, ctx: "Context", data: dict, form: Any) -> Any:
        form.fill_record(ctx.tenant, data)
        ctx.db.flush()
        form.save_relationships(ctx.tenant, data)
        ctx.db.commit()
        return ctx.tenant

    def key_of(self, tenant: Any) -> str:
        pk = sa_inspect(type(tenant)).primary_key[0]
        return str(getattr(tenant, pk.key))

    def slug_of(self, tenant: Any) -> str:
        """The tenant's part of the URL."""
        if self.slug_attribute:
            return str(getattr(tenant, self.slug_attribute))
        return self.key_of(tenant)

    def find(self, ctx: "Context", slug: str) -> Any:
        """The user's tenant with this URL slug, or None (other tenants are never found)."""
        for t in self.tenants(ctx):
            if self.slug_of(t) == str(slug):
                return t
        return None

    def url(self, ctx: "Context", tenant: Any, *parts: Any, **query: Any) -> str:
        """A link to ``parts`` inside ``tenant`` (the panel home when no parts)."""
        token = set_url_slug(self.slug_of(tenant) if self.in_url else None)
        try:
            return ctx.panel.url(*parts, **query)
        finally:
            reset_url_slug(token)

    def avatar(self, tenant: Any) -> str | None:
        return getattr(tenant, self.avatar_attribute, None) if self.avatar_attribute and tenant is not None else None

    def can_profile(self, ctx: "Context") -> bool:
        if self.profile is None or ctx.tenant is None:
            return False
        if self.can_edit_profile is None:
            return True
        return bool(call(self.can_edit_profile, user=ctx.user, tenant=ctx.tenant, ctx=ctx, db=ctx.db))

    def can_billing(self, ctx: "Context") -> bool:
        return self.billing is not None and ctx.tenant is not None and bool(self.billing.can_manage(ctx, ctx.tenant))

    def build_form(self, ctx: "Context", which: str, record: Any = None) -> Any:
        """The registration or profile form, bound for live refresh."""
        from .forms import Form

        spec = self.registration if which == "register" else self.profile
        form = Form().model(self.model)
        form = spec(form) if callable(spec) else form.schema(list(spec or []))
        form.bind(ctx, operation="create" if which == "register" else "edit", record=record,
                  source={"kind": "host", "host": f"tenant-{which}", "op": "edit", "record": ""})
        return form

    def tenants(self, ctx: "Context") -> list:
        if ctx.user is None:
            return []
        cached = getattr(ctx, "_tw_tenants", None)  # asked for by the resolver, the switcher and the URL check
        if cached is not None and cached[0] is ctx.user:
            return list(cached[1])
        options = list(call(self._tenants, user=ctx.user, db=ctx.db, ctx=ctx) or [])
        ctx._tw_tenants = (ctx.user, options)
        return list(options)

    def forget(self, ctx: "Context") -> None:
        """Drop the cached tenant list (after a new tenant is registered)."""
        ctx.__dict__.pop("_tw_tenants", None)

    def resolve(self, ctx: "Context") -> Any:
        """The current tenant: the one in the URL (``url=True``), else the last one picked."""
        slug = ctx.request.scope.get("tw_tenant") if self.in_url else None
        if slug is not None:
            tenant = self.find(ctx, slug)
            if tenant is not None and "session" in ctx.request.scope:
                ctx.session[self.session_key] = self.key_of(tenant)
            return tenant
        options = self.tenants(ctx)
        if not options:
            return None
        wanted = ctx.session.get(self.session_key)
        for t in options:
            if self.key_of(t) == str(wanted):
                return t
        ctx.session[self.session_key] = self.key_of(options[0])
        return options[0]

    def switch(self, ctx: "Context", key: str) -> Any:
        """Make the user's tenant with this key the current one; returns it (None when not theirs)."""
        for t in self.tenants(ctx):
            if self.key_of(t) == str(key):
                ctx.session[self.session_key] = self.key_of(t)
                return t
        return None

    def label(self, tenant: Any) -> str:
        return str(getattr(tenant, self.label_attribute, tenant)) if tenant is not None else ""

    def _has(self, model: Any, attribute: str) -> bool:
        try:
            mapper = sa_inspect(model)
        except Exception:  # noqa: BLE001
            return False
        return attribute in mapper.columns or attribute in mapper.relationships

    def _owned(self, model: Any) -> bool:
        return self._has(model, self.ownership)

    def ownership_for(self, ctx: "Context | None", model: Any, resource: Any = None) -> str | None:
        """The column or relationship that links ``model`` to a tenant, or None when it is not scoped.

        ``resource`` (or else the panel's resource for ``model``) can opt out with
        ``tenant_scoped = False`` or name another attribute with ``tenant_ownership``.
        """
        if resource is None and ctx is not None and model is not None:
            resource = ctx.panel.resource_for_model(model)
        if resource is not None:
            if not getattr(resource, "tenant_scoped", True):
                return None
            if getattr(resource, "tenant_ownership", None):
                return resource.tenant_ownership
        return self.ownership if self._owned(model) else None

    def _tenant_key(self, tenant: Any) -> Any:
        return getattr(tenant, sa_inspect(type(tenant)).primary_key[0].key)

    def scope(self, ctx: "Context", model: Any, query: Any, resource: Any = None) -> Any:
        attribute = self.ownership_for(ctx, model, resource)
        if attribute is None:
            return query
        if ctx.tenant is None:
            # no current tenant (the user belongs to none): show nothing rather than everything
            return query.where(false())
        mapper = sa_inspect(model)
        if attribute in mapper.relationships:
            rel = mapper.relationships[attribute]
            target_pk = getattr(rel.mapper.class_, rel.mapper.primary_key[0].key)
            match = target_pk == self._tenant_key(ctx.tenant)
            prop = getattr(model, attribute)
            return query.where(prop.any(match) if rel.uselist else prop.has(match))
        return query.where(getattr(model, attribute) == self._tenant_key(ctx.tenant))

    def assign(self, ctx: "Context", model: Any, record: Any, resource: Any = None) -> None:
        attribute = self.ownership_for(ctx, model, resource)
        if attribute is None:
            return
        if ctx.tenant is None:
            raise PermissionError("No tenant is selected, so records can't be created here.")
        mapper = sa_inspect(model)
        if attribute in mapper.relationships:
            rel = mapper.relationships[attribute]
            if rel.uselist:
                collection = getattr(record, attribute)
                if not collection:
                    collection.append(ctx.tenant)
                return
            local_keys = [mapper.get_property_by_column(c).key for c in rel.local_columns]
            if getattr(record, attribute, None) is None and all(getattr(record, k, None) is None for k in local_keys):
                setattr(record, attribute, ctx.tenant)
            return
        if getattr(record, attribute, None) is None:
            setattr(record, attribute, self._tenant_key(ctx.tenant))


class TenantHost:
    """Lets the tenant registration and settings forms use live refresh (``/_tw/form``)."""

    model = None
    soft_delete_column = None

    def __init__(self, tenancy: Tenancy, which: str) -> None:
        self.tenancy = tenancy
        self.which = which
        self.key = f"tenant-{which}"
        self.model = tenancy.model

    def can(self, ctx: "Context", ability: str, record: Any = None) -> bool:
        if self.which == "register":
            return ctx.user is not None and self.tenancy.registration is not None
        return self.tenancy.can_profile(ctx)

    def find_record(self, ctx: "Context", key: Any, with_trashed: bool = True) -> Any:
        return ctx.tenant if self.which == "profile" else None

    def record_key(self, record: Any) -> str:
        return self.tenancy.key_of(record)

    def form(self, ctx: "Context", operation: str = "edit", record: Any = None) -> Any:
        return self.tenancy.build_form(ctx, self.which, ctx.tenant if self.which == "profile" else None)

    def tenant_resource(self) -> Any:
        return None
