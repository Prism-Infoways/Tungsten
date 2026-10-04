"""Dashboard numbers for leads."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from tungsten import Stat, StatsOverviewWidget

from .models import Lead


class LeadStats(StatsOverviewWidget):
    lazy = False

    @classmethod
    def stats(cls, db, ctx):
        def count(*where):
            return db.scalar(select(func.count()).select_from(Lead).where(*where)) or 0

        week_ago = dt.datetime.now() - dt.timedelta(days=7)
        total = count()
        won = count(Lead.status == "won")
        lost = count(Lead.status == "lost")
        closed = won + lost
        rate = f"{won * 100 / closed:.0f}%" if closed else "—"
        return [
            Stat("Total leads", f"{total:,}").icon("contact").color("primary"),
            Stat("New this week", f"{count(Lead.created_at >= week_ago):,}").icon("sparkles").color("info"),
            Stat("Follow-ups due", f"{count(Lead.follow_up_at <= dt.datetime.now(), Lead.status.notin_(['won', 'lost'])):,}")
            .icon("alarm-clock").color("warning"),
            Stat("Won", f"{won:,}").icon("trophy").color("success").describe(f"Win rate {rate}"),
        ]
