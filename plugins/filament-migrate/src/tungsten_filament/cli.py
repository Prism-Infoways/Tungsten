"""``tungsten-filament``: convert a Filament admin to Tungsten.

    tungsten-filament scan PATH
    tungsten-filament convert PATH [--out tungsten_admin] [--database-url URL] [--force]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .generate import build, write


def _summary(result, out: Path) -> None:
    s = result.summary
    fil = result.filament
    print(f"Filament {fil.version} project: {len(result.project.models)} models, {len(fil.resources)} resources, "
          f"{len(fil.pages)} custom pages, {len(fil.widgets)} widgets")
    print(f"Converted: {s['models']} models, {s['resources']} resources, {s['relation_managers']} relation managers")
    print(f"Needs a human: {len(result.todos)} item(s), see {out / 'MIGRATION_REPORT.md'}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tungsten-filament",
                                     description="Move a Laravel Filament admin panel to Tungsten.")
    parser.add_argument("--version", action="version", version=f"tungsten-filament {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    scan = sub.add_parser("scan", help="show what can be converted, write nothing")
    scan.add_argument("path", type=Path, help="the Laravel project folder")
    scan.add_argument("--database-url", help="read tables from this database instead of the migrations")

    conv = sub.add_parser("convert", help="write the Tungsten admin")
    conv.add_argument("path", type=Path, help="the Laravel project folder")
    conv.add_argument("--out", "-o", type=Path, default=Path("tungsten_admin"),
                      help="folder to write (a Python package; default: tungsten_admin)")
    conv.add_argument("--database-url", help="read tables from this database instead of the migrations")
    conv.add_argument("--force", "-f", action="store_true", help="overwrite the folder if it is not empty")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    out = getattr(args, "out", Path("tungsten_admin"))
    try:
        result = build(args.path, out, args.database_url)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.command == "scan":
        _summary(result, out)
        for todo in result.todos:
            where = f"{todo.file}:{todo.line}" if todo.line else todo.file
            print(f"  - {where}: {todo.reason}")
        return 0
    try:
        files = write(result, out, force=args.force)
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    _summary(result, out)
    print(f"Wrote {len(files)} files to {out}/. Next: uvicorn {out.name}.app:app --reload")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
