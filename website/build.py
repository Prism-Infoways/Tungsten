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
import textwrap
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

ROOT = Path(__file__).resolve().parent.parent
SITE = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
OUT = SITE / "_site"
REPO = "https://github.com/Prism-Infoways/Tungsten"

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
    ("Plugins", ["facebook-leads", "whatsapp", "mcp", "tickets"]),
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


def build(base_url: str = "") -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SITE / "static", OUT / "static")
    video = ROOT / "promo" / "promo.mp4"
    if video.exists():
        shutil.copy(video, OUT / "static" / "img" / "promo.mp4")

    env = Environment(loader=FileSystemLoader(SITE / "templates"), autoescape=True)
    env.globals.update(repo=REPO, nav=NAV, year=2026)
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
                       "description": meta.get("description", ""), "body": Markup(body), "toc": toc}

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
        out = tpl.render(page=page, pages=pages, section=section_of[slug], prev=prev_page, next=next_page,
                         root="../", edit_url=f"{REPO}/blob/HEAD/docs/{slug}.md")
        (docs_out / f"{slug}.html").write_text(out, encoding="utf-8")
        if slug == "introduction":
            (docs_out / "index.html").write_text(out, encoding="utf-8")
        search.append({"slug": slug, "title": page["title"], "section": section_of[slug],
                       "description": page["description"],
                       "headings": [[t["id"], t["name"]] for t in page["toc"]] +
                                   [[c["id"], c["name"]] for t in page["toc"] for c in t["children"]],
                       "text": plain(str(page["body"]))[:4000]})

    (OUT / "static" / "search-index.js").write_text(
        "window.TW_SEARCH = " + json.dumps(search, ensure_ascii=False) + ";\n", encoding="utf-8")
    (OUT / "index.html").write_text(env.get_template("home.html").render(root="", pages=pages), encoding="utf-8")
    (OUT / "404.html").write_text(env.get_template("404.html").render(root=base_url or "/"), encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    print(f"built {len(order)} doc pages into {OUT}")


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
