"""The "Saved views" page (user menu): rename, recolour, share, order and delete your views."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, false, or_, select

from tungsten import Resource
from tungsten.actions import Action, DeleteAction, EditAction
from tungsten.forms import Select, TextInput, Toggle
from tungsten.tables import TextColumn

from .models import SavedView
from .service import MAX_NAME, forget_view

COLOR_OPTIONS = {"gray": "Gray", "primary": "Brand", "info": "Blue", "success": "Green", "warning": "Amber",
                 "danger": "Red"}


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("saved-views")


class SavedViewPolicy:
    """Everyone manages their own views; ``saved_views.manage`` also covers views others shared."""

    @staticmethod
    def view_any(ctx):
        return _plugin(ctx) is not None and (ctx.user is not None or not ctx.panel.auth.enabled)

    @staticmethod
    def view(ctx, record):
        return SavedViewPolicy.update(ctx, record)

    @staticmethod
    def create(ctx):
        return False  # views are saved from a list, where the filters are

    @staticmethod
    def update(ctx, record):
        plugin = _plugin(ctx)
        return plugin is not None and record is not None and plugin.can_edit(ctx, record)

    @staticmethod
    def delete(ctx, record=None):
        if record is None:
            return SavedViewPolicy.view_any(ctx)
        return SavedViewPolicy.update(ctx, record)

    @staticmethod
    def delete_any(ctx, record=None):
        return SavedViewPolicy.delete(ctx, record)


def resource_label(ctx: Any, slug: str) -> str:
    resource = ctx.panel.resource(slug)
    return resource.get_plural_label() if resource is not None else slug


def open_url(ctx: Any, record: SavedView) -> str | None:
    plugin = _plugin(ctx)
    item = next((i for i in plugin.views_for(ctx, record.resource) if i.id == record.id), None) if plugin else None
    return item.url if item is not None else None


def delete_view(ctx: Any, record: SavedView) -> None:
    """Delete from the Saved views page: also clears defaults that pointed at it, and tells listeners."""
    plugin = _plugin(ctx)
    if plugin is not None:
        plugin._fire(plugin.deleted_listeners, ctx.db, record)
    forget_view(ctx.db, record)
    ctx.db.commit()


class SavedViewResource(Resource):
    model = SavedView
    slug = "saved-views"
    icon = "bookmark"
    label = "Saved view"
    description = "Views you saved above your lists. Open one, or change its name, colour, order and sharing."
    show_in_navigation = False
    pages = ("index", "edit")
    simple = True
    tenant_scoped = False
    soft_delete_column = None
    policy = SavedViewPolicy

    @classmethod
    def query(cls, ctx):
        plugin = _plugin(ctx)
        if plugin is None:
            return select(SavedView).where(false())
        me, tenant = plugin.user_key(ctx), plugin.tenant_key(ctx)
        mine = and_(SavedView.user_id == me, SavedView.tenant_key == tenant)
        if plugin.can_manage(ctx):
            mine = or_(mine, and_(SavedView.is_shared.is_(True), SavedView.tenant_key == tenant))
        return select(SavedView).where(mine)

    @classmethod
    def form(cls, form):
        def can_share(ctx):
            plugin = _plugin(ctx)
            return plugin is not None and plugin.can_share(ctx)

        return form.columns(2).schema([
            TextInput("name").required().max_length(MAX_NAME).column_span("full"),
            Select("color").label("Colour").options(COLOR_OPTIONS).default("gray").required(),
            TextInput("sort").label("Order").integer().default(0),
            TextInput("icon").label("Icon").max_length(40).placeholder("star")
            .regex(r"^[a-z0-9-]*$", "Use an icon name like star or user-round.")
            .helper_text("Any Lucide icon name, like star, flag or user-round. Empty: none."),
            Toggle("is_shared").label("Share with everyone").visible(can_share),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").searchable().sortable().badge().color(lambda record: record.color or "gray"),
                TextColumn("resource").label("List").sortable()
                .state(lambda record, ctx: resource_label(ctx, record.resource)),
                TextColumn("is_shared").label("Who sees it")
                .state(lambda record: "Everyone" if record.is_shared else "Only me"),
                TextColumn("updated_at").label("Changed").since().sortable(),
            ])
            .actions([
                Action("open").label("Open").icon("external-link")
                .url(lambda record, ctx: open_url(ctx, record)),
                EditAction(),
                DeleteAction().action(delete_view),
            ])
            .reorderable("sort")
            .default_sort("sort", "asc")
            .empty_state("No saved views yet",
                         "Open any list, set filters or a search, then click “Save view” above the table.",
                         "bookmark")
        )
