"""The "Media library" screen: upload, browse, edit alt text, see where a file is used, delete safely."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup, escape
from sqlalchemy import func, select

from tungsten import Notification, Resource
from tungsten.actions import Action, ActionGroup, BulkAction, DeleteAction, EditAction, ViewAction
from tungsten.actions.action import Halt
from tungsten.forms import FileUpload, Group, Placeholder, Section, TagsInput, Textarea, TextInput
from tungsten.infolists import TextEntry
from tungsten.tables import ImageColumn, ListTab, SelectFilter, TernaryFilter, TextColumn

from .models import MediaItem
from .service import KINDS, check_files, clean_folder, find_item, human_size, record_file


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("media") if ctx is not None else None


def _me(ctx: Any) -> str | None:
    return ctx.panel.auth.user_id(ctx.user) if ctx is not None and ctx.user is not None else None


def folder_options(ctx: Any) -> dict[str, str]:
    rows = ctx.db.scalars(select(MediaItem.folder).where(MediaItem.folder != "").distinct()
                          .order_by(MediaItem.folder).limit(300)).all()
    return {f: f for f in rows}


def _kind_label(state: Any) -> str:
    return KINDS.get(str(state), KINDS["other"])[0]


def _kind_color(state: Any) -> str:
    return KINDS.get(str(state), KINDS["other"])[1]


def _preview(record: Any) -> str | None:
    return record.path if record is not None and record.kind == "image" and not record.missing else None


def _link(ctx: Any, record: Any) -> str:
    plugin = _plugin(ctx)
    return plugin.url(record) if plugin is not None else ""


def _absolute_link(ctx: Any, record: Any) -> str:
    url = _link(ctx, record)
    if url.startswith("/") and ctx is not None and getattr(ctx, "request", None) is not None:
        return ctx.panel.absolute_url(ctx, url)
    return url


def _markdown(ctx: Any, record: Any) -> str:
    url = _absolute_link(ctx, record)
    if record.kind == "image":
        alt = (record.alt or record.title or "").replace("]", "")
        return f"![{alt}]({url})"
    return f"[{str(record).replace(']', '')}]({url})"


def _usages_html(ctx: Any, record: Any) -> Markup:
    plugin = _plugin(ctx)
    used = plugin.usages(ctx.db, record, ctx) if plugin is not None else []
    if not used:
        return Markup('<p class="text-sm text-gray-500 dark:text-gray-400">Not used anywhere we know of. '
                      'Safe to delete.</p>')
    rows = []
    for u in used:
        title = escape(u.get("title") or "")
        link = f'<a href="{escape(u["url"])}" class="font-medium text-primary-600 hover:underline ' \
               f'dark:text-primary-400">{title}</a>' if u.get("url") else f'<span class="font-medium">{title}</span>'
        rows.append(f'<li class="flex items-center gap-x-2 py-1.5 text-sm"><span class="text-gray-500 '
                    f'dark:text-gray-400">{escape(u.get("label") or "")}</span>{link}</li>')
    return Markup('<ul class="divide-y divide-gray-100 dark:divide-white/5">' + "".join(rows) + "</ul>")


def _missing_note(record: Any) -> Markup:
    if record is None or not record.missing:
        return Markup("")
    return Markup('<p class="rounded-lg bg-danger-50 px-3 py-2 text-sm text-danger-700 dark:bg-danger-400/10 '
                  'dark:text-danger-400">This file is missing from storage. Upload it again, or delete this '
                  'entry.</p>')


def _file_card(ctx: Any, record: Any) -> Markup:
    """Big preview on the edit and view pages."""
    if record is None:
        return Markup("")
    url = escape(_link(ctx, record))
    if record.missing:
        return _missing_note(record)
    if record.kind == "image":
        return Markup(f'<a href="{url}" target="_blank" rel="noopener"><img src="{url}" alt="{escape(record.alt or "")}"'
                      f' loading="lazy" class="w-full rounded-lg ring-1 ring-gray-950/10 dark:ring-white/10" '
                      f'style="max-height:420px;object-fit:contain;background:#f3f4f6"></a>')
    if record.kind == "video":
        return Markup(f'<video src="{url}" controls preload="metadata" class="w-full rounded-lg" '
                      f'style="max-height:420px"></video>')
    if record.kind == "audio":
        return Markup(f'<audio src="{url}" controls preload="metadata" class="w-full"></audio>')
    return Markup(f'<a href="{url}" target="_blank" rel="noopener" class="tw-btn px-3 py-2 text-sm bg-white ring-1 '
                  f'ring-gray-950/10 dark:bg-transparent dark:ring-white/20">Open {escape(record.name)}</a>')


# ---------------------------------------------------------------------- delete, safely
def _blocked(ctx: Any, record: Any) -> list[dict]:
    plugin = _plugin(ctx)
    if plugin is None or not plugin.protect_used:
        return []
    return plugin.usages(ctx.db, record, ctx)


def delete_bulk_action() -> BulkAction:
    """Delete the selected files; files still in use are skipped and named."""

    def run(records, db, ctx):
        plugin = _plugin(ctx)
        host = MediaResource.host()
        deleted, kept = 0, []
        for record in records or []:
            if not host.can(ctx, "delete", record):
                continue
            if _blocked(ctx, record):
                kept.append(str(record))
                continue
            path = record.path
            db.delete(record)
            db.flush()
            plugin.forget_file(db, record, path)
            deleted += 1
        db.commit()
        if kept:
            names = ", ".join(kept[:5]) + (f" and {len(kept) - 5} more" if len(kept) > 5 else "")
            Notification("Some files are in use").body(f"Not deleted: {names}. Remove them where they are used "
                                                       f"first.").warning().send(ctx)
        if deleted:
            Notification("Deleted").body(f"{deleted} file(s) deleted.").success().send(ctx)

    return (
        BulkAction("delete").label("Delete").icon("trash-2").color("danger").requires_confirmation()
        .modal_heading("Delete selected files")
        .modal_description("The files are removed from storage too. Files still used by a post, ticket or "
                           "employee are skipped.")
        .modal_submit_action_label("Delete")
        .authorize("delete_any")
        .action(run)
        .success_notification_title(None)
    )


def move_bulk_action() -> BulkAction:
    def run(records, data, db):
        folder = clean_folder(data.get("folder"))
        for record in records or []:
            record.folder = folder
        db.commit()

    return (
        BulkAction("move").label("Move to folder").icon("folder-input").color("gray")
        .form(lambda ctx: [TextInput("folder").label("Folder").max_length(100).datalist(folder_options(ctx))
                           .helper_text("Empty: no folder.")])
        .authorize("update")
        .action(run)
        .success_notification_title("Moved")
    )


# ---------------------------------------------------------------------- upload and check
def upload_action() -> Action:
    """Upload many files at once. Each one joins the library as soon as it is uploaded."""

    def form(ctx):
        plugin = _plugin(ctx)
        upload = FileUpload("files").label("Files").multiple().directory(plugin.directory) \
            .max_size(plugin.max_size).max_files(plugin.max_files).required()
        upload._media_library_upload = True  # always recorded; no "Choose from library" inside the library
        if plugin.accepted_file_types:
            upload.accepted_file_types(plugin.accepted_file_types)
        return [
            upload,
            TextInput("folder").label("Folder").max_length(100).datalist(folder_options(ctx))
            .placeholder("blog, products, team...").helper_text("Optional. Groups files so they are easy to find."),
        ]

    def run(data, db, ctx):
        plugin = _plugin(ctx)
        folder = clean_folder(data.get("folder")) if data.get("folder") else None
        paths = [p for p in data.get("files") or [] if isinstance(p, str) and p]
        if not paths:
            Notification("Pick at least one file").warning().send(ctx)
            raise Halt()
        for path in dict.fromkeys(paths):  # the same file picked twice counts once
            item = find_item(db, path) or plugin.add_file(db, path, user_id=_me(ctx))
            if folder is not None:
                item.folder = folder
        db.commit()
        return len(paths)

    return (
        Action("upload").label("Upload files").icon("upload").color("primary")
        .modal_heading("Upload files")
        .modal_description("Images, PDFs, videos and other files. Upload once, then use them anywhere.")
        .modal_width("2xl")
        .form(form)
        .modal_submit_action_label("Add to library")
        .authorize("create")
        .action(run)
        .success_notification_title("Added to the library")
    )


def check_files_action() -> Action:
    def run(db, ctx):
        missing, found = check_files(db, ctx.panel.storage)
        db.commit()
        if missing or found:
            Notification("Files checked").body(f"{missing} missing, {found} found again.") \
                .warning().send(ctx)
        else:
            Notification("All files are there").success().send(ctx)

    return (
        Action("check_files").label("Check files").icon("scan-search").color("gray")
        .tooltip("Find library entries whose file is gone from storage")
        .authorize("update")
        .action(run)
        .success_notification_title(None)
    )


# ---------------------------------------------------------------------- resource
class MediaResource(Resource):
    model = MediaItem
    slug = "media"
    label = "File"
    plural_label = "Media library"
    navigation_label = "Media library"
    icon = "images"
    description = "Every image and file in one place. Upload once, reuse anywhere."
    pages = ("index", "edit", "view")
    global_search_attributes = ["name", "title", "alt"]
    record_title_attribute = "name"

    @classmethod
    def global_search_image(cls, record: Any) -> str | None:
        return _preview(record)

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Group([
                Section("File").icon("image").columns(1).schema([
                    Placeholder("preview").hidden_label().content(lambda record, ctx: _file_card(ctx, record)),
                ]),
            ]).columns(1).column_span(2),
            Section("Details").icon("pencil").columns(1).column_span(1).schema([
                TextInput("name").label("File name").required().max_length(255),
                TextInput("title").max_length(255),
                TextInput("alt").label("Alt text").max_length(255)
                .helper_text("Say what the image shows. Screen readers and search engines read it.")
                .visible(lambda record: record is None or record.kind == "image"),
                Textarea("caption").rows(2).max_length(2000),
                TextInput("folder").max_length(100).datalist(folder_options)
                .dehydrate_state_using(lambda state: clean_folder(state)),
                TagsInput("tags"),
            ]),
        ])

    @classmethod
    def infolist(cls, infolist):
        return infolist.columns(3).schema([
            Group([
                Section("File").icon("image").columns(1).schema([
                    Placeholder("preview").hidden_label().content(lambda record, ctx: _file_card(ctx, record)),
                ]),
                Section("Use it").icon("copy").columns(1).schema([
                    TextEntry("link").label("Link").copyable().limit(90)
                    .state(lambda record, ctx: _absolute_link(ctx, record)),
                    TextEntry("markdown").label("Markdown").copyable().limit(90)
                    .state(lambda record, ctx: _markdown(ctx, record))
                    .helper_text("Paste into a blog post or a page."),
                ]),
                Section("Used in").icon("link").columns(1).schema([
                    Placeholder("used").hidden_label().content(lambda record, ctx: _usages_html(ctx, record)),
                ]),
            ]).columns(1).column_span(2),
            Section("Details").icon("info").columns(1).column_span(1).schema([
                TextEntry("name").label("Name").inline_label(),
                TextEntry("title").placeholder("—").inline_label(),
                TextEntry("alt").label("Alt text").placeholder("—").inline_label()
                .visible(lambda record: record is not None and record.kind == "image"),
                TextEntry("kind").label("Type").badge().inline_label().format_state_using(_kind_label)
                .color(_kind_color),
                TextEntry("mime").label("Format").inline_label(),
                TextEntry("size").inline_label().format_state_using(lambda state: human_size(state)),
                TextEntry("dims").label("Pixels").inline_label()
                .state(lambda record: record.dimensions).placeholder("—")
                .visible(lambda record: record is not None and record.kind == "image"),
                TextEntry("folder").placeholder("—").inline_label(),
                TextEntry("created_at").label("Added").since().inline_label(),
            ]),
        ])

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        if page in ("list", "index"):
            return [check_files_action(), upload_action()]
        if page == "view":
            return [Action("open").label("Open").icon("external-link").color("gray")
                    .url(lambda record, ctx: _link(ctx, record), open_in_new_tab=True),
                    ActionGroup([EditAction(), DeleteAction()]).button()]
        return super().header_actions(ctx, page, record)

    @classmethod
    def before_delete(cls, record, ctx):
        used = _blocked(ctx, record)
        if used:
            where = ", ".join(f"{u['label']} {u['title']}" for u in used[:3])
            Notification("This file is in use").body(f"Used in {where}. Remove it there first.").danger().send(ctx)
            raise Halt()

    @classmethod
    def after_delete(cls, record, db, ctx):
        plugin = _plugin(ctx)
        if plugin is not None:
            plugin.forget_file(db, record, record.path)

    @classmethod
    def table(cls, table):
        def kind_tab(kind):
            return lambda query, model: query.where(model.kind == kind)

        return (
            table.columns([
                ImageColumn("preview").label("").state(_preview).size(48)
                .default_image_url(None),
                TextColumn("name").label("File").weight("medium").searchable(columns=["name", "title", "alt"])
                .sortable().limit(48).icon(lambda record: "triangle-alert" if record.missing
                                           else KINDS.get(record.kind, KINDS["other"])[2])
                .icon_color(lambda record: "danger" if record.missing else "gray")
                .description(lambda record: record.title if record.title and record.title != record.name
                             else None),
                TextColumn("kind").label("Type").badge().format_state_using(_kind_label).color(_kind_color),
                TextColumn("size").sortable().format_state_using(lambda state: human_size(state)).alignment("end"),
                TextColumn("dims").label("Pixels").state(lambda record: record.dimensions).placeholder("—")
                .toggleable(),
                TextColumn("folder").placeholder("—").badge().color("gray").sortable().toggleable(),
                TextColumn("alt").label("Alt text").placeholder("—").limit(40).toggleable(hidden_by_default=True),
                TextColumn("created_at").label("Uploaded").since().sortable(),
            ])
            .filters([
                SelectFilter("folder").options(folder_options),
                TernaryFilter("missing").label("File missing"),
                TernaryFilter("alt").label("Has alt text")
                .queries(true=lambda query, model: query.where(model.alt.is_not(None), model.alt != ""),
                         false=lambda query, model: query.where((model.alt.is_(None)) | (model.alt == ""))),
            ])
            .tabs([
                ListTab("all").label("All"),
                ListTab("images").label("Images").icon("image").query(kind_tab("image")),
                ListTab("documents").label("Documents").icon("file-text").query(kind_tab("document")),
                ListTab("videos").label("Videos").icon("film").query(kind_tab("video")),
                ListTab("audio").label("Audio").icon("music").query(kind_tab("audio")),
                ListTab("other").label("Other").query(kind_tab("other")),
            ])
            .actions([ActionGroup([ViewAction(), EditAction(), DeleteAction()])])
            .bulk_actions([move_bulk_action(), delete_bulk_action()])
            .record_url(lambda record, ctx: MediaResource.get_url(ctx, "view", record))
            .empty_state("No files yet", "Upload images and files, or add a cover to a blog post. "
                         "They all show up here.", "images")
            .default_sort("created_at", "desc")
            .paginated([24, 48, 96], 24)
        )


def total_size(db: Any) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(MediaItem.size), 0))) or 0)


__all__ = ["MediaResource", "record_file", "total_size", "upload_action"]
