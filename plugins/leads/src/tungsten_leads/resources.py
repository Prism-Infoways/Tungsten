"""Admin screens of the leads plugin: Leads, its timeline, and Lead fields."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from sqlalchemy import func, select
from tungsten import RelationManager, Resource
from tungsten.actions import (
    Action,
    ActionGroup,
    BulkAction,
    CreateAction,
    DeleteAction,
    DeleteBulkAction,
    EditAction,
    ViewAction,
)
from tungsten.forms import (
    DateTimePicker,
    Group,
    Section,
    Select,
    TagsInput,
    Textarea,
    TextInput,
    Toggle,
)
from tungsten.importexport import ExportAction, ExportBulkAction
from tungsten.tables import DateFilter, ListTab, SelectFilter, TextColumn, ToggleColumn

from .fields import FIELD_TYPES, OPTION_TYPES, CustomFields
from .models import Lead, LeadActivity, LeadField
from .widgets import LeadStats

DEFAULT_STATUSES = {
    "new": ("New", "info"),
    "contacted": ("Contacted", "warning"),
    "qualified": ("Qualified", "primary"),
    "proposal": ("Proposal sent", "purple"),
    "won": ("Won", "success"),
    "lost": ("Lost", "danger"),
}
DEFAULT_SOURCES = {
    "manual": "Added by hand",
    "website": "Website",
    "meta": "Facebook / Instagram",
    "whatsapp": "WhatsApp",
    "import": "Import",
    "referral": "Referral",
    "other": "Other",
}
ACTIVITY_TYPES = {
    "note": "Note",
    "call": "Call",
    "email": "Email",
    "meeting": "Meeting",
    "whatsapp": "WhatsApp",
    "system": "System",
}


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("leads") if ctx is not None else None


def statuses(ctx: Any) -> dict[str, tuple[str, str]]:
    plugin = _plugin(ctx)
    return plugin.statuses if plugin is not None else DEFAULT_STATUSES


def status_options(ctx: Any) -> dict[str, str]:
    return {key: label for key, (label, _) in statuses(ctx).items()}


def source_options(ctx: Any) -> dict[str, str]:
    plugin = _plugin(ctx)
    return dict(plugin.sources if plugin is not None else DEFAULT_SOURCES)


def user_options(ctx: Any) -> dict[str, str]:
    """Panel users, for the "Assigned to" dropdown."""
    auth = ctx.panel.auth
    if auth.user_model is None:
        return {}
    users = ctx.db.scalars(select(auth.user_model).limit(500)).all()
    return {auth.user_id(u): auth.display_name(u) for u in users}


def user_name(ctx: Any, user_id: str | None) -> str | None:
    if not user_id or ctx is None:
        return None
    cache = ctx.__dict__.setdefault("_lead_user_names", {})
    if user_id not in cache:
        user = ctx.panel.auth.find_by_id(ctx.db, user_id)
        cache[user_id] = ctx.panel.auth.display_name(user) if user is not None else None
    return cache[user_id]


def _status_color(ctx: Any, state: Any) -> str:
    return statuses(ctx).get(str(state), ("", "gray"))[1]


class ActivitiesRelationManager(RelationManager):
    """The lead's timeline: notes, calls, emails, messages."""

    relationship = "activities"
    icon = "messages-square"
    title = "Timeline"

    @classmethod
    def form(cls, form):
        return form.schema([
            Select("type").options(ACTIVITY_TYPES).default("note").required(),
            Textarea("body").label("Details").rows(3).required().column_span("full"),
        ])

    @classmethod
    def before_create(cls, record, ctx):
        if ctx.user is not None:
            record.user_id = ctx.panel.auth.user_id(ctx.user)

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("type").badge().format_state_using(lambda state: ACTIVITY_TYPES.get(state, state)),
                TextColumn("body").label("Details").wrap().limit(200),
                TextColumn("user_id").label("By").state(lambda record, ctx: user_name(ctx, record.user_id)),
                TextColumn("created_at").label("When").since().sortable(),
            ])
            .header_actions([CreateAction().label("Add note")])
            .actions([EditAction(), DeleteAction()])
            .default_sort("created_at", "desc")
        )


class LeadResource(Resource):
    model = Lead
    icon = "contact"
    navigation_group = "Leads"
    navigation_sort = 1
    description = "Everyone who showed interest, from every source."
    global_search_attributes = ["name", "email", "phone", "company"]
    relations = [ActivitiesRelationManager]
    widgets = [LeadStats]

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(Lead).where(Lead.status == "new")) or None

    navigation_badge_color = "info"

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Group([
                Section("Contact").icon("user").schema([
                    TextInput("name").required().max_length(150).placeholder("Amit Sharma"),
                    TextInput("company").max_length(150),
                    TextInput("email").email().max_length(255).prefix_icon("mail"),
                    TextInput("phone").tel().max_length(40).prefix_icon("phone").placeholder("+91 98765 43210"),
                ]),
                CustomFields("More details").icon("list-plus"),
                Section("Notes").icon("notebook-pen").columns(1).schema([
                    TagsInput("tags"),
                    Textarea("notes").rows(3),
                ]),
            ]).columns(1).column_span(2),
            Section("Status").icon("flag").column_span(1).columns(1).schema([
                Select("status").options(status_options).default("new").required(),
                Select("source").options(source_options).default("manual").required(),
                Select("assigned_to").label("Assigned to").options(user_options).searchable()
                .default(lambda ctx: ctx.panel.auth.user_id(ctx.user) if ctx and ctx.user is not None else None),
                TextInput("value").label("Deal value").numeric().min_value(0),
                DateTimePicker("follow_up_at").label("Next follow-up"),
            ]),
        ])

    @classmethod
    def after_create(cls, record, db, ctx):
        from .service import add_activity, _listeners

        user_id = ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None
        add_activity(db, record, "Lead added", type="system", user_id=user_id)
        for fn in list(_listeners):
            fn(db, record)

    @classmethod
    def table(cls, table):
        def set_status(key):
            return lambda records, db: ([setattr(r, "status", key) for r in records], db.commit())

        return (
            table.columns([
                TextColumn("name").weight("medium").searchable().sortable()
                .description(lambda record: record.company),
                TextColumn("phone").searchable().copyable().toggleable(),
                TextColumn("email").searchable().copyable().toggleable(),
                TextColumn("status").badge().sortable()
                .format_state_using(lambda state, ctx: status_options(ctx).get(state, state))
                .color(lambda state, ctx: _status_color(ctx, state)),
                TextColumn("source").badge().color("gray").sortable()
                .format_state_using(lambda state, ctx: source_options(ctx).get(state, state)),
                TextColumn("assigned_to").label("Assigned to").toggleable()
                .state(lambda record, ctx: user_name(ctx, record.assigned_to)),
                TextColumn("follow_up_at").label("Follow-up").datetime().sortable().toggleable(),
                TextColumn("created_at").label("Added").since().sortable(),
            ])
            .filters([
                SelectFilter("status").options(status_options).multiple(),
                SelectFilter("source").options(source_options).multiple(),
                SelectFilter("assigned_to").label("Assigned to").options(user_options),
                DateFilter("created_at").label("Added on"),
            ])
            .tabs([
                ListTab("all").label("All leads").badge(),
                ListTab("mine").label("My leads").query(
                    lambda query, model, ctx: query.where(model.assigned_to == ctx.panel.auth.user_id(ctx.user))
                    if ctx.user is not None else query),
                ListTab("follow_up").label("Follow-up due").badge(color="warning").query(
                    lambda query, model: query.where(model.follow_up_at <= dt.datetime.now(),
                                                     model.status.notin_(["won", "lost"]))),
                ListTab("new").label("New").badge(color="info").query(
                    lambda query, model: query.where(model.status == "new")),
                ListTab("won").label("Won").query(lambda query, model: query.where(model.status == "won")),
            ])
            .actions([
                Action("call").label("Call").icon("phone").color("success").icon_button()
                .visible(lambda record: bool(record.phone)).url(lambda record: f"tel:{record.phone}"),
                EditAction(),
                ActionGroup([ViewAction(), DeleteAction()]),
            ])
            .bulk_actions([
                BulkAction("assign").label("Assign to").icon("user-check")
                .form(lambda form: form.schema([Select("user").label("User").options(user_options).required()]))
                .action(lambda records, data, db: ([setattr(r, "assigned_to", data["user"]) for r in records],
                                                   db.commit()))
                .success_notification_title("Leads assigned"),
                BulkAction("won").label("Mark won").icon("trophy").color("success").action(set_status("won"))
                .success_notification_title("Leads marked as won"),
                BulkAction("lost").label("Mark lost").icon("circle-x").color("danger").action(set_status("lost"))
                .success_notification_title("Leads marked as lost"),
                ExportBulkAction(),
                DeleteBulkAction(),
            ])
            .header_actions([ExportAction()])
            .default_sort("created_at", "desc")
        )


def _slug_key(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")[:60]


class LeadFieldResource(Resource):
    """Settings screen: add your own fields to the lead form."""

    model = LeadField
    icon = "list-plus"
    navigation_group = "Leads"
    navigation_sort = 50
    label = "Lead field"
    description = "Add your own fields to the lead form, like budget, city or course."
    simple = True

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("label").required().max_length(100).live(on_blur=True)
            .after_state_updated(lambda state, set, get, operation:
                                 set("key", _slug_key(state)) if operation == "create" else None),
            TextInput("key").label("Key").required().max_length(60).unique()
            .regex(r"^[a-z][a-z0-9_]*$", "Use small letters, numbers and _ only, starting with a letter.")
            .helper_text("Saved data uses this name. Don't change it after leads have values."),
            Select("type").options(FIELD_TYPES).default("text").required().live(),
            TextInput("sort").label("Order").integer().default(0),
            TagsInput("options").label("Choices").visible(lambda get: get("type") in OPTION_TYPES)
            .required(lambda get: get("type") in OPTION_TYPES).column_span("full")
            .helper_text("Type a choice and press Enter."),
            TextInput("help_text").label("Help text").max_length(255).column_span("full"),
            Toggle("required"),
            Toggle("is_active").label("Show on the form").default(True),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("label").weight("medium").searchable()
                .description(lambda record: record.key),
                TextColumn("type").badge().format_state_using(lambda state: FIELD_TYPES.get(state, state)),
                TextColumn("options").label("Choices").state(lambda record: ", ".join(record.options or [])).limit(60),
                ToggleColumn("required"),
                ToggleColumn("is_active").label("Shown"),
                TextColumn("sort").label("Order").sortable(),
            ])
            .actions([EditAction(), DeleteAction()])
            .reorderable("sort")
            .default_sort("sort", "asc")
        )


__all__ = ["ActivitiesRelationManager", "LeadFieldResource", "LeadResource", "LeadActivity"]
