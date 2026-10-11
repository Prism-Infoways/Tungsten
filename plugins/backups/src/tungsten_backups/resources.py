"""The Backups screen: back up now, download, check and delete."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup, escape
from sqlalchemy import exists, select

from tungsten import Notification, Resource
from tungsten.actions import Action
from tungsten.forms import Radio, Textarea
from tungsten.tables import SelectFilter, TextColumn

from .engine import BackupError, free_space, human_size
from .models import DONE, FAILED, RUNNING, Backup
from .service import KINDS, delete_backup, file_of, start_backup, verify

PERMISSION = "backups.manage"
DOWNLOAD_PERMISSION = "backups.download"
STATUS = {RUNNING: ("Running", "warning"), DONE: ("Ready", "success"), FAILED: ("Failed", "danger")}
METHODS = {"sqlite": "SQLite copy", "pg_dump": "pg_dump", "mysqldump": "mysqldump", "json": "JSON tables"}


def plugin_of(ctx: Any) -> Any:
    return ctx.panel.get_plugin("backups")


def _user_id(ctx: Any) -> str | None:
    return ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None


def allowed(ctx: Any, permission: str = PERMISSION) -> bool:
    plugin = plugin_of(ctx)
    if not ctx.can(permission):
        return False
    return plugin.allow is None or bool(plugin.allow(ctx))


def can_download(ctx: Any, record: Backup | None = None) -> bool:
    plugin = plugin_of(ctx)
    if not ctx.panel.auth.enabled and not plugin.allow_without_login:
        return False  # without a login anyone who reaches the panel could take all your data
    if not allowed(ctx, DOWNLOAD_PERMISSION):
        return False
    if record is None:
        return True
    path = file_of(plugin, record)
    return record.status == DONE and path is not None and path.is_file()


def download_url(ctx: Any, record: Backup) -> str:
    return ctx.url("backups-download", record.id)


# ====================================================================== actions
def _start(ctx: Any, db: Any, data: dict) -> None:
    plugin = plugin_of(ctx)
    kind = data.get("kind") or "database"
    try:
        row = start_backup(plugin, kind=kind, note=data.get("note"), user_id=_user_id(ctx))
    except BackupError as exc:
        Notification("Backup not started").body(str(exc)).danger().send(ctx)
        return
    ctx.panel.log_activity(ctx, "created", row, f"Started backup {row.name}")
    db.commit()
    if row.status == RUNNING:
        Notification("Backup started").body("It runs in the background. This list updates when it's ready.") \
            .info().send(ctx)
    elif row.status == DONE:
        Notification("Backup ready").body(f"{row.name} ({human_size(row.size)})").success().send(ctx)
    else:
        Notification("Backup failed").body(row.error or "Unknown error").danger().send(ctx)


def backup_action() -> Action:
    return (
        Action("backup").label("Back up now").icon("database-backup")
        .visible(lambda ctx: allowed(ctx))
        .modal_heading("Make a backup").modal_width("lg")
        .modal_description(lambda ctx: _free_text(ctx))
        .form([
            Radio("kind").label("What to save").options(KINDS).default("database")
            .descriptions({"database": "Every table of your database.",
                           "full": "The database plus uploaded files (images, documents)."}),
            Textarea("note").label("Note").rows(2).max_length(300).placeholder("Before the price update"),
        ])
        .modal_submit_action_label("Back up")
        .action(lambda ctx, db, data: _start(ctx, db, data))
    )


def _free_text(ctx: Any) -> str:
    plugin = plugin_of(ctx)
    try:
        free = human_size(free_space(plugin.folder))
    except OSError:
        free = "unknown"
    return f"Saved to a private folder on the server, never a public link. Free disk space: {free}."


def _verify(ctx: Any, db: Any, record: Backup) -> None:
    problems = verify(plugin_of(ctx), db, record)
    if problems:
        Notification("Backup has problems").body(" ".join(problems)).danger().send(ctx)
    else:
        Notification("Backup is fine").body("Every part reads back and matches its checksum.").success().send(ctx)


def _delete(ctx: Any, db: Any, records: list[Backup]) -> None:
    deleted = 0
    for record in records:
        try:
            ctx.panel.log_activity(ctx, "deleted", record, f"Deleted backup {record.name}")
            delete_backup(plugin_of(ctx), db, record)
            deleted += 1
        except BackupError as exc:
            Notification("Not deleted").body(str(exc)).warning().send(ctx)
    db.commit()
    if deleted:
        Notification("Deleted").body(f"{deleted} backup(s) and their files removed.").success().send(ctx)


def details(record: Backup) -> Markup:
    rows = [("File", record.name), ("What", KINDS.get(record.kind, record.kind)),
            ("Status", STATUS.get(record.status, (record.status, ""))[0])]
    if record.status == DONE:
        rows += [("Size", human_size(record.size)), ("Database saved as", METHODS.get(record.method or "", "-")),
                 ("Tables", f"{record.tables:,}"), ("Rows", f"{record.rows:,}" if record.rows else "-"),
                 ("Files", f"{record.files:,}"), ("SHA-256", record.sha256 or "-"),
                 ("Took", f"{(record.details or {}).get('seconds', '-')} s"),
                 ("Last checked", f"{record.verified_at:%d %b %Y, %H:%M}" if record.verified_at else "Never")]
    if record.note:
        rows.append(("Note", record.note))
    if record.error:
        rows.append(("Error", record.error))
    info = record.details or {}
    if info.get("note"):
        rows.append(("Heads up", info["note"]))
    if info.get("skipped"):
        more = info.get("skipped_count", 0) - len(info["skipped"])
        rows.append(("Skipped files", ", ".join(info["skipped"]) + (f" and {more} more" if more > 0 else "")))
    body = "".join(
        f'<div style="display:grid;grid-template-columns:9rem 1fr;gap:.75rem;padding:.5rem 0;'
        f'border-bottom:1px solid rgba(127,127,127,.15)"><div style="opacity:.65">{escape(k)}</div>'
        f'<div style="word-break:break-all">{escape(v)}</div></div>' for k, v in rows)
    return Markup(f"<div>{body}</div>")


# ====================================================================== the screen
class BackupResource(Resource):
    model = Backup
    slug = "backups"
    label = "Backup"
    icon = "database-backup"
    navigation_group = "Settings"
    navigation_label = "Backups"
    navigation_sort = 95
    description = "Copies of your database (and uploaded files) you can download. Only admins see this."
    record_title_attribute = "name"
    simple = True
    pages = ("index",)
    permission = PERMISSION

    @classmethod
    def can(cls, ctx, ability, record=None):
        if ability in ("create", "update", "replicate", "delete", "delete_any", "restore", "force_delete"):
            return False  # backups are made with "Back up now" and deleted by the action below
        return allowed(ctx)

    @classmethod
    def abilities(cls):
        return []  # one permission covers the screen

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return [backup_action()]

    @classmethod
    def table(cls, table):
        ctx = getattr(table, "ctx", None)
        running = False
        if ctx is not None:
            running = bool(ctx.db.scalar(select(exists().where(Backup.status == RUNNING))))
        table = (
            table.columns([
                TextColumn("created_at").label("Made").datetime().sortable(),
                TextColumn("status").badge()
                .state(lambda record: STATUS.get(record.status, (record.status, "gray"))[0])
                .color(lambda record: STATUS.get(record.status, (record.status, "gray"))[1]),
                TextColumn("kind").label("What").state(lambda record: KINDS.get(record.kind, record.kind)),
                TextColumn("size").state(lambda record: human_size(record.size) if record.status == DONE else "-")
                .sortable(),
                TextColumn("note").placeholder("-").color("gray").limit(40)
                .description(lambda record: (record.error or "")[:120] or None),
                TextColumn("name").label("File").searchable().color("gray").limit(44).toggleable(hidden_by_default=True),
            ])
            .filters([
                SelectFilter("status").options({k: v[0] for k, v in STATUS.items()}),
                SelectFilter("kind").label("What").options(KINDS),
            ])
            .actions([
                Action("download").label("Download").icon("download").color("primary")
                .visible(lambda ctx, record: can_download(ctx, record))
                .url(lambda ctx, record: download_url(ctx, record), open_in_new_tab=True),
                Action("view").label("Details").icon("eye").color("gray").slide_over().modal_width("2xl")
                .modal_heading(lambda record: record.name)
                .modal_content(lambda record: details(record))
                .modal_submit_action(False).modal_cancel_action_label("Close"),
                Action("verify").label("Check").icon("shield-check").color("gray")
                .visible(lambda record: record.status == DONE)
                .action(lambda ctx, db, record: _verify(ctx, db, record)),
                Action("remove").label("Delete").icon("trash-2").color("danger")
                .visible(lambda record: record.status != RUNNING)
                .requires_confirmation().modal_heading("Delete this backup?")
                .modal_description("The file is removed from the server. This can't be undone.")
                .modal_submit_action_label("Delete")
                .action(lambda ctx, db, record: _delete(ctx, db, [record])),
            ])
            .bulk_actions([
                Action("remove_many").label("Delete").icon("trash-2").color("danger")
                .requires_confirmation().modal_heading("Delete these backups?")
                .modal_description("Their files are removed from the server. This can't be undone.")
                .modal_submit_action_label("Delete")
                .action(lambda ctx, db, records: _delete(ctx, db, list(records))),
            ])
            .empty_state("No backups yet", "Press Back up now to save a copy of your data.", "database-backup")
            .default_sort("created_at", "desc")
        )
        return table.poll("3s") if running else table
