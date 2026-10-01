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
        ctx.panel.tenancy.assign(ctx, self.model, record)
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
        return ctx.panel.tenancy.scope(ctx, self.model, query)

    def get_table(self, ctx: "Context") -> "Table":
        from .tables.table import Table

        table = self.resource.table(Table())
        return table

    def page_actions(self, ctx: "Context", record: Any = None, page: str | None = None) -> list:
        page = page or ("edit" if record is not None else "list")
        return list(self.resource.header_actions(ctx, page, record) or [])

    def all_page_actions(self, ctx: "Context", record: Any = None) -> list:
        out = []
        for page in ("list", "create", "edit", "view"):
            out.extend(self.resource.header_actions(ctx, page, record) or [])
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
    """A relation manager table shown on a record's edit/view page."""

    def __init__(self, resource: type, owner: Any, manager: type) -> None:
        self.resource = resource
        self.owner = owner
        self.manager = manager
        rel = sa_inspect(type(owner)).relationships[manager.relationship]
        self.rel = rel
        self.model = rel.mapper.class_
        self.many_to_many = rel.secondary is not None
        owner_key = str(getattr(owner, sa_inspect(type(owner)).primary_key[0].key))
        self.owner_key = owner_key
        self.key = f"relation:{resource.get_slug()}:{owner_key}:{manager.get_name()}"
        self.soft_delete_column = detect_soft_delete(self.model, manager.soft_delete_column)

    def base_query(self, ctx: "Context"):
        from sqlalchemy.orm import with_parent

        query = select(self.model).where(with_parent(self.owner, getattr(type(self.owner), self.manager.relationship)))
        return call(self.manager.query, query=query, owner=self.owner, ctx=ctx) if hasattr(self.manager, "query") else query

    def get_table(self, ctx: "Context") -> "Table":
        from .tables.table import Table

        return self.manager.table(Table())

    def can(self, ctx: "Context", ability: str, record: Any = None) -> bool:
        return self.manager.can(ctx, ability, record, owner=self.owner, resource=self.resource)

    def title(self) -> str:
        return self.manager.get_title()

    def model_label(self) -> str:
        return self.manager.get_label()

    def record_title(self, record: Any) -> str:
        return self.manager.get_record_title(record)

    def page_url(self, ctx: "Context") -> str | None:
        return None

    def form(self, ctx: "Context", operation: str, record: Any = None) -> "Form":
        from .forms.form import Form

        blank = Form().model(self.model)
        blank.operation, blank.record = operation, record
        form = self.manager.form(blank)
        form.model(self.model)
        return form

    def attach_new(self, ctx: "Context", record: Any) -> None:
        getattr(self.owner, self.manager.relationship).append(record)
        ctx.db.add(record)

    def hook(self, name: str, ctx: "Context", **kwargs: Any) -> Any:
        fn = getattr(self.manager, name, None)
        if fn is None:
            return kwargs.get("data")
        return call(fn, **{"ctx": ctx, "db": ctx.db, "owner": self.owner, "user": ctx.user, **kwargs})

    def detach(self, ctx: "Context", record: Any) -> None:
        collection = getattr(self.owner, self.manager.relationship)
        if record in collection:
            collection.remove(record)
        ctx.db.commit()

    def attach(self, ctx: "Context", records: list) -> None:
        collection = getattr(self.owner, self.manager.relationship)
        for r in records:
            if r not in collection:
                collection.append(r)
        ctx.db.commit()

    def delete(self, ctx: "Context", record: Any) -> None:
        if self.many_to_many:
            self.detach(ctx, record)
            ctx.db.delete(record)
            ctx.db.commit()
            return
        super().delete(ctx, record)
