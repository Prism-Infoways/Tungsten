"""The public blog: list and post pages, feeds, sitemap, robots.txt and llms.txt."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import math
from typing import Any
from urllib.parse import urlencode, urlparse
from xml.sax.saxutils import escape as xml_escape

from fastapi import Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from tungsten.support.html import sanitize

from . import schema
from .markdown import post_markdown
from .models import BlogAuthor, BlogCategory, BlogPost, BlogTag
from .text import items, reading_minutes, shorten, strip_tags, with_heading_ids

#: AI crawlers named in robots.txt, so it is clear they are welcome (or not, with ``ai_crawlers=False``)
AI_CRAWLERS = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User",
               "PerplexityBot", "Google-Extended", "Applebot-Extended", "CCBot", "Bingbot")


def live_filter(query: Any) -> Any:
    now = dt.datetime.now()
    return query.where(BlogPost.status == "published",
                       or_(BlogPost.published_at.is_(None), BlogPost.published_at <= now))


def preview_token(secret: str, post_id: Any) -> str:
    return hmac.new(secret.encode(), f"tungsten-blog-preview:{post_id}".encode(), hashlib.sha256).hexdigest()[:32]


class Site:
    """Everything a page needs to build absolute links: the site, the blog path, the storage."""

    def __init__(self, plugin: Any, panel: Any, request: Request | None) -> None:
        self.plugin = plugin
        self.panel = panel
        base = plugin.site_url or panel.app_url
        if not base and request is not None:
            base = f"{request.url.scheme}://{request.url.netloc}"
        self.url = (base or "").rstrip("/")
        self.host = urlparse(self.url).netloc or None
        self.name = plugin.site_name
        self.title = plugin.title
        self.description = plugin.description
        self.language = plugin.language
        self.same_as = plugin.same_as
        self.accent = plugin.accent
        self.nav_links = plugin.nav_links
        self.twitter = plugin.twitter
        self.logo = self.media_url(plugin.logo) if plugin.logo else None
        self.blog_url = f"{self.url}{plugin.path}"

    def media_url(self, path: Any) -> str | None:
        if not path:
            return None
        url = self.panel.storage.url(str(path))
        return f"{self.url}{url}" if url.startswith("/") else url

    def post_url(self, post: Any) -> str:
        return f"{self.blog_url}/{post.slug}"

    def category_url(self, category: Any) -> str:
        return f"{self.blog_url}/category/{category.slug}"

    def tag_url(self, tag: Any) -> str:
        return f"{self.blog_url}/tag/{tag.slug}"

    def author_url(self, author: Any) -> str:
        return f"{self.blog_url}/author/{author.slug}"


def _xml(body: str, media_type: str = "application/xml") -> Response:
    return Response(body, media_type=f"{media_type}; charset=utf-8")


class PublicBlog:
    def __init__(self, plugin: Any, panel: Any) -> None:
        self.plugin = plugin
        self.panel = panel

    # ------------------------------------------------------------------ helpers
    async def _db(self, fn: Any) -> Any:
        return await run_in_threadpool(self.panel.with_session, fn)

    def render(self, name: str, status_code: int = 200, **context: Any) -> HTMLResponse:
        html = self.panel.renderer.render(name, blog=self.plugin, **context)
        return HTMLResponse(html, status_code=status_code)

    def not_found(self, site: Site) -> HTMLResponse:
        return self.render("tungsten_blog/public/not_found.html", status_code=404, site=site,
                           meta={"title": f"Page not found | {site.name}", "robots": "noindex, follow",
                                 "canonical": None})

    def _posts_query(self) -> Any:
        return live_filter(select(BlogPost)).options(
            selectinload(BlogPost.author), selectinload(BlogPost.category), selectinload(BlogPost.tags))

    def _page(self, db: Any, query: Any, page: int) -> tuple[list, int]:
        per_page = self.plugin.per_page
        total = db.scalar(select(func.count()).select_from(
            query.with_only_columns(BlogPost.id).order_by(None).subquery())) or 0
        pages = max(1, math.ceil(total / per_page))
        posts = db.scalars(query.order_by(BlogPost.published_at.desc(), BlogPost.id.desc())
                           .offset((page - 1) * per_page).limit(per_page)).all()
        return list(posts), pages

    def _categories(self, db: Any) -> list:
        used = live_filter(select(BlogPost.category_id)).where(BlogPost.category_id.isnot(None))
        return list(db.scalars(select(BlogCategory).where(BlogCategory.id.in_(used))
                               .order_by(BlogCategory.sort, BlogCategory.name)).all())

    def _list(self, request: Request, site: Site, db: Any, query: Any, *, heading: str, url: str,
              intro: str | None = None, crumbs: list[tuple[str, str]], meta_title: str | None = None,
              meta_description: str | None = None, extra_graph: list | None = None, kind: str = "index",
              author: Any = None) -> HTMLResponse:
        try:
            page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            page = 1
        search = (request.query_params.get("q") or "").strip()[:100]
        if search:
            like = f"%{search}%"
            query = query.where(or_(BlogPost.title.ilike(like), BlogPost.excerpt.ilike(like),
                                    BlogPost.content.ilike(like)))
        posts, pages = self._page(db, query, page)
        if page > pages:
            return self.not_found(site)

        def page_url(n: int) -> str:
            params = {**({"q": search} if search else {}), **({"page": n} if n > 1 else {})}
            return f"{url}?{urlencode(params)}" if params else url

        description = meta_description or (strip_tags(intro) if intro else None) or site.description
        graph = schema.list_graph(site, heading, page_url(page), posts, crumbs, description) + (extra_graph or [])
        title = meta_title or heading
        if page > 1:
            title = f"{title} (page {page})"
        meta = {
            "title": f"{title} | {site.name}" if site.name and site.name not in title else title,
            "description": shorten(description, 160) if description else None,
            "canonical": page_url(page),
            # search results pages are thin and endless: keep them out of the index
            "robots": "noindex, follow" if search else "index, follow, max-image-preview:large",
            "prev": page_url(page - 1) if page > 1 else None,
            "next": page_url(page + 1) if page < pages else None,
            "type": "website",
            "image": site.logo,
        }
        featured = posts[0] if posts and page == 1 and not search and kind == "index" else None
        return self.render("tungsten_blog/public/index.html", site=site, meta=meta, posts=posts, page=page,
                           pages=pages, page_url=page_url, heading=heading, intro=intro, crumbs=crumbs,
                           categories=self._categories(db), search=search, featured=featured, kind=kind,
                           author=author, jsonld=schema.to_script(graph), reading_minutes=reading_minutes)

    # ------------------------------------------------------------------ pages
    async def index(self, request: Request) -> Response:
        def run(db):
            site = Site(self.plugin, self.panel, request)
            return self._list(request, site, db, self._posts_query(), heading=site.title, url=site.blog_url,
                              intro=site.description, crumbs=[(site.name, f"{site.url}/"), (site.title, site.blog_url)])
        return await self._db(run)

    async def category(self, request: Request, slug: str) -> Response:
        def run(db):
            site = Site(self.plugin, self.panel, request)
            category = db.scalar(select(BlogCategory).where(BlogCategory.slug == slug))
            if category is None:
                return self.not_found(site)
            url = site.category_url(category)
            return self._list(request, site, db, self._posts_query().where(BlogPost.category_id == category.id),
                              heading=category.name, url=url, intro=category.description, kind="category",
                              meta_title=category.meta_title, meta_description=category.meta_description,
                              crumbs=[(site.name, f"{site.url}/"), (site.title, site.blog_url), (category.name, url)])
        return await self._db(run)

    async def tag(self, request: Request, slug: str) -> Response:
        def run(db):
            site = Site(self.plugin, self.panel, request)
            tag = db.scalar(select(BlogTag).where(BlogTag.slug == slug))
            if tag is None:
                return self.not_found(site)
            url = site.tag_url(tag)
            query = self._posts_query().where(BlogPost.tags.any(BlogTag.id == tag.id))
            return self._list(request, site, db, query, heading=f"Posts tagged “{tag.name}”", url=url, kind="tag",
                              crumbs=[(site.name, f"{site.url}/"), (site.title, site.blog_url), (tag.name, url)])
        return await self._db(run)

    async def author(self, request: Request, slug: str) -> Response:
        def run(db):
            site = Site(self.plugin, self.panel, request)
            author = db.scalar(select(BlogAuthor).where(BlogAuthor.slug == slug))
            if author is None:
                return self.not_found(site)
            url = site.author_url(author)
            profile = {"@type": "ProfilePage", "@id": f"{url}#profile", "url": url,
                       "mainEntity": schema.person(site, author)}
            return self._list(request, site, db, self._posts_query().where(BlogPost.author_id == author.id),
                              heading=author.name, url=url, intro=author.bio, kind="author", author=author,
                              meta_title=f"{author.name}, author at {site.name}", extra_graph=[profile],
                              crumbs=[(site.name, f"{site.url}/"), (site.title, site.blog_url), (author.name, url)])
        return await self._db(run)

    def _find_post(self, db: Any, request: Request, slug: str) -> tuple[Any, bool]:
        post = db.scalar(select(BlogPost).where(BlogPost.slug == slug).options(
            selectinload(BlogPost.author), selectinload(BlogPost.category), selectinload(BlogPost.tags)))
        if post is None:
            return None, False
        token = request.query_params.get("preview")
        if token and hmac.compare_digest(token, preview_token(self.panel.secret_key, post.id)):
            return post, True
        return (post, False) if post.is_live else (None, False)

    async def post(self, request: Request, slug: str) -> Response:
        def run(db):
            site = Site(self.plugin, self.panel, request)
            post, preview = self._find_post(db, request, slug)
            if post is None:
                return self.not_found(site)
            url = site.post_url(post)
            crumbs = [(site.name, f"{site.url}/"), (site.title, site.blog_url)]
            if post.category is not None:
                crumbs.append((post.category.name, site.category_url(post.category)))
            crumbs.append((post.title, url))
            content, toc = with_heading_ids(sanitize(post.content or ""))
            related: list = []
            if post.category_id:
                related = list(db.scalars(self._posts_query().where(
                    BlogPost.category_id == post.category_id, BlogPost.id != post.id)
                    .order_by(BlogPost.published_at.desc()).limit(3)).all())
            description = post.meta_description or post.excerpt or post.summary or strip_tags(post.content)
            meta = {
                "title": post.meta_title or f"{post.title} | {site.name}",
                "description": shorten(strip_tags(description), 160),
                "canonical": post.canonical_url or url,
                "robots": "noindex, nofollow" if (post.noindex or preview)
                else "index, follow, max-image-preview:large, max-snippet:-1",
                "type": "article",
                "image": site.media_url(post.og_image or post.cover_image) or site.logo,
                "image_alt": post.cover_alt,
                "published": post.published_at,
                "modified": post.updated_at,
                "author": post.author.name if post.author else None,
                "section": post.category.name if post.category else None,
                "tags": [t.name for t in post.tags],
                "markdown": f"{url}.md",
            }
            graph = schema.post_graph(site, post, url, crumbs)
            return self.render(
                "tungsten_blog/public/post.html", site=site, meta=meta, post=post, content=content, toc=toc,
                crumbs=crumbs, related=related, preview=preview, jsonld=schema.to_script(graph),
                key_points=items(post.key_points, "text"), sources=items(post.sources, "url"),
                faqs=items(post.faqs, "question", "answer"), steps=items(post.howto_steps, "text"),
                minutes=reading_minutes(post.content), reading_minutes=reading_minutes,
                show_updated=bool(post.published_at and post.updated_at
                                  and post.updated_at.date() > post.published_at.date()))
        return await self._db(run)

    async def post_md(self, request: Request, slug: str) -> Response:
        def run(db):
            site = Site(self.plugin, self.panel, request)
            post, _ = self._find_post(db, request, slug)
            if post is None or post.noindex:
                return PlainTextResponse("Not found", status_code=404)
            return PlainTextResponse(post_markdown(site, post), media_type="text/markdown; charset=utf-8",
                                     headers={"Link": f'<{site.post_url(post)}>; rel="canonical"'})
        return await self._db(run)

    # ------------------------------------------------------------------ machine files
    async def feed(self, request: Request) -> Response:
        def run(db):
            site = Site(self.plugin, self.panel, request)
            posts = db.scalars(self._posts_query().order_by(BlogPost.published_at.desc()).limit(30)).all()
            out = ['<?xml version="1.0" encoding="UTF-8"?>',
                   '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/">', "<channel>",
                   f"<title>{xml_escape(f'{site.title} | {site.name}')}</title>",
                   f"<link>{xml_escape(site.blog_url)}</link>",
                   f'<atom:link href="{xml_escape(site.blog_url)}/feed.xml" rel="self" type="application/rss+xml"/>',
                   f"<description>{xml_escape(site.description or site.title)}</description>",
                   f"<language>{xml_escape(site.language)}</language>"]
            for post in posts:
                summary = post.excerpt or post.summary or shorten(strip_tags(post.content), 300)
                out += ["<item>", f"<title>{xml_escape(post.title)}</title>",
                        f"<link>{xml_escape(site.post_url(post))}</link>",
                        f'<guid isPermaLink="true">{xml_escape(site.post_url(post))}</guid>',
                        f"<description>{xml_escape(strip_tags(summary))}</description>"]
                if post.published_at:
                    out.append(f"<pubDate>{post.published_at.strftime('%a, %d %b %Y %H:%M:%S')} +0000</pubDate>")
                if post.author:
                    out.append(f"<dc:creator>{xml_escape(post.author.name)}</dc:creator>")
                if post.category:
                    out.append(f"<category>{xml_escape(post.category.name)}</category>")
                out.append("</item>")
            out += ["</channel>", "</rss>"]
            return _xml("\n".join(out), "application/rss+xml")
        return await self._db(run)

    def _sitemap_urls(self, db: Any, site: Site) -> list[tuple[str, Any]]:
        posts = db.scalars(live_filter(select(BlogPost)).where(BlogPost.noindex.is_(False))
                           .order_by(BlogPost.published_at.desc())).all()
        newest = max((p.updated_at or p.published_at for p in posts), default=None)
        urls: list[tuple[str, Any]] = [(site.blog_url, newest)]
        urls += [(site.post_url(p), p.updated_at or p.published_at) for p in posts if not p.canonical_url
                 or p.canonical_url.rstrip("/") == site.post_url(p)]
        for category in self._categories(db):
            urls.append((site.category_url(category), None))
        authors = db.scalars(select(BlogAuthor).where(BlogAuthor.id.in_(
            live_filter(select(BlogPost.author_id)).where(BlogPost.author_id.isnot(None))))).all()
        urls += [(site.author_url(a), None) for a in authors]
        tags = db.scalars(select(BlogTag).where(BlogTag.posts.any(BlogPost.id.in_(
            live_filter(select(BlogPost.id)))))).all()
        urls += [(site.tag_url(t), None) for t in tags]
        return urls

    async def sitemap(self, request: Request) -> Response:
        def run(db):
            site = Site(self.plugin, self.panel, request)
            out = ['<?xml version="1.0" encoding="UTF-8"?>',
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
            for url, lastmod in self._sitemap_urls(db, site):
                out.append(f"<url><loc>{xml_escape(url)}</loc>"
                           + (f"<lastmod>{lastmod:%Y-%m-%d}</lastmod>" if lastmod else "") + "</url>")
            out.append("</urlset>")
            return _xml("\n".join(out))
        return await self._db(run)

    async def robots(self, request: Request) -> Response:
        site = Site(self.plugin, self.panel, request)
        lines = ["User-agent: *", "Allow: /"]
        if self.panel.path:
            lines.append(f"Disallow: {self.panel.path}/")
        lines.append("")
        for bot in AI_CRAWLERS:
            if bot == "Bingbot":
                continue
            lines += [f"User-agent: {bot}", "Allow: /" if self.plugin.ai_crawlers else "Disallow: /"]
            if self.plugin.ai_crawlers and self.panel.path:
                lines.append(f"Disallow: {self.panel.path}/")
            lines.append("")
        lines.append(f"Sitemap: {site.url}/sitemap.xml" if self.plugin.site_files
                     else f"Sitemap: {site.blog_url}/sitemap.xml")
        return PlainTextResponse("\n".join(lines) + "\n")

    async def llms(self, request: Request) -> Response:
        """``/llms.txt`` (https://llmstxt.org): a map of the site for AI tools, linking each post's Markdown."""
        def run(db):
            site = Site(self.plugin, self.panel, request)
            posts = db.scalars(self._posts_query().where(BlogPost.noindex.is_(False))
                               .order_by(BlogPost.published_at.desc()).limit(200)).all()
            lines = [f"# {site.name}", ""]
            if site.description:
                lines += [f"> {strip_tags(site.description)}", ""]
            if self.plugin.llms_intro:
                lines += [self.plugin.llms_intro.strip(), ""]
            groups: dict[str, list] = {}
            for post in posts:
                groups.setdefault(post.category.name if post.category else site.title, []).append(post)
            for name, group in groups.items():
                lines += [f"## {name}", ""]
                for post in group:
                    note = strip_tags(post.summary or post.excerpt or post.meta_description or "")
                    lines.append(f"- [{post.title}]({site.post_url(post)}.md)" + (f": {shorten(note, 200)}"
                                                                                    if note else ""))
                lines.append("")
            lines += ["## Optional", "", f"- [Blog home]({site.blog_url})", f"- [RSS feed]({site.blog_url}/feed.xml)",
                      f"- [Sitemap]({site.blog_url}/sitemap.xml)", ""]
            return PlainTextResponse("\n".join(lines), media_type="text/plain; charset=utf-8")
        return await self._db(run)

    # ------------------------------------------------------------------ routes
    def add_routes(self, app: Any) -> None:
        path = self.plugin.path
        if self.plugin.site_files:
            app.add_api_route("/sitemap.xml", self.sitemap, methods=["GET"], include_in_schema=False)
            app.add_api_route("/robots.txt", self.robots, methods=["GET"], include_in_schema=False)
            app.add_api_route("/llms.txt", self.llms, methods=["GET"], include_in_schema=False)
        routes = [
            (path or "/", self.index), (f"{path}/feed.xml", self.feed), (f"{path}/sitemap.xml", self.sitemap),
            (f"{path}/llms.txt", self.llms), (f"{path}/category/{{slug}}", self.category),
            (f"{path}/tag/{{slug}}", self.tag), (f"{path}/author/{{slug}}", self.author),
            (f"{path}/{{slug}}.md", self.post_md), (f"{path}/{{slug}}", self.post),
        ]
        if path:
            routes.insert(1, (f"{path}/", self.index))
        for route, endpoint in routes:
            app.add_api_route(route, endpoint, methods=["GET"], include_in_schema=False,
                              response_class=HTMLResponse)
