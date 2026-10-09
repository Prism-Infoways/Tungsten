"""Admin screens of the tickets plugin: Tickets (with the conversation), Categories and Saved replies."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select

from tungsten import Resource
from tungsten.actions import (
    Action,
    ActionGroup,
    BulkAction,
    DeleteAction,
    DeleteBulkAction,
    EditAction,
    ViewAction,
)
from tungsten.forms import (
    DateTimePicker,
    FileUpload,
    Group,
    Placeholder,
    Section,
    Select,
    TagsInput,
    Textarea,
    TextInput,
    Toggle,
)
from tungsten.importexport import ExportAction, ExportBulkAction
from tungsten.infolists import TextEntry
from tungsten.support.colors import COLOR_NAMES
from tungsten.tables import DateFilter, ListTab, SelectFilter, TextColumn, ToggleColumn

from .models import SavedReply, Ticket, TicketCategory
from .service import (
    CLOSED_STATUSES,
    DEFAULT_PRIORITIES,
    DEFAULT_STATUSES,
    add_event,
    add_reply,
    prepare_new,
    set_status,
    status_changed,
    ticket_created,
)
from .views import render_conversation
from .widgets import TicketStats

SOURCES = {"panel": "Panel", "portal": "Support page", "api": "API", "email": "Email", "whatsapp": "WhatsApp"}


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("tickets") if ctx is not None else None


def statuses(ctx: Any) -> dict[str, tuple[str, str]]:
    plugin = _plugin(ctx)
    return plugin.statuses if plugin is not None else DEFAULT_STATUSES


def priorities(ctx: Any) -> dict[str, tuple[str, str]]:
    plugin = _plugin(ctx)
    return plugin.priorities if plugin is not None else DEFAULT_PRIORITIES


def status_options(ctx: Any) -> dict[str, str]:
    return {key: label for key, (label, _) in statuses(ctx).items()}


def priority_options(ctx: Any) -> dict[str, str]:
    return {key: label for key, (label, _) in priorities(ctx).items()}


def user_options(ctx: Any) -> dict[str, str]:
    """Panel users, for the "Agent" dropdowns."""
    auth = ctx.panel.auth
    if auth.user_model is None:
        return {}
    users = ctx.db.scalars(select(auth.user_model).limit(500)).all()
    return {auth.user_id(u): auth.display_name(u) for u in users}


def user_name(ctx: Any, user_id: str | None) -> str | None:
    if not user_id or ctx is None:
        return None
    cache = ctx.__dict__.setdefault("_ticket_user_names", {})
    if user_id not in cache:
        user = ctx.panel.auth.find_by_id(ctx.db, user_id)
        cache[user_id] = ctx.panel.auth.display_name(user) if user is not None else None
    return cache[user_id]


def _me(ctx: Any) -> str | None:
    return ctx.panel.auth.user_id(ctx.user) if ctx is not None and ctx.user is not None else None


def _my_name(ctx: Any) -> str | None:
    return ctx.panel.auth.display_name(ctx.user) if ctx is not None and ctx.user is not None else None


def _saved_reply_options(ctx: Any) -> dict[str, str]:
    rows = ctx.db.scalars(select(SavedReply).order_by(SavedReply.sort, SavedReply.title)).all()
    return {str(r.id): r.title for r in rows}


def _use_saved_reply(state: Any, set: Any, db: Any) -> None:
    if state:
        saved = db.get(SavedReply, int(state))
        if saved is not None:
            set("body", saved.body)


def _view_url(ctx: Any, record: Any) -> str:
    return TicketResource.get_url(ctx, "view", record)


# ---------------------------------------------------------------------- actions
def reply_action() -> Action:
    """Answer the customer: the message is emailed to them and shows on their ticket page."""

    def run(record, data, db, ctx):
        add_reply(db, record, data["body"], user_id=_me(ctx), author_name=_my_name(ctx),
                  attachments=data.get("attachments") or [], status=data.get("status") or None, ctx=ctx)
        db.commit()

    return (
        Action("reply").label("Reply").icon("reply").color("primary")
        .modal_heading(lambda record: f"Reply to {record.number}")
        .modal_width("2xl")
        .form(lambda ctx: [
            *([Select("saved_reply").label("Use a saved reply").options(_saved_reply_options).native()
               .after_state_updated(_use_saved_reply)] if _saved_reply_options(ctx) else []),
            Textarea("body").label("Message").rows(7).required().max_length(20000),
            FileUpload("attachments").multiple().directory("tickets").max_size(10240).max_files(5),
            Select("status").label("Then set status").options(status_options).native(),
        ])
        .fill_form(lambda record: {"status": "waiting" if record.status != "closed" else "open"})
        .modal_submit_action_label("Send reply")
        .action(run)
        .success_notification_title("Reply sent")
        .success_redirect_url(_view_url)
    )


def note_action() -> Action:
    """A note only agents see."""

    def run(record, data, db, ctx):
        add_reply(db, record, data["body"], user_id=_me(ctx), author_name=_my_name(ctx), internal=True,
                  attachments=data.get("attachments") or [], ctx=ctx)
        db.commit()

    return (
        Action("note").label("Internal note").icon("sticky-note").color("warning")
        .modal_heading("Internal note")
        .modal_description("Only your team sees this. The customer is not told.")
        .form([
            Textarea("body").label("Note").rows(5).required().max_length(20000),
            FileUpload("attachments").multiple().directory("tickets").max_size(10240).max_files(5),
        ])
        .modal_submit_action_label("Add note")
        .action(run)
        .success_notification_title("Note added")
        .success_redirect_url(_view_url)
    )


def resolve_action() -> Action:
    def run(record, db, ctx):
        set_status(db, record, "resolved", user_id=_me(ctx), by=_my_name(ctx), ctx=ctx)
        db.commit()

    return (
        Action("resolve").label("Resolve").icon("circle-check").color("success")
        .visible(lambda record: record is not None and record.status not in CLOSED_STATUSES)
        .requires_confirmation()
        .modal_description("The customer gets an email that the ticket is resolved. "
                           "If they reply, it opens again.")
        .action(run)
        .success_notification_title("Ticket resolved")
    )


def take_action() -> Action:
    def run(record, db, ctx):
        record.assigned_to = _me(ctx)
        add_event(db, record, f"Assigned to {_my_name(ctx)}", user_id=_me(ctx))
        db.commit()

    return (
        Action("take").label("Assign to me").icon("user-check").color("gray")
        .visible(lambda record, ctx: record is not None and ctx.user is not None and not record.assigned_to)
        .action(run)
        .success_notification_title("The ticket is yours")
    )


class TicketResource(Resource):
    model = Ticket
    slug = "tickets"
    icon = "life-buoy"
    navigation_group = "Help desk"
    navigation_sort = 1
    description = "Customer questions and problems, from the panel, your support page and the API."
    global_search_attributes = ["number", "subject", "requester_name", "requester_email"]
    record_title_attribute = "subject"
    widgets = [TicketStats]

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(Ticket).where(
            Ticket.status.notin_(CLOSED_STATUSES), Ticket.assigned_to.is_(None))) or None

    navigation_badge_color = "warning"

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Group([
                Section("Ticket").icon("life-buoy").columns(1).schema([
                    TextInput("subject").required().max_length(200).placeholder("Can't log in to my account"),
                    Textarea("description").label("Message from the customer").rows(6)
                    .visible(lambda operation: operation == "create"),
                    TagsInput("tags"),
                ]),
                Section("Customer").icon("user").schema([
                    TextInput("requester_name").label("Name").max_length(150),
                    TextInput("requester_email").label("Email").email().max_length(255).prefix_icon("mail"),
                    TextInput("requester_phone").label("Phone").tel().max_length(40).prefix_icon("phone"),
                ]),
            ]).columns(1).column_span(2),
            Section("Details").icon("flag").column_span(1).columns(1).schema([
                Select("status").options(status_options).default("open").required(),
                Select("priority").options(priority_options).default("normal").required(),
                Select("category_id").label("Category").relationship("category", "name").preload(),
                Select("assigned_to").label("Agent").options(user_options).searchable()
                .helper_text("Empty: the category's agent, if it has one."),
                DateTimePicker("due_at").label("Due by")
                .helper_text("Empty: set from the priority (the SLA)."),
                Select("source").options(SOURCES).default("panel").visible(lambda operation: operation != "create"),
            ]),
        ])

    @classmethod
    def infolist(cls, infolist):
        def status_color(state, ctx):
            return statuses(ctx).get(str(state), ("", "gray"))[1]

        def priority_color(state, ctx):
            return priorities(ctx).get(str(state), ("", "gray"))[1]

        return infolist.columns(3).schema([
            Section("Conversation").icon("message-square").column_span(2).columns(1).schema([
                Placeholder("conversation").hidden_label()
                .content(lambda record, ctx: render_conversation(ctx, record)),
            ]),
            Group([
                Section("Details").icon("flag").columns(1).schema([
                    TextEntry("number").label("Ticket").copyable().inline_label(),
                    TextEntry("status").badge().inline_label()
                    .format_state_using(lambda state, ctx: status_options(ctx).get(state, state))
                    .color(status_color),
                    TextEntry("priority").badge().inline_label()
                    .format_state_using(lambda state, ctx: priority_options(ctx).get(state, state))
                    .color(priority_color),
                    TextEntry("category.name").label("Category").placeholder("—").inline_label(),
                    TextEntry("assigned_to").label("Agent").inline_label().placeholder("Nobody yet")
                    .state(lambda record, ctx: user_name(ctx, record.assigned_to)),
                    TextEntry("due_at").label("Due by").datetime().placeholder("—").inline_label()
                    .color(lambda record: "danger" if record.is_overdue else None),
                    TextEntry("first_response_at").label("First reply").since().placeholder("Not yet")
                    .inline_label(),
                    TextEntry("tags").badge().placeholder("—").inline_label(),
                ]),
                Section("Customer").icon("user").columns(1).schema([
                    TextEntry("requester_name").label("Name").placeholder("—").inline_label(),
                    TextEntry("requester_email").label("Email").copyable().placeholder("—").inline_label(),
                    TextEntry("requester_phone").label("Phone").copyable().placeholder("—").inline_label(),
                    TextEntry("source").badge().color("gray").inline_label()
                    .format_state_using(lambda state: SOURCES.get(state, state)),
                    TextEntry("created_at").label("Opened").since().inline_label(),
                ]),
            ]).columns(1).column_span(1),
        ])

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        actions = super().header_actions(ctx, page, record)
        if page == "view":
            return [reply_action().button(), note_action().button(), resolve_action().button(),
                    take_action().button(), ActionGroup([EditAction(), DeleteAction()]).button()]
        return actions

    # ------------------------------------------------------------------ save hooks
    @classmethod
    def after_create(cls, record, db, ctx):
        prepare_new(db, record)
        db.flush()
        ticket_created(db, record, ctx)
        if record.assigned_to:
            add_event(db, record, f"Assigned to {user_name(ctx, record.assigned_to) or record.assigned_to}",
                      user_id=_me(ctx))

    @classmethod
    def before_save(cls, record, ctx):
        record.__dict__["_tw_before"] = (record.status, record.assigned_to)

    @classmethod
    def after_save(cls, record, db, ctx):
        old_status, old_agent = record.__dict__.pop("_tw_before", (record.status, record.assigned_to))
        plugin = _plugin(ctx)
        if record.status != old_status:
            status_changed(db, record, old_status, user_id=_me(ctx), by=_my_name(ctx), ctx=ctx)
        if record.assigned_to != old_agent:
            who = user_name(ctx, record.assigned_to) if record.assigned_to else "nobody"
            add_event(db, record, f"Assigned to {who}" + (f" by {_my_name(ctx)}" if _my_name(ctx) else ""),
                      user_id=_me(ctx))
            if plugin is not None and record.assigned_to:
                plugin.notify_agent(db, record, "Ticket assigned to you", f"{record.number}: {record.subject}", ctx)

    # ------------------------------------------------------------------ list
    @classmethod
    def table(cls, table):
        def status_color(state, ctx):
            return statuses(ctx).get(str(state), ("", "gray"))[1]

        def priority_color(state, ctx):
            return priorities(ctx).get(str(state), ("", "gray"))[1]

        def is_open(model):
            return model.status.notin_(CLOSED_STATUSES)

        def bulk_status(key, label):
            def run(records, db, ctx):
                for r in records:
                    set_status(db, r, key, user_id=_me(ctx), by=_my_name(ctx), ctx=ctx)
                db.commit()
            return run

        def bulk_assign(records, data, db, ctx):
            for r in records:
                if r.assigned_to != data["user"]:
                    r.assigned_to = data["user"]
                    add_event(db, r, f"Assigned to {user_name(ctx, r.assigned_to)}", user_id=_me(ctx))
                    plugin = _plugin(ctx)
                    if plugin is not None:
                        plugin.notify_agent(db, r, "Ticket assigned to you", f"{r.number}: {r.subject}", ctx)
            db.commit()

        return (
            table.columns([
                TextColumn("number").label("No.").searchable().sortable().copyable().weight("medium"),
                TextColumn("subject").weight("medium").searchable().limit(70)
                .description(lambda record: record.requester_name or record.requester_email),
                TextColumn("requester_email").label("Email").searchable().toggleable(hidden_by_default=True),
                TextColumn("status").badge().sortable()
                .format_state_using(lambda state, ctx: status_options(ctx).get(state, state))
                .color(status_color),
                TextColumn("priority").badge().sortable()
                .format_state_using(lambda state, ctx: priority_options(ctx).get(state, state))
                .color(priority_color),
                TextColumn("category.name").label("Category").toggleable(),
                TextColumn("assigned_to").label("Agent").toggleable().placeholder("—")
                .state(lambda record, ctx: user_name(ctx, record.assigned_to)),
                TextColumn("due_at").label("Due").since().sortable().toggleable()
                .color(lambda record: "danger" if record.is_overdue else None),
                TextColumn("updated_at").label("Updated").since().sortable(),
            ])
            .filters([
                SelectFilter("status").options(status_options).multiple(),
                SelectFilter("priority").options(priority_options).multiple(),
                SelectFilter("category_id").label("Category").relationship("category", "name"),
                SelectFilter("assigned_to").label("Agent").options(user_options),
                SelectFilter("source").options(SOURCES),
                DateFilter("created_at").label("Opened on"),
            ])
            .tabs([
                ListTab("open").label("Open").badge().query(lambda query, model: query.where(is_open(model))),
                ListTab("mine").label("My tickets").query(
                    lambda query, model, ctx: query.where(is_open(model), model.assigned_to == _me(ctx))
                    if ctx.user is not None else query.where(is_open(model))),
                ListTab("unassigned").label("Unassigned").badge(color="warning").query(
                    lambda query, model: query.where(is_open(model), model.assigned_to.is_(None))),
                ListTab("overdue").label("Overdue").badge(color="danger").query(
                    lambda query, model: query.where(is_open(model), model.due_at < dt.datetime.now())),
                ListTab("waiting").label("Waiting on customer").query(
                    lambda query, model: query.where(model.status == "waiting")),
                ListTab("done").label("Resolved").query(
                    lambda query, model: query.where(model.status.in_(CLOSED_STATUSES))),
                ListTab("all").label("All"),
            ])
            .actions([
                reply_action().icon_button(),
                ActionGroup([ViewAction(), EditAction(), DeleteAction()]),
            ])
            .bulk_actions([
                BulkAction("assign").label("Assign to").icon("user-check")
                .form(lambda form: form.schema([Select("user").label("Agent").options(user_options).required()]))
                .action(bulk_assign).success_notification_title("Tickets assigned"),
                BulkAction("resolve").label("Resolve").icon("circle-check").color("success")
                .action(bulk_status("resolved", "Resolved")).success_notification_title("Tickets resolved"),
                BulkAction("close").label("Close").icon("lock").color("gray")
                .action(bulk_status("closed", "Closed")).success_notification_title("Tickets closed"),
                ExportBulkAction(),
                DeleteBulkAction(),
            ])
            .header_actions([ExportAction()])
            .record_url(lambda record, ctx: _view_url(ctx, record))
            .default_sort("updated_at", "desc")
        )


class TicketCategoryResource(Resource):
    """Settings screen: kinds of tickets, and who gets them."""

    model = TicketCategory
    slug = "ticket-categories"
    icon = "folder"
    navigation_group = "Help desk"
    navigation_sort = 50
    label = "Ticket category"
    description = "Kinds of tickets, like Billing or Bug. New tickets of a category can go to one agent."
    simple = True

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("name").required().max_length(100).placeholder("Billing"),
            Select("color").options({c: c.title() for c in COLOR_NAMES if c != "primary"} | {"primary": "Brand"})
            .default("gray").required(),
            Select("assign_to").label("Give new tickets to").options(user_options).searchable()
            .column_span("full"),
            TextInput("description").max_length(255).column_span("full"),
            TextInput("sort").label("Order").integer().default(0),
            Toggle("is_public").label("Show on the support page").default(True),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").badge().color(lambda record: record.color or "gray")
                .description(lambda record: record.description),
                TextColumn("assign_to").label("New tickets go to").placeholder("—")
                .state(lambda record, ctx: user_name(ctx, record.assign_to)),
                ToggleColumn("is_public").label("On support page"),
                TextColumn("sort").label("Order").sortable(),
            ])
            .actions([EditAction(), DeleteAction()])
            .reorderable("sort")
            .default_sort("sort", "asc")
        )


class SavedReplyResource(Resource):
    """Ready answers agents pick in the Reply box."""

    model = SavedReply
    slug = "saved-replies"
    icon = "message-square-text"
    navigation_group = "Help desk"
    navigation_sort = 60
    label = "Saved reply"
    description = "Ready answers for common questions. Pick one in the Reply box and change it if needed."
    simple = True

    @classmethod
    def form(cls, form):
        return form.columns(1).schema([
            TextInput("title").required().max_length(100).placeholder("Password reset steps"),
            Textarea("body").label("Message").rows(8).required(),
            TextInput("sort").label("Order").integer().default(0),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("title").weight("medium").searchable(),
                TextColumn("body").label("Message").limit(90).searchable(),
                TextColumn("sort").label("Order").sortable(),
            ])
            .actions([EditAction(), DeleteAction()])
            .reorderable("sort")
            .default_sort("sort", "asc")
        )


__all__ = ["SavedReplyResource", "TicketCategoryResource", "TicketResource", "note_action", "reply_action"]
