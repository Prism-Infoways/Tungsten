"""The WhatsApp setup page."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup, escape
from tungsten import Notification, Page
from tungsten.actions import Action, Halt
from tungsten.forms import (
    CheckboxList,
    Section,
    Select,
    Textarea,
    TextInput,
    Toggle,
    ToggleButtons,
)
from tungsten_leads.resources import source_options

from .client import CloudClient, WebClient, WhatsAppError
from .service import client_for, get_settings, send, sync_templates

CHANNELS = {
    "": "Links only",
    "cloud": "Cloud API (official)",
    "web": "WhatsApp Web (linked phone)",
}
#: fields kept as they are when left empty (secrets are never shown again)
SECRETS = ("access_token", "app_secret", "gateway_api_key")
FIELDS = ("channel", "country_code", "phone_number_id", "business_account_id", "gateway_url", "gateway_session",
          "create_leads", "welcome_enabled", "welcome_sources", "welcome_text", "welcome_template",
          "welcome_language") + SECRETS


def plugin_of(ctx: Any) -> Any:
    return ctx.panel.get_plugin("whatsapp")


def _saved(name: str):
    return lambda ctx: "Saved. Type a new one to change it." if getattr(get_settings(ctx.db), name) else None


def _is(channel: str):
    return lambda get: (get("channel") or "") == channel


def template_options(db: Any) -> dict[str, str]:
    from sqlalchemy import select

    from .models import WhatsAppTemplate

    rows = db.scalars(select(WhatsAppTemplate).order_by(WhatsAppTemplate.name)).all()
    return {r.name: f"{r.name} ({r.language})" for r in rows if (r.status or "APPROVED") == "APPROVED"}


class WhatsAppSetupPage(Page):
    slug = "whatsapp"
    title = "WhatsApp"
    subheading = "Send and receive WhatsApp messages with your leads."
    icon = "message-circle"
    navigation_group = "Leads"
    navigation_label = "WhatsApp setup"
    navigation_sort = 71

    @classmethod
    def content(cls, ctx):
        plugin = plugin_of(ctx)
        settings = get_settings(ctx.db)
        if settings.channel == "cloud":
            ready = bool(settings.phone_number_id and settings.access_token and settings.app_secret)
            data = {
                "channel_label": "WhatsApp Cloud API",
                "channel_text": "The official way. Free text within 24 hours of the lead's last message, "
                                "templates any time.",
                "state_label": "Ready" if ready else "Keys missing", "state_color": "success" if ready else "warning",
                "urls": [("Callback URL", plugin.webhook_url(ctx.request, "webhook")),
                         ("Verify token", settings.verify_token)],
                "help": "In your Meta app: WhatsApp, Configuration, Webhook. Paste these two, then subscribe to "
                        "the messages field.",
            }
        elif settings.channel == "web":
            working = settings.web_status == "WORKING"
            data = {
                "channel_label": "WhatsApp Web",
                "channel_text": f"Linked to +{settings.web_phone}." if working and settings.web_phone else
                "Sends from your own WhatsApp number through a WAHA gateway. Press Link phone and scan the QR code.",
                "state_label": "Linked" if working else (settings.web_status or "Not linked").replace("_", " ").title(),
                "state_color": "success" if working else "warning",
                "urls": [("Webhook URL (set for you by Link phone)",
                          plugin.webhook_url(ctx.request, "web-webhook", token=settings.web_webhook_token))],
                "help": "WhatsApp Web is not an official API. Send to people who expect your message, "
                        "and avoid bulk sends, or WhatsApp may block the number.",
            }
        else:
            data = {
                "channel_label": "Links only",
                "channel_text": "The WhatsApp button on a lead opens WhatsApp with the chat ready. Nothing is sent "
                                "by itself and nothing comes back here.",
                "state_label": "Ready", "state_color": "success", "urls": [], "help": None,
            }
        return ctx.panel.renderer.render("tungsten_whatsapp/status.html", ctx=ctx, **data)

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            Section("How to send").icon("send").schema([
                ToggleButtons("channel").hidden_label().options(CHANNELS).live().column_span("full"),
                TextInput("country_code").label("Country code").prefix("+").max_length(4).default("91")
                .helper_text("Added to 10-digit numbers."),
            ]),
            Section("Cloud API keys").icon("key-round").visible(_is("cloud")).description(
                "From developers.facebook.com, your app, WhatsApp, API setup.").schema([
                TextInput("phone_number_id").label("Phone number ID").required(_is("cloud")),
                TextInput("business_account_id").label("WhatsApp Business Account ID")
                .helper_text("Needed for templates."),
                TextInput("access_token").label("Access token").password().revealable().placeholder(_saved("access_token"))
                .helper_text("A permanent System User token. Leave empty to keep the saved one."),
                TextInput("app_secret").label("App secret").password().revealable().placeholder(_saved("app_secret"))
                .helper_text("Checks that messages really come from Meta. Leave empty to keep the saved one."),
            ]),
            Section("WhatsApp Web gateway").icon("server").visible(_is("web")).description(
                "A WAHA gateway (waha.devlike.pro) keeps your phone linked. Run it on a server with Docker: "
                "docker run -p 3000:3000 devlikeapro/waha").schema([
                TextInput("gateway_url").label("Gateway URL").url().placeholder("http://localhost:3000")
                .required(_is("web")),
                TextInput("gateway_api_key").label("API key").password().revealable().placeholder(_saved("gateway_api_key"))
                .helper_text("WAHA_API_KEY of the gateway, if set. Leave empty to keep the saved one."),
                TextInput("gateway_session").label("Session name").default("default"),
            ]),
            Section("Automation").icon("bot").column_span("full").schema([
                Toggle("create_leads").label("New chats become leads")
                .helper_text("When someone new messages you, add them to Leads."),
                Toggle("welcome_enabled").label("Welcome new leads").live()
                .helper_text("Send a WhatsApp message as soon as a lead is added."),
                CheckboxList("welcome_sources").label("Only for leads from").options(source_options).columns(3)
                .visible(lambda get: bool(get("welcome_enabled"))).column_span("full")
                .helper_text("Pick none to welcome every lead."),
                Select("welcome_template").label("Template").options(lambda db: template_options(db))
                .visible(lambda get: bool(get("welcome_enabled")) and get("channel") == "cloud")
                .helper_text("The Cloud API needs an approved template to start a chat. {{1}} gets the first name."),
                TextInput("welcome_language").label("Template language").default("en")
                .visible(lambda get: bool(get("welcome_enabled")) and get("channel") == "cloud"),
                Textarea("welcome_text").label("Message").rows(3).column_span("full")
                .default("Hi {first_name}, thanks for your interest! How can we help you?")
                .visible(lambda get: bool(get("welcome_enabled")) and get("channel") != "cloud")
                .helper_text("{name}, {first_name}, {company} are filled in."),
            ]),
        ])

    @classmethod
    def mount(cls, ctx):
        settings = get_settings(ctx.db)
        data = {name: getattr(settings, name) for name in FIELDS if name not in SECRETS}
        data["channel"] = data["channel"] or ""
        data["welcome_sources"] = data["welcome_sources"] or []
        return data

    @classmethod
    def save(cls, ctx, data):
        settings = get_settings(ctx.db)
        for name in FIELDS:
            if name not in data or (name in SECRETS and not data[name]):
                continue
            setattr(settings, name, data[name])
        settings.channel = settings.channel or None
        settings.country_code = (settings.country_code or "91").lstrip("+")
        ctx.db.commit()

    @classmethod
    def header_actions(cls, ctx):
        settings = get_settings(ctx.db)
        return [
            Action("link").label("Link phone").icon("qr-code").color("primary")
            .visible(settings.channel == "web" and bool(settings.gateway_url))
            .modal_heading("Link your phone").modal_width("md")
            .modal_description("On your phone: WhatsApp, Linked devices, Link a device. Then scan this code.")
            .modal_content(lambda ctx: link_phone(ctx)).modal_submit_action_label("I have scanned it")
            .action(lambda ctx, db: check_web(ctx, db)),
            Action("templates").label("Sync templates").icon("refresh-cw").color("gray").outlined()
            .visible(settings.channel == "cloud").action(lambda ctx, db: refresh_templates(ctx, db)),
            Action("test").label("Send a test").icon("send").color("gray").outlined()
            .visible(settings.channel in ("cloud", "web"))
            .form([TextInput("phone").label("To").tel().required().placeholder("+91 98765 43210"),
                   Textarea("text").label("Message").rows(2).required().default("Hello from Tungsten!")])
            .modal_submit_action_label("Send").action(lambda data, ctx, db: send_test(ctx, db, data)),
        ]


def _fail(ctx: Any, db: Any, exc: Exception) -> None:
    db.commit()
    Notification("WhatsApp said no").body(str(exc)).danger().send(ctx)
    raise Halt from exc


def link_phone(ctx: Any) -> Markup:
    """Start the gateway session and show its QR code (or say it is already linked)."""
    plugin = plugin_of(ctx)
    settings = get_settings(ctx.db)
    client = client_for(settings, plugin.transport)
    if not isinstance(client, WebClient):
        return Markup("")
    try:
        client.start(plugin.webhook_url(ctx.request, "web-webhook", token=settings.web_webhook_token))
        info = client.status()
        settings.web_status = info.get("status")
        if info.get("status") == "WORKING":
            phone = str((info.get("me") or {}).get("id", "")).split("@")[0]
            settings.web_phone = phone or settings.web_phone
            ctx.db.commit()
            return Markup('<p class="text-sm text-success-600">{}</p>').format(f"Already linked to +{phone}.")
        qr = client.qr_data_uri()
        ctx.db.commit()
    except WhatsAppError as exc:
        return Markup('<p class="text-sm text-danger-600">{}</p>').format(f"The gateway said: {exc}")
    return Markup('<img src="{}" alt="QR code" class="mx-auto h-64 w-64 rounded-lg bg-white p-2">').format(escape(qr))


def check_web(ctx: Any, db: Any) -> None:
    settings = get_settings(db)
    client = client_for(settings, plugin_of(ctx).transport)
    try:
        info = client.status() if isinstance(client, WebClient) else {}
    except WhatsAppError as exc:
        _fail(ctx, db, exc)
    settings.web_status = info.get("status")
    if info.get("status") == "WORKING":
        settings.web_phone = str((info.get("me") or {}).get("id", "")).split("@")[0] or settings.web_phone
        db.commit()
        Notification("Phone linked").body(f"Messages now go from +{settings.web_phone}.").success().send(ctx)
        return
    db.commit()
    Notification("Not linked yet").body("Scan the QR code, then press the button again.").warning().send(ctx)
    raise Halt


def refresh_templates(ctx: Any, db: Any) -> None:
    client = client_for(get_settings(db), plugin_of(ctx).transport)
    try:
        count = sync_templates(db, client) if isinstance(client, CloudClient) else 0
    except WhatsAppError as exc:
        _fail(ctx, db, exc)
    db.commit()
    Notification("Templates synced").body(f"{count} templates.").success().send(ctx)


def send_test(ctx: Any, db: Any, data: dict) -> None:
    try:
        send(db, phone=data["phone"], text=data["text"], transport=plugin_of(ctx).transport,
             user_id=ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None)
    except WhatsAppError as exc:
        _fail(ctx, db, exc)
    db.commit()
    Notification("Sent").body(f"Message sent to {data['phone']}.").success().send(ctx)
