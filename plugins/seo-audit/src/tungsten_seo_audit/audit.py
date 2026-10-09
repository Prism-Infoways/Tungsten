"""Running an audit: crawl the site, run the checks, save pages, issues and the score."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Iterable
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from .checks import ERROR, NOTICE, WARNING, Issue, check_page, check_robots, has_faq, score
from .crawler import PageInfo, Response, Transport, fetch, normalize, read_html

#: links to files like these are not opened as pages
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif", ".ico", ".pdf", ".zip", ".mp4", ".mp3",
            ".webm", ".css", ".js", ".json", ".xml", ".txt", ".woff", ".woff2", ".ttf", ".doc", ".docx", ".xls",
            ".xlsx", ".csv", ".rar", ".gz")
#: most links (inside and outside the site) checked after the crawl
MAX_LINK_CHECKS = 60


def site_root(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _is_page_link(href: str) -> bool:
    return not href.lower().startswith(("mailto:", "tel:", "javascript:", "data:", "#", "sms:", "whatsapp:"))


def _local(url: str) -> bool:
    """Links to the visitor's own machine (docs often show http://127.0.0.1:8000) are not checked."""
    h = (urlparse(url).hostname or "").lower()
    return h in ("localhost", "0.0.0.0", "::1") or h.startswith("127.") or h.endswith((".local", ".localhost"))


def _same_site(url: str, host: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return netloc == host or netloc.removeprefix("www.") == host.removeprefix("www.")


def sitemap_urls(res: Response, transport: Transport | None, depth: int = 0) -> tuple[list[str], bool]:
    """Page addresses in a sitemap (following one level of sitemap index), and whether it was valid XML."""
    try:
        root = ET.fromstring(res.body)
    except ET.ParseError:
        return [], False
    locs = [el.text.strip() for el in root.iter() if el.tag.endswith("loc") and el.text]
    if root.tag.endswith("sitemapindex"):
        out: list[str] = []
        if depth == 0:
            for loc in locs[:5]:
                child = fetch(loc, transport)
                if child.status == 200:
                    out += sitemap_urls(child, transport, depth + 1)[0]
        return out, True
    return locs, True


def run_audit(db: Any, audit: Any, transport: Transport | None = None, extra_urls: Iterable[str] = (),
              check_external: bool = True) -> Any:
    """Crawl ``audit.url`` and fill the audit with pages, issues and a score.

    Commits after each page, so the panel shows the progress. Any crash marks the audit failed.
    """
    from .models import SeoIssue, SeoPage

    try:
        _crawl(db, audit, transport, list(extra_urls), check_external, SeoPage, SeoIssue)
    except Exception as exc:
        db.rollback()
        audit.status = "failed"
        audit.error = str(exc) or exc.__class__.__name__
        audit.finished_at = dt.datetime.now()
        db.commit()
        raise
    return audit


def _crawl(db: Any, audit: Any, transport: Transport | None, extra: list[str], check_external: bool,
           SeoPage: Any, SeoIssue: Any) -> None:
    start_url = normalize(audit.url.strip() if "://" in audit.url else "https://" + audit.url.strip())
    first = fetch(start_url, transport)
    if not first.error and first.redirects and urlparse(first.url).netloc != urlparse(start_url).netloc:
        start_url = normalize(first.url)  # example.com moves to www.example.com: audit www
    audit.url = start_url
    root = site_root(start_url)
    host = urlparse(start_url).netloc.lower()
    issues: list[Issue] = []

    # site files
    robots_res = fetch(root + "/robots.txt", transport)
    robots_issues, sitemaps = check_robots(robots_res if robots_res.status else None, root)
    issues += robots_issues
    robots = RobotFileParser()
    robots.parse(robots_res.text.splitlines() if robots_res.status == 200 else [])

    queue: deque[str] = deque([start_url])
    queued = {start_url}

    def enqueue(url: str) -> None:
        url = normalize(url)
        if url not in queued and _same_site(url, host) and urlparse(url).scheme in ("http", "https") \
                and not urlparse(url).path.lower().endswith(SKIP_EXT):
            queued.add(url)
            queue.append(url)

    found_sitemap = False
    for sm in sitemaps or [root + "/sitemap.xml"]:
        res = fetch(sm, transport)
        if res.status != 200:
            continue
        found_sitemap = True
        urls, valid = sitemap_urls(res, transport)
        if not valid:
            issues.append(Issue("sitemap_invalid", ERROR, f"{sm} is not valid XML."))
        for u in urls[: audit.max_pages * 2]:
            enqueue(u)
        break
    if not found_sitemap:
        issues.append(Issue("sitemap_missing", WARNING, "The site has no sitemap.xml."))
    for u in extra:
        enqueue(urljoin(root + "/", u))
    llms = fetch(root + "/llms.txt", transport)
    if llms.status != 200:
        issues.append(Issue("llms_missing", NOTICE, "The site has no llms.txt."))

    # https
    if urlparse(start_url).scheme != "https":
        issues.append(Issue("not_https", ERROR, "The site address starts with http://, not https://."))
    else:
        plain = fetch("http://" + host + "/", transport)
        if not plain.error and not plain.redirects and plain.status < 400:
            issues.append(Issue("http_no_redirect", WARNING, "http:// pages open without moving to https://."))
        elif plain.redirects and urlparse(plain.url).scheme != "https":
            issues.append(Issue("http_no_redirect", WARNING, "http:// pages do not move to https://."))

    missing = fetch(root + "/tungsten-seo-audit-check-404-page", transport)
    if missing.status == 200:
        issues.append(Issue("soft_404", WARNING, "A page that doesn't exist answers with 200 instead of 404."))

    # pages
    status_of: dict[str, Response] = {}
    links_from: dict[str, set[str]] = {}
    infos: dict[str, PageInfo] = {}
    pages: list[Any] = []
    crawled: set[str] = set()
    broken_pages: list[str] = []
    while queue and len(pages) < audit.max_pages:
        url = queue.popleft()
        if robots_res.status == 200 and not robots.can_fetch("*", url) and url != start_url:
            continue
        if url in crawled:
            continue
        res = fetch(url, transport)
        status_of[url] = res
        final = normalize(res.url)
        if final != url:  # a redirect: audit the page it lands on, once
            if final in crawled or not _same_site(final, host):
                continue
            status_of[final] = replace(res, redirects=[])
            url = final
        crawled.add(url)
        if (res.error or res.status >= 400) and url != start_url:
            broken_pages.append(url)  # reported as a broken link, or below when nothing links to it
            continue
        info = read_html(res.text) if res.status == 200 and res.is_html else None
        page_issues = check_page(url, res, info)
        if info is not None:
            infos[url] = info
            for href, rel in info.links:
                if not _is_page_link(href):
                    continue
                target = normalize(urljoin(res.url, href))
                links_from.setdefault(target, set()).add(url)
                if "nofollow" not in rel and _same_site(res.url, host):
                    enqueue(target)
        issues += page_issues
        page = SeoPage(url=url, status_code=res.status or None, title=(info.title or None) if info else None,
                       description=(info.meta.get("description") or None) if info else None,
                       h1=(info.h1[0][:500] if info.h1 else None) if info else None,
                       words=info.words if info else 0, size_kb=round(res.size / 1024),
                       load_ms=res.elapsed_ms, issues_count=len(page_issues))
        audit.pages.append(page)
        pages.append(page)
        audit.pages_count = len(pages)
        db.commit()

    if pages and not any(has_faq(i) for i in infos.values()):
        issues.append(Issue("faq_missing", NOTICE, "No page has FAQ structured data."))

    # duplicates
    for field, check, label in (("title", "title_duplicate", "title"),
                                ("description", "description_duplicate", "meta description")):
        seen: dict[str, list[str]] = {}
        for p in pages:
            value = getattr(p, field)
            if value:
                seen.setdefault(value.strip().lower(), []).append(p.url)
        for urls in seen.values():
            for u in urls[1:] if len(urls) > 1 else []:
                issues.append(Issue(check, WARNING, f"Same {label} as {urls[0]}.", u))

    # links
    checks_left = MAX_LINK_CHECKS
    for target, sources in sorted(links_from.items()):
        internal = _same_site(target, host)
        res = status_of.get(target)
        if res is None:
            if checks_left <= 0 or (not internal and not check_external) or _local(target) \
                    or urlparse(target).scheme not in ("http", "https"):
                continue
            checks_left -= 1
            res = fetch(target, transport, method="HEAD")
            if res.status in (403, 405, 501):  # some servers refuse HEAD
                res = fetch(target, transport)
            status_of[target] = res
        broken = bool(res.error) or res.status >= 400
        for src in sorted(sources)[:5]:
            if broken and internal:
                issues.append(Issue("broken_link", ERROR, f"Link to {target} is broken ({res.status or res.error}).", src))
            elif broken:
                issues.append(Issue("broken_external", WARNING,
                                    f"Link to {target} is broken ({res.status or res.error}).", src))
            elif internal and res.redirects:
                issues.append(Issue("link_redirect", NOTICE, f"Link to {target} redirects to {res.url}.", src))

    for url in broken_pages:
        if url not in links_from:  # from the sitemap or the extra pages
            for issue in check_page(url, status_of[url], None):
                issues.append(Issue(issue.check, issue.severity, f"{url}: {issue.message}"))

    total, categories, page_scores = score(issues, [p.url for p in pages])
    for p in pages:
        p.score = page_scores.get(p.url, 100)
        p.issues_count = sum(1 for i in issues if i.page_url == p.url)
    for i in issues:
        audit.issues.append(SeoIssue(page_url=i.page_url, check=i.check, category=i.category, severity=i.severity,
                                     message=i.message[:2000], tip=i.tip))
    audit.score = total if infos else 0
    audit.categories = categories
    audit.errors = sum(1 for i in issues if i.severity == ERROR)
    audit.warnings = sum(1 for i in issues if i.severity == WARNING)
    audit.notices = sum(1 for i in issues if i.severity == NOTICE)
    audit.status = "done"
    if not pages or not infos:
        first = status_of.get(start_url)
        audit.error = f"The first page did not open ({first.error or first.status})." if first and \
            (first.error or first.status >= 400) else ("No page could be read." if not infos else None)
    audit.finished_at = dt.datetime.now()
    db.commit()
