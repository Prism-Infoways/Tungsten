from __future__ import annotations

from sqlalchemy import select
from tungsten_seo_audit import SeoAudit, SeoIssue, SeoPage, check_page, read_html
from tungsten_seo_audit.checks import check_robots, score
from tungsten_seo_audit.crawler import Response, fetch

from conftest import page

ACTION = "/admin/_tw/action"


def run(panel, url="https://site.test", max_pages=25, check_external=True):
    plugin = panel.get_plugin("seo-audit")
    with panel.db() as db:
        audit = plugin.start_audit(db, url, max_pages, check_external)
        return audit.id


def issues_of(panel, audit_id):
    with panel.db() as db:
        return [(i.check, i.severity, i.page_url) for i in
                db.scalars(select(SeoIssue).where(SeoIssue.audit_id == audit_id)).all()]


def checks(issues, url=None):
    return {c for c, _, p in issues if url is None or p == url}


def test_reads_html():
    info = read_html('<html lang="hi"><head><title> Hello\n world </title><meta name="Description" content="d">'
                     '<link rel="canonical" href="/x"><script type="application/ld+json">{"@graph": '
                     '[{"@type": "FAQPage"}]}</script><script type="application/ld+json">{bad</script></head>'
                     '<body><h1>A <b>b</b></h1><h2>c</h2><img src="1.png"><img src="2.png" alt="">'
                     '<a href="/y" rel="nofollow">y</a><script>var x = "no words here";</script>'
                     '<p>one two three</p></body></html>')
    assert info.lang == "hi" and info.title == "Hello world" and info.meta["description"] == "d"
    assert info.canonical == "/x" and info.h1 == ["A b"] and info.headings[1] == (2, "c")
    assert [i["alt"] for i in info.images] == [None, ""]
    assert info.links == [("/y", "nofollow")]
    assert info.json_ld == [{"@type": "FAQPage"}] and info.bad_json_ld == 1
    assert "no words" not in info.text and info.words == 7


def test_page_checks():
    html = "<html><head><title>Hi</title></head><body><h2>x</h2><h4>y</h4><img src=a></body></html>"
    res = Response("http://site.test/", 200, {"content-type": "text/html"}, html.encode(), elapsed_ms=4000)
    found = {(i.check, i.severity) for i in check_page("http://site.test/", res, read_html(html))}
    for check in ("title_short", "description_missing", "h1_missing", "heading_skip", "img_alt", "lang_missing",
                  "viewport_missing", "canonical_missing", "not_https", "schema_missing", "og_missing",
                  "twitter_missing", "slow", "thin_content"):
        assert check in {c for c, _ in found}, check
    assert ("h1_missing", "error") in found and ("slow", "warning") in found

    good = page("/", "Tungsten admin panels for FastAPI apps", "x" * 100, "<h1>T</h1>" + "<p>word</p>" * 400)
    res = Response("https://site.test/", 200, {"content-type": "text/html"}, good.encode())
    assert check_page("https://site.test/", res, read_html(good)) == []

    broken = check_page("https://site.test/x", Response("https://site.test/x", 500), None)
    assert [(i.check, i.severity) for i in broken] == [("http_error", "error")]
    noindex = Response("https://site.test/", 200, {"x-robots-tag": "noindex"}, good.encode())
    assert "noindex" in {i.check for i in check_page("https://site.test/", noindex, read_html(good))}


def test_robots_checks():
    def robots(text):
        return Response("https://s.test/robots.txt", 200, {"content-type": "text/plain"}, text.encode())

    issues, sitemaps = check_robots(robots("User-agent: *\nDisallow: /\n\nUser-agent: GPTBot\nDisallow: /\n"), "https://s.test")
    assert {i.check for i in issues} == {"robots_blocks_all", "ai_blocked", "robots_no_sitemap"}
    assert "GPTBot" in next(i.message for i in issues if i.check == "ai_blocked")
    issues, sitemaps = check_robots(robots("User-agent: *\nDisallow:\nSitemap: /map.xml"), "https://s.test")
    assert issues == [] and sitemaps == ["https://s.test/map.xml"]
    assert [i.check for i in check_robots(None, "https://s.test")[0]] == ["robots_missing"]


def test_score():
    from tungsten_seo_audit import Issue

    total, cats, pages = score([Issue("h1_missing", "error", "", "a"), Issue("img_alt", "warning", "", "b"),
                                Issue("sitemap_missing", "warning", "")], ["a", "b"])
    assert pages == {"a": 88, "b": 95}
    assert total == round((88 + 95) / 2 - 5)
    assert cats["Content"] == round((88 + 95) / 2) and cats["Technical"] == 95 and cats["Social"] == 100
    assert score([], [])[0] == 100


def test_fetch_keeps_redirects(site):
    res = fetch("https://site.test/old", site)
    assert res.status == 200 and res.url == "https://site.test/about"
    assert res.redirects == [("https://site.test/old", 301)]

    def boom(method, url, headers):
        raise OSError("Name or service not known")

    res = fetch("https://nope.test/", boom)
    assert res.status == 0 and "not known" in res.error


def test_full_audit(panel, site):
    audit_id = run(panel)
    with panel.db() as db:
        audit = db.get(SeoAudit, audit_id)
        pages = {p.url: p for p in db.scalars(select(SeoPage).where(SeoPage.audit_id == audit_id))}
        assert audit.status == "done" and audit.error is None
        assert set(pages) == {"https://site.test/", "https://site.test/about"}  # /private/ is blocked by robots.txt
        assert audit.pages_count == 2 and 0 < audit.score < 100
        assert set(audit.categories) >= {"Content", "Technical", "Links", "Social", "Speed", "AI search"}
        assert pages["https://site.test/"].score > pages["https://site.test/about"].score
        assert pages["https://site.test/"].h1 == "Home" and pages["https://site.test/"].words > 300

    issues = issues_of(panel, audit_id)
    assert checks(issues, "https://site.test/") == {"broken_link", "link_redirect"}
    assert ("broken_link", "error", "https://site.test/") in issues
    about = checks(issues, "https://site.test/about")
    assert {"title_short", "description_short", "h1_many", "heading_skip", "img_alt", "mixed_content",
            "thin_content"} <= about
    assert checks(issues, None) - about - checks(issues, "https://site.test/") == set()  # no site-wide issues
    assert ("GET", "https://site.test/private/x") not in site.calls
    assert ("HEAD", "https://other.test/x") in site.calls
    assert not any("127.0.0.1" in url for _, url in site.calls)
    with panel.db() as db:
        audit = db.get(SeoAudit, audit_id)
        assert audit.errors == sum(1 for _, s, _ in issues if s == "error")


def test_site_wide_issues(panel, site):
    for path in ("/robots.txt", "/sitemap.xml", "/llms.txt"):
        del site.pages["https://site.test" + path]
    site.add("http://site.test/", "plain")
    site.add("https://site.test/tungsten-seo-audit-check-404-page", "soft")
    site.pages["https://site.test/about"] = site.pages["https://site.test/"]
    audit_id = run(panel, check_external=False)
    issues = issues_of(panel, audit_id)
    site_wide = {c for c, _, p in issues if p is None}
    assert site_wide == {"robots_missing", "sitemap_missing", "llms_missing", "http_no_redirect", "soft_404"}
    assert {"title_duplicate", "description_duplicate"} <= checks(issues, "https://site.test/about")
    assert ("HEAD", "https://other.test/x") not in site.calls


def test_audit_follows_host_redirect_and_limits_pages(panel, site):
    site.redirect("https://www.site.test/", "https://site.test/")
    audit_id = run(panel, "www.site.test", max_pages=1)
    with panel.db() as db:
        audit = db.get(SeoAudit, audit_id)
        assert audit.url == "https://site.test/" and audit.pages_count == 1


def test_unreachable_site(panel):
    def boom(method, url, headers):
        raise OSError("Connection refused")

    panel.get_plugin("seo-audit").transport = boom
    audit_id = run(panel, "https://down.test")
    with panel.db() as db:
        audit = db.get(SeoAudit, audit_id)
        assert audit.status == "done" and audit.score == 0 and "Connection refused" in audit.error


def test_extra_urls_from_other_plugins(panel, site):
    class BlogLike:
        id = "blog-like"

        def seo_urls(self, db):
            return ["/blog/hello"]

    panel._plugins.append(BlogLike())
    site.add("https://site.test/blog/hello", page("/blog/hello", "Hello", "d", "<h1>Hello</h1>"))
    audit_id = run(panel)
    with panel.db() as db:
        urls = set(db.scalars(select(SeoPage.url).where(SeoPage.audit_id == audit_id)))
    assert "https://site.test/blog/hello" in urls


def test_screens(panel, admin, site):
    r = admin.get("/admin/seo-audits")
    assert r.status_code == 200 and "No audits yet" in r.text and "New audit" in r.text
    modal = admin.get(f"{ACTION}?_tw_host=resource:seo-audits&_tw_scope=page&_tw_name=audit")
    assert modal.status_code == 200 and "https://site.test" in modal.text
    r = admin.post(ACTION, {"_tw_host": "resource:seo-audits", "_tw_scope": "page", "_tw_name": "audit",
                            "url": "https://site.test", "max_pages": "10", "check_external": "1"})
    assert r.status_code in (200, 204)
    with panel.db() as db:
        audit = db.scalars(select(SeoAudit)).one()
    assert audit.status == "done" and f"/admin/seo-audits/{audit.id}" in r.headers.get("hx-redirect", "") + r.text

    view = admin.get(f"/admin/seo-audits/{audit.id}")
    assert view.status_code == 200 and f"{audit.score}/100" in view.text and "Score by area" in view.text
    assert "Issues" in view.text and "Pages" in view.text and "Fix or remove the link" in view.text

    index = admin.get("/admin/seo-audits")
    assert "SEO score" in index.text and "https://site.test/" in index.text
    assert admin.get("/admin/seo-audits/create").status_code == 404

    r = admin.post(ACTION, {"_tw_host": "resource:seo-audits", "_tw_scope": "page", "_tw_name": "rerun",
                            "_tw_record": str(audit.id)})
    with panel.db() as db:
        assert len(db.scalars(select(SeoAudit)).all()) == 2


def test_background_audit(panel, site):
    import time

    plugin = panel.get_plugin("seo-audit")
    plugin.background = True
    audit_id = run(panel)
    for _ in range(100):
        with panel.db() as db:
            if db.get(SeoAudit, audit_id).status != "running":
                break
        time.sleep(0.05)
    with panel.db() as db:
        assert db.get(SeoAudit, audit_id).status == "done"
