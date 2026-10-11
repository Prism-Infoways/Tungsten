"""The media library table: one row per stored file. Users are stored by id as a string, so any user model works."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> dt.datetime:
    return dt.datetime.now()


class MediaBase(DeclarativeBase):
    pass


class MediaItem(MediaBase):
    """A file in the library: an image, document, video or audio file kept in the panel storage."""

    __tablename__ = "tungsten_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: the storage path, the same value file fields save (``media/2026/10/3f9c...jpg``)
    path: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    #: the file name it was uploaded with
    name: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: text for screen readers and search engines (images)
    alt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder: Mapped[str] = mapped_column(String(100), default="", index=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    mime: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    #: image, video, audio, document or other
    kind: Mapped[str] = mapped_column(String(20), default="other", index=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: sha256 of the content, to spot the same file uploaded twice
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: the file is gone from storage (set by "Check files")
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    @property
    def is_image(self) -> bool:
        return self.kind == "image"

    @property
    def extension(self) -> str:
        name = self.path.rsplit("/", 1)[-1]
        return name.rsplit(".", 1)[-1].lower() if "." in name else ""

    @property
    def dimensions(self) -> str | None:
        return f"{self.width} × {self.height}" if self.width and self.height else None

    def __str__(self) -> str:
        return self.title or self.name or self.path.rsplit("/", 1)[-1]
