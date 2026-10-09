"""Dashboard numbers for the help desk."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from tungsten import Stat, StatsOverviewWidget

from .models import Ticket
from .service import CLOSED_STATUSES


class TicketStats(StatsOverviewWidget):
    lazy = False

    @classmethod
    def stats(cls, db, ctx):
        def count(*where):
            return db.scalar(select(func.count()).select_from(Ticket).where(*where)) or 0

        is_open = Ticket.status.notin_(CLOSED_STATUSES)
        now = dt.datetime.now()
        week_ago = now - dt.timedelta(days=7)
        overdue = count(is_open, Ticket.due_at < now)
        return [
            Stat("Open tickets", f"{count(is_open):,}").icon("life-buoy").color("primary"),
            Stat("Unassigned", f"{count(is_open, Ticket.assigned_to.is_(None)):,}").icon("user-x").color("info"),
            Stat("Overdue", f"{overdue:,}").icon("alarm-clock").color("danger" if overdue else "gray"),
            Stat("Resolved this week", f"{count(Ticket.resolved_at >= week_ago):,}").icon("circle-check")
            .color("success"),
        ]
