"""Ready-made actions: create, edit, view, delete, restore, replicate, attach..."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..i18n import translate as __
from ..support.evaluate import call
from .action import Action, BulkAction

if TYPE_CHECKING:  # pragma: no cover
    from ..context import Context
    from ..forms.form import Form
    from ..hosts import Host


class RecordFormAction(Action):
    """Base for actions that show the host's own form in a modal (create/edit/view)."""

    operation = "create"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._form = True  # marker: uses host form
        self._modal_width = "2xl"
        self._mutate: Any = None
        self._using: Any = None

    def mutate_form_data_using(self, fn: Any) -> "RecordFormAction":
        self._mutate = fn
        return self

    def using(self, fn: Any) -> "RecordFormAction":
        """Replace the save logic: ``using(lambda data, record, ctx: ...)``."""
        self._using = fn
        return self

    def build_form(self, ctx: "Context", host: "Host | None", record: Any = None, records: Any = None) -> "Form | None":
        if self._form is not True:
            return super().build_form(ctx, host, record, records)
        form = host.form(ctx, self.operation, record) if host else None
        if form is not None:
            form.operation = self.operation
            form.record = record
        return form

    def fill(self, form: "Form", ctx: "Context", record: Any = None, records: Any = None) -> None:
        if self.operation == "create":
            form.fill(None)
        else:
            form.fill(record)
        if self._fill_form is not None:
            data = call(self._fill_form, **self.ev(ctx, record, records, form=form)) or {}
            for key, value in data.items():
                form.set(key, value)


class CreateAction(RecordFormAction):
    operation = "create"

    def __init__(self, name: str = "create") -> None:
        super().__init__(name)
        self._icon = "plus"
        self._authorize = "create"
        self._success_title = "Created"
        self._create_another = True

    def create_another(self, condition: bool = True) -> "CreateAction":
        """Show a "Create & create another" button in the modal (on by default). It saves, then
        opens an empty form again."""
        self._create_another = condition
        return self

    def get_label(self, ev: dict | None = None) -> str:
        if self._label is None and ev and ev.get("host") is not None:
            return __("New :label", label=ev["host"].model_label().lower())
        return super().get_label(ev)

    def view_data(self, ctx, host, record=None, **kw):  # type: ignore[override]
        v = super().view_data(ctx, host, None, **kw)
        if self._url is None and host is not None and host.create_url(ctx):
            v["url"] = host.create_url(ctx)
            v["modal"] = False
        return v

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        if self._action is not None:
            return super().run(ctx, host, record, records, data, form)
        if self._mutate:
            data = call(self._mutate, data=data, ctx=ctx) or data
        if self._using:
            return call(self._using, data=data, ctx=ctx, form=form, host=host)
        return host.create(ctx, data, form)


class EditAction(RecordFormAction):
    operation = "edit"

    def __init__(self, name: str = "edit") -> None:
        super().__init__(name)
        self._icon = "square-pen"
        self._color = "gray"
        self._authorize = "update"
        self._success_title = "Saved"

    def view_data(self, ctx, host, record=None, **kw):  # type: ignore[override]
        v = super().view_data(ctx, host, record, **kw)
        if self._url is None and host is not None and record is not None and host.edit_url(ctx, record):
            v["url"] = host.edit_url(ctx, record)
            v["modal"] = False
        return v

    def is_available(self, host, ctx, record=None) -> bool:  # type: ignore[override]
        return super().is_available(host, ctx, record) and not (host and record is not None and host.is_trashed(record))

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        if self._action is not None:
            return super().run(ctx, host, record, records, data, form)
        if self._mutate:
            data = call(self._mutate, data=data, record=record, ctx=ctx) or data
        if self._using:
            return call(self._using, data=data, record=record, ctx=ctx, form=form, host=host)
        return host.update(ctx, record, data, form)


class ViewAction(RecordFormAction):
    operation = "view"

    def build_form(self, ctx, host, record=None, records=None):  # type: ignore[override]
        if self._form is True and host is not None and record is not None:
            infolist = host.infolist(ctx, record)
            if infolist is not None:
                return infolist
        return super().build_form(ctx, host, record, records)

    def __init__(self, name: str = "view") -> None:
        super().__init__(name)
        self._icon = "eye"
        self._color = "gray"
        self._authorize = "view"
        self._modal_submit_label = None
        self._modal_cancel_label = "Close"

    def view_data(self, ctx, host, record=None, **kw):  # type: ignore[override]
        v = super().view_data(ctx, host, record, **kw)
        if self._url is None and host is not None and record is not None and host.view_url(ctx, record):
            v["url"] = host.view_url(ctx, record)
            v["modal"] = False
        return v


class DeleteAction(Action):
    def __init__(self, name: str = "delete") -> None:
        super().__init__(name)
        self._icon = "trash-2"
        self._color = "danger"
        self._requires_confirmation = True
        self._modal_icon = "triangle-alert"
        self._modal_icon_color = "danger"
        self._modal_submit_label = "Delete"
        self._authorize = "delete"
        self._success_title = "Deleted"
        self._modal_width = "md"

    def get_modal_heading(self, host: "Host | None") -> str:
        return __("Delete :label", label=host.model_label().lower()) if host else __("Delete")

    def get_modal_description(self, host: "Host | None") -> str:
        label = host.model_label().lower() if host else __("record")
        return __("Are you sure you want to delete this :label? This action cannot be undone.", label=label)

    def is_available(self, host, ctx, record=None) -> bool:  # type: ignore[override]
        return super().is_available(host, ctx, record) and not (host and record is not None and host.is_trashed(record))

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        if self._action is not None:
            return super().run(ctx, host, record, records, data, form)
        host.delete(ctx, record)
        if self.scope == "page":
            url = host.page_url(ctx)
            if url:
                ctx.redirect(url)


class RestoreAction(Action):
    def __init__(self, name: str = "restore") -> None:
        super().__init__(name)
        self._icon = "rotate-ccw"
        self._color = "gray"
        self._requires_confirmation = True
        self._modal_submit_label = "Restore"
        self._authorize = "restore"
        self._success_title = "Restored"
        self._modal_width = "md"

    def is_available(self, host, ctx, record=None) -> bool:  # type: ignore[override]
        return super().is_available(host, ctx, record) and bool(host and record is not None and host.is_trashed(record))

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        host.restore(ctx, record)


class ForceDeleteAction(Action):
    def __init__(self, name: str = "forceDelete") -> None:
        super().__init__(name)
        self._label = "Force delete"
        self._icon = "trash-2"
        self._color = "danger"
        self._requires_confirmation = True
        self._modal_icon = "triangle-alert"
        self._modal_icon_color = "danger"
        self._modal_description = "This record will be removed for good. This cannot be undone."
        self._modal_submit_label = "Delete forever"
        self._authorize = "force_delete"
        self._success_title = "Deleted"
        self._modal_width = "md"

    def is_available(self, host, ctx, record=None) -> bool:  # type: ignore[override]
        return super().is_available(host, ctx, record) and bool(host and record is not None and host.is_trashed(record))

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        host.force_delete(ctx, record)
        if self.scope == "page":
            url = host.page_url(ctx)
            if url:
                ctx.redirect(url)


class ReplicateAction(Action):
    """Copy a record. ``excluded`` lists attributes not copied (besides the primary key)."""

    def __init__(self, name: str = "replicate", excluded: list[str] | None = None) -> None:
        super().__init__(name)
        self._icon = "copy"
        self._color = "gray"
        self._requires_confirmation = True
        self._modal_submit_label = "Replicate"
        self._authorize = "create"
        self._success_title = "Replicated"
        self._excluded = set(excluded or [])
        self._before_save: Any = None
        self._modal_width = "md"

    def before_replica_saved(self, fn: Any) -> "ReplicateAction":
        self._before_save = fn
        return self

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(type(record))
        pks = {c.key for c in mapper.primary_key}
        copy = type(record)()
        for attr in mapper.column_attrs:
            if attr.key in pks or attr.key in self._excluded or attr.key in ("created_at", "updated_at"):
                continue
            setattr(copy, attr.key, getattr(record, attr.key))
        if self._before_save:
            call(self._before_save, replica=copy, record=record, data=data)
        ctx.db.add(copy)
        ctx.db.commit()
        return copy


# ---------------------------------------------------------------------- bulk
class DeleteBulkAction(BulkAction):
    def __init__(self, name: str = "delete") -> None:
        super().__init__(name)
        self._label = "Delete"
        self._icon = "trash-2"
        self._color = "danger"
        self._requires_confirmation = True
        self._modal_icon = "triangle-alert"
        self._modal_icon_color = "danger"
        self._modal_submit_label = "Delete"
        self._modal_heading = "Delete selected"
        self._modal_description = "Are you sure you want to delete the selected records?"
        self._authorize = "delete_any"
        self._success_title = "Deleted"
        self._modal_width = "md"

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        for r in records or []:
            if host.can(ctx, "delete", r) and not host.is_trashed(r):
                host.delete(ctx, r)


class RestoreBulkAction(BulkAction):
    def __init__(self, name: str = "restore") -> None:
        super().__init__(name)
        self._label = "Restore"
        self._icon = "rotate-ccw"
        self._requires_confirmation = True
        self._modal_submit_label = "Restore"
        self._authorize = "restore_any"
        self._success_title = "Restored"
        self._modal_width = "md"

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        for r in records or []:
            if host.is_trashed(r):
                host.restore(ctx, r)


class ForceDeleteBulkAction(BulkAction):
    def __init__(self, name: str = "forceDelete") -> None:
        super().__init__(name)
        self._label = "Force delete"
        self._icon = "trash-2"
        self._color = "danger"
        self._requires_confirmation = True
        self._modal_icon = "triangle-alert"
        self._modal_icon_color = "danger"
        self._modal_submit_label = "Delete forever"
        self._authorize = "force_delete_any"
        self._success_title = "Deleted"
        self._modal_width = "md"

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        for r in records or []:
            host.force_delete(ctx, r)


# ---------------------------------------------------------------------- relations
class AttachAction(Action):
    """Many-to-many: pick existing records to link to the owner."""

    def __init__(self, name: str = "attach", title_attribute: str | None = None) -> None:
        super().__init__(name)
        self._label = "Attach"
        self._icon = "link"
        self._color = "gray"
        self._title_attribute = title_attribute
        self._success_title = "Attached"
        self._authorize = "attach"
        self._form = True

    def build_form(self, ctx, host, record=None, records=None):  # type: ignore[override]
        from sqlalchemy import select
        from sqlalchemy.orm import with_parent

        from ..forms.fields import Select
        from ..forms.form import Form

        title = self._title_attribute or getattr(host.manager, "record_title_attribute", None)
        model = host.model
        pk = host.primary_key()
        attached = select(pk).where(with_parent(host.owner, getattr(type(host.owner), host.manager.relationship)))
        query = ctx.panel.tenancy.scope(ctx, model, select(model).where(pk.not_in(attached)))
        if title:
            query = query.order_by(getattr(model, title))
        rows = ctx.db.scalars(query.limit(500)).all()
        options = {str(getattr(r, pk.key)): (str(getattr(r, title)) if title else str(r)) for r in rows}
        form = Form().schema([
            Select("records").label(host.model_label().capitalize() if host.model_label() else "Records")
            .multiple().searchable().options(options).required()
        ]).columns(1)
        return form

    def fill(self, form, ctx, record=None, records=None):  # type: ignore[override]
        form.fill(None)

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        from sqlalchemy import select

        keys = [host._typed_key(k) for k in (data or {}).get("records") or []]
        # look up outside the relation scope: these records are not attached yet
        query = ctx.panel.tenancy.scope(ctx, host.model, select(host.model).where(host.primary_key().in_(keys)))
        found = ctx.db.scalars(query).all() if keys else []
        host.attach(ctx, list(found))


class DetachAction(Action):
    def __init__(self, name: str = "detach") -> None:
        super().__init__(name)
        self._label = "Detach"
        self._icon = "unlink"
        self._color = "danger"
        self._requires_confirmation = True
        self._modal_submit_label = "Detach"
        self._success_title = "Detached"
        self._authorize = "detach"
        self._modal_width = "md"

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        host.detach(ctx, record)


class DetachBulkAction(BulkAction):
    def __init__(self, name: str = "detach") -> None:
        super().__init__(name)
        self._label = "Detach"
        self._icon = "unlink"
        self._color = "danger"
        self._requires_confirmation = True
        self._modal_submit_label = "Detach"
        self._success_title = "Detached"
        self._authorize = "detach"
        self._modal_width = "md"

    def run(self, ctx, host, record=None, records=None, data=None, form=None):  # type: ignore[override]
        for r in records or []:
            host.detach(ctx, r)
