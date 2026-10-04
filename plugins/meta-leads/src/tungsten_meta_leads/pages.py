"""The "Facebook & Instagram" setup page."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import func, select
from tungsten import Notification, Page
from tungsten.actions import Action, Halt
from tungsten.forms import Placeholder, Section, TextInput

from .graph import GraphError
from .models import MetaForm, MetaPage
from .sync import SCOPES, disconnect, get_settings, refresh_forms, sync_form

MESSAGES = {
    "connected": ("Facebook is connected. New leads will now come in by themselves.", False),
    "denied": ("Facebook login was cancelled.", True),
    "state": ("The login link expired. Please press Connect Facebook again.", True),
    "keys": ("Add your Meta App ID and App secret first.", True),
}


def plugin_of(ctx: Any) -> Any:
    return ctx.panel.get_plugin("meta-leads")


class MetaSetupPage(Page):
    slug = "meta-leads"
    title = "Facebook & Instagram"
    navigation_label = "Facebook & Instagram"
    subheading = "Bring leads from your Facebook and Instagram lead forms into Leads."
    icon = "facebook"
    navigation_group = "Leads"
    navigation_sort = 60
    save_label = "Save keys"

    @classmethod
    def content(cls, ctx):
        plugin = plugin_of(ctx)
        settings = get_settings(ctx.db)
        app_id, app_secret = plugin.keys(ctx.db)
        pages = ctx.db.scalars(select(MetaPage).order_by(MetaPage.name)).all()
        counts = dict(ctx.db.execute(select(MetaForm.page_id, func.count()).group_by(MetaForm.page_id)).all())
        code = ctx.request.query_params.get("meta")
        message, is_error = MESSAGES.get(code, (None, False))
        if code == "error":
            message, is_error = ctx.request.query_params.get("reason") or "Facebook said no.", True
        steps = [
            {"title": "Add your Meta app keys", "done": bool(app_id and app_secret),
             "text": "Create an app at developers.facebook.com with the use case \"Capture & manage ad leads with "
                     "Marketing API\", then paste its App ID and App secret below. Paste the Redirect URI below "
                     "in its Facebook Login for Business settings."},
            {"title": "Connect Facebook", "done": settings.user_token is not None,
             "text": f"Connected as {settings.user_name}." if settings.user_token else
             "Press Connect Facebook and allow access to your pages and their leads."},
            # Meta has no way to ask if the app is live, so this is done once a lead really arrived
            {"title": "Receive leads", "done": bool(settings.webhook_ok and any(p.subscribed for p in pages)
                                                    and settings.last_webhook_at),
             "error": settings.webhook_error,
             "text": "Publish the app in Meta (Publish, Go live), then send a test lead. From then on Meta sends "
                     "every new lead here the moment it is submitted."},
        ]
        return ctx.panel.renderer.render(
            "tungsten_meta_leads/setup.html", ctx=ctx, steps=steps, message=message, message_error=is_error,
            redirect_uri=plugin.redirect_uri(ctx.request), app_domain=plugin.app_domain(ctx.request),
            webhook_url=plugin.webhook_url(ctx.request), verify_token=settings.verify_token,
            last_webhook_at=settings.last_webhook_at.strftime("%d %b, %H:%M") if settings.last_webhook_at else None,
            pages=[{"name": p.name, "subscribed": p.subscribed, "error": p.error, "forms": counts.get(p.page_id, 0)}
                   for p in pages],
            forms_url=ctx.url("meta-forms"),
        )

    # ------------------------------------------------------------------ keys form
    @classmethod
    def form(cls, form):
        return form.schema([
            Section("Meta app keys").icon("key-round").description(
                "From developers.facebook.com, your app, App settings, Basic.").schema([
                TextInput("app_id").label("App ID").max_length(64).required(),
                TextInput("app_secret").label("App secret").password().revealable().max_length(128)
                .helper_text("Leave empty to keep the saved secret."),
            ]).visible(lambda ctx: not plugin_of(ctx).app_id),
            Section("Meta app keys").icon("key-round").schema([
                Placeholder("keys_note").hidden_label()
                .content("The App ID and App secret are set in your code (MetaLeadsPlugin), so there is nothing to fill here."),
            ]).visible(lambda ctx: bool(plugin_of(ctx).app_id)),
        ])

    @classmethod
    def mount(cls, ctx):
        settings = get_settings(ctx.db)
        return {"app_id": settings.app_id or ""}

    @classmethod
    def save(cls, ctx, data):
        if plugin_of(ctx).app_id:
            return
        settings = get_settings(ctx.db)
        settings.app_id = data.get("app_id") or None
        if data.get("app_secret"):
            settings.app_secret = data["app_secret"]
        ctx.db.commit()
        ctx.redirect(str(ctx.request.url.path))  # reload, so Connect Facebook uses the new keys

    # ------------------------------------------------------------------ buttons
    @classmethod
    def header_actions(cls, ctx):
        settings = get_settings(ctx.db)
        connected = settings.user_token is not None
        return [
            Action("guide").label("Setup guide").icon("book-open").color("gray").outlined()
            .slide_over().modal_width("2xl").modal_heading("Connect Facebook and Instagram")
            .modal_description("Every click, from a new Meta app to your first lead.")
            .modal_content(lambda ctx: guide(ctx)).modal_submit_action(False).modal_cancel_action_label("Close"),
            Action("connect").label("Reconnect Facebook" if connected else "Connect Facebook").icon("facebook")
            .color("gray" if connected else "primary").url(lambda ctx: connect_url(ctx)),
            Action("sync").label("Sync forms and leads").icon("refresh-cw").color("gray").outlined()
            .visible(connected).action(lambda ctx, db: sync_everything(ctx, db)),
            Action("disconnect").label("Disconnect").icon("unplug").color("danger").outlined()
            .visible(connected).requires_confirmation()
            .modal_description("New leads will stop coming in. Leads already saved stay.")
            .action(lambda db: (disconnect(db), db.commit()))
            .success_notification_title("Facebook disconnected"),
        ]


def guide(ctx: Any) -> Any:
    """The step-by-step setup guide, with this site's own addresses filled in."""
    plugin = plugin_of(ctx)
    settings = get_settings(ctx.db)
    app_id, app_secret = plugin.keys(ctx.db)
    redirect_uri = plugin.redirect_uri(ctx.request)
    return ctx.panel.renderer.render(
        "tungsten_meta_leads/guide.html", ctx=ctx, redirect_uri=redirect_uri, app_domain=plugin.app_domain(ctx.request),
        webhook_url=plugin.webhook_url(ctx.request), verify_token=settings.verify_token,
        https=redirect_uri.startswith("https://"), keys_saved=bool(app_id and app_secret),
        connected=settings.user_token is not None, got_lead=settings.last_webhook_at is not None,
    )


def connect_url(ctx: Any) -> str:
    """The Facebook login link, with a one-time ``state`` kept in the session."""
    plugin = plugin_of(ctx)
    app_id, app_secret = plugin.keys(ctx.db)
    if not (app_id and app_secret):
        return ctx.url("meta-leads", meta="keys")
    state = ctx.session.get("tw_meta_state") or secrets.token_urlsafe(24)
    ctx.session["tw_meta_state"] = state
    return plugin.graph(ctx.db).dialog_url(app_id, plugin.redirect_uri(ctx.request), state, SCOPES)


def sync_everything(ctx: Any, db: Any) -> None:
    plugin = plugin_of(ctx)
    graph = plugin.graph(db)
    try:
        forms = refresh_forms(db, graph, auto_create_fields=plugin.auto_create_fields)
        new = sum(sync_form(db, graph, f, limit=plugin.sync_limit, default_status=plugin.default_status)
                  for f in forms if f.enabled)
    except GraphError as exc:
        db.rollback()
        Notification("Meta said no").body(str(exc)).danger().send(ctx)
        raise Halt from exc
    db.commit()
    Notification("Synced").body(f"{len(forms)} lead forms, {new} new leads.").success().send(ctx)
