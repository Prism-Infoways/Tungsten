"""A "Recent backup" check for the Security audit plugin (tungsten-security-audit), when it is installed."""

from __future__ import annotations

import datetime as dt
from typing import Any

from .models import FAILED, Backup
from .service import file_of, latest_good


def backup_check(plugin: Any) -> Any:
    def check_backups(audit: Any) -> Any:
        from sqlalchemy import func, select
        from tungsten_security_audit.checks import FAIL, MEDIUM, PASS, WARN, Result

        last = latest_good(audit.db)
        key, group, title = "backups", "Settings", "Recent backup"
        if last is None:
            return Result(key, group, title, FAIL, MEDIUM, "No backup has been made yet.",
                          "Open Backups and press Back up now, or turn on every_hours= for automatic backups.")
        age = dt.datetime.now() - last.created_at
        path = file_of(plugin, last)
        if path is None or not path.is_file():
            return Result(key, group, title, WARN, MEDIUM, f"The newest backup file ({last.name}) is missing.",
                          "Make a new backup.")
        failed = audit.db.scalar(select(func.max(Backup.created_at)).where(Backup.status == FAILED))
        if age > dt.timedelta(days=plugin.max_age_days):
            return Result(key, group, title, WARN, MEDIUM, f"The newest backup is {age.days} days old.",
                          "Make a new backup, or set every_hours= so they run on their own.")
        if failed is not None and failed > last.created_at:
            return Result(key, group, title, WARN, MEDIUM, "The last backup try failed.",
                          "Open Backups and read the error on the failed row.")
        detail = f"The newest backup is from {last.created_at:%d %b %Y, %H:%M}."
        if plugin.every_hours:
            detail += f" Automatic backups run every {plugin.every_hours:g} hours."
        return Result(key, group, title, PASS, MEDIUM, detail)

    return check_backups
