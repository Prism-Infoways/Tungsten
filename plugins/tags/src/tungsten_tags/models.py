"""Tables of the tags plugin: the tags themselves and which record carries which tag.

A tagging points at any record by its table name and primary key (stored as text), so
one tag works on leads, tickets, employees, invoices or your own models alike.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> dt.datetime:
    return dt.datetime.now()


class TagsBase(DeclarativeBase):
    pass


class Tag(TagsBase):
    """A label like "VIP" or "Follow up". ``key`` is the name in lower case, so "vip" and "VIP" are one tag."""

    __tablename__ = "tungsten_tags"
    __table_args__ = (UniqueConstraint("type", "key", name="uq_tungsten_tags_type_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    key: Mapped[str] = mapped_column(String(50), index=True)
    #: optional group, like "industry" or "priority". "" is the shared group every module uses.
    type: Mapped[str] = mapped_column(String(50), default="", index=True)
    color: Mapped[str] = mapped_column(String(20), default="gray")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    taggings: Mapped[list[Tagging]] = relationship(back_populates="tag", cascade="all, delete-orphan",
                                                   passive_deletes=True)

    def __str__(self) -> str:
        return self.name


class Tagging(TagsBase):
    """One tag on one record."""

    __tablename__ = "tungsten_taggings"
    __table_args__ = (
        UniqueConstraint("taggable_type", "taggable_id", "tag_id", name="uq_tungsten_taggings_record_tag"),
        Index("ix_tungsten_taggings_tag_type", "tag_id", "taggable_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tungsten_tags.id", ondelete="CASCADE"))
    #: the record's table name, like "tungsten_leads"
    taggable_type: Mapped[str] = mapped_column(String(100))
    #: the record's primary key, as text
    taggable_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    tag: Mapped[Tag] = relationship(back_populates="taggings")
