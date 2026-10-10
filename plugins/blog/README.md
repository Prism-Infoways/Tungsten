# tungsten-blog

A blog for your [Tungsten](https://tungsten.prisminfoways.com/) panel, built to be found: on Google (**SEO**), in AI search like ChatGPT, Perplexity and Google AI Overviews (**GEO**), and in answer boxes and voice assistants (**AEO**).

## What you get

**In the panel**

- A **Blog** menu: Posts, Categories, Tags and Authors.
- A post editor with a rich text editor, cover image, draft / publish / schedule, and three tabs: SEO, GEO and AEO.
- A live **SEO / GEO / AEO score** next to the editor, with a tip for every check that fails. The posts list shows the score too.
- A **Preview** link for drafts and scheduled posts.

**On your site**

- `/blog`: the post list with a featured post, categories, search and pages.
- `/blog/<slug>`: the post, with a summary box, key points, table of contents, how-to steps, FAQs, sources, author box and related posts.
- `/blog/category/<slug>`, `/blog/tag/<slug>`, `/blog/author/<slug>`.
- `/blog/feed.xml` (RSS), `/blog/sitemap.xml`, and at the site root `/sitemap.xml`, `/robots.txt` and `/llms.txt`.
- `/blog/<slug>.md`: a clean Markdown copy of each post, for AI tools.

### SEO

Title and meta description, canonical URL, `noindex` switch, Open Graph and X (Twitter) cards, clean slugs, breadcrumbs, `rel=prev/next` pages, a sitemap with last-modified dates, and schema.org JSON-LD: `BlogPosting`, `BreadcrumbList`, `WebSite`, `Organization` and `Person`.

### GEO (generative engine optimization)

What AI search can quote: a short **summary** (TL;DR) at the top, **key points**, **sources** (as `citation` in the schema), a real **author** with bio and profile links, "updated" dates, `/llms.txt` that lists every post with its summary, and a Markdown copy of each post. `robots.txt` welcomes AI crawlers like GPTBot, ClaudeBot and PerplexityBot (turn off with `ai_crawlers=False`).

### AEO (answer engine optimization)

Direct answers: **FAQs** shown on the page and as `FAQPage` schema, **how-to steps** as `HowTo` schema, `speakable` marks for voice assistants, and score checks for question-style headings and short answers.

## Install

```bash
pip install tungsten-blog
```

```python
from tungsten import Panel
from tungsten.storage import LocalStorage
from tungsten_blog import BlogPlugin

panel = Panel(
    ...,
    storage=LocalStorage(public=True),   # so visitors can see cover images
)
panel.plugin(BlogPlugin(
    site_name="Acme",
    site_url="https://acme.com",
    description="Guides and news from the Acme team.",
    logo="https://acme.com/logo.png",
    same_as=["https://www.linkedin.com/company/acme"],
    nav_links=[("Home", "/"), ("Pricing", "/pricing")],
))
panel.create_tables(engine)
panel.mount(app)
```

Needs `tungsten-admin` 0.1.5 or newer.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `site_name` | `"Blog"` | Your site's name, in titles, feeds and schema |
| `site_url` | panel `app_url`, else the request host | Public address used in canonical links, sitemap and schema |
| `path` | `"/blog"` | Where the blog lives |
| `title` | `"Blog"` | Heading of the blog home |
| `description`, `logo`, `language` | | Used in meta tags, feeds and schema |
| `per_page` | `10` | Posts per page |
| `site_files` | `True` | Serve `/sitemap.xml`, `/robots.txt`, `/llms.txt` at the site root. Turn off if your site has its own |
| `ai_crawlers` | `True` | Allow AI crawlers in `robots.txt` |
| `same_as` | `[]` | Your organization's profile links |
| `nav_links` | `[]` | Links in the blog header |
| `twitter` | | Your X handle, like `@acme` |
| `accent` | `"#dc2626"` | Link and button color |
| `llms_intro` | | Extra text at the top of `llms.txt` |

## Your own design

The pages are Jinja templates. Copy any of them into one of your panel's `template_dirs` with the same path to change it:

- `tungsten_blog/public/layout.html` (head tags, header, footer, styles)
- `tungsten_blog/public/index.html` (lists)
- `tungsten_blog/public/post.html` (a post)
- `tungsten_blog/public/not_found.html`

## Score in your own code

```python
from tungsten_blog import analyze_post

report = analyze_post(post)
report.score            # 0 to 100
report["geo"].checks    # each with .ok, .label and .tip
```

## With the MCP plugin

With [`tungsten-mcp`](https://github.com/Prism-Infoways/Tungsten/tree/claude/tungsten-admin-panel/plugins/mcp) installed, AI assistants like Claude can write and edit posts for you: *"Write a draft post about X with 4 FAQs and a summary."*

## More Tungsten plugins

| Package | What it adds | Docs |
| --- | --- | --- |
| [`tungsten-leads`](https://pypi.org/project/tungsten-leads/) | Leads list, stages, timeline and your own lead form fields | [README](https://github.com/Prism-Infoways/Tungsten/tree/claude/tungsten-admin-panel/plugins/leads) |
| [`tungsten-meta-leads`](https://pypi.org/project/tungsten-meta-leads/) | Facebook and Instagram lead form leads, with one-click setup | [Guide](https://tungsten.prisminfoways.com/docs/facebook-leads.html) |
| [`tungsten-whatsapp`](https://pypi.org/project/tungsten-whatsapp/) | WhatsApp for leads: click-to-chat, Cloud API or WhatsApp Web | [Guide](https://tungsten.prisminfoways.com/docs/whatsapp.html) |
| [`tungsten-mcp`](https://pypi.org/project/tungsten-mcp/) | MCP server, so AI assistants like Claude can read and change your data | [Guide](https://tungsten.prisminfoways.com/docs/mcp.html) |
| [`tungsten-tickets`](https://pypi.org/project/tungsten-tickets/) | Help desk: tickets, replies, notes, SLA and a customer support page | [Guide](https://tungsten.prisminfoways.com/docs/tickets.html) |
| [`tungsten-seo-audit`](https://pypi.org/project/tungsten-seo-audit/) | SEO audit of your website: score, fix tips, AI search checks, history | [Guide](https://tungsten.prisminfoways.com/docs/seo-audit.html) |
| [`tungsten-security-audit`](https://pypi.org/project/tungsten-security-audit/) | Security audit with a score and fix tips, plus a login log with lockout | [Guide](https://tungsten.prisminfoways.com/docs/security-audit.html) |
| [`tungsten-finance`](https://pypi.org/project/tungsten-finance/) | Finance: invoices with GST, payments, expenses, bank balances and profit reports | [Guide](https://tungsten.prisminfoways.com/docs/finance.html) |

Core package: [`tungsten-admin`](https://pypi.org/project/tungsten-admin/). Website and docs: https://tungsten.prisminfoways.com/
