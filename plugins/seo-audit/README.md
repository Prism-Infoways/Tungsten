# tungsten-seo-audit

SEO audit for [Tungsten](https://tungsten.prisminfoways.com/) admin panels. Type your site's address, and the audit
checks its pages and gives a score from 0 to 100, a list of issues, and a simple tip to fix each one. Every audit stays
in the history, so you can see the score go up.

```bash
pip install tungsten-seo-audit
```

```python
from tungsten_seo_audit import SeoAuditPlugin

panel.plugin(SeoAuditPlugin(site_url="https://www.example.com"))
panel.create_tables(engine)
```

Open **SEO audits** in the panel and press **New audit**.

## What it checks

| Area | Checks |
| --- | --- |
| Content | Title and meta description (missing, too short, too long, duplicate), H1 and heading order, thin pages, image alt texts, page language |
| Technical | Status codes, redirect chains, canonical links, noindex, mobile viewport, HTTPS and http to https redirect, mixed content, structured data (JSON-LD), robots.txt, sitemap.xml, real 404 pages |
| Links | Broken links inside the site and to other sites, links that redirect |
| Social | Open Graph and Twitter card tags |
| Speed | Load time, HTML size, number of scripts, images without width and height |
| AI search | AI crawlers blocked in robots.txt, llms.txt, FAQ structured data |

## Options

```python
SeoAuditPlugin(
    site_url="https://www.example.com",   # the address the form starts with (default: the panel's app_url)
    max_pages=25,                          # pages per audit, unless the form says otherwise
    urls=lambda db: ["/landing/offer"],    # extra pages the links don't reach
    background=True,                       # run audits in a thread; False waits for the result
)
```

Other plugins can add their pages to every audit with a `seo_urls(db)` method. The blog plugin uses it for its posts.

Docs: https://tungsten.prisminfoways.com/docs/seo-audit.html

## More Tungsten plugins

| Package | What it adds | Docs |
| --- | --- | --- |
| [`tungsten-leads`](https://pypi.org/project/tungsten-leads/) | Leads list, stages, timeline and your own lead form fields | [README](https://github.com/Prism-Infoways/Tungsten/tree/claude/tungsten-admin-panel/plugins/leads) |
| [`tungsten-meta-leads`](https://pypi.org/project/tungsten-meta-leads/) | Facebook and Instagram lead form leads, with one-click setup | [Guide](https://tungsten.prisminfoways.com/docs/facebook-leads.html) |
| [`tungsten-whatsapp`](https://pypi.org/project/tungsten-whatsapp/) | WhatsApp for leads: click-to-chat, Cloud API or WhatsApp Web | [Guide](https://tungsten.prisminfoways.com/docs/whatsapp.html) |
| [`tungsten-mcp`](https://pypi.org/project/tungsten-mcp/) | MCP server, so AI assistants like Claude can read and change your data | [Guide](https://tungsten.prisminfoways.com/docs/mcp.html) |
| [`tungsten-tickets`](https://pypi.org/project/tungsten-tickets/) | Help desk: tickets, replies, notes, SLA and a customer support page | [Guide](https://tungsten.prisminfoways.com/docs/tickets.html) |
| [`tungsten-blog`](https://pypi.org/project/tungsten-blog/) | Blog built for SEO, GEO and AEO, with a live score, sitemap and llms.txt | [Guide](https://tungsten.prisminfoways.com/docs/blog.html) |
| [`tungsten-security-audit`](https://pypi.org/project/tungsten-security-audit/) | Security audit with a score and fix tips, plus a login log with lockout | [Guide](https://tungsten.prisminfoways.com/docs/security-audit.html) |

Core package: [`tungsten-admin`](https://pypi.org/project/tungsten-admin/). Website and docs: https://tungsten.prisminfoways.com/
