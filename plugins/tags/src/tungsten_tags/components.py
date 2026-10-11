"""Ready-made pieces that put tags on any resource: a form field, a table column, a filter,
an infolist entry and two bulk actions. :meth:`TagsPlugin.attach` adds them for you;
use them directly when you want them in a particular place.
"""

from __future__ import annotations

from typing import Any

from tungsten import Notification
from tungsten.actions import BulkAction
from tungsten.forms import Section, Select, TagsInput
from tungsten.i18n import translate as __
from tungsten.infolists import TextEntry
from tungsten.tables import TextColumn
from tungsten.tables.filters import Filter

from . import service

#: name of the form field the plugin adds to a resource that has no tag column of its own
FIELD = "tungsten_tags"


def plugin_of(ctx: Any) -> Any:
    panel = getattr(ctx, "panel", None)
    return panel.get_plugin("tags") if panel is not None else None


def target_of(ctx: Any, resource: Any) -> Any:
    """The plugin's settings for ``resource``, or None when this panel does not tag it."""
    plugin = plugin_of(ctx)
    return plugin.target_for(resource) if plugin is not None else None


def _cache(holder: Any) -> dict:
    """Per-request cache, kept on the table (or on the request context for a view page)."""
    cache = holder.__dict__.get("_tungsten_tags")
    if cache is None:
        cache = holder.__dict__["_tungsten_tags"] = {}
    return cache


def _colors(table: Any, target: Any, db: Any) -> dict[str, str]:
    cache = _cache(table)
    if "colors" not in cache:
        cache["colors"] = service.tag_colors(db, target.type)
    return cache["colors"]


def record_names(table: Any, target: Any, record: Any, db: Any) -> list[str]:
    """Tag names of a record. For a table, the whole page is read in one query."""
    if target.column:
        return service.clean_names(getattr(record, target.column, None))
    cache = _cache(table).setdefault("names", {})
    _, key = service.record_ref(record)
    if key is None:
        return []
    if key not in cache:
        page = [service.record_ref(r)[1] for r in getattr(table, "_page_records", None) or ()]
        wanted = [k for k in [*page, key] if k is not None and k not in cache]
        for record_id, rows in service.record_tags(db, target.kind, wanted, target.type).items():
            cache[record_id] = [row.name for row in rows]
    return cache.get(key, [])


def _state(resource: Any):
    def state(record: Any, ctx: Any, db: Any, table: Any = None) -> list[str]:
        target = target_of(ctx, resource)
        if target is None or record is None:
            return []
        return record_names(table if table is not None else ctx, target, record, db)
    return state


def _color(resource: Any):
    def color(state: Any, ctx: Any, db: Any, table: Any = None) -> str:
        target = target_of(ctx, resource)
        if target is None or not state:
            return "gray"
        return _colors(table if table is not None else ctx, target, db).get(service.tag_key(str(state)), "gray")
    return color


def tags_column(resource: Any, name: str | None = None) -> TextColumn:
    """A column of colored tag badges (at most three, then "+2 more")."""
    return (TextColumn(name or FIELD).label("Tags").badge().limit_list(3)
            .state(_state(resource)).color(_color(resource)).toggleable())


def tags_entry(resource: Any, name: str | None = None) -> TextEntry:
    return (TextEntry(name or FIELD).label("Tags").badge().placeholder("No tags")
            .state(_state(resource)).color(_color(resource)))


def color_existing(component: Any, resource: Any) -> None:
    """Give an existing tags column or entry the tag colors."""
    column = getattr(component, "column", component)
    if getattr(column, "_color", None) is None and getattr(column, "_colors", None) is None:
        column.color(_color(resource))


def _suggestions(resource: Any):
    def suggest(ctx: Any, db: Any) -> list[str]:
        target = target_of(ctx, resource)
        return service.tag_names(db, target.type) if target is not None and db is not None else []
    return suggest


def _rule(resource: Any):
    def check(value: Any, ctx: Any, db: Any) -> Any:
        target = target_of(ctx, resource)
        if target is None:
            return True
        names = service.clean_names(value)
        plugin = plugin_of(ctx)
        if plugin.max_tags and len(names) > plugin.max_tags:
            return __("Use at most :count tags.", count=plugin.max_tags)
        if not plugin.allow_new:
            found = service.find_tags(db, names, target.type)
            unknown = [n for n in names if service.tag_key(n) not in found]
            if unknown:
                return __("Unknown tag: :names. Pick from the list, or add it under Tags first.",
                          names=", ".join(unknown))
        return True
    return check


def enhance_input(field: TagsInput, resource: Any) -> TagsInput:
    """Suggest the shared tags in an existing ``TagsInput`` and check the limits."""
    if field._suggestions is None:
        field.suggestions(_suggestions(resource))
    return field.rule(_rule(resource))


def tags_input(resource: Any) -> TagsInput:
    """A tags box that saves into the shared tags (for models without a tags column)."""

    def load(record: Any, ctx: Any, db: Any) -> list[str]:
        target = target_of(ctx, resource)
        if target is None or record is None:
            return []
        _, key = service.record_ref(record)
        if key is None:
            return []
        return [row.name for row in service.record_tags(db, target.kind, [key], target.type)[key]]

    def save(record: Any, state: Any, ctx: Any, db: Any) -> None:
        plugin = plugin_of(ctx)
        if plugin is not None and plugin.target_for(resource) is not None:
            plugin.set_tags(db, record, state or [], resource=resource)

    field = (TagsInput(FIELD).label("Tags").placeholder("Add a tag")
             .helper_text("Press Enter after each tag. Use tags to group and filter records.")
             .format_state_using(load).save_relationships_using(save)
             .visible(lambda ctx: target_of(ctx, resource) is not None))
    return enhance_input(field, resource)


def tags_section(resource: Any) -> Section:
    return (Section("Tags").icon("tags").columns(1).column_span_full()
            .visible(lambda ctx: target_of(ctx, resource) is not None)
            .schema([tags_input(resource)]))


class TagFilter(Filter):
    """Show records with any (or all) of the picked tags."""

    def __init__(self, resource: Any, name: str = "tags") -> None:
        super().__init__(name)
        self.resource = resource
        self._label = "Tags"
        self._labels: dict[str, str] = {}

    def _build_fields(self) -> list:
        return [
            Select("values").label("Tags").multiple().searchable().placeholder("Any tag"),
            Select("match").label("Match").options({"any": "Any of these tags", "all": "All of these tags"})
            .default("any").native(),
        ]

    def bind_options(self, table: Any) -> None:
        target = target_of(table.ctx, self.resource)
        options = service.tag_options(table.ctx.db, target.type) if target is not None else {}
        self._labels = {str(k): v for k, v in options.items()}
        self.get_fields()[0].options(options)

    def is_active(self, data: dict[str, Any]) -> bool:
        return bool(self._ids(data))

    @staticmethod
    def _ids(data: dict[str, Any]) -> list[int]:
        values = data.get("values") or []
        if not isinstance(values, (list, tuple)):
            values = [values]
        out = []
        for v in values:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
        return out

    def apply(self, query: Any, data: dict[str, Any], table: Any) -> Any:
        ids = self._ids(data)
        if not ids or target_of(table.ctx, self.resource) is None:
            return query
        match = "all" if data.get("match") == "all" else "any"
        return query.where(service.tagged(table.model, ids, match))

    def indicators(self, data: dict[str, Any], table: Any) -> list[str]:
        ids = self._ids(data)
        if not ids:
            return []
        names = ", ".join(self._labels.get(str(i), f"#{i}") for i in ids)
        word = __("all of") if data.get("match") == "all" and len(ids) > 1 else ""
        return [f"{__('Tags')}: {word + ' ' if word else ''}{names}"]


def bulk_actions(resource: Any) -> list[BulkAction]:
    """"Add tags" and "Remove tags" for the selected rows."""

    def add(records: Any, data: dict, db: Any, ctx: Any) -> None:
        plugin = plugin_of(ctx)
        names = service.clean_names(data.get("tags"))
        for record in records or []:
            plugin.add_tags(db, record, names, resource=resource)
        db.commit()
        Notification(__("Tags added")).body(__(":count records updated.", count=len(records or []))) \
            .success().send(ctx)

    def remove(records: Any, data: dict, db: Any, ctx: Any) -> None:
        plugin = plugin_of(ctx)
        target = plugin.target_for(resource)
        options = service.tag_options(db, target.type)
        names = [options[int(i)] for i in (data.get("tags") or []) if str(i).isdigit() and int(i) in options]
        for record in records or []:
            plugin.remove_tags(db, record, names, resource=resource)
        db.commit()
        Notification(__("Tags removed")).body(__(":count records updated.", count=len(records or []))) \
            .success().send(ctx)

    def visible(ctx: Any) -> bool:
        return target_of(ctx, resource) is not None

    def suggestions(ctx: Any, db: Any) -> list[str]:
        target = target_of(ctx, resource)
        return service.tag_names(db, target.type) if target is not None else []

    def options(ctx: Any, db: Any) -> dict:
        target = target_of(ctx, resource)
        return service.tag_options(db, target.type) if target is not None else {}

    return [
        BulkAction("add_tags").label("Add tags").icon("tag").authorize("update").visible(visible)
        .modal_heading("Add tags to the selected rows")
        .form([TagsInput("tags").label("Tags").required().suggestions(suggestions).rule(_rule(resource))])
        .action(add),
        BulkAction("remove_tags").label("Remove tags").icon("tag").authorize("update").visible(visible)
        .modal_heading("Remove tags from the selected rows")
        .form([Select("tags").label("Tags").multiple().searchable().required().options(options)])
        .action(remove),
    ]
