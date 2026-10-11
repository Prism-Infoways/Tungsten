"""``python -m tungsten_backups myapp:panel`` makes a backup from the command line (for cron).

    python -m tungsten_backups myapp:panel            # the database
    python -m tungsten_backups myapp:panel --full     # the database and uploaded files
    python -m tungsten_backups myapp:panel --list     # the backups you have
    python -m tungsten_backups myapp:panel --verify   # check the newest one
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import select

from .engine import BackupError, human_size
from .models import DONE, Backup
from .service import latest_good, start_backup, verify


def main(argv: Sequence[str] | None = None) -> int:
    from tungsten.cli import load

    parser = argparse.ArgumentParser(prog="python -m tungsten_backups", description="Back up a Tungsten panel.")
    parser.add_argument("panel", help="where your panel lives, as module:attribute (e.g. myapp:panel)")
    parser.add_argument("--full", action="store_true", help="also save uploaded files")
    parser.add_argument("--note", default=None, help="a note shown in the panel")
    parser.add_argument("--list", action="store_true", help="list backups and exit")
    parser.add_argument("--verify", action="store_true", help="check the newest backup and exit")
    args = parser.parse_args(argv)
    try:
        panel = load(args.panel)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not load {args.panel}: {exc}", file=sys.stderr)
        return 2
    plugin = panel.get_plugin("backups")
    if plugin is None:
        print("This panel has no BackupsPlugin. Add panel.plugin(BackupsPlugin()).", file=sys.stderr)
        return 2
    if args.list:
        rows = panel.with_session(lambda db: [(b.created_at, b.status, b.kind, b.size, b.name) for b in
                                              db.scalars(select(Backup).order_by(Backup.created_at.desc()))])
        for created, status, kind, size, name in rows:
            print(f"{created:%Y-%m-%d %H:%M}  {status:8} {kind:9} {human_size(size):>9}  {name}")
        return 0
    if args.verify:
        def check(db):
            last = latest_good(db)
            return None if last is None else (last.name, verify(plugin, db, last))

        found = panel.with_session(check)
        if found is None:
            print("No backup yet.", file=sys.stderr)
            return 1
        name, problems = found
        print(f"{name}: " + ("OK" if not problems else "; ".join(problems)))
        return 0 if not problems else 1
    try:
        row = start_backup(plugin, kind="full" if args.full else "database", note=args.note, source="cli",
                           background=False)
    except BackupError as exc:
        print(f"Backup not made: {exc}", file=sys.stderr)
        return 1
    if row.status != DONE:
        print(f"Backup failed: {row.error}", file=sys.stderr)
        return 1
    print(f"{plugin.folder / row.name} ({human_size(row.size)})")
    return 0
