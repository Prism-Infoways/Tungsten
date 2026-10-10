"""Build the Tungsten website (landing page + docs) into website/_site.

    pip install -r website/requirements.txt
    python website/build.py            # build
    python website/build.py --serve    # build, then serve on http://127.0.0.1:8080

Docs are the Markdown files in /docs. Each starts with front matter
(title, description). The sidebar order is the NAV list below.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import textwrap
from datetime import date
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

from site_plugins import PLUGIN_FAQS, PLUGINS

ROOT = Path(__file__).resolve().parent.parent
SITE = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
OUT = SITE / "_site"
REPO = "https://github.com/Prism-Infoways/Tungsten"
SITE_URL = "https://tungsten.prisminfoways.com"
DESCRIPTION = ("Tungsten is a free, open source admin panel builder for FastAPI and SQLAlchemy. Describe forms and "
               "tables in Python classes and get a complete admin panel with search, filters, actions, charts, "
               "logins and roles.")

NAV = [
    ("Getting started", ["introduction", "installation", "quick-start", "demo-app"]),
    ("Panel", ["panel-configuration", "navigation", "theming"]),
    ("Resources", ["resources", "relation-managers", "infolists", "custom-pages"]),
    ("Forms", ["forms", "form-fields", "form-layouts"]),
    ("Tables", ["tables", "table-columns", "table-filters", "query-builder", "table-features"]),
    ("Actions & notifications", ["actions", "notifications"]),
    ("Widgets", ["widgets"]),
    ("Users & security", ["authentication", "email-verification", "roles-and-permissions", "security"]),
    ("More", ["import-export", "multi-tenancy", "translations", "async-database", "plugins-and-hooks", "cli"]),
    ("Plugins", ["leads", "facebook-leads", "whatsapp", "mcp", "tickets", "finance", "blog", "seo-audit", "security-audit"]),
]

# Answers shown on the home page and as FAQPage schema (answer engines and AI search quote these).
HOME_FAQS = [
    ("What is Tungsten?",
     "Tungsten is a free, open source admin panel builder for FastAPI. You describe resources, forms and tables in "
     "Python classes, and Tungsten builds a complete admin panel with search, filters, actions, charts, logins and roles."),
    ("Is Tungsten like Filament or Django admin?",
     "Yes. Tungsten brings the Filament way of building panels to Python. Like Django admin it builds screens from "
     "your models, but it works with FastAPI and SQLAlchemy and gives you far more control over forms, tables and dashboards."),
    ("How do I install Tungsten?",
     "Run pip install tungsten-admin, describe a resource for one of your SQLAlchemy models, mount the panel on your "
     "FastAPI app with panel.mount(app), and create a user with tungsten make:user. It needs Python 3.10 or newer."),
    ("Do I need to write HTML or JavaScript?",
     "No. Pages are rendered on the server with Jinja, made interactive with HTMX and Alpine.js, and styled with a "
     "prebuilt Tailwind CSS file. You only write Python, and there is no npm build step."),
    ("Does Tungsten work with async SQLAlchemy?",
     "Yes. Tungsten works with normal and async SQLAlchemy engines, and hooks can be async functions."),
    ("Is Tungsten free for commercial use?",
     "Yes. Tungsten and all its official plugins are MIT licensed, so you can use them in commercial projects for free."),
]

CALLOUT = re.compile(r"^> \[!(NOTE|TIP|WARNING)\]\s*\n((?:>.*\n?)*)", re.M)
CALLOUT_TITLES = {"NOTE": "Note", "TIP": "Tip", "WARNING": "Warning"}


def read_doc(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    if text.startswith("---"):
        _, head, text = text.split("---", 2)
        for line in head.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"')
    return meta, text.lstrip("\n")


def callouts(text: str) -> str:
    """GitHub style `> [!TIP]` blocks become styled boxes."""

    def repl(m: re.Match) -> str:
        kind = m.group(1)
        body = "\n".join(re.sub(r"^> ?", "", line) for line in m.group(2).splitlines())
        return (f'<div class="callout callout-{kind.lower()}" markdown="1">\n'
                f'<p class="callout-title">{CALLOUT_TITLES[kind]}</p>\n\n{body}\n\n</div>\n')

    return CALLOUT.sub(repl, text)


def doc_links(body: str, slugs: set[str]) -> str:
    """`[x](query-builder#y)` → `query-builder.html#y` so links work on any static host."""

    def repl(m: re.Match) -> str:
        target, anchor = m.group(1), m.group(2) or ""
        return f'href="{target}.html{anchor}"' if target in slugs else m.group(0)

    return re.sub(r'href="([a-z0-9-]+)(#[^"]*)?"', repl, body)


def plain(html_text: str) -> str:
    text = re.sub(r"<pre.*?</pre>", " ", html_text, flags=re.S)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()


def last_modified(*paths: Path) -> str:
    """Last commit date of the given files (YYYY-MM-DD), or today outside git."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", *map(str, paths)], cwd=ROOT,
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or date.today().isoformat()


def package_version(folder: Path) -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (folder / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


def faq_schema(faqs) -> dict:
    return {"@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs]}


def crumbs_schema(items) -> dict:
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i, "name": name, "item": url} for i, (name, url) in enumerate(items, 1)]}


ORG = {"@type": "Organization", "@id": f"{SITE_URL}/#org", "name": "Prism Infoways",
       "url": "https://prisminfoways.com", "logo": f"{SITE_URL}/static/img/favicon.svg", "sameAs": [REPO]}
APP = {"@type": "SoftwareApplication", "@id": f"{SITE_URL}/#software", "name": "Tungsten",
       "alternateName": "tungsten-admin", "applicationCategory": "DeveloperApplication",
       "applicationSubCategory": "Admin panel framework", "operatingSystem": "Linux, macOS, Windows",
       "programmingLanguage": "Python", "description": DESCRIPTION, "url": f"{SITE_URL}/",
       "downloadUrl": "https://pypi.org/project/tungsten-admin/", "codeRepository": REPO,
       "license": "https://opensource.org/licenses/MIT", "isAccessibleForFree": True,
       "image": f"{SITE_URL}/static/img/og-image.jpg", "screenshot": f"{SITE_URL}/static/img/dashboard.webp",
       "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
       "author": {"@id": f"{SITE_URL}/#org"}, "publisher": {"@id": f"{SITE_URL}/#org"}}


def graph(*nodes) -> dict:
    return {"@context": "https://schema.org", "@graph": list(nodes)}


def build(base_url: str = "") -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SITE / "static", OUT / "static")
    video = ROOT / "promo" / "promo.mp4"
    if video.exists():
        shutil.copy(video, OUT / "static" / "img" / "promo.mp4")

    env = Environment(loader=FileSystemLoader(SITE / "templates"), autoescape=True)
    plugins = [dict(p, version=package_version(ROOT / "plugins" / p["package"].removeprefix("tungsten-")))
               for p in PLUGINS]
    env.globals.update(repo=REPO, nav=NAV, year=2026, site_url=SITE_URL, plugins=plugins)
    env.filters["code"] = lambda src, lang="python": Markup(
        highlight(textwrap.dedent(str(src)).strip("\n"), get_lexer_by_name(lang), HtmlFormatter(cssclass="codehilite")))

    slugs = {s for _, items in NAV for s in items}
    pages: dict[str, dict] = {}
    for slug in slugs:
        path = DOCS / f"{slug}.md"
        if not path.exists():
            print(f"  missing doc: {slug}.md")
            continue
        meta, text = read_doc(path)
        md = markdown.Markdown(extensions=[
            "fenced_code", "tables", "md_in_html", "attr_list", "sane_lists",
            "codehilite", "toc",
        ], extension_configs={
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
            "toc": {"toc_depth": "2-3", "permalink": "#", "permalink_class": "anchor", "permalink_title": "Link to this section"},
        })
        body = doc_links(md.convert(callouts(text)), slugs)
        toc = [{"id": t["id"], "name": html.unescape(t["name"]),
                "children": [{"id": c["id"], "name": html.unescape(c["name"])} for c in t["children"]]}
               for t in md.toc_tokens]
        pages[slug] = {"slug": slug, "title": meta.get("title", slug.replace("-", " ").title()),
                       "description": meta.get("description", ""), "body": Markup(body), "toc": toc,
                       "markdown": text, "modified": last_modified(path)}

    order = [s for _, items in NAV for s in items if s in pages]
    section_of = {s: name for name, items in NAV for s in items}
    docs_out = OUT / "docs"
    docs_out.mkdir(parents=True)
    tpl = env.get_template("doc.html")
    search = []
    for i, slug in enumerate(order):
        page = pages[slug]
        prev_page = pages[order[i - 1]] if i else None
        next_page = pages[order[i + 1]] if i + 1 < len(order) else None
        url = f"{SITE_URL}/docs/{slug}.html"
        schema = graph(
            {"@type": "TechArticle", "headline": page["title"], "description": page["description"], "url": url,
             "mainEntityOfPage": url, "dateModified": page["modified"], "inLanguage": "en",
             "image": f"{SITE_URL}/static/img/og-image.jpg", "articleSection": section_of[slug],
             "author": {"@id": f"{SITE_URL}/#org"}, "publisher": {"@id": f"{SITE_URL}/#org"},
             "about": {"@id": f"{SITE_URL}/#software"}, "isPartOf": {"@type": "WebSite", "@id": f"{SITE_URL}/#site"}},
            crumbs_schema([("Home", f"{SITE_URL}/"), ("Docs", f"{SITE_URL}/docs/introduction.html"),
                           (page["title"], url)]),
            ORG)
        out = tpl.render(page=page, pages=pages, section=section_of[slug], prev=prev_page, next=next_page,
                         root="../", edit_url=f"{REPO}/blob/HEAD/docs/{slug}.md", canonical=url,
                         md_url=f"{SITE_URL}/docs/{slug}.md", og_type="article", schema=schema)
        (docs_out / f"{slug}.html").write_text(out, encoding="utf-8")
        (docs_out / f"{slug}.md").write_text(f"# {page['title']}\n\n> {page['description']}\n\n{page['markdown']}",
                                             encoding="utf-8")
        if slug == "introduction":
            (docs_out / "index.html").write_text(out, encoding="utf-8")
        search.append({"slug": slug, "title": page["title"], "section": section_of[slug],
                       "description": page["description"],
                       "headings": [[t["id"], t["name"]] for t in page["toc"]] +
                                   [[c["id"], c["name"]] for t in page["toc"] for c in t["children"]],
                       "text": plain(str(page["body"]))[:4000]})

    (OUT / "static" / "search-index.js").write_text(
        "window.TW_SEARCH = " + json.dumps(search, ensure_ascii=False) + ";\n", encoding="utf-8")
    home_schema = graph(
        {"@type": "WebSite", "@id": f"{SITE_URL}/#site", "name": "Tungsten", "url": f"{SITE_URL}/",
         "description": DESCRIPTION, "inLanguage": "en", "publisher": {"@id": f"{SITE_URL}/#org"}},
        ORG, APP, dict(faq_schema(HOME_FAQS), url=f"{SITE_URL}/#faq"))
    (OUT / "index.html").write_text(env.get_template("home.html").render(
        root="", pages=pages, faqs=HOME_FAQS, canonical=f"{SITE_URL}/", schema=home_schema), encoding="utf-8")
    (OUT / "404.html").write_text(env.get_template("404.html").render(root=base_url or "/", noindex=True),
                                  encoding="utf-8")

    # plugin pages
    plugins_out = OUT / "plugins"
    plugins_out.mkdir()
    index_url = f"{SITE_URL}/plugins/"
    index_schema = graph(
        {"@type": "CollectionPage", "name": "Tungsten plugins", "url": index_url, "isPartOf": {"@id": f"{SITE_URL}/#site"},
         "mainEntity": {"@type": "ItemList", "itemListElement": [
             {"@type": "ListItem", "position": i, "url": f"{SITE_URL}/plugins/{p['slug']}.html", "name": p["name"]}
             for i, p in enumerate(plugins, 1)]}},
        crumbs_schema([("Home", f"{SITE_URL}/"), ("Plugins", index_url)]),
        faq_schema(PLUGIN_FAQS))
    (plugins_out / "index.html").write_text(env.get_template("plugins.html").render(
        root="../", faqs=PLUGIN_FAQS, canonical=index_url, schema=index_schema),
        encoding="utf-8")
    tpl = env.get_template("plugin.html")
    for p in plugins:
        url = f"{SITE_URL}/plugins/{p['slug']}.html"
        related = [o for o in plugins if o is not p and o["category"] == p["category"]]
        related += [o for o in plugins if o is not p and o not in related]
        schema = graph(
            {"@type": "SoftwareApplication", "name": f"{p['package']}", "alternateName": p["name"],
             "description": p["summary"], "url": url, "applicationCategory": "DeveloperApplication",
             "applicationSubCategory": "Tungsten plugin", "operatingSystem": "Linux, macOS, Windows",
             "programmingLanguage": "Python", "softwareVersion": p["version"],
             "downloadUrl": f"https://pypi.org/project/{p['package']}/",
             "codeRepository": f"{REPO}/tree/HEAD/plugins/{p['package'].removeprefix('tungsten-')}",
             "license": "https://opensource.org/licenses/MIT", "isAccessibleForFree": True,
             "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
             "featureList": [f"{t}: {d}" for t, d in p["features"]],
             "softwareRequirements": ", ".join(["tungsten-admin", *p["needs"]]),
             "isPartOf": {"@id": f"{SITE_URL}/#software"}, "author": {"@id": f"{SITE_URL}/#org"}},
            {"@type": "WebPage", "url": url, "name": f"{p['name']} plugin for Tungsten",
             "speakable": {"@type": "SpeakableSpecification", "cssSelector": [".speakable"]}},
            crumbs_schema([("Home", f"{SITE_URL}/"), ("Plugins", index_url), (p["name"], url)]),
            faq_schema(p["faqs"]), ORG)
        (plugins_out / f"{p['slug']}.html").write_text(tpl.render(
            root="../", p=p, faqs=p["faqs"], related=related[:3], canonical=url, schema=schema), encoding="utf-8")

    site_files(pages, order, plugins)
    print(f"built {len(order)} doc pages into {OUT}")


def site_files(pages: dict, order: list[str], plugins: list[dict]) -> None:
    """sitemap.xml, robots.txt, llms.txt, llms-full.txt and .htaccess."""
    site_mod = last_modified(SITE, DOCS)
    urls = [(f"{SITE_URL}/", site_mod, "1.0"), (f"{SITE_URL}/plugins/", last_modified(SITE / "site_plugins.py"), "0.9")]
    urls += [(f"{SITE_URL}/plugins/{p['slug']}.html", last_modified(SITE / "site_plugins.py"), "0.8") for p in plugins]
    urls += [(f"{SITE_URL}/docs/{s}.html", pages[s]["modified"], "0.7") for s in order]
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc><lastmod>{m}</lastmod><priority>{p}</priority></url>\n" for u, m, p in urls)
        + "</urlset>\n", encoding="utf-8")

    ai_bots = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "Claude-SearchBot",
               "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "Bingbot", "CCBot"]
    (OUT / "robots.txt").write_text(
        "# Search engines and AI assistants are welcome to read and quote these docs.\n"
        "User-agent: *\nAllow: /\nDisallow: /cgi-bin/\n\n"
        + "".join(f"User-agent: {b}\n" for b in ai_bots) + "Allow: /\n\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")

    lines = [f"# Tungsten", "", f"> {DESCRIPTION}", "",
             "Install with `pip install tungsten-admin` (Python 3.10+). MIT licensed, made by Prism Infoways. "
             f"Source: {REPO}. Each docs page below also has a Markdown copy at the same address ending in .md.", ""]
    for name, slugs in NAV:
        items = [s for s in slugs if s in pages]
        if items:
            lines += [f"## {name}", ""]
            lines += [f"- [{pages[s]['title']}]({SITE_URL}/docs/{s}.md): {pages[s]['description']}" for s in items]
            lines.append("")
    lines += ["## Plugin pages", ""]
    lines += [f"- [{p['name']} ({p['package']})]({SITE_URL}/plugins/{p['slug']}.html): {p['summary']}" for p in plugins]
    lines += ["", "## Optional", "", f"- [Full docs in one file]({SITE_URL}/llms-full.txt)",
              "- [PyPI package](https://pypi.org/project/tungsten-admin/)", f"- [GitHub]({REPO})", ""]
    (OUT / "llms.txt").write_text("\n".join(lines), encoding="utf-8")

    full = [f"# Tungsten documentation\n\n> {DESCRIPTION}\n"]
    full += [f"\n\n---\n\n# {pages[s]['title']}\n\nSource: {SITE_URL}/docs/{s}.html\n\n{pages[s]['markdown']}"
             for s in order]
    full += ["\n\n---\n\n# Plugins\n"]
    full += [f"\n## {p['name']} (`pip install {p['package']}`)\n\n{p['summary']}\n\n"
             + "".join(f"- **{t}**: {d}\n" for t, d in p["features"])
             + "".join(f"\n**{q}** {a}\n" for q, a in p["faqs"]) for p in plugins]
    (OUT / "llms-full.txt").write_text("".join(full), encoding="utf-8")

    (OUT / ".htaccess").write_text("""# Apache / LiteSpeed: https only, one host, real 404s, caching and compression.
Options -Indexes
ErrorDocument 404 /404.html
DirectoryIndex index.html

<IfModule mod_rewrite.c>
RewriteEngine On
RewriteCond %{HTTPS} !=on
RewriteCond %{HTTP:X-Forwarded-Proto} !=https
RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [L,R=301]
RewriteCond %{HTTP_HOST} ^www\\.(.+)$ [NC]
RewriteRule ^ https://%1%{REQUEST_URI} [L,R=301]
</IfModule>

<IfModule mod_headers.c>
Header always set Strict-Transport-Security "max-age=31536000"
Header always set X-Content-Type-Options "nosniff"
Header always set Referrer-Policy "strict-origin-when-cross-origin"
Header always set X-Frame-Options "SAMEORIGIN"
<FilesMatch "\\.(md|txt)$">
Header set Content-Type "text/plain; charset=utf-8"
</FilesMatch>
</IfModule>

<IfModule mod_deflate.c>
AddOutputFilterByType DEFLATE text/html text/css text/plain text/xml application/javascript application/xml image/svg+xml
</IfModule>

<IfModule mod_expires.c>
ExpiresActive On
ExpiresByType text/html "access plus 0 seconds"
ExpiresByType text/css "access plus 7 days"
ExpiresByType application/javascript "access plus 7 days"
ExpiresByType image/webp "access plus 30 days"
ExpiresByType image/jpeg "access plus 30 days"
ExpiresByType image/svg+xml "access plus 30 days"
ExpiresByType video/mp4 "access plus 30 days"
</IfModule>
""", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--base-url", default="", help="site root for the 404 page, e.g. /Tungsten/")
    args = ap.parse_args()
    build(args.base_url)
    if args.serve:
        import functools
        import http.server

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        print("serving on http://127.0.0.1:8080")
        http.server.ThreadingHTTPServer(("127.0.0.1", 8080), handler).serve_forever()
