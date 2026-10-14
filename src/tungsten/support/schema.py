"""Small schema upgrades for Tungsten's own tables (no migration tool needed)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn

log = logging.getLogger("tungsten")


def add_missing_columns(conn: Any, metadata: Any) -> list[str]:
    """``ALTER TABLE ... ADD COLUMN`` for columns a newer version added to an existing table.

    Only columns that can be added to a table with rows (nullable, or with a server default) are added;
    others are logged. Returns ``["table.column", ...]`` that were added.
    """
    insp = inspect(conn)
    existing_tables = set(insp.get_table_names())
    added = []
    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            if not column.nullable and column.server_default is None:
                log.warning("Tungsten: column %s.%s is missing; add it by hand", table.name, column.name)
                continue
            ddl = CreateColumn(column).compile(dialect=conn.dialect)
            conn.execute(text(f"ALTER TABLE {conn.dialect.identifier_preparer.format_table(table)} ADD COLUMN {ddl}"))
            added.append(f"{table.name}.{column.name}")
    if added:
        log.info("Tungsten: added columns %s", ", ".join(added))
    return added
