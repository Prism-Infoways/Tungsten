"""Blog plugin for Tungsten, built for SEO, GEO and AEO.

    from tungsten_blog import BlogPlugin

    panel.plugin(BlogPlugin(site_name="Acme", site_url="https://acme.com"))
    panel.create_tables(engine)   # also creates the blog tables
    panel.mount(app)              # adds /blog, /sitemap.xml, /robots.txt and /llms.txt to your app

Adds a "Blog" menu (posts, categories, tags, authors) with a live SEO / GEO / AEO
score in the post editor, and a public blog with meta tags, JSON-LD, a sitemap,
an RSS feed, llms.txt and a Markdown copy of every post.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tungsten import Plugin

from .markdown import html_to_markdown, post_markdown
from .models import BlogAuthor, BlogBase, BlogCategory, BlogPost, BlogTag
from .public import AI_CRAWLERS, PublicBlog, Site, live_filter, preview_token
from .resources import AuthorResource, CategoryResource, PostResource, TagResource
from .score import Report, analyze, analyze_post
from .text import slugify

__version__ = "0.1.0"


class BlogPlugin(Plugin):
    """``BlogPlugin(site_name=..., site_url=..., path="/blog", ...)``.

    * ``site_name``, ``description``, ``logo``, ``language``: used in titles, feeds and schema.org data.
    * ``site_url``: the public address, like ``https://acme.com``. Empty: the panel's ``app_url``,
      else the request's host.
    * ``path``: where the blog lives on your site (``"/blog"``).
    * ``site_files``: also serve ``/sitemap.xml``, ``/robots.txt`` and ``/llms.txt`` at the site root.
      Turn it off when your site has its own; the blog ones stay at ``/blog/sitemap.xml`` and ``/blog/llms.txt``.
    * ``ai_crawlers``: let AI crawlers (GPTBot, ClaudeBot, PerplexityBot ...) read the site. Needed for GEO.
    * ``same_as``: your organization's profile links (LinkedIn, X, YouTube ...).
    * ``nav_links``: ``[("Home", "/"), ("Pricing", "/pricing")]`` for the blog header.
    """

    id = "blog"
    metadata = BlogBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, site_name: str = "Blog", site_url: str | None = None, *, path: str = "/blog",
                 title: str = "Blog", description: str | None = None, logo: str | None = None,
                 language: str = "en", per_page: int = 10, site_files: bool = True, ai_crawlers: bool = True,
                 same_as: Iterable[str] = (), nav_links: Iterable[tuple[str, str]] = (), twitter: str | None = None,
                 accent: str = "#dc2626", llms_intro: str | None = None) -> None:
        self.site_name = site_name
        self.site_url = site_url.rstrip("/") if site_url else None
        self.path = "/" + path.strip("/") if path.strip("/") else ""
        self.title = title
        self.description = description
        self.logo = logo
        self.language = language
        self.per_page = per_page
        self.site_files = site_files
        self.ai_crawlers = ai_crawlers
        self.same_as = list(same_as)
        self.nav_links = list(nav_links)
        self.twitter = twitter
        self.accent = accent
        self.llms_intro = llms_intro
        self.panel: Any = None

    def register(self, panel: Any) -> None:
        self.panel = panel
        panel.resources([PostResource, CategoryResource, TagResource, AuthorResource])
        panel.navigation_group("Blog", icon="newspaper")

    def mount(self, app: Any, panel: Any) -> None:
        PublicBlog(self, panel).add_routes(app)


__all__ = [
    "AI_CRAWLERS", "AuthorResource", "BlogAuthor", "BlogBase", "BlogCategory", "BlogPlugin", "BlogPost", "BlogTag",
    "CategoryResource", "PostResource", "PublicBlog", "Report", "Site", "TagResource", "analyze", "analyze_post",
    "html_to_markdown", "live_filter", "post_markdown", "preview_token", "slugify",
]
