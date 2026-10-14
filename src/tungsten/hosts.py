"""Hosts own a table and/or forms and know how to load and save their records.

A resource list page, a relation manager, a table widget and a custom page are
all hosts. The generic ``/_tw/*`` endpoints (table reload, actions, live form
refresh) resolve a host from its key, so every feature works the same way
everywhere.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from .support.evaluate import call

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .forms.form import Form
    from .tables.table import Table


class Host:
    key: str = ""
    model: Any = None
    soft_delete_column: str | None = None

    # ------------------------------------------------------------------ records
    def primary_key(self):
        return sa_inspect(self.model).primary_key[0]

    def record_key(self, record: Any) -> str:
        return str(getattr(record, self.primary_key().key))

    def _typed_key(self, key: Any) -> Any:
        pk = self.primary_key()
        try:
            return pk.type.python_type(key)
        except (TypeError, ValueError, NotImplementedError):
            return key

    def base_query(self, ctx: "Context"):
        return select(self.model)

    def scoped_query(self, ctx: "Context", with_trashed: bool = True):
        query = self.base_query(ctx)
        if not with_trashed and self.soft_delete_column:
            query = query.where(getattr(self.model, self.soft_delete_column).is_(None))
        return query

    def find_record(self, ctx: "Context", key: Any, with_trashed: bool = True) -> Any:
        if key in (None, ""):
            return None
        query = self.scoped_query(ctx, with_trashed).where(self.primary_key() == self._typed_key(key))
        return ctx.db.scalars(query).first()

    def find_records(self, ctx: "Context", keys: list) -> list:
        if not keys:
            return []
        query = self.scoped_query(ctx).where(self.primary_key().in_([self._typed_key(k) for k in keys]))
        return list(ctx.db.scalars(query).all())

    def is_trashed(self, record: Any) -> bool:
        return bool(self.soft_delete_column and getattr(record, self.soft_delete_column, None) is not None)

    def tenant_resource(self) -> Any:
        """The resource whose tenancy settings apply to ``model`` (None: the panel's resource for it)."""
        return None

    # ------------------------------------------------------------------ ui
    def get_table(self, ctx: "Context") -> "Table | None":
        return None

    def page_actions(self, ctx: "Context", record: Any = None) -> list:
        return []

    def page_url(self, ctx: "Context") -> str | None:
        return None

    def can(self, ctx: "Context", ability: str, record: Any = None) -> bool:
        return True

    def title(self) -> str:
        return ""

    def model_label(self) -> str:
        return ""

    def record_title(self, record: Any) -> str:
        return str(record)

    # ------------------------------------------------------------------ crud
    def form(self, ctx: "Context", operation: str, record: Any = None) -> "Form | None":
        return None

    def infolist(self, ctx: "Context", record: Any) -> "Form | None":
        return None

    def create_url(self, ctx: "Context") -> str | None:
        return None

    def edit_url(self, ctx: "Context", record: Any) -> str | None:
        return None

    def view_url(self, ctx: "Context", record: Any) -> str | None:
        return None

    def new_record(self, ctx: "Context") -> Any:
        return self.model()

    def hook(self, name: str, ctx: "Context", **kwargs: Any) -> Any:
        return kwargs.get("data")

    def attach_new(self, ctx: "Context", record: Any) -> None:
        ctx.db.add(record)

    def create(self, ctx: "Context", data: dict, form: "Form") -> Any:
        data = self.hook("mutate_form_data_before_create", ctx, data=data, form=form) or data
        record = self.new_record(ctx)
        self.hook("before_create", ctx, record=record, data=data, form=form)
        form.fill_record(record, data)
        ctx.panel.tenancy.assign(ctx, self.model, record, self.tenant_resource())
        self.attach_new(ctx, record)
        ctx.db.flush()
        form.record = record
        form.save_relationships(record, data)
        self.hook("after_create", ctx, record=record, data=data, form=form)
        ctx.db.commit()
        return record

    def update(self, ctx: "Context", record: Any, data: dict, form: "Form") -> Any:
        data = self.hook("mutate_form_data_before_save", ctx, data=data, record=record, form=form) or data
        self.hook("before_save", ctx, record=record, data=data, form=form)
        form.fill_record(record, data)
        ctx.db.flush()
        form.save_relationships(record, data)
        self.hook("after_save", ctx, record=record, data=data, form=form)
        ctx.db.commit()
        return record

    def delete(self, ctx: "Context", record: Any) -> None:
        self.hook("before_delete", ctx, record=record)
        if self.soft_delete_column:
            setattr(record, self.soft_delete_column, dt.datetime.now())
        else:
            ctx.db.delete(record)
        ctx.db.flush()
        self.hook("after_delete", ctx, record=record)
        ctx.db.commit()

    def restore(self, ctx: "Context", record: Any) -> None:
        if self.soft_delete_column:
            setattr(record, self.soft_delete_column, None)
            self.hook("after_restore", ctx, record=record)
            ctx.db.commit()

    def force_delete(self, ctx: "Context", record: Any) -> None:
        self.hook("before_delete", ctx, record=record)
        ctx.db.delete(record)
        ctx.db.flush()
        self.hook("after_delete", ctx, record=record)
        ctx.db.commit()


def detect_soft_delete(model: Any, column: str | None = "deleted_at") -> str | None:
    if not column:
        return None
    try:
        return column if column in sa_inspect(model).columns else None
    except Exception:  # noqa: BLE001
        return None


class ResourceHost(Host):
    """List/create/edit/view pages of a :class:`~tungsten.Resource`."""

    def __init__(self, resource: type) -> None:
        self.resource = resource
        self.model = resource.model
        self.key = f"resource:{resource.get_slug()}"
        self.soft_delete_column = resource.get_soft_delete_column()

    def base_query(self, ctx: "Context"):
        query = self.resource.query(ctx)
        return ctx.panel.tenancy.scope(ctx, self.model, query, self.resource)

    def tenant_resource(self) -> Any:
        return self.resource

    def get_table(self, ctx: "Context") -> "Table":
        from .tables.table import Table

        table = Table()
        table.ctx = ctx  # so ``table(cls, table)`` can look at the request (bind() sets it again)
        table = self.resource.table(table)
        if table is not None and ctx is not None:
            extra = ctx.panel.record_actions_for(self.resource, "row")  # buttons other plugins add
            if extra:
                table._actions = [*table._actions, *extra]
        return table

    def page_actions(self, ctx: "Context", record: Any = None, page: str | None = None) -> list:
        page = page or ("edit" if record is not None else "list")
        actions = list(self.resource.header_actions(ctx, page, record) or [])
        if record is not None:
            actions = [*ctx.panel.record_actions_for(self.resource, page), *actions]
        return actions

    def all_page_actions(self, ctx: "Context", record: Any = None) -> list:
        out = []
        for page in ("list", "create", "edit", "view"):
            out.extend(self.resource.header_actions(ctx, page, record) or [])
            if record is not None:
                out.extend(ctx.panel.record_actions_for(self.resource, page))
        return out

    def page_url(self, ctx: "Context") -> str | None:
        return self.resource.get_url(ctx, "index")

    def can(self, ctx: "Context", ability: str, record: Any = None) -> bool:
        return self.resource.can(ctx, ability, record)

    def title(self) -> str:
        return self.resource.get_plural_label()

    def model_label(self) -> str:
        return self.resource.get_label()

    def record_title(self, record: Any) -> str:
        return self.resource.get_record_title(record)

    def form(self, ctx: "Context", operation: str, record: Any = None) -> "Form":
        from .forms.form import Form

        blank = Form().model(self.model)
        blank.operation, blank.record = operation, record
        form = self.resource.form(blank)
        form.model(self.model)
        key = self.record_key(record) if record is not None else ""
        form.bind(ctx, operation=operation, record=record,
                  source={"kind": "host", "host": self.key, "op": operation, "record": key})
        return form

    def infolist(self, ctx: "Context", record: Any) -> "Form | None":
        return _build_infolist(self.resource, ctx, self.model, record, self)

    def create_url(self, ctx: "Context") -> str | None:
        return self.resource.get_url(ctx, "create") if self.resource.has_page("create") else None

    def edit_url(self, ctx: "Context", record: Any) -> str | None:
        return self.resource.get_url(ctx, "edit", record) if self.resource.has_page("edit") else None

    def view_url(self, ctx: "Context", record: Any) -> str | None:
        return self.resource.get_url(ctx, "view", record) if self.resource.has_page("view") else None

    def hook(self, name: str, ctx: "Context", **kwargs: Any) -> Any:
        fn = getattr(self.resource, name, None)
        if fn is None:
            return kwargs.get("data")
        return call(fn, **{"ctx": ctx, "db": ctx.db, "user": ctx.user, **kwargs})


class RelationHost(Host):
    """A relation manager table shown on a record's edit/view page (or on its own page).

    ``manager.relationship`` is one relationship (``"orders"``) or a dotted path of them for
    "has many through" (``"teams.projects"``: the projects of the owner's teams). A manager with a
    ``related_resource`` takes that resource's form, table and infolist, and its records open on
    nested pages (``/courses/1/lessons/5/edit``).
    """

    def __init__(self, resource: type, owner: Any, manager: type) -> None:
        from .relations import RelationLink

        self.resource = resource
        self.owner = owner
        self.manager = manager
        self.related_resource = getattr(manager, "related_resource", None)
        self.link = RelationLink(type(owner), manager.relationship, getattr(manager, "linkable", None))
        self.rel = self.link.rel
        self.model = self.link.model
        self.many_to_many = self.link.many_to_many
        owner_key = str(getattr(owner, sa_inspect(type(owner)).primary_key[0].key))
        self.owner_key = owner_key
        self.key = f"relation:{resource.get_slug()}:{owner_key}:{manager.get_name()}"
        column = manager.soft_delete_column
        if self.related_resource is not None and "soft_delete_column" not in manager.__dict__:
            column = self.related_resource.soft_delete_column
        self.soft_delete_column = detect_soft_delete(self.model, column)

    @staticmethod
    def key_of(record: Any) -> str:
        return str(getattr(record, sa_inspect(type(record)).primary_key[0].key))

    def base_query(self, ctx: "Context"):
        query = self.link.query(self.owner)
        if hasattr(self.manager, "query"):
            return call(self.manager.query, query=query, owner=self.owner, ctx=ctx)
        if self.related_resource is not None and "query" in vars(self.related_resource):
            # the nested resource's own scope, limited to this owner's records
            scoped = self.related_resource.query(ctx)
            return scoped.where(self.primary_key().in_(query.with_only_columns(self.primary_key())))
        return query

    def tenant_resource(self) -> Any:
        return self.related_resource

    def _defines(self, name: str) -> bool:
        """Did the manager itself define ``name`` (not just inherit RelationManager's default)?"""
        from .resources.relation_manager import RelationManager

        return getattr(self.manager, name).__func__ is not getattr(RelationManager, name).__func__

    def get_table(self, ctx: "Context") -> "Table":
        from .tables.table import Table

        table = Table()
        table.ctx = ctx
        if self.related_resource is not None and not self._defines("table"):
            return self.related_resource.table(table)
        return self.manager.table(table)

    def can(self, ctx: "Context", ability: str, record: Any = None) -> bool:
        if ability in ("create", "attach", "detach", "associate", "dissociate") and not self.link.linkable:
            return False
        if ability in ("associate", "dissociate") and self.link.many_to_many:
            return False
        if ability == "dissociate" and not self.link.can_unlink_one_to_many():
            return False
        return self.manager.can(ctx, ability, record, owner=self.owner, resource=self.resource)

    def title(self) -> str:
        return self.manager.get_title()

    def model_label(self) -> str:
        if self.related_resource is not None and not self.manager.label:
            return self.related_resource.get_label()
        return self.manager.get_label()

    def record_title(self, record: Any) -> str:
        if self.related_resource is not None and not self.manager.record_title_attribute:
            return self.related_resource.get_record_title(record)
        return self.manager.get_record_title(record)

    def page_url(self, ctx: "Context") -> str | None:
        """The relation's own page, when it has one (the table keeps its state in that URL)."""
        return self.manager.get_url(ctx, self.resource, self.owner) if self.manager.separate_page else None

    def return_url(self, ctx: "Context") -> str | None:
        """Where a nested record page goes after its record is deleted: back to the related records."""
        url = self.page_url(ctx)
        if url:
            return url
        owner_host = self.resource.host()
        if self.resource.has_page("edit") and self.resource.can(ctx, "update", self.owner):
            return owner_host.edit_url(ctx, self.owner)
        return owner_host.view_url(ctx, self.owner) or owner_host.edit_url(ctx, self.owner)

    # nested resources: records open on their own pages under the owner
    def _nested_url(self, ctx: "Context", page: str, record: Any = None) -> str | None:
        if self.related_resource is None or not self.related_resource.has_page(page):
            return None
        return self.manager.get_url(ctx, self.resource, self.owner, page, record)

    def create_url(self, ctx: "Context") -> str | None:
        return self._nested_url(ctx, "create")

    def edit_url(self, ctx: "Context", record: Any) -> str | None:
        return self._nested_url(ctx, "edit", record)

    def view_url(self, ctx: "Context", record: Any) -> str | None:
        return self._nested_url(ctx, "view", record)

    def page_actions(self, ctx: "Context", record: Any = None, page: str | None = None) -> list:
        if self.related_resource is None:
            return []
        page = page or ("edit" if record is not None else "list")
        return list(self.related_resource.header_actions(ctx, page, record) or [])

    def all_page_actions(self, ctx: "Context", record: Any = None) -> list:
        out: list = []
        for page in ("create", "edit", "view"):
            out.extend(self.page_actions(ctx, record, page))
        return out

    def form(self, ctx: "Context", operation: str, record: Any = None) -> "Form":
        from .forms.form import Form

        blank = Form().model(self.model)
        blank.operation, blank.record = operation, record
        if self.related_resource is not None and not self._defines("form"):
            form = self.related_resource.form(blank)
        else:
            form = self.manager.form(blank)
        form.model(self.model)
        return form

    def infolist(self, ctx: "Context", record: Any) -> "Form | None":
        source = self.manager
        if self.related_resource is not None and not self._defines("infolist"):
            source = self.related_resource
        return _build_infolist(source, ctx, self.model, record, self)

    def prepare_records(self, ctx: "Context", records: list) -> None:
        """Give each row a ``pivot`` with the extra columns of the link table (``TextColumn("pivot.role")``)."""
        self.link.load_pivots(ctx.db, self.owner, records)

    def attach_new(self, ctx: "Context", record: Any) -> None:
        if not self.link.linkable:
            raise PermissionError("Records can't be created through this relationship")
        ctx.db.add(record)
        self.link.link(ctx.db, self.owner, [record])

    def hook(self, name: str, ctx: "Context", **kwargs: Any) -> Any:
        fn = getattr(self.manager, name, None)
        if fn is None and self.related_resource is not None:
            fn = getattr(self.related_resource, name, None)
        if fn is None:
            return kwargs.get("data")
        return call(fn, **{"ctx": ctx, "db": ctx.db, "owner": self.owner, "user": ctx.user, **kwargs})

    def detach(self, ctx: "Context", record: Any) -> None:
        self.link.unlink(ctx.db, self.owner, [record])
        ctx.db.commit()

    def attach(self, ctx: "Context", records: list, pivot: dict | None = None) -> None:
        self.link.link(ctx.db, self.owner, records, pivot=pivot)
        ctx.db.commit()

    def associate(self, ctx: "Context", records: list) -> None:
        self.link.link(ctx.db, self.owner, records)
        ctx.db.commit()

    def dissociate(self, ctx: "Context", records: list) -> None:
        self.link.unlink(ctx.db, self.owner, records)
        ctx.db.commit()

    def delete(self, ctx: "Context", record: Any) -> None:
        if self.many_to_many:
            self.link.unlink(ctx.db, self.owner, [record])
            ctx.db.flush()
            super().delete(ctx, record)
            return
        super().delete(ctx, record)


def _build_infolist(owner: Any, ctx: "Context", model: Any, record: Any, host: Any = None) -> "Form | None":
    from .infolists import Infolist

    blank = Infolist().model(model)
    blank._host = host  # type: ignore[attr-defined]
    blank.operation, blank.record = "view", record
    infolist = owner.infolist(blank)
    if infolist is None:
        return None
    infolist.model(model)
    infolist._host = host  # type: ignore[attr-defined]
    infolist.bind(ctx, record=record, id="tw-infolist")
    return infolist
