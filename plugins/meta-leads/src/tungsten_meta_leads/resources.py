"""Screens for lead forms and the log of leads Meta sent."""

from __future__ import annotations

from sqlalchemy import func, select
from tungsten import Notification, Resource
from tungsten.actions import Action, EditAction, Halt
from tungsten.forms import KeyValue, Section, Select, Toggle
from tungsten.tables import SelectFilter, TextColumn, ToggleColumn
from tungsten_leads.resources import status_options, user_options

from .graph import GraphError
from .models import MetaForm, MetaLeadLog
from .sync import import_leadgen, sync_form

LOG_COLORS = {"imported": "success", "duplicate": "gray", "skipped": "warning", "failed": "danger"}


def _plugin(ctx):
    return ctx.panel.get_plugin("meta-leads")


def sync_one(record, ctx, db):
    plugin = _plugin(ctx)
    try:
        new = sync_form(db, plugin.graph(db), record, limit=plugin.sync_limit, default_status=plugin.default_status)
    except GraphError as exc:
        db.rollback()
        Notification("Meta said no").body(str(exc)).danger().send(ctx)
        raise Halt from exc
    db.commit()
    Notification("Synced").body(f"{new} new leads from {record.name}.").success().send(ctx)


class MetaFormResource(Resource):
    model = MetaForm
    slug = "meta-forms"
    label = "Meta lead form"
    icon = "file-input"
    navigation_group = "Leads"
    navigation_sort = 61
    description = "Lead forms of your connected pages. Switch a form off to stop its leads."
    pages = ("index", "edit")

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return []  # forms come from Meta: no "create", and a deleted form would come back on the next sync

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Section("New leads from this form").icon("settings-2").column_span(1).columns(1).schema([
                Toggle("enabled").label("Bring leads in"),
                Select("default_status").label("Start as").options(status_options).placeholder("New"),
                Select("assign_to").label("Assign to").options(user_options).searchable(),
            ]),
            Section("Answers go to").icon("arrow-right-left").column_span(2).columns(1).description(
                'Left: the question in Meta. Right: name, email, phone, company, notes, or a lead field key. '
                'Leave the right side empty to skip an answer.').schema([
                KeyValue("field_map").hidden_label().key_label("Meta question").value_label("Save to")
                .addable(False).deletable(False).editable_keys(False),
            ]),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").label("Form").weight("medium").searchable()
                .description(lambda record: record.page_name),
                TextColumn("status").badge().colors({"success": "ACTIVE", "gray": ["ARCHIVED", "DELETED"]}),
                ToggleColumn("enabled").label("Bring leads in"),
                TextColumn("leads_imported").label("Leads imported").sortable(),
                TextColumn("last_lead_at").label("Last lead").since().sortable(),
                TextColumn("last_synced_at").label("Last sync").since().toggleable(),
            ])
            .filters([SelectFilter("page_name").label("Page").options(
                lambda db: {n: n for n in db.scalars(select(MetaForm.page_name).distinct())})])
            .actions([
                Action("sync").label("Sync leads").icon("refresh-cw").color("gray").icon_button()
                .action(sync_one),
                EditAction(),
            ])
            .default_sort("last_lead_at", "desc")
            .empty_state("No lead forms yet", "Connect Facebook on the Facebook & Instagram page to see your lead forms.",
                         "file-input")
        )


class MetaLeadLogResource(Resource):
    model = MetaLeadLog
    slug = "meta-lead-log"
    label = "Meta lead"
    plural_label = "Meta lead log"
    icon = "scroll-text"
    navigation_group = "Leads"
    navigation_sort = 62
    description = "Every lead Meta sent, and what happened to it."
    pages = ("index",)

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(MetaLeadLog).where(MetaLeadLog.status == "failed")) or None

    navigation_badge_color = "danger"

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return []

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("created_at").label("When").since().sortable(),
                TextColumn("status").badge().colors({c: s for s, c in LOG_COLORS.items()}),
                TextColumn("leadgen_id").label("Meta lead id").searchable().copyable().font_mono(),
                TextColumn("via").badge().color("gray"),
                TextColumn("error").wrap().limit(160),
                TextColumn("lead_id").label("Lead").url(
                    lambda record, ctx: ctx.url("leads", record.lead_id) if record.lead_id else None)
                .format_state_using(lambda state: f"#{state}" if state else ""),
            ])
            .filters([SelectFilter("status").options({s: s.capitalize() for s in LOG_COLORS}).multiple()])
            .actions([
                Action("retry").label("Try again").icon("rotate-ccw").color("gray").icon_button()
                .visible(lambda record: record.status == "failed").action(retry),
            ])
            .default_sort("created_at", "desc")
        )


def retry(record, ctx, db):
    plugin = _plugin(ctx)
    log = import_leadgen(db, plugin.graph(db), leadgen_id=record.leadgen_id, page_id=record.page_id,
                         form_id=record.form_id, via="retry", default_status=plugin.default_status)
    if log.status in ("imported", "duplicate"):
        db.delete(record)
    else:
        db.delete(log)
        record.error = log.error
    db.commit()
    Notification("Imported" if log.status == "imported" else "Still failing").body(log.error) \
        .status("success" if log.status in ("imported", "duplicate") else "danger").send(ctx)
