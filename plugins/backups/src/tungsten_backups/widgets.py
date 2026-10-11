"""A dashboard card: when the last good backup was made."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from tungsten import Stat, StatsOverviewWidget

from .engine import free_space, human_size
from .models import DONE, FAILED, Backup
from .resources import allowed, plugin_of
from .service import latest_good


def ago(when: dt.datetime) -> str:
    seconds = max(0, (dt.datetime.now() - when).total_seconds())
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = int(seconds // size)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


class BackupStats(StatsOverviewWidget):
    lazy = False
    columns = 3
    sort = 90

    @classmethod
    def can_view(cls, ctx):
        return allowed(ctx)

    @classmethod
    def stats(cls, db, ctx):
        plugin = plugin_of(ctx)
        last = latest_good(db)
        count, total = db.execute(select(func.count(), func.coalesce(func.sum(Backup.size), 0))
                                  .where(Backup.status == DONE)).one()
        last_failed = db.scalar(select(func.max(Backup.created_at)).where(Backup.status == FAILED))
        stale = last is None or dt.datetime.now() - last.created_at > dt.timedelta(days=plugin.max_age_days)
        if last is None:
            first = Stat("Last backup", "Never").describe("Make your first backup").color("danger")
        else:
            first = Stat("Last backup", ago(last.created_at)).describe(human_size(last.size)) \
                .color("warning" if stale else "success")
        if last_failed is not None and (last is None or last_failed > last.created_at):
            first = first.describe("The last try failed").color("danger")
        try:
            free = human_size(free_space(plugin.folder))
        except OSError:
            free = "unknown"
        url = ctx.url("backups")
        return [
            first.icon("database-backup").url(url),
            Stat("Backups kept", f"{count:,}").describe(human_size(total)).icon("archive").color("primary").url(url),
            Stat("Free disk space", free).icon("hard-drive").color("gray"),
        ]
