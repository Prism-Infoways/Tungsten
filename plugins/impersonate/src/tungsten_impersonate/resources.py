"""The impersonation log screen, with a "Log in as a user" button for any user."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select

from tungsten import Notification, Resource
from tungsten.actions import Action
from tungsten.forms import Select, Textarea
from tungsten.tables import TernaryFilter, TextColumn

from .models import ImpersonationLog
from .service import ImpersonationError, can_impersonate, start

#: users listed in the "Log in as a user" picker (search narrows them in the browser)
PICKER_LIMIT = 500

END_REASONS = {
    "left": ("Went back", "success"),
    "expired": ("Time ran out", "warning"),
    "logged_out": ("Logged out", "gray"),
    "ended": ("Ended", "gray"),
}


def plugin_of(ctx: Any) -> Any:
    return ctx.panel.get_plugin("impersonate")


def status_of(ctx: Any, record: ImpersonationLog) -> tuple[str, str]:
    if record.ended_at is not None:
        return END_REASONS.get(record.end_reason or "", ("Ended", "gray"))
    plugin = plugin_of(ctx)
    limit = plugin.max_minutes if plugin is not None else 0
    if limit and record.started_at < ctx.panel.now() - dt.timedelta(minutes=limit):
        return ("Timed out", "gray")  # the browser never came back to close it
    return ("Active", "danger")


def duration_of(record: ImpersonationLog) -> str:
    minutes = record.minutes
    if minutes is None:
        return ""
    return "under 1 min" if minutes < 1 else f"{minutes} min"


def _user_options(ctx: Any) -> dict[str, str]:
    auth = ctx.panel.auth
    model = auth.user_model
    query = select(model)
    name = getattr(model, auth.name_field, None)
    query = query.order_by(name if name is not None else getattr(model, auth.email_field))
    query = ctx.panel.tenancy.scope(ctx, model, query)
    me = auth.user_id(ctx.user) if ctx.user is not None else None
    options = {}
    for user in ctx.db.scalars(query.limit(PICKER_LIMIT)):
        uid = auth.user_id(user)
        if uid == me:
            continue
        email = getattr(user, auth.email_field, "") or ""
        label = auth.display_name(user)
        options[uid] = f"{label} ({email})" if email and email != label else label
    return options


def _pick(ctx: Any, data: dict) -> None:
    plugin = plugin_of(ctx)
    target = ctx.panel.auth.find_by_id(ctx.db, data.get("user")) if data.get("user") else None
    try:
        url = start(plugin, ctx, target, data.get("reason"))
    except ImpersonationError as exc:
        Notification("Can't log in as this user").body(str(exc)).danger().send(ctx)
        return
    ctx.redirect(url)


def pick_action() -> Action:
    return (
        Action("login_as_user").label("Log in as a user").icon("venetian-mask")
        .visible(lambda ctx: can_impersonate(plugin_of(ctx), ctx))
        .modal_heading("Log in as a user").modal_width("lg")
        .modal_description("See the panel exactly as they do. You can go back from the bar at the top.")
        .form(lambda ctx: [
            Select("user").label("User").options(lambda: _user_options(ctx)).searchable().required(),
            *([Textarea("reason").label("Why?" if plugin_of(ctx).require_reason else "Why? (optional)")
               .required(plugin_of(ctx).require_reason).max_length(2000).rows(2)]
              if plugin_of(ctx).asks_reason else []),
        ])
        .modal_submit_action_label("Log in as user")
        .action(lambda ctx, data: _pick(ctx, data))
    )


class ImpersonationLogResource(Resource):
    model = ImpersonationLog
    slug = "impersonation-log"
    label = "Impersonation"
    plural_label = "Impersonation log"
    icon = "venetian-mask"
    navigation_group = "Security"
    navigation_label = "Impersonation log"
    navigation_sort = 93
    description = "Every time an admin logged in as another user: who, as whom, why and for how long."
    record_title_attribute = "target_name"
    simple = True
    pages = ("index",)

    @classmethod
    def can(cls, ctx, ability, record=None):
        if ability != "view_any" and ability != "view":
            return False  # the log is read-only: nobody edits or deletes history
        plugin = plugin_of(ctx)
        if plugin is not None and not plugin.may_view_log(ctx):
            return False
        return super().can(ctx, "view_any", record)

    @classmethod
    def abilities(cls):
        return ["view_any"]

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return [pick_action()]

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("started_at").label("When").since().sortable(),
                TextColumn("impersonator_name").label("Admin").searchable().sortable(),
                TextColumn("target_name").label("Logged in as").searchable().sortable(),
                TextColumn("end_reason").label("Status").badge()
                .state(lambda ctx, record: status_of(ctx, record)[0])
                .color(lambda ctx, record: status_of(ctx, record)[1]),
                TextColumn("ended_at").label("Time").state(lambda record: duration_of(record))
                .placeholder("-").color("gray"),
                TextColumn("reason").label("Why").placeholder("No reason given").color("gray").limit(60),
                TextColumn("ip").label("IP").searchable().placeholder("Unknown").color("gray")
                .toggleable(hidden_by_default=True),
                TextColumn("user_agent").label("Browser").placeholder("Unknown").color("gray").limit(40)
                .toggleable(hidden_by_default=True),
            ])
            .filters([
                TernaryFilter("ended_at").label("Status").nullable()
                .true_label("Ended").false_label("Still open"),
            ])
            .empty_state("Nobody logged in as anyone yet",
                         "When an admin uses \"Log in as\", it shows here.", "venetian-mask")
            .default_sort("started_at", "desc")
        )
