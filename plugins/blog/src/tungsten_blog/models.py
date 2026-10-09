"""Tables of the blog plugin: posts, categories, tags and authors."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .text import slugify


def _now() -> dt.datetime:
    return dt.datetime.now()


class BlogBase(DeclarativeBase):
    pass


post_tags = Table(
    "tungsten_blog_post_tags",
    BlogBase.metadata,
    Column("post_id", ForeignKey("tungsten_blog_posts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tungsten_blog_tags.id", ondelete="CASCADE"), primary_key=True),
)


class BlogAuthor(BlogBase):
    """The person shown on a post. A real name, bio and profile links help search and AI engines trust it."""

    __tablename__ = "tungsten_blog_authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True, default="")
    job_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: profile links (LinkedIn, X, GitHub...), used as schema.org ``sameAs``
    profiles: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    posts: Mapped[list[BlogPost]] = relationship(back_populates="author")

    def __str__(self) -> str:
        return self.name


class BlogCategory(BlogBase):
    __tablename__ = "tungsten_blog_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    posts: Mapped[list[BlogPost]] = relationship(back_populates="category")

    def __str__(self) -> str:
        return self.name


class BlogTag(BlogBase):
    __tablename__ = "tungsten_blog_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(100), unique=True, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    posts: Mapped[list[BlogPost]] = relationship(secondary=post_tags, back_populates="tags")

    def __str__(self) -> str:
        return self.name


class BlogPost(BlogBase):
    __tablename__ = "tungsten_blog_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), unique=True, default="")
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cover_alt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: draft or published; a published post with a future date is scheduled
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_blog_authors.id", ondelete="SET NULL"), nullable=True, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_blog_categories.id", ondelete="SET NULL"), nullable=True, index=True)

    # SEO
    meta_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(320), nullable=True)
    focus_keyword: Mapped[str | None] = mapped_column(String(120), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    noindex: Mapped[bool] = mapped_column(Boolean, default=False)
    og_image: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # GEO: what AI search engines quote
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: ``[{"text": "..."}]``
    key_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: ``[{"title": "...", "url": "..."}]``
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # AEO: direct answers
    #: ``[{"question": "...", "answer": "..."}]``
    faqs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    howto_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: ``[{"name": "...", "text": "..."}]``
    howto_steps: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    author: Mapped[BlogAuthor | None] = relationship(back_populates="posts")
    category: Mapped[BlogCategory | None] = relationship(back_populates="posts")
    tags: Mapped[list[BlogTag]] = relationship(secondary=post_tags, back_populates="posts", order_by=BlogTag.name)

    def __str__(self) -> str:
        return self.title

    @property
    def is_live(self) -> bool:
        """Published and its date has come."""
        return self.status == "published" and (self.published_at is None or self.published_at <= _now())

    @property
    def is_scheduled(self) -> bool:
        return self.status == "published" and self.published_at is not None and self.published_at > _now()


def _fill_slug(connection, target, source: str, limit: int) -> None:
    """Make ``target.slug`` from ``source`` (or clean the given one) and keep it unique."""
    base = slugify(target.slug or source)[:limit].strip("-") or "post"
    table = type(target).__table__
    slug, n = base, 2
    while True:
        query = select(table.c.id).where(table.c.slug == slug)
        if target.id is not None:
            query = query.where(table.c.id != target.id)
        if connection.execute(query).first() is None:
            break
        slug = f"{base[:limit - len(str(n)) - 1]}-{n}"
        n += 1
    target.slug = slug


def _before_post_saved(mapper, connection, target: BlogPost) -> None:
    _fill_slug(connection, target, target.title, 200)
    if target.status == "published" and target.published_at is None:
        target.published_at = _now().replace(microsecond=0)


for _model, _source, _limit in ((BlogAuthor, "name", 140), (BlogCategory, "name", 140), (BlogTag, "name", 100)):
    def _make(source: str, limit: int):
        def fill(mapper, connection, target):
            _fill_slug(connection, target, getattr(target, source), limit)
        return fill

    event.listen(_model, "before_insert", _make(_source, _limit))
    event.listen(_model, "before_update", _make(_source, _limit))

event.listen(BlogPost, "before_insert", _before_post_saved)
event.listen(BlogPost, "before_update", _before_post_saved)
