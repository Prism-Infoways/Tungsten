"""Tables of the SEO audit plugin."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> dt.datetime:
    return dt.datetime.now()


class SeoAuditBase(DeclarativeBase):
    pass


class SeoAudit(SeoAuditBase):
    """One run of the audit over a site."""

    __tablename__ = "tungsten_seo_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(500))
    #: running, done or failed
    status: Mapped[str] = mapped_column(String(10), default="running", index=True)
    #: 0 to 100, set when the audit is done
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_pages: Mapped[int] = mapped_column(Integer, default=25)
    pages_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    notices: Mapped[int] = mapped_column(Integer, default=0)
    #: score of each group of checks, like {"Content": 80, "Technical": 95}
    categories: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    pages: Mapped[list[SeoPage]] = relationship(back_populates="audit", cascade="all, delete-orphan",
                                                order_by="SeoPage.id")
    issues: Mapped[list[SeoIssue]] = relationship(back_populates="audit", cascade="all, delete-orphan",
                                                  order_by="SeoIssue.id")

    def __str__(self) -> str:
        return self.url


class SeoPage(SeoAuditBase):
    """One page the audit opened."""

    __tablename__ = "tungsten_seo_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("tungsten_seo_audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    h1: Mapped[str | None] = mapped_column(String(500), nullable=True)
    words: Mapped[int] = mapped_column(Integer, default=0)
    size_kb: Mapped[int] = mapped_column(Integer, default=0)
    load_ms: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=100)
    issues_count: Mapped[int] = mapped_column(Integer, default=0)

    audit: Mapped[SeoAudit] = relationship(back_populates="pages")

    def __str__(self) -> str:
        return self.url


class SeoIssue(SeoAuditBase):
    """One problem found, with a tip to fix it."""

    __tablename__ = "tungsten_seo_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("tungsten_seo_audits.id", ondelete="CASCADE"), index=True)
    #: the page, or None for the whole site (robots.txt, sitemap.xml...)
    page_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    check: Mapped[str] = mapped_column(String(40), index=True)
    #: Content, Technical, Links, Social, Speed
    category: Mapped[str] = mapped_column(String(20), index=True)
    #: error, warning or notice
    severity: Mapped[str] = mapped_column(String(10), index=True)
    message: Mapped[str] = mapped_column(Text)
    tip: Mapped[str] = mapped_column(Text, default="")

    audit: Mapped[SeoAudit] = relationship(back_populates="issues")

    def __str__(self) -> str:
        return self.message
