"""WhatsApp screens, and the WhatsApp buttons on leads."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from tungsten import Notification, Resource
from tungsten.actions import Action, BulkAction, Halt
from tungsten.forms import Placeholder, Select, Textarea, TextInput
from tungsten.tables import SelectFilter, TextColumn
from tungsten_leads import Lead

from .client import WhatsAppError, click_to_chat_url
from .models import WhatsAppMessage, WhatsAppTemplate
from .pages import template_options
from .service import approved_template, client_for, fill, get_settings, send

STATUS_COLORS = {"received": "info", "sent": "gray", "delivered": "primary", "read": "success", "failed": "danger"}


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("whatsapp")


def _user_id(ctx: Any) -> str | None:
    return ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None


def _can_send(ctx: Any) -> bool:
    return client_for(get_settings(ctx.db)) is not None


def message_fields(ctx: Any, many: bool = False) -> list:
    """Fields of the "send WhatsApp" modal: a template (Cloud API) or a free text."""
    settings = get_settings(ctx.db)
    fields: list = []
    if settings.channel == "cloud":
        fields += [
            Select("template").label("Template").options(lambda db: template_options(db)).live()
            .placeholder("No template, write a message").helper_text(
                "Text messages reach a lead only within 24 hours of their last message. Use a template otherwise."),
            TextInput("params").label("Template values").visible(lambda get: bool(get("template")))
            .helper_text("One value for each {{...}} in the template, in order, separated by |. Leave empty to use the first name."),
        ]
    fields.append(Textarea("message").rows(4).required(lambda get: not get("template"))
                  .visible(lambda get: not get("template"))
                  .default("Hi {first_name}, " if many else None)
                  .helper_text("{name}, {first_name}, {company} are filled in for each lead."))
    if many and settings.channel == "web":
        fields.insert(0, Placeholder("warning").hidden_label().content(
            "WhatsApp may block numbers that send many messages to people who don't expect them. "
            "Keep bulk sends small."))
    return fields


def send_to_lead(ctx: Any, db: Any, lead: Lead, data: dict) -> None:
    template = data.get("template") or None
    params = [p.strip() for p in (data.get("params") or "").split("|") if p.strip()] if template else []
    if template and not params:
        tpl = approved_template(db.scalars(select(WhatsAppTemplate).where(WhatsAppTemplate.name == template)
                                           .order_by(WhatsAppTemplate.id)).all())
        params = [lead.name.split(" ")[0]] * (tpl.params if tpl else 0)
    send(db, phone=lead.phone or "", text=fill(data.get("message") or "", lead), template=template, params=params,
         lead=lead, user_id=_user_id(ctx), transport=_plugin(ctx).transport)


def whatsapp_action() -> Action:
    """The WhatsApp button on a lead: a send form when WhatsApp is set up, else a wa.me link."""

    def run(record, data, ctx, db):
        try:
            send_to_lead(ctx, db, record, data)
        except WhatsAppError as exc:
            db.commit()
            Notification("Not sent").body(str(exc)).danger().send(ctx)
            raise Halt from exc
        db.commit()

    return (
        Action("whatsapp").label("WhatsApp").icon("message-circle").color("success")
        .visible(lambda record: bool(record is not None and record.phone))
        .url(lambda record, ctx: None if _can_send(ctx) else
             click_to_chat_url(record.phone, None, get_settings(ctx.db).country_code))
        .modal_heading("Send WhatsApp").modal_submit_action_label("Send")
        .form(lambda form, ctx: form.schema(message_fields(ctx)))
        .action(run)
        .success_notification_title("WhatsApp sent")
    )


def whatsapp_bulk_action() -> BulkAction:
    def run(records, data, ctx, db):
        sent = failed = 0
        for lead in records:
            if not lead.phone:
                continue
            try:
                send_to_lead(ctx, db, lead, data)
                sent += 1
            except WhatsAppError:
                failed += 1
        db.commit()
        note = Notification("WhatsApp sent").body(f"{sent} sent" + (f", {failed} failed" if failed else "") + ".")
        (note.warning() if failed else note.success()).send(ctx)

    return (
        BulkAction("whatsapp").label("Send WhatsApp").icon("message-circle").color("success")
        .visible(lambda ctx: _can_send(ctx))
        .modal_heading("Send WhatsApp to the selected leads").modal_submit_action_label("Send")
        .form(lambda form, ctx: form.schema(message_fields(ctx, many=True)))
        .action(run)
    )


class WhatsAppMessageResource(Resource):
    model = WhatsAppMessage
    slug = "whatsapp-messages"
    label = "WhatsApp message"
    plural_label = "WhatsApp chats"
    icon = "messages-square"
    navigation_group = "Leads"
    navigation_sort = 70
    description = "Every WhatsApp message sent to and received from your leads."
    pages = ("index",)

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        if not _can_send(ctx):
            return []

        def run(data, ctx, db):
            try:
                send(db, phone=data["phone"], text=data["message"], user_id=_user_id(ctx),
                     transport=_plugin(ctx).transport)
            except WhatsAppError as exc:
                db.commit()
                Notification("Not sent").body(str(exc)).danger().send(ctx)
                raise Halt from exc
            db.commit()

        return [
            Action("new").label("New message").icon("send").color("primary")
            .form([TextInput("phone").label("To").tel().required().placeholder("+91 98765 43210"),
                   Textarea("message").rows(4).required()])
            .modal_submit_action_label("Send").action(run).success_notification_title("WhatsApp sent"),
        ]

    @classmethod
    def table(cls, table):
        def reply(record, data, ctx, db):
            lead = db.get(Lead, record.lead_id) if record.lead_id else None
            try:
                send(db, phone=record.phone, text=data["message"], lead=lead, user_id=_user_id(ctx),
                     transport=_plugin(ctx).transport)
            except WhatsAppError as exc:
                db.commit()
                Notification("Not sent").body(str(exc)).danger().send(ctx)
                raise Halt from exc
            db.commit()

        return (
            table.columns([
                TextColumn("direction").label("").icon(lambda state: "arrow-down-left" if state == "in" else "arrow-up-right")
                .format_state_using(lambda state: "In" if state == "in" else "Out")
                .color(lambda state: "info" if state == "in" else "gray"),
                TextColumn("phone").state(lambda record: f"+{record.phone}" if record.phone else "Number hidden")
                .searchable().copyable(),
                TextColumn("lead_id").label("Lead").state(
                    lambda record, ctx: lead_name(ctx, record.lead_id))
                .url(lambda record, ctx: ctx.url("leads", record.lead_id) if record.lead_id else None),
                TextColumn("body").label("Message").wrap().limit(160).searchable(),
                TextColumn("status").badge().colors({c: s for s, c in STATUS_COLORS.items()})
                .description(lambda record: record.error),
                TextColumn("created_at").label("When").since().sortable(),
            ])
            .filters([
                SelectFilter("direction").options({"in": "Received", "out": "Sent"}),
                SelectFilter("status").options({s: s.capitalize() for s in STATUS_COLORS}).multiple(),
            ])
            .actions([
                Action("reply").label("Reply").icon("reply").color("success").icon_button()
                .visible(lambda record, ctx: record.direction == "in" and bool(record.phone) and _can_send(ctx))
                .form([Textarea("message").rows(4).required()]).modal_submit_action_label("Send").action(reply)
                .success_notification_title("WhatsApp sent"),
            ])
            .default_sort("created_at", "desc")
            .poll("15s")
        )


def lead_name(ctx: Any, lead_id: int | None) -> str | None:
    if not lead_id:
        return None
    cache = ctx.__dict__.setdefault("_wa_lead_names", {})
    if lead_id not in cache:
        lead = ctx.db.get(Lead, lead_id)
        cache[lead_id] = lead.name if lead else None
    return cache[lead_id]


class WhatsAppTemplateResource(Resource):
    model = WhatsAppTemplate
    slug = "whatsapp-templates"
    label = "WhatsApp template"
    icon = "layout-template"
    navigation_group = "Leads"
    navigation_sort = 72
    description = "Message templates approved by Meta. Make them in WhatsApp Manager, then press Sync templates."
    pages = ("index",)

    @classmethod
    def can(cls, ctx, ability, record=None):
        return get_settings(ctx.db).channel == "cloud" and super().can(ctx, ability, record)

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return []

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").weight("medium").searchable().description(lambda record: record.category),
                TextColumn("language").badge().color("gray"),
                TextColumn("status").badge().colors({"success": "APPROVED", "warning": "PENDING",
                                                     "danger": ["REJECTED", "PAUSED", "DISABLED"]}),
                TextColumn("body").wrap().limit(200),
            ])
            .default_sort("name", "asc")
        )
