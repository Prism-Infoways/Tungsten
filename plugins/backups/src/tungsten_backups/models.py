"""The backups table: one row per backup file."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

RUNNING, DONE, FAILED = "running", "done", "failed"


def _now() -> dt.datetime:
    return dt.datetime.now()


class BackupsBase(DeclarativeBase):
    pass


class Backup(BackupsBase):
    """One backup: a zip file in the private backups folder, or a failed try."""

    __tablename__ = "tungsten_backups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: the file name inside the backups folder (never a path)
    name: Mapped[str] = mapped_column(String(200), index=True)
    #: ``database`` or ``full`` (database and uploaded files)
    kind: Mapped[str] = mapped_column(String(20), default="database")
    #: ``running``, ``done`` or ``failed``
    status: Mapped[str] = mapped_column(String(20), default=RUNNING, index=True)
    #: how the database was saved: ``sqlite``, ``pg_dump``, ``mysqldump`` or ``json``
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tables: Mapped[int] = mapped_column(Integer, default=0)
    rows: Mapped[int] = mapped_column(BigInteger, default=0)
    files: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``{"skipped": [...], "folders": [...], ...}`` from the manifest
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    #: ``panel``, ``schedule`` or ``cli``
    source: Mapped[str] = mapped_column(String(20), default="panel")
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
