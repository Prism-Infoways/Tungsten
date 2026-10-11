"""Tags for Tungsten: put tags on any record and filter by them.

    from tungsten_tags import TagsPlugin

    panel.plugin(TagsPlugin())
    panel.create_tables(engine)   # also creates the tag tables

Adds a "Tags" page to name, color, group and merge tags. When the Leads, Tickets, HR or
Finance plugins are on the panel, their records get tags too: a tags box on the form, a
tags column, a tag filter and "Add tags" / "Remove tags" bulk actions. Tag your own
resources with ``panel.get_plugin("tags").attach(ProductResource)``.
"""

from __future__ import annotations

import inspect
import logging
import weakref
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, select
from sqlalchemy import inspect as sa_inspect

from tungsten import Plugin

from . import service
from .components import (
    FIELD,
    TagFilter,
    bulk_actions,
    color_existing,
    enhance_input,
    tags_column,
    tags_entry,
    tags_input,
    tags_section,
)
from .models import Tag, Tagging, TagsBase
from .service import clean_name, clean_names, tag_key

__version__ = "0.1.0"

log = logging.getLogger("tungsten.tags")

#: tables of other plugins that get tags automatically, and the JSON list column they already have
KNOWN = {
    "tungsten_leads": "tags",          # tungsten-leads
    "tungsten_tickets": "tags",        # tungsten-tickets
    "tungsten_hr_employees": None,     # tungsten-hr
    "tungsten_fin_contacts": None,     # tungsten-finance: customers and vendors
    "tungsten_fin_invoices": None,     # tungsten-finance: invoices, quotes, bills, notes
    "tungsten_fin_expenses": None,     # tungsten-finance
}


@dataclass
class Target:
    """A resource that carries tags."""

    resource: Any
    model: Any
    #: the record's table name, as stored in taggings
    kind: str
    #: the tag group it uses ("" is the shared group)
    type: str = ""
    #: a JSON list column the model already has (Leads and Tickets keep tags there)
    column: str | None = None

    @property
    def label(self) -> str:
        return self.resource.get_plural_label()


# ---------------------------------------------------------------------- model events
#: models whose JSON tags column is mirrored into taggings: model -> (column, type)
_COLUMN_MODELS: dict[Any, tuple[str, str]] = {}
#: models whose taggings are dropped when a record is deleted
_CLEANUP_MODELS: set[Any] = set()


#: databases known to have the tag tables (a panel without the plugin may share the models)
_READY: "weakref.WeakKeyDictionary[Any, bool]" = weakref.WeakKeyDictionary()


def _ready(connection: Any) -> bool:
    """Whether this database has the tag tables. Saving a lead must never fail because of tags."""
    engine = connection.engine
    if _READY.get(engine):
        return True
    ok = sa_inspect(connection).has_table(Tagging.__tablename__)
    if ok:
        _READY[engine] = True
    return ok


def _column_config(cls: Any) -> tuple[str, str] | None:
    for klass in cls.__mro__:
        if klass in _COLUMN_MODELS:
            return _COLUMN_MODELS[klass]
    return None


def _normalize(mapper: Any, connection: Any, target: Any) -> None:
    """Before saving: tidy the tags list and use the spelling of existing tags ("vip" -> "VIP")."""
    config = _column_config(type(target))
    if config is None or not _ready(connection):
        return
    column, group = config
    state = sa_inspect(target)
    if state.has_identity and not state.attrs[column].history.has_changes():
        return
    raw = getattr(target, column, None)
    names = clean_names(raw)
    found = service.find_tags(connection, names, group) if names else {}
    names = [found[tag_key(n)].name if tag_key(n) in found else n for n in names]
    value: Any = names if names else ([] if isinstance(raw, list) else None)
    if isinstance(raw, str):
        value = ", ".join(names) or None
    if value != raw:
        setattr(target, column, value)


def _mirror(mapper: Any, connection: Any, target: Any, inserted: bool) -> None:
    config = _column_config(type(target))
    if config is None or not _ready(connection):
        return
    column, group = config
    if not inserted and not sa_inspect(target).attrs[column].history.has_changes():
        return
    kind, record_id = service.record_ref(target)
    if record_id is None:
        return
    names = clean_names(getattr(target, column, None))
    if inserted and not names:
        return
    rows = service.ensure_tags(connection, names, group)
    service.set_record_tags(connection, kind, record_id, [r.id for r in rows], group)


def _after_insert(mapper: Any, connection: Any, target: Any) -> None:
    _mirror(mapper, connection, target, True)


def _after_update(mapper: Any, connection: Any, target: Any) -> None:
    _mirror(mapper, connection, target, False)


def _after_delete(mapper: Any, connection: Any, target: Any) -> None:
    if not any(klass in _CLEANUP_MODELS for klass in type(target).__mro__) or not _ready(connection):
        return
    kind, record_id = service.record_ref(target)
    if record_id is not None:
        service.forget_record(connection, kind, record_id)


def watch_deletes(model: Any) -> None:
    """Drop a record's tags when it is deleted (soft deletes keep them)."""
    if model in _CLEANUP_MODELS:
        return
    _CLEANUP_MODELS.add(model)
    if not event.contains(model, "after_delete", _after_delete):
        event.listen(model, "after_delete", _after_delete, propagate=True)


def mirror_column(model: Any, column: str, type: str = "") -> None:
    """Keep the taggings in step with a JSON list column, however the record is saved."""
    _COLUMN_MODELS[model] = (column, type)
    for name, fn in (("before_insert", _normalize), ("before_update", _normalize),
                     ("after_insert", _after_insert), ("after_update", _after_update)):
        if not event.contains(model, name, fn):
            event.listen(model, name, fn, propagate=True)


# ---------------------------------------------------------------------- resource wrapping
_MARK = "__tungsten_tags__"


def _wrap(resource: Any, method: str, extend: Any) -> None:
    """Run ``extend(cls, result)`` after ``resource.<method>(obj)``. Safe to call twice."""
    current = resource.__dict__.get(method)
    if current is not None and getattr(getattr(current, "__func__", None), _MARK, False):
        return
    original = inspect.getattr_static(resource, method)
    func = original.__func__ if isinstance(original, classmethod) else None

    def wrapped(cls: Any, obj: Any) -> Any:
        result = func(cls, obj) if func is not None else original(obj)
        if result is None:  # e.g. no infolist: the view page shows the form instead
            return None
        if getattr(result, "_tungsten_tags_done", False):  # a parent class already added the pieces
            return result
        result._tungsten_tags_done = True
        return extend(cls, result)

    setattr(wrapped, _MARK, True)
    setattr(resource, method, classmethod(wrapped))


def _walk(components: Any) -> Any:
    for comp in components or []:
        yield comp
        children = getattr(comp, "child_components", None)
        if children is not None:
            yield from _walk(children())


def _find(components: Any, name: str, kind: type | None = None) -> Any:
    for comp in _walk(components):
        if getattr(comp, "name", None) == name and (kind is None or isinstance(comp, kind)):
            return comp
    return None


def _extend_table(cls: Any, table: Any) -> Any:
    from .components import plugin_of

    plugin = plugin_of(table.ctx)
    target = plugin.target_for(cls) if plugin is not None else None
    if target is None:
        return table
    name = target.column or FIELD
    existing = next((c for c in table._columns if c.name == name), None)
    if existing is None:
        table._columns.append(tags_column(cls, name))
    else:
        color_existing(existing, cls)
    if not any(f.name == "tags" for f in table._filters):
        table._filters.append(TagFilter(cls))
    taken = {getattr(a, "name", None) for a in table._bulk_actions}
    table._bulk_actions.extend(a for a in bulk_actions(cls) if a.name not in taken)
    return table


def _extend_form(cls: Any, form: Any) -> Any:
    from tungsten.forms import TagsInput

    column = TagsPlugin.column_for(cls)
    if column:
        field = _find(form.get_schema(), column, TagsInput)
        if field is not None:
            enhance_input(field, cls)
            return form
    if _find(form.get_schema(), FIELD) is None:
        form.schema([*form.get_schema(), tags_section(cls)])
    return form


def _extend_infolist(cls: Any, infolist: Any) -> Any:
    from tungsten.forms import Section

    from .components import target_of

    column = TagsPlugin.column_for(cls)
    entry = _find(infolist.get_schema(), column) if column else None
    if entry is not None:
        color_existing(entry, cls)
        return infolist
    if _find(infolist.get_schema(), FIELD) is None:
        infolist.schema([*infolist.get_schema(),
                         Section("Tags").icon("tags").columns(1).column_span_full()
                         .visible(lambda ctx: target_of(ctx, cls) is not None)
                         .schema([tags_entry(cls).hidden_label()])])
    return infolist


# ---------------------------------------------------------------------- plugin
class TagsPlugin(Plugin):
    """``TagsPlugin(auto_attach=True, allow_new=True, max_tags=20, navigation_group=None)``.

    - ``auto_attach``: tag the records of the Leads, Tickets, HR and Finance plugins when they are
      on the panel. Pass ``False`` and call :meth:`attach` to choose yourself.
    - ``allow_new``: anyone who edits a record may type a new tag. ``False``: only pick existing
      tags (new ones are made on the Tags page).
    - ``max_tags``: most tags one record may carry (``None``: no limit).
    """

    id = "tags"
    metadata = TagsBase.metadata
    #: settings per resource, shared by every panel in the process (the pieces check the panel)
    _columns: dict[Any, str | None] = {}

    def __init__(self, auto_attach: bool = True, allow_new: bool = True, max_tags: int | None = 20,
                 navigation_group: str | None = None, navigation_sort: int = 90) -> None:
        self.auto_attach = auto_attach
        self.allow_new = allow_new
        self.max_tags = max_tags
        self.navigation_group = navigation_group
        self.navigation_sort = navigation_sort
        self.panel: Any = None
        self.targets: dict[Any, Target] = {}

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        from .resources import TagResource

        self.panel = panel
        TagResource.navigation_group = self.navigation_group
        TagResource.navigation_sort = self.navigation_sort
        panel.resources([TagResource])

    def boot(self, panel: Any) -> None:
        if not self.auto_attach:
            return
        for resource in panel.get_resources():
            model = getattr(resource, "model", None)
            if model is None or resource in self.targets:
                continue
            try:
                kind = service.model_type(model)
            except Exception:  # noqa: BLE001 - not a mapped class
                continue
            if kind in KNOWN:
                self.attach(resource, column=KNOWN[kind])

    # ------------------------------------------------------------------ hook for other plugins and apps
    def attach(self, resource: Any, type: str = "", column: str | None = None) -> Target:
        """Let ``resource``'s records carry tags.

        - ``type``: a tag group of its own ("" shares the tags with every other module).
        - ``column``: the model already keeps tags in this JSON list column (like Leads); the plugin
          keeps the tag tables in step with it, so filters and the Tags page see those tags too.
        """
        model = resource.model
        service.primary_key(model)  # one primary key column is needed
        if column is not None and column not in sa_inspect(model).columns:
            raise ValueError(f"{model.__name__} has no column {column!r}.")
        target = Target(resource=resource, model=model, kind=service.model_type(model), type=type or "",
                        column=column)
        self.targets[resource] = target
        TagsPlugin._columns[resource] = column
        watch_deletes(model)
        if column:
            mirror_column(model, column, target.type)
        _wrap(resource, "table", _extend_table)
        _wrap(resource, "form", _extend_form)
        _wrap(resource, "infolist", _extend_infolist)
        return target

    def target_for(self, resource: Any) -> Target | None:
        """Settings of ``resource`` (or of the nearest parent class that was attached)."""
        for klass in getattr(resource, "__mro__", ()):
            if klass in self.targets:
                return self.targets[klass]
        return None

    @classmethod
    def column_for(cls, resource: Any) -> str | None:
        for klass in getattr(resource, "__mro__", ()):
            if klass in cls._columns:
                return cls._columns[klass]
        return None

    def targets_of_kind(self, kind: str) -> list[Target]:
        return [t for t in self.targets.values() if t.kind == kind]

    # ------------------------------------------------------------------ tags on records
    def _target(self, record: Any, resource: Any = None) -> Target | None:
        if resource is not None:
            return self.target_for(resource)
        model = type(record)
        return next((t for t in self.targets.values() if issubclass(model, t.model)), None)

    def tags_for(self, db: Any, record: Any, resource: Any = None, group: str | None = None) -> list[str]:
        """Names of the tags on ``record``."""
        target = self._target(record, resource)
        if target is not None and target.column:
            return clean_names(getattr(record, target.column, None))
        kind, key = service.record_ref(record)
        if key is None:
            return []
        group = target.type if target is not None and group is None else (group or "")
        return [row.name for row in service.record_tags(db, kind, [key], group)[key]]

    def set_tags(self, db: Any, record: Any, names: Any, resource: Any = None, group: str | None = None) -> list[str]:
        """Give ``record`` exactly these tags. Works on any model; new names become new tags."""
        names = clean_names(names)
        if self.max_tags:
            names = names[: self.max_tags]
        target = self._target(record, resource)
        if target is not None and target.column:
            setattr(record, target.column, names)  # the model events update the tag tables
            db.flush()
            return clean_names(getattr(record, target.column, None))
        group = target.type if target is not None and group is None else (group or "")
        watch_deletes(type(record))
        kind, key = service.record_ref(record)
        if key is None:
            db.flush()
            kind, key = service.record_ref(record)
        rows = service.ensure_tags(db, names, group, create=self.allow_new)
        service.set_record_tags(db, kind, key, [r.id for r in rows], group)
        return [r.name for r in rows]

    def add_tags(self, db: Any, record: Any, names: Any, resource: Any = None, group: str | None = None) -> list[str]:
        """Add tags to ``record``, keeping the ones it has."""
        current = self.tags_for(db, record, resource, group)
        return self.set_tags(db, record, [*current, *clean_names(names)], resource, group)

    def remove_tags(self, db: Any, record: Any, names: Any, resource: Any = None,
                    group: str | None = None) -> list[str]:
        drop = {tag_key(n) for n in clean_names(names)}
        current = self.tags_for(db, record, resource, group)
        return self.set_tags(db, record, [n for n in current if tag_key(n) not in drop], resource, group)

    # ------------------------------------------------------------------ the tags themselves
    def _records(self, db: Any, target: Target, ids: list[str]) -> list[Any]:
        """Records of a column target by their stored ids."""
        pk = service.primary_key(target.model)
        attr = getattr(target.model, sa_inspect(target.model).get_property_by_column(pk).key)
        try:
            python_type = pk.type.python_type
        except NotImplementedError:  # pragma: no cover
            python_type = str
        keys = []
        for i in ids:
            try:
                keys.append(python_type(i))
            except (TypeError, ValueError):
                continue
        out: list[Any] = []
        for start in range(0, len(keys), 500):
            out.extend(db.scalars(select(target.model).where(attr.in_(keys[start:start + 500]))).all())
        return out

    def _rewrite(self, db: Any, tag: Tag, fn: Any) -> None:
        """Change the JSON tags lists that hold ``tag`` (rename, merge, delete)."""
        for target in {t.kind: t for t in self.targets.values() if t.column and t.type == tag.type}.values():
            for record in self._records(db, target, service.tagged_ids(db, tag.id, target.kind)):
                names = clean_names(getattr(record, target.column, None))
                setattr(record, target.column, fn(names))

    def rename_tag(self, db: Any, tag: Tag, old_name: str) -> None:
        """After a rename: update the JSON tags lists of Leads, Tickets..."""
        old = tag_key(old_name)
        self._rewrite(db, tag, lambda names: [tag.name if tag_key(n) == old else n for n in names])
        db.flush()

    def delete_tag(self, db: Any, tag: Tag) -> None:
        """Take the tag off every record, then delete it."""
        key = tag.key
        self._rewrite(db, tag, lambda names: [n for n in names if tag_key(n) != key])
        db.flush()
        service.forget_tag(db, tag.id)

    def merge_tags(self, db: Any, sources: list[Tag], into: Tag) -> int:
        """Move every record of ``sources`` onto ``into`` and delete ``sources``. Returns how many merged."""
        merged = 0
        for source in sources:
            if source.id == into.id or source.type != into.type:
                continue
            key = source.key
            self._rewrite(db, source, lambda names, k=key: [into.name if tag_key(n) == k else n for n in names])
            db.flush()
            service.move_taggings(db, source.id, into.id)
            db.delete(source)
            merged += 1
        db.flush()
        return merged

    def sync(self, db: Any) -> dict[str, int]:
        """Copy tags already saved on Leads and Tickets into the tag tables, and drop tags of
        records that were deleted outside the panel. Safe to run any time."""
        synced = removed = 0
        for target in {t.kind: t for t in self.targets.values() if t.column}.values():
            pk = service.primary_key(target.model)
            attr = getattr(target.model, sa_inspect(target.model).get_property_by_column(pk).key)
            column = getattr(target.model, target.column)
            for key, value in db.execute(select(attr, column)).all():
                names = clean_names(value)
                rows = service.ensure_tags(db, names, target.type)
                service.set_record_tags(db, target.kind, str(key), [r.id for r in rows], target.type)
                synced += 1
        for target in {t.kind: t for t in self.targets.values()}.values():
            removed += service.drop_orphans(db, target.model)
        db.flush()
        return {"records": synced, "removed": removed}


__all__ = [
    "FIELD", "KNOWN", "Tag", "TagFilter", "Tagging", "TagsBase", "TagsPlugin", "Target", "bulk_actions",
    "clean_name", "clean_names", "mirror_column", "tag_key", "tags_column", "tags_entry", "tags_input",
    "watch_deletes",
]
