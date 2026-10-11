"""Ready-made boards for the other official plugins. Each one is only made when that plugin is added.

- leads:   lead stages (New, Contacted, ... Won, Lost); a move is written on the lead's timeline
- tickets: ticket status; a move goes through the help desk, so it is logged and the customer
           gets the "resolved" email like any other status change
- hr:      leave requests by status; a move approves, rejects or cancels through HR, with the
           same balance checks and rules as the Approve / Reject buttons
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

from .board import COLORS, Board, MoveRefused


def _me(ctx: Any) -> str | None:
    return ctx.panel.auth.user_id(ctx.user) if ctx is not None and ctx.user is not None else None


def _my_name(ctx: Any) -> str | None:
    return ctx.panel.auth.display_name(ctx.user) if ctx is not None and ctx.user is not None else None


def _label(statuses: dict, key: Any) -> str:
    spec = statuses.get(key)
    if isinstance(spec, (tuple, list)) and spec:
        return str(spec[0])
    return str(spec or key)


# ---------------------------------------------------------------------- leads
def leads_boards(panel: Any) -> list[Board]:
    from tungsten_leads.resources import DEFAULT_SOURCES, LeadResource, statuses, user_name
    from tungsten_leads.service import add_activity

    plugin = panel.get_plugin("leads")
    sources = dict(getattr(plugin, "sources", None) or DEFAULT_SOURCES)

    def on_move(record: Any, old: Any, new: Any, db: Any, ctx: Any) -> None:
        record.status = new
        labels = statuses(ctx)
        who = _my_name(ctx)
        add_activity(db, record, f"Stage changed from {_label(labels, old)} to {_label(labels, new)} on the board"
                     + (f" by {who}" if who else ""), type="system", user_id=_me(ctx))

    return [Board(
        LeadResource, column="status", columns=statuses, slug="leads-board", label="Leads board",
        icon="square-kanban", title="name", description="company",
        fields={"Value": "value", "Follow up": "follow_up_at",
                "Owner": lambda record, ctx: user_name(ctx, record.assigned_to)},
        badges=[lambda record: sources.get(record.source, record.source) if record.source else None,
                lambda record: (("Follow up due", "danger") if record.follow_up_at
                                and record.follow_up_at <= dt.datetime.now() else None)],
        search=["name", "email", "phone", "company"], assignee="assigned_to", on_move=on_move,
        sort_by="-created_at",
    )]


# ---------------------------------------------------------------------- tickets
def tickets_boards(panel: Any) -> list[Board]:
    from tungsten_tickets.resources import TicketResource, priorities, statuses, user_name
    from tungsten_tickets.service import set_status

    def on_move(record: Any, new: Any, db: Any, ctx: Any) -> None:
        set_status(db, record, new, user_id=_me(ctx), by=_my_name(ctx), ctx=ctx)

    def priority_badge(record: Any, ctx: Any) -> Any:
        label, color = priorities(ctx).get(record.priority, (record.priority, "gray"))
        return (label, color) if label else None

    def late_badge(record: Any) -> Any:
        if record.due_at and record.is_open and record.due_at <= dt.datetime.now():
            return ("Overdue", "danger")
        return None

    return [Board(
        TicketResource, column="status", columns=statuses, slug="tickets-board", label="Tickets board",
        icon="square-kanban", title=lambda record: f"{record.number or ''} {record.subject}".strip(),
        description=lambda record: record.requester_name or record.requester_email,
        fields={"Agent": lambda record, ctx: user_name(ctx, record.assigned_to), "Due": "due_at"},
        badges=[priority_badge, late_badge, lambda record: record.category.name if record.category else None],
        search=["number", "subject", "requester_name", "requester_email"], assignee="assigned_to",
        on_move=on_move, sort_by="-created_at",
    )]


# ---------------------------------------------------------------------- hr
def hr_boards(panel: Any) -> list[Board]:
    from tungsten_hr.resources import LeaveRequestResource, my_employee
    from tungsten_hr.service import LEAVE_STATUSES, LeaveError, decide_leave

    def can_move(record: Any, new: Any, ctx: Any) -> Any:
        if new == "pending":
            return "A decided request can't go back to pending. Ask for a new one instead."
        mine = my_employee(ctx)
        if new in ("approved", "rejected") and mine is not None and mine.id == record.employee_id:
            return "You can't approve or reject your own leave."
        return True

    def on_move(record: Any, new: Any, db: Any, ctx: Any) -> None:
        try:
            changed = decide_leave(db, record, new, user_id=_me(ctx), note="Changed on the leave board", ctx=ctx)
        except LeaveError as exc:
            raise MoveRefused(str(exc)) from exc
        if not changed:
            raise MoveRefused("This request can't move there.")

    def dates(record: Any) -> str:
        start, end = record.start_date, record.end_date
        if not start:
            return ""
        if not end or end == start:
            return f"{start:%d %b %Y}"
        return f"{start:%d %b} – {end:%d %b %Y}"

    return [Board(
        LeaveRequestResource, column="status", columns=LEAVE_STATUSES, slug="leave-board", label="Leave board",
        icon="square-kanban",
        title=lambda record: str(record.employee) if record.employee else f"Leave #{record.id}",
        description="reason",
        fields={"Dates": dates, "Days": lambda record: f"{record.days:g}" if record.days else None},
        badges=[lambda record: record.leave_type.name if record.leave_type else None,
                lambda record: ("Half day", "info") if record.half_day else None],
        transitions={"pending": ["approved", "rejected", "cancelled"], "approved": ["cancelled"],
                     "rejected": [], "cancelled": []},
        can_move=can_move, on_move=on_move, sort_by="start_date",
    )]


# ---------------------------------------------------------------------- tags
def tag_badges(record: Any, board: Board, ctx: Any) -> list:
    """With the Tags plugin, a card shows its record's tags in their colors."""
    from types import SimpleNamespace

    from tungsten_tags.components import _colors, record_names, target_of
    from tungsten_tags.service import tag_key

    target = target_of(ctx, board.resource)
    if target is None:
        return []
    holder = ctx.__dict__.setdefault("_kanban_tags", SimpleNamespace())  # colors are read once a page
    colors = _colors(holder, target, ctx.db)
    out = []
    for name in record_names(holder, target, record, ctx.db):
        color = colors.get(tag_key(name), "gray")
        out.append((name, color if color in COLORS else "gray"))
    return out


#: plugin id -> function that makes its boards
BUILDERS: dict[str, Callable[[Any], list[Board]]] = {
    "leads": leads_boards,
    "tickets": tickets_boards,
    "hr": hr_boards,
}
