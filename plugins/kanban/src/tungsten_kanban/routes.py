"""Board routes, under the panel path:

    POST <panel>/_kanban/<board>/move     move a card (and save the order of its column)
    GET  <panel>/_kanban/<board>/cards    the next cards of a column ("Load more")

Both use the panel's own login, CSRF and tenancy checks. A move answers in JSON:
``{"ok": true, "counts": {...}}`` or ``{"ok": false, "error": "...", "reload": bool}``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from markupsafe import Markup

from tungsten.i18n import translate as __
from tungsten.routes import Routes
from tungsten.support.evaluate import call

from .board import MAX_ORDER_KEYS, MoveRefused, key_of

if TYPE_CHECKING:  # pragma: no cover
    from . import KanbanPlugin
    from .board import Board

log = logging.getLogger("tungsten.kanban")


def _error(message: str, status: int, reload: bool = False) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message, "reload": reload}, status_code=status)


def _label(columns: list, key: str) -> str:
    return next((c.label for c in columns if c.key == key), key or __("Other"))


def move_card(ctx: Any, board: Board, plugin: KanbanPlugin, fd: Any) -> JSONResponse:
    if fd is None:
        return _error(__("Send the card to move."), 400)
    if not board.can_view(ctx):
        return _error(__("You don't have permission to do that."), 403)
    key = str(fd.get("record") or "")
    to = str(fd.get("to") if fd.get("to") is not None else "")
    expected = fd.get("from")
    columns = board.get_columns(ctx)
    target = next((c for c in columns if c.key == to), None)
    if target is None:
        return _error(__("That column is not on this board any more. The board was refreshed."), 422, reload=True)
    host = board.host()
    record = None
    if key:
        query = board.base_query(ctx).where(host.primary_key() == host._typed_key(key))
        record = ctx.db.scalars(query).unique().first()
    if record is None:
        return _error(__("This card is gone or you can't see it any more. The board was refreshed."), 404,
                      reload=True)
    if not board.can_update(ctx, record):
        return _error(__("You can't change this card."), 403)
    old_value = getattr(record, board.column, None)
    old = key_of(old_value)
    if expected is not None and str(expected) != old:
        return _error(__("Someone else moved this card. The board was refreshed."), 409, reload=True)

    try:
        if to != old:
            if board.transitions is not None and old in board.transitions and to not in board.transitions[old]:
                raise MoveRefused(__(":from cards can't go to :to.", **{"from": _label(columns, old),
                                                                         "to": target.label}))
            if board.can_move is not None:
                verdict = call(board.can_move, record=record, old=old_value, new=target.value, ctx=ctx,
                               db=ctx.db, user=ctx.user, board=board)
                if verdict is False or isinstance(verdict, str):
                    raise MoveRefused(verdict if isinstance(verdict, str) and verdict
                                      else __("This card can't move there."))
            if board.on_move is not None:
                result = call(board.on_move, record=record, old=old_value, new=target.value, ctx=ctx,
                              db=ctx.db, user=ctx.user, board=board)
                if result is False:
                    raise MoveRefused(__("This card can't move there."))
            else:
                setattr(record, board.column, target.value)
            ctx.db.flush()
            for fn in list(plugin.move_listeners.values()):
                call(fn, db=ctx.db, record=record, old=old_value, new=target.value, board=board, ctx=ctx)
        elif not board.order_column:
            return JSONResponse({"ok": True, "changed": False})
        if board.order_column:
            keys = [str(k) for k in fd.getlist("order")][:MAX_ORDER_KEYS]
            if keys:
                save_order(ctx, board, target, keys)
        ctx.db.commit()
    except MoveRefused as exc:
        ctx.db.rollback()
        return _error(str(exc) or __("This card can't move there."), 422)
    except ValueError as exc:  # services raise these with a plain reason (leave balance...)
        ctx.db.rollback()
        return _error(str(exc) or __("This card can't move there."), 422)
    except Exception:
        ctx.db.rollback()
        log.exception("Could not move card %s on board %s", key, board.slug)
        return _error(__("Could not save the move. Please try again."), 500, reload=True)

    q, mine = (fd.get("q") or "")[:100], fd.get("mine") in ("1", "true", "on")
    counts = board.counts(ctx, columns, q, mine)
    return JSONResponse({"ok": True, "changed": to != old, "counts": counts,
                         "targets": board.targets(ctx, record, columns),
                         "message": __("Moved to :column", column=target.label) if to != old else None})


def save_order(ctx: Any, board: Board, column: Any, keys: list[str]) -> None:
    """Renumber a column: the cards on screen take the slots they held, in their new order.

    Cards not on screen (a search is on, or not loaded yet) keep their place.
    """
    host = board.host()
    model = board.resource.model
    order = getattr(model, board.order_column)
    query = board.base_query(ctx).where(board.model_column() == column.value) \
        .order_by(None).order_by(order.is_(None), order, host.primary_key())
    records = list(ctx.db.scalars(query).unique().all())
    by_key = {host.record_key(r): r for r in records}
    moved = [by_key[k] for k in dict.fromkeys(keys) if k in by_key]
    moved_ids = {id(r) for r in moved}
    new_order = iter(moved)
    records = [next(new_order) if id(r) in moved_ids else r for r in records]
    for position, record in enumerate(records, start=1):
        if getattr(record, board.order_column) != position:
            setattr(record, board.order_column, position)


def more_cards(ctx: Any, board: Board) -> HTMLResponse:
    from .page import board_state

    if not board.can_view(ctx):
        return HTMLResponse("", status_code=403)
    params = ctx.request.query_params
    key = params.get("column") or ""
    try:
        offset = max(0, int(params.get("offset") or 0))
    except ValueError:
        offset = 0
    columns = board.get_columns(ctx)
    column = next((c for c in columns if c.key == key), None)
    if column is None and key:
        return HTMLResponse("", status_code=404)
    q, mine = board_state(ctx)
    records, more = board.records(ctx, column, columns, q, mine, offset=offset)
    html = ctx.panel.renderer.render(
        "tungsten_kanban/cards.html", ctx=ctx, board=board, cards=[board.card(ctx, r, columns) for r in records],
        columns=columns, more=more, column_key=key, offset=offset + len(records), q=q, mine=mine,
        cards_url=ctx.url("_kanban", board.slug, "cards"))
    return HTMLResponse(str(Markup(html)))


def add_routes(app: Any, panel: Any, plugin: KanbanPlugin) -> None:
    routes = Routes(panel)

    def find(slug: str) -> Board | None:
        return plugin.boards.get(slug)

    @app.post("/_kanban/{slug}/move")
    async def move(request: Request, slug: str):
        board = find(slug)
        if board is None:
            return _error(__("This board does not exist."), 404)
        return await routes.run(request, lambda ctx, fd: move_card(ctx, board, plugin, fd), read_form=True)

    @app.get("/_kanban/{slug}/cards")
    async def cards(request: Request, slug: str):
        board = find(slug)
        if board is None:
            return HTMLResponse("", status_code=404)
        return await routes.run(request, lambda ctx, fd: more_cards(ctx, board))

