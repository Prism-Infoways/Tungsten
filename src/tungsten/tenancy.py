"""Multi-tenancy: scope records to the current team/company.

    panel = Panel(..., tenancy=Tenancy(Team, ownership="team_id",
                                      tenants=lambda user, db: user.teams))

Every resource whose model has the ``ownership`` column is filtered by the
current tenant, and new records get it set automatically. Users switch tenant
from the user menu. A user without any tenant sees no tenant-owned records.

A resource can name another column or relationship with ``tenant_ownership``,
or opt out (a model shared by all tenants) with ``tenant_scoped = False``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy import false
from sqlalchemy import inspect as sa_inspect

from .support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context


class NoTenancy:
    enabled = False

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
    ) -> None:
        self.model = model
        self.ownership = ownership
        self._tenants = tenants
        self.label_attribute = label_attribute
        self.session_key = session_key

    def key_of(self, tenant: Any) -> str:
        pk = sa_inspect(type(tenant)).primary_key[0]
        return str(getattr(tenant, pk.key))

    def tenants(self, ctx: "Context") -> list:
        if ctx.user is None:
            return []
        return list(call(self._tenants, user=ctx.user, db=ctx.db, ctx=ctx) or [])

    def resolve(self, ctx: "Context") -> Any:
        options = self.tenants(ctx)
        if not options:
            return None
        wanted = ctx.session.get(self.session_key)
        for t in options:
            if self.key_of(t) == str(wanted):
                return t
        ctx.session[self.session_key] = self.key_of(options[0])
        return options[0]

    def switch(self, ctx: "Context", key: str) -> bool:
        for t in self.tenants(ctx):
            if self.key_of(t) == str(key):
                ctx.session[self.session_key] = self.key_of(t)
                return True
        return False

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
