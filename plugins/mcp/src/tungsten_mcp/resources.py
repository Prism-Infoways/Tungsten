"""The "AI access (MCP)" screen: make and revoke tokens, and see how to connect."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from tungsten import Resource
from tungsten.actions import Action, DeleteAction, DeleteBulkAction, EditAction
from tungsten.forms import TextInput, Toggle
from tungsten.tables import TextColumn

from .models import McpToken, hash_token, new_token


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("mcp")


def _user_id(ctx: Any) -> str | None:
    return ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None


def guide(ctx: Any, token: str | None = None) -> Markup:
    plugin = _plugin(ctx)
    return ctx.panel.renderer.render("tungsten_mcp/guide.html", ctx=ctx, url=plugin.endpoint_url(ctx.request),
                                     read_only=plugin.read_only, token=token)


def create_token(ctx: Any, db: Any, data: dict) -> Any:
    """Save a new token and show it once, in a popup with the connect steps filled in.

    Not a toast: a toast would ride along in the session cookie until the next page load.
    """
    token = new_token()
    db.add(McpToken(name=data["name"], can_write=bool(data.get("can_write")) and not _plugin(ctx).read_only,
                    token_hash=hash_token(token), hint=token[:12], user_id=_user_id(ctx)))
    db.commit()
    ctx.dispatch("tw-refresh")
    m = {"endpoint": ctx.url("_tw", "action"), "heading": "Token created", "description": None, "icon": None,
         "icon_color": "success", "submit_label": None, "cancel_label": "Done", "color": "primary",
         "width": "2xl", "slide_over": True, "confirm_only": False, "content": guide(ctx, token),
         "multipart": False, "create_another_label": None}
    hidden = {"_tw_host": McpTokenResource.host().key, "_tw_scope": "page", "_tw_name": "done", "_tw_record": ""}
    return ctx.html(ctx.panel.renderer.render("tungsten/actions/modal.html", m=m, form=None, hidden=hidden,
                                              records=[], ctx=ctx))


def token_fields() -> list:
    return [
        TextInput("name").required().max_length(100).placeholder("Claude on my laptop")
        .helper_text("To tell your tokens apart."),
        Toggle("can_write").label("Allow changes")
        .helper_text("Let the AI create, change and delete records. Off: it can only read.")
        .visible(lambda ctx: not _plugin(ctx).read_only),
    ]


class McpTokenResource(Resource):
    model = McpToken
    slug = "mcp-tokens"
    label = "MCP token"
    icon = "bot"
    navigation_group = "Settings"
    navigation_label = "AI access (MCP)"
    navigation_sort = 95
    description = "Tokens that let AI assistants like Claude read and change this panel's data. " \
                  "Each token acts as you, with your permissions."
    record_title_attribute = "name"
    simple = True
    pages = ("index",)

    @classmethod
    def query(cls, ctx):
        query = super().query(ctx)
        if ctx.panel.auth.enabled:  # everyone sees and revokes only their own tokens
            query = query.where(McpToken.user_id == _user_id(ctx))
        return query

    @classmethod
    def form(cls, form):
        return form.schema(token_fields()).columns(1)

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        return [
            Action("guide").label("How to connect").icon("book-open").color("gray").outlined()
            .slide_over().modal_width("2xl").modal_heading("Connect an AI assistant")
            .modal_description("Make a token, then add this panel to your AI app.")
            .modal_content(lambda ctx: guide(ctx)).modal_submit_action(False).modal_cancel_action_label("Close"),
            Action("create").label("New token").icon("plus").authorize("create")
            .modal_heading("New MCP token").modal_width("md")
            .form(token_fields()).modal_submit_action_label("Create token")
            .action(lambda ctx, db, data: create_token(ctx, db, data)),
        ]

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").searchable().sortable(),
                TextColumn("hint").label("Token").state(lambda record: f"{record.hint}…").color("gray"),
                TextColumn("can_write").label("Access").badge()
                .state(lambda record: "Read and change" if record.can_write else "Read only")
                .color(lambda record: "warning" if record.can_write else "gray"),
                TextColumn("last_used_at").label("Last used").since().placeholder("Never").sortable(),
                TextColumn("created_at").date().sortable(),
            ])
            .actions([EditAction(), DeleteAction().label("Revoke")])
            .bulk_actions([DeleteBulkAction()])
            .empty_state("No tokens yet", "Press New token, then How to connect.", "bot")
            .default_sort("created_at", "desc")
        )
