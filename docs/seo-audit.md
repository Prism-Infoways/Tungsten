---
title: SEO audit
description: Check your website for SEO problems from the panel, with a score from 0 to 100, a fix tip for each issue, AI search checks and a history of audits.
---

The `tungsten-seo-audit` plugin adds an **SEO audits** screen to your panel. Type your site's address and press **Start audit**. It opens your pages like a search engine does, and gives you:

- a **score** from 0 to 100, and a score for each area (Content, Technical, Links, Social, Speed, AI search),
- a list of **issues**, each marked Error, Warning or Notice, with a short **tip** to fix it,
- a **pages** table with each page's score, status, word count, load time and size,
- a **history** of audits, with the score trend on top, so you can see your fixes working.

## Install

```bash
pip install tungsten-seo-audit
```

```python
from tungsten_seo_audit import SeoAuditPlugin

panel.plugin(SeoAuditPlugin(site_url="https://www.example.com"))
panel.create_tables(engine)
```

This adds **SEO audits** under the **SEO** group. It needs `tungsten-admin` 0.1.4 or newer.

## Run an audit

1. Open **SEO audits** and press **New audit**.
2. Check the **Site address**. It starts with `site_url`, or the panel's `app_url`.
3. Pick how many **pages to check** (25 by default, up to 500), and whether to check links to other sites.
4. Press **Start audit**.

The audit runs in the background, so you can leave the page. The list refreshes by itself, and the report fills in as pages are checked. Press **Run again** on an old audit to check the same site again. The old one stays in the history.

The audit starts at the address you typed, reads `robots.txt` and `sitemap.xml`, and follows the links on each page. It stays on the same site and skips pages that `robots.txt` blocks. If your address moves to another one (like `example.com` to `www.example.com`), the audit follows it.

## What it checks

| Area | Checks |
| --- | --- |
| Content | Title missing, too short (under 30) or too long (over 60). Meta description missing, short (under 70) or long (over 160). Duplicate titles and descriptions. No H1 or more than one. Skipped heading levels. Thin pages (under 300 words). Images without alt text. No `lang` on `<html>`. |
| Technical | Pages that answer 4xx or 5xx, or don't open. Redirect chains. Canonical missing, relative, or pointing to another page. `noindex` (meta tag or `X-Robots-Tag`). No mobile viewport. No HTTPS, or http:// that doesn't move to https://. Mixed content. Structured data missing or broken. `robots.txt` missing or blocking the whole site. `sitemap.xml` missing or broken. Missing pages that answer 200 instead of 404. |
| Links | Broken links inside the site (error) and to other sites (warning). Links that go through a redirect. |
| Social | Open Graph `og:title`, `og:description`, `og:image`, and `twitter:card`. |
| Speed | Load time over 1.5 s (notice) or 3 s (warning). HTML over 500 KB. More than 15 script files. Images without width and height. |
| AI search | AI crawlers (GPTBot, ClaudeBot, PerplexityBot...) blocked in `robots.txt`. No `/llms.txt`. No FAQ structured data on any page. |

Links to `localhost` and `127.0.0.1` are skipped, since docs often show them on purpose.

## How the score works

Every page starts at 100. Each issue on it takes points off: **12** for an error, **5** for a warning, **1** for a notice. The site's score is the average of its pages, minus the same points for site-wide issues (like a missing sitemap). The area scores work the same way with only that area's issues.

90 and up is green, 50 to 89 is amber, under 50 is red.

> [!TIP]
> Fix the errors first, then the warnings. Notices are nice to have.

## Options

```python
SeoAuditPlugin(
    site_url="https://www.example.com",   # the address the form starts with
    max_pages=25,                          # pages per audit, unless the form says otherwise
    urls=["/landing/offer"],               # extra pages the links don't reach (or a function of db)
    background=True,                       # False runs the audit while the page waits
)
```

## Add your pages from another plugin

Pages that no link reaches, like blog posts behind a search box, can be added to every audit. Give your plugin a `seo_urls(db)` method that returns their addresses:

```python
class BlogPlugin(Plugin):
    id = "blog"

    def seo_urls(self, db):
        return [f"/blog/{post.slug}" for post in db.scalars(select(Post).where(Post.published))]
```

The audit picks up every plugin with this method. Or pass `urls=lambda db: [...]` to `SeoAuditPlugin`.

## Run an audit from code

```python
plugin = panel.get_plugin("seo-audit")
with panel.session_factory() as db:
    audit = plugin.start_audit(db, "https://www.example.com", max_pages=50)
```

With `background=False` the call returns when the audit is done. `audit.score`, `audit.issues` and `audit.pages` hold the results. A weekly cron job with this code keeps the history up to date.

> [!NOTE]
> The audit runs on your server and opens your site over the internet, like a visitor would. Run it on a site you own: crawling other people's sites may break their rules.
