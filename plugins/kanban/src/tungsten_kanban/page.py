"""The panel page that shows a board."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from markupsafe import Markup

from tungsten import Page
from tungsten.i18n import translate as __

if TYPE_CHECKING:  # pragma: no cover
    from .board import Board


def board_state(ctx: Any) -> tuple[str, bool]:
    """The search text and "only mine" switch from the address."""
    params = ctx.request.query_params
    return (params.get("q") or "").strip()[:100], params.get("mine") in ("1", "true", "on")


def quick_create_url(ctx: Any, board: Board) -> str | None:
    """With the Quick Create plugin, "New" opens the form in a side panel right on the board."""
    plugin = ctx.panel.get_plugin("quick-create")
    if plugin is None:
        return None
    try:
        resource = board.resource
        if resource in plugin.resources() and plugin.allowed(ctx, resource):
            return ctx.url("_quick-create", resource.get_slug())
    except Exception:  # noqa: BLE001  (an add-on must never break the board)
        return None
    return None


def render_board(ctx: Any, board: Board) -> Markup:
    q, mine = board_state(ctx)
    columns = board.get_columns(ctx)
    counts = board.counts(ctx, columns, q, mine)
    lanes = []
    for column in columns:
        records, more = board.records(ctx, column, columns, q, mine)
        lanes.append({"column": column, "cards": [board.card(ctx, r, columns) for r in records], "more": more,
                      "count": counts.get(column.key, 0)})
    if board.show_other and counts.get("", 0):
        from .board import Column

        other = Column("", None, __("Other"), "gray", accepts=False)
        records, more = board.records(ctx, None, columns, q, mine)
        lanes.append({"column": other, "cards": [board.card(ctx, r, columns) for r in records], "more": more,
                      "count": counts[""]})
    base = ctx.url("_kanban", board.slug)
    quick_url = quick_create_url(ctx, board)
    return Markup(ctx.panel.renderer.render(
        "tungsten_kanban/board.html", ctx=ctx, board=board, lanes=lanes, columns=columns, q=q, mine=mine,
        move_url=f"{base}/move", cards_url=f"{base}/cards", page_url=ctx.url(board.slug),
        sortable=bool(board.order_column), total=sum(counts.values()), quick_url=quick_url,
        new_label=__("New :thing", thing=board.resource.get_label()),
    ))


class BoardPage(Page):
    """Base class of every board page (one subclass per board)."""

    board: ClassVar[Any] = None
    icon = "square-kanban"

    @classmethod
    def get_title(cls) -> str:
        return cls.board.get_label()

    @classmethod
    def get_subheading(cls, ctx: Any) -> str | None:
        if cls.board.subheading:
            return __(cls.board.subheading)
        if cls.board.order_column:
            return __("Drag cards to another column to change them, or up and down to reorder.")
        return __("Drag a card to another column to change it.")

    @classmethod
    def can_access(cls, ctx: Any) -> bool:
        return cls.board.can_view(ctx)

    @classmethod
    def content(cls, ctx: Any) -> Any:
        return render_board(ctx, cls.board)

    @classmethod
    def header_actions(cls, ctx: Any) -> list:
        from tungsten.actions import Action

        resource = cls.board.resource
        actions = []
        if resource.has_page("create") and resource.can(ctx, "create") and quick_create_url(ctx, cls.board) is None:
            actions.append(Action("kanban_create").label(__("New :thing", thing=resource.get_label()))
                           .icon("plus").url(resource.get_url(ctx, "create")))
        actions.append(Action("kanban_list").label(__("List view")).icon("list").color("gray")
                       .url(resource.get_url(ctx)))
        return actions


def make_page(board: Board) -> type[BoardPage]:
    name = "".join(part.capitalize() for part in board.slug.split("-")) + "Page"
    return type(name, (BoardPage,), {
        "board": board, "slug": board.slug, "icon": board.icon, "navigation_group": board.navigation_group,
        "navigation_sort": board.navigation_sort, "show_in_navigation": board.show_in_navigation,
        "permission": board.permission, "__module__": __name__,
    })
