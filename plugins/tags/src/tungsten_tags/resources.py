"""The "Tags" page: name, color and group tags, see where each is used, merge duplicates."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup, escape
from sqlalchemy import func, select

from tungsten import Notification, Resource
from tungsten.actions import Action, BulkAction, DeleteAction, DeleteBulkAction, EditAction
from tungsten.forms import Placeholder, Section, Select, Textarea, TextInput
from tungsten.i18n import translate as __
from tungsten.infolists import TextEntry
from tungsten.tables import SelectFilter, TextColumn

from . import service
from .models import Tag


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("tags") if ctx is not None else None


def _groups(db: Any) -> dict[str, str]:
    rows = db.execute(select(Tag.type).where(Tag.type != "").distinct().order_by(Tag.type)).scalars()
    return {t: t for t in rows}


def records(count: int) -> str:
    return __("1 record") if count == 1 else __(":count records", count=count)


def _unique_name(value: Any, record: Any, get: Any, db: Any) -> Any:
    name = service.clean_name(value)
    if name is None:
        return __("Type a name.")
    group = (get("type") or "").strip() if record is None else record.type
    query = select(Tag.id).where(Tag.type == group, Tag.key == service.tag_key(name))
    if record is not None:
        query = query.where(Tag.id != record.id)
    if db.scalar(query) is not None:
        return __("A tag with this name already exists (names ignore capital letters).")
    return True


def used_on(ctx: Any, record: Any) -> Markup:
    """Where the tag is used, one line per module, with a link to the filtered list."""
    plugin = _plugin(ctx)
    if plugin is None or record is None:
        return Markup("")
    lines = []
    for target in plugin.targets.values():
        if target.type != record.type or not target.resource.can(ctx, "view_any"):
            continue
        host = target.resource.host()
        query = host.base_query(ctx).where(service.tagged(target.model, [record.id]))
        count = ctx.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        if not count:
            continue
        url = target.resource.get_url(ctx, "index", _f=1, **{"filters.tags.values": record.id})
        lines.append(
            f'<li class="flex items-center justify-between gap-3 py-2">'
            f'<span class="text-sm font-medium text-gray-950 dark:text-white">{escape(target.label)}</span>'
            f'<a href="{escape(url)}" class="text-sm text-primary-600 hover:underline dark:text-primary-400">'
            f'{escape(records(count))}</a></li>')
    if not lines:
        return Markup(f'<p class="text-sm text-gray-500 dark:text-gray-400">{escape(__("Not used yet."))}</p>')
    return Markup('<ul class="divide-y divide-gray-950/5 dark:divide-white/10">' + "".join(lines) + "</ul>")


class TagResource(Resource):
    model = Tag
    slug = "tags"
    icon = "tags"
    navigation_sort = 90
    description = "Labels you put on leads, tickets, employees, invoices and more, to group and filter them."
    record_title_attribute = "name"
    global_search_attributes = ["name", "description"]
    #: tags are shared by the whole panel
    tenant_scoped = False

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            Section("Tag").icon("tag").columns(2).column_span_full().schema([
                TextInput("name").required().max_length(service.MAX_LENGTH).autofocus()
                .placeholder("VIP").rule(_unique_name),
                Select("color").options(service.COLORS).default("gray").required(),
                TextInput("type").label("Group").max_length(50).placeholder("Shared")
                .helper_text("Leave empty to share the tag with every module. A group keeps a set apart, "
                             "like Industry. It can't change later.")
                .disabled(lambda operation: operation != "create"),
                TextInput("sort").label("Order").integer().default(0)
                .helper_text("Smaller numbers come first in lists."),
                Textarea("description").rows(2).max_length(255).column_span_full(),
            ]),
        ])

    @classmethod
    def infolist(cls, infolist):
        return infolist.columns(3).schema([
            Section("Tag").icon("tag").column_span(1).columns(1).schema([
                TextEntry("name").badge().color(lambda record: record.color or "gray").inline_label(),
                TextEntry("type").label("Group").inline_label()
                .state(lambda record: record.type or __("Shared")),
                TextEntry("description").placeholder("—"),
            ]),
            Section("Used on").icon("link").column_span(2).columns(1).schema([
                Placeholder("used_on").hidden_label().content(lambda record, ctx: used_on(ctx, record)),
            ]),
        ])

    @classmethod
    def table(cls, table):
        def merge(records, data, db, ctx):
            plugin = _plugin(ctx)
            into = next((r for r in records if str(r.id) == str(data.get("into"))), None)
            if into is None:
                Notification(__("Pick the tag to keep")).warning().send(ctx)
                return
            skipped = [r.name for r in records if r.id != into.id and r.type != into.type]
            merged = plugin.merge_tags(db, list(records), into)
            db.commit()
            note = Notification(__("Tags merged")).body(
                __(":count tags merged into :name.", count=merged, name=into.name)).success()
            if skipped:
                note = Notification(__("Some tags were not merged")).body(
                    __("Only tags of the same group can be merged: :names.", names=", ".join(skipped))).warning()
            note.send(ctx)

        groups = _groups(table.ctx.db) if table.ctx is not None else {}
        return (
            table.columns([
                TextColumn("name").badge().color(lambda record: record.color or "gray")
                .searchable().sortable(),
                TextColumn("type").label("Group").sortable().placeholder(__("Shared")).toggleable(),
                TextColumn("taggings_count").label("Used on").counts("taggings")
                .format_state_using(lambda state: records(int(state or 0))),
                TextColumn("description").limit(60).placeholder("—").toggleable(),
                TextColumn("created_at").label("Added").since().sortable().toggleable(hidden_by_default=True),
            ])
            .filters([SelectFilter("type").label("Group").placeholder("All groups").options(groups)]
                     if groups else [])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([
                BulkAction("merge").label("Merge").icon("merge").authorize("update")
                .modal_heading("Merge tags")
                .modal_description("Records with any of these tags get the one you keep. The others are deleted.")
                .form(lambda records: [
                    Select("into").label("Keep").required()
                    .options({r.id: r.name for r in records or []}),
                ])
                .action(merge),
                DeleteBulkAction(),
            ])
            .default_sort("name")
            .empty_state("No tags yet", "Add one here, or type a tag on any lead, ticket or invoice. "
                         "Already have tags on leads or tickets? Use Sync tags.", "tags")
        )

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        actions = super().header_actions(ctx, page, record)
        if page in ("index", "list"):
            def run(db, ctx):
                result = _plugin(ctx).sync(db)
                db.commit()
                Notification(__("Tags synced")).body(
                    __(":records records checked, :removed old links removed.", **result)).success().send(ctx)

            actions = [*actions, Action("sync").label("Sync tags").icon("refresh-cw").color("gray")
                       .authorize("create")
                       .requires_confirmation()
                       .modal_description("Copies tags already saved on leads and tickets into this list, "
                                          "and removes tags of records that no longer exist.")
                       .action(run)]
        return actions

    # ------------------------------------------------------------------ save hooks
    @classmethod
    def before_create(cls, record, data):
        record.name = service.clean_name(data.get("name")) or ""
        record.key = service.tag_key(record.name)
        record.type = (data.get("type") or "").strip()
        data["name"], data["type"] = record.name, record.type

    @classmethod
    def before_save(cls, record, data):
        record.__dict__["_tags_old_name"] = record.name
        name = service.clean_name(data.get("name")) or record.name
        data["name"] = name
        data.pop("type", None)  # the group can't change once records use the tag
        record.key = service.tag_key(name)

    @classmethod
    def after_save(cls, record, db, ctx):
        old = record.__dict__.pop("_tags_old_name", None)
        if old is not None and old != record.name:
            _plugin(ctx).rename_tag(db, record, old)

    @classmethod
    def before_delete(cls, record, db, ctx):
        plugin = _plugin(ctx)
        if plugin is not None:
            plugin.delete_tag(db, record)
