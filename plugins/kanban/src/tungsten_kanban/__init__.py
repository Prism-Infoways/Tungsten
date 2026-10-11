"""Kanban boards for Tungsten: show any resource as drag-and-drop columns.

    from tungsten_kanban import Board, KanbanPlugin

    panel.plugin(KanbanPlugin(boards=[
        Board(TaskResource, column="status", columns={
            "todo": ("To do", "gray"), "doing": ("Doing", "primary"), "done": ("Done", "success"),
        }, order_column="sort"),
    ]))

With the leads, tickets or HR plugins installed, their boards (lead stages, ticket
status, leave requests) are added for you. With Tags, cards show their tags; with
Quick Create, "New" opens the form right on the board. Each board is a page in the menu, and
the resource's list gets a "Board view" button.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from markupsafe import Markup, escape

from tungsten import Plugin

from .board import Board, Card, Column, MoveRefused, key_of
from .page import BoardPage, make_page
from .routes import add_routes

__version__ = "0.1.0"

#: built-in boards for the other official plugins, by plugin id
AUTO_BOARDS = ("leads", "tickets", "hr")


class KanbanPlugin(Plugin):
    """``KanbanPlugin(boards=[...], auto_boards=True, list_button=True)``.

    - ``boards``: your own :class:`Board` definitions.
    - ``auto_boards``: ``True`` adds a board for every official plugin that is installed
      (leads, tickets, hr); a list like ``["tickets"]`` picks some; ``False`` adds none.
    - ``list_button``: put a "Board view" button above the list of every resource with a board.
    """

    id = "kanban"
    templates = Path(__file__).with_name("templates")
    static = Path(__file__).with_name("static")

    def __init__(self, boards: list[Board] | None = None, auto_boards: Any = True,
                 list_button: bool = True) -> None:
        self.boards: dict[str, Board] = {}
        self.auto_boards = auto_boards
        self.list_button = list_button
        self.panel: Any = None
        #: other plugins hook in with the methods below
        self.move_listeners: dict[str, Any] = {}
        self.badge_providers: dict[str, Any] = {}
        self._booted = False
        for board in boards or []:
            self.add_board(board)

    # ------------------------------------------------------------------ hooks for other code
    def add_board(self, board: Board) -> Board:
        """Add a board. Works before the panel starts; a board with the same slug is replaced."""
        if self._booted:
            raise RuntimeError("Add boards before the panel starts serving")
        board.plugin = self
        self.boards[board.slug] = board
        if self.panel is not None:
            self._register_board(board)
        return board

    def on_card_moved(self, key: str, fn: Any) -> None:
        """Run ``fn(db, record, old, new, board, ctx)`` after a card moves to another column.

        It runs before the save is committed, so an error undoes the move. The same ``key`` replaces it.
        """
        self.move_listeners[key] = fn

    def add_card_badges(self, key: str, fn: Any) -> None:
        """Add badges to every card: ``fn(record, board, ctx)`` returns text, ``(text, color)`` or a list."""
        self.badge_providers[key] = fn

    def board_for(self, resource: Any) -> Board | None:
        """The board of a resource (class or slug), or None."""
        for board in self.boards.values():
            if board.resource is resource or board.resource.get_slug() == resource:
                return board
        return None

    def board_url(self, board: Board | str) -> str:
        board = self.boards[board] if isinstance(board, str) else board
        return self.panel.url(board.slug)

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        for board in self.boards.values():
            self._register_board(board)
        panel.routes(lambda app, p: add_routes(app, p, self))

    def _register_board(self, board: Board) -> None:
        if board.page is None:
            board.page = make_page(board)
        if board.page not in self.panel.get_pages():
            self.panel.pages([board.page])

    def boot(self, panel: Any) -> None:
        # other plugins may be added after this one, so their boards are made here
        if self.auto_boards:
            from .integrations import BUILDERS

            wanted = AUTO_BOARDS if self.auto_boards is True else tuple(self.auto_boards)
            for name in wanted:
                builder = BUILDERS.get(name)
                if builder is None or panel.get_plugin(name) is None:
                    continue
                for board in builder(panel):
                    if board.slug in self.boards or self.board_for(board.resource) is not None:
                        continue  # the app made its own board for this
                    self.add_board(board)
        if panel.get_plugin("tags") is not None and "tags" not in self.badge_providers:
            from .integrations import tag_badges

            self.add_card_badges("tags", tag_badges)
        self._booted = True
        panel.render_hook("head.end", self._assets)
        if self.list_button:
            panel.render_hook("resource.list.before-table", self._list_button)

    # ------------------------------------------------------------------ html
    def _assets(self) -> Markup:
        css = self.panel.plugin_asset(self.id, f"kanban.css?v={__version__}")
        js = self.panel.plugin_asset(self.id, f"kanban.js?v={__version__}")
        return Markup(f'<link rel="stylesheet" href="{escape(css)}">'
                      f'<script defer src="{escape(js)}"></script>')

    def _list_button(self, ctx: Any) -> Markup | None:
        path = ctx.request.url.path.rstrip("/")
        for board in self.boards.values():
            resource = board.resource
            if path != resource.get_url(ctx).rstrip("/"):
                continue
            if not board.can_view(ctx):
                return None
            return Markup(ctx.panel.renderer.render("tungsten_kanban/list-button.html", ctx=ctx,
                                                    url=ctx.url(board.slug), label=board.get_label()))
        return None

    def permissions(self) -> list[tuple[str, str]]:
        return []


__all__ = ["Board", "BoardPage", "Card", "Column", "KanbanPlugin", "MoveRefused", "key_of"]
