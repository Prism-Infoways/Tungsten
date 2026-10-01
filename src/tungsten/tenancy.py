"""Multi-tenancy: scope records to the current team/company.

    panel = Panel(..., tenancy=Tenancy(Team, ownership="team_id",
                                      tenants=lambda user, db: user.teams))

Every resource whose model has the ``ownership`` column is filtered by the
current tenant, and new records get it set automatically. Users switch tenant
from the user menu.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from sqlalchemy import inspect as sa_inspect

from .support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context


class NoTenancy:
    enabled = False

    def resolve(self, ctx: "Context") -> Any:
        return None

    def scope(self, ctx: "Context", model: Any, query: Any) -> Any:
        return query

    def assign(self, ctx: "Context", model: Any, record: Any) -> None:
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

    def _owned(self, model: Any) -> bool:
        try:
            return self.ownership in sa_inspect(model).columns
        except Exception:  # noqa: BLE001
            return False

    def scope(self, ctx: "Context", model: Any, query: Any) -> Any:
        if ctx.tenant is None or not self._owned(model):
            return query
        return query.where(getattr(model, self.ownership) == getattr(ctx.tenant, sa_inspect(type(ctx.tenant)).primary_key[0].key))

    def assign(self, ctx: "Context", model: Any, record: Any) -> None:
        if ctx.tenant is None or not self._owned(model):
            return
        if getattr(record, self.ownership, None) is None:
            setattr(record, self.ownership, getattr(ctx.tenant, sa_inspect(type(ctx.tenant)).primary_key[0].key))
