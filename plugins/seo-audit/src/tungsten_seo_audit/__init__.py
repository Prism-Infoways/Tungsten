"""SEO audit for Tungsten.

    from tungsten_seo_audit import SeoAuditPlugin

    panel.plugin(SeoAuditPlugin(site_url="https://www.example.com"))
    panel.create_tables(engine)

Open "SEO audits" in the panel and press New audit. The audit crawls the site and checks titles,
meta descriptions, headings, image alt texts, broken links and redirects, canonical links,
robots.txt, sitemap.xml, Open Graph tags, structured data, the mobile viewport, HTTPS, page
size and speed, and AI search readiness (llms.txt, AI crawlers, FAQ markup). Each issue comes
with a tip, the site gets a score from 0 to 100, and every audit stays in the history.

Other plugins can add their public pages to every audit (the blog plugin adds its posts):
give the plugin a ``seo_urls(db) -> list[str]`` method, or pass ``urls=`` here.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import select

from tungsten import Plugin

from .audit import run_audit
from .checks import CATEGORIES, CHECKS, Issue, check_page, score
from .crawler import Response, Transport, fetch, read_html
from .models import SeoAudit, SeoAuditBase, SeoIssue, SeoPage
from .resources import SeoAuditResource, SeoStats

__version__ = "0.1.0"


class SeoAuditPlugin(Plugin):
    """``SeoAuditPlugin(site_url=None, max_pages=25, urls=None, background=True)``.

    - ``site_url``: the site the New audit form starts with. Defaults to the panel's ``app_url``.
    - ``max_pages``: how many pages an audit checks unless the form says otherwise.
    - ``urls``: a list of extra addresses, or ``fn(db) -> list`` (pages the links don't reach).
    - ``background``: run audits in a thread, so the page doesn't wait. ``False`` waits (tests, scripts).
    - ``transport``: swap the HTTP layer (tests).
    """

    id = "seo-audit"
    metadata = SeoAuditBase.metadata

    def __init__(self, site_url: str | None = None, max_pages: int = 25,
                 urls: Iterable[str] | Callable[[Any], Iterable[str]] | None = None, background: bool = True,
                 transport: Transport | None = None) -> None:
        self.site_url = site_url.rstrip("/") if site_url else None
        self.max_pages = max_pages
        self.urls = urls
        self.background = background
        self.transport = transport
        self.panel: Any = None

    def register(self, panel: Any) -> None:
        self.panel = panel
        panel.resources([SeoAuditResource])

    def default_url(self, ctx: Any = None) -> str | None:
        if self.site_url:
            return self.site_url
        if self.panel is not None and self.panel.app_url:
            return self.panel.app_url
        return None

    def extra_urls(self, db: Any) -> list[str]:
        """Addresses from ``urls=`` and from other plugins with a ``seo_urls(db)`` method."""
        out: list[str] = []
        if callable(self.urls):
            out += list(self.urls(db) or [])
        elif self.urls:
            out += list(self.urls)
        for plugin in getattr(self.panel, "_plugins", []):
            fn = getattr(plugin, "seo_urls", None)
            if plugin is not self and callable(fn):
                try:
                    out += list(fn(db) or [])
                except Exception:  # another plugin's bug must not stop the audit
                    pass
        return out

    def start_audit(self, db: Any, url: str, max_pages: int | None = None, check_external: bool = True,
                    user_id: str | None = None) -> SeoAudit:
        """Save a new audit and run it (in a thread when ``background``)."""
        stale = dt.datetime.now() - dt.timedelta(hours=2)
        for old in db.scalars(select(SeoAudit).where(SeoAudit.status == "running", SeoAudit.started_at < stale)):
            old.status, old.error = "failed", "Stopped before it finished (the server restarted?)."
        audit = SeoAudit(url=url.strip(), max_pages=max(1, min(500, max_pages or self.max_pages)), user_id=user_id)
        db.add(audit)
        db.commit()
        extra = self.extra_urls(db)
        if not self.background:
            try:
                run_audit(db, audit, self.transport, extra, check_external)
            except Exception:
                pass  # saved on the audit as failed
            return audit
        audit_id = audit.id

        def work(session: Any) -> None:
            row = session.get(SeoAudit, audit_id)
            if row is not None:
                run_audit(session, row, self.transport, extra, check_external)

        def thread() -> None:
            try:
                self.panel.with_session(work)
            except Exception:
                pass

        threading.Thread(target=thread, name=f"seo-audit-{audit_id}", daemon=True).start()
        return audit


__all__ = [
    "CATEGORIES", "CHECKS", "Issue", "Response", "SeoAudit", "SeoAuditPlugin", "SeoAuditResource", "SeoIssue",
    "SeoPage", "SeoStats", "check_page", "fetch", "read_html", "run_audit", "score",
]
