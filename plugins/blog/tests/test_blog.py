from __future__ import annotations

import datetime as dt
import json
import re

from sqlalchemy import select
from tungsten_blog import BlogAuthor, BlogCategory, BlogPost, BlogTag, analyze, html_to_markdown, preview_token, slugify

CONTENT = (
    "<p>FastAPI admin panels save weeks of work. This guide shows how a FastAPI admin panel works in 2026.</p>"
    "<h2>What is a FastAPI admin panel?</h2><p>It is a set of screens to manage your data.</p>"
    "<h2>How do I install it?</h2><ul><li>Run pip install</li><li>Add the panel</li></ul>"
    "<h3>Next steps</h3><p>Read the <a href=\"/docs\">docs</a> and <a href=\"https://fastapi.tiangolo.com\">FastAPI</a>.</p>"
    "<script>alert(1)</script>"
)


def make_post(panel, **kw):
    def run(db):
        author = BlogAuthor(name="Asha Rao", job_title="Python developer", bio="Builds admin panels.",
                            profiles=[{"url": "https://www.linkedin.com/in/asha"}])
        category = db.scalar(select(BlogCategory)) or BlogCategory(name="Guides", description="How-to guides.")
        tag = BlogTag(name="FastAPI")
        data = dict(
            title="FastAPI admin panel: a complete guide", content=CONTENT, status="published",
            excerpt="Everything about FastAPI admin panels.", summary="A FastAPI admin panel gives you screens "
            "to manage data. Tungsten builds one from your models in minutes, with forms, tables and roles.",
            key_points=[{"text": "Free and open source"}, {"text": "Works with SQLAlchemy"}, {"text": "Has roles"}],
            sources=[{"title": "FastAPI docs", "url": "https://fastapi.tiangolo.com"}],
            faqs=[{"question": "Is Tungsten free?", "answer": "Yes, it is MIT licensed."},
                  {"question": "Does it need React?", "answer": "No, it renders HTML on the server."}],
            howto_title="How to add Tungsten", howto_steps=[{"name": "Install", "text": "pip install tungsten-admin"},
                                                            {"name": "Mount", "text": "Call panel.mount(app)."}],
            focus_keyword="FastAPI admin panel", cover_image="https://cdn.test/cover.jpg", cover_alt="A dashboard",
            author=author, category=category, tags=[tag],
        )
        data.update(kw)
        post = BlogPost(**data)
        db.add(post)
        db.commit()
        return post.id, post.slug
    return panel.with_session(run)


def test_slugs_are_made_and_kept_unique(panel):
    _, first = make_post(panel)
    _, second = make_post(panel)
    assert first == "fastapi-admin-panel-a-complete-guide"
    assert second == "fastapi-admin-panel-a-complete-guide-2"
    assert slugify("Hello, World!  Again") == "hello-world-again"
    assert slugify("नमस्ते दुनिया") == "नमस्ते-दुनिया"


def test_publishing_fills_the_date(panel):
    post_id, _ = make_post(panel)
    post = panel.with_session(lambda db: db.get(BlogPost, post_id))
    assert post.published_at is not None and post.is_live


def test_blog_home_lists_live_posts_only(panel, client):
    make_post(panel, title="Live post")
    make_post(panel, title="Draft post", status="draft")
    make_post(panel, title="Future post", published_at=dt.datetime.now() + dt.timedelta(days=3))
    r = client.get("/blog")
    assert r.status_code == 200
    assert "Live post" in r.text
    assert "Draft post" not in r.text and "Future post" not in r.text
    assert '<link rel="canonical" href="https://acme.test/blog">' in r.text
    assert '"@type": "CollectionPage"' in r.text
    assert client.get("/blog/").status_code == 200


def test_post_page_has_seo_geo_aeo_markup(panel, client):
    _, slug = make_post(panel)
    r = client.get(f"/blog/{slug}")
    assert r.status_code == 200
    html = r.text
    assert "<title>FastAPI admin panel: a complete guide | Acme</title>" in html
    assert f'<link rel="canonical" href="https://acme.test/blog/{slug}">' in html
    assert '<meta property="og:type" content="article">' in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    assert f'<link rel="alternate" type="text/markdown" href="https://acme.test/blog/{slug}.md">' in html
    assert "<script>alert(1)</script>" not in html  # content is cleaned
    assert 'id="what-is-a-fastapi-admin-panel"' in html  # headings get anchors for the table of contents
    assert "Frequently asked questions" in html and "Key points" in html and "Sources" in html

    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL).group(1)
    graph = {node["@type"]: node for node in json.loads(raw)["@graph"]}
    assert set(graph) >= {"BlogPosting", "BreadcrumbList", "WebSite", "Organization", "Person", "FAQPage", "HowTo"}
    article = graph["BlogPosting"]
    assert article["author"] == {"@id": "https://acme.test/blog/author/asha-rao#person"}
    assert article["citation"][0]["url"] == "https://fastapi.tiangolo.com"
    assert article["abstract"].startswith("A FastAPI admin panel")
    assert graph["FAQPage"]["mainEntity"][0]["name"] == "Is Tungsten free?"
    assert len(graph["HowTo"]["step"]) == 2
    assert graph["Person"]["sameAs"] == ["https://www.linkedin.com/in/asha"]


def test_drafts_need_the_preview_link(panel, client):
    post_id, slug = make_post(panel, status="draft")
    assert client.get(f"/blog/{slug}").status_code == 404
    assert client.get(f"/blog/{slug}?preview=wrong").status_code == 404
    r = client.get(f"/blog/{slug}?preview={preview_token(panel.secret_key, post_id)}")
    assert r.status_code == 200
    assert '<meta name="robots" content="noindex, nofollow">' in r.text


def test_category_tag_and_author_pages(panel, client):
    make_post(panel)
    assert "Guides" in client.get("/blog/category/guides").text
    assert client.get("/blog/tag/fastapi").status_code == 200
    r = client.get("/blog/author/asha-rao")
    assert r.status_code == 200 and '"@type": "ProfilePage"' in r.text
    assert client.get("/blog/category/nope").status_code == 404


def test_search_and_pages(panel, client):
    for i in range(12):
        make_post(panel, title=f"Post number {i}")
    r = client.get("/blog")
    assert '<link rel="next" href="https://acme.test/blog?page=2">' in r.text
    assert client.get("/blog?page=2").status_code == 200
    assert client.get("/blog?page=9").status_code == 404
    r = client.get("/blog?q=number 11")
    assert "Post number 11" in r.text and "Post number 3" not in r.text
    assert 'content="noindex, follow"' in r.text


def test_machine_files(panel, client):
    _, slug = make_post(panel)
    make_post(panel, title="Hidden one", noindex=True)

    md = client.get(f"/blog/{slug}.md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.text.startswith("# FastAPI admin panel: a complete guide")
    assert "## Frequently asked questions" in md.text and "1. **Install**: pip install tungsten-admin" in md.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200 and f"<loc>https://acme.test/blog/{slug}</loc>" in sitemap.text
    assert "hidden-one" not in sitemap.text
    assert "https://acme.test/blog/category/guides" in sitemap.text

    feed = client.get("/blog/feed.xml")
    assert "<rss" in feed.text and "FastAPI admin panel: a complete guide" in feed.text

    robots = client.get("/robots.txt").text
    assert "User-agent: GPTBot\nAllow: /" in robots and "Disallow: /admin/" in robots
    assert "Sitemap: https://acme.test/sitemap.xml" in robots

    llms = client.get("/llms.txt").text
    assert llms.startswith("# Acme\n\n> Guides from Acme.")
    assert f"- [FastAPI admin panel: a complete guide](https://acme.test/blog/{slug}.md): A FastAPI admin" in llms
    assert "Hidden one" not in llms


def test_score_rewards_a_complete_post():
    empty = analyze({"title": "Hi"})
    assert empty.score < 30
    assert any(not c.ok and "summary" in c.tip.lower() for c in empty["geo"].checks)

    words = "</p><p>".join(["Tungsten makes a FastAPI admin panel in 5 minutes. " * 7] * 10)
    full = analyze({
        "title": "FastAPI admin panel: the complete 2026 guide",
        "meta_description": "Learn how to build a FastAPI admin panel with Tungsten: forms, tables, roles and charts "
                            "in minutes, with real code you can copy today.",
        "focus_keyword": "FastAPI admin panel",
        "content": f"<p>A FastAPI admin panel saves time.</p><h2>What is a FastAPI admin panel?</h2><p>{words}</p>"
                   "<h2>How to start?</h2><ul><li>One</li></ul><p><a href=\"/docs\">Docs</a> "
                   "<a href=\"https://fastapi.tiangolo.com\">FastAPI</a></p>",
        "cover_image": "x.jpg", "cover_alt": "Panel",
        "summary": "A FastAPI admin panel is a set of screens to manage your data. Tungsten builds one from your "
                   "SQLAlchemy models in minutes, with forms, tables and roles.",
        "key_points": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
        "sources": [{"url": "https://a.test"}, {"url": "https://b.test"}],
        "faqs": [{"question": f"Q{i}?", "answer": "Short answer."} for i in range(3)],
        "author_id": "1", "excerpt": "All about it.",
    })
    assert full["seo"].score >= 90 and full["geo"].score == 100 and full["aeo"].score == 100


def test_html_to_markdown():
    md = html_to_markdown("<h2>Title</h2><p>Some <strong>bold</strong> and <a href=\"/x\">link</a>.</p>"
                          "<ol><li>One</li><li>Two</li></ol>")
    assert md == "## Title\n\nSome **bold** and [link](/x).\n\n1. One\n2. Two"


def test_admin_screens(panel, admin):
    post_id, _ = make_post(panel)
    r = admin.get("/admin/blog-posts")
    assert r.status_code == 200 and "FastAPI admin panel: a complete guide" in r.text
    r = admin.get(f"/admin/blog-posts/{post_id}/edit")
    assert r.status_code == 200
    assert "SEO" in r.text and "GEO" in r.text and "AEO" in r.text and "Click a score to see tips" in r.text
    assert admin.get("/admin/blog-posts/create").status_code == 200
    for slug in ("blog-categories", "blog-tags", "blog-authors"):
        assert admin.get(f"/admin/{slug}").status_code == 200, slug
        assert admin.get(f"/admin/{slug}/create").status_code == 200, slug


def test_create_post_from_the_editor(panel, admin):
    tag_id = panel.with_session(lambda db: (db.add(t := BlogTag(name="News")), db.commit(), t.id)[2])
    admin.get("/admin/blog-posts/create")
    r = admin.post("/admin/blog-posts/create", {
        "title": "Hello world post", "status": "published", "content": "<p>Hi</p>", "tags": [str(tag_id)],
        "faqs.0.__row": "1", "faqs.0.question": "Why?", "faqs.0.answer": "Because.",
        "key_points.0.__row": "1", "key_points.0.text": "One point",
    })
    assert r.status_code == 204, r.text[:2000]
    post = panel.with_session(lambda db: db.scalar(select(BlogPost).where(BlogPost.title == "Hello world post")))
    assert post.slug == "hello-world-post" and post.published_at is not None
    assert post.faqs == [{"question": "Why?", "answer": "Because."}]
    assert post.key_points == [{"text": "One point"}]
    assert panel.with_session(lambda db: [t.name for t in db.get(BlogPost, post.id).tags]) == ["News"]
