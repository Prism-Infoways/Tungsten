"""The checks: what counts as a problem, how bad it is, and how to fix it."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from .crawler import PageInfo, Response, normalize

ERROR, WARNING, NOTICE = "error", "warning", "notice"
SEVERITIES = {ERROR: "Error", WARNING: "Warning", NOTICE: "Notice"}
CATEGORIES = ("Content", "Technical", "Links", "Social", "Speed", "AI search")
#: how many points one issue takes off a page's score (or the site's, for site-wide issues)
WEIGHTS = {ERROR: 12, WARNING: 5, NOTICE: 1}

#: check code: (category, fix tip)
CHECKS: dict[str, tuple[str, str]] = {
    # content
    "title_missing": ("Content", "Add a <title> to the page. Put the main keyword first and keep it under 60 characters."),
    "title_short": ("Content", "Make the title 30 to 60 characters, so it says what the page is about."),
    "title_long": ("Content", "Cut the title to 60 characters or less, or Google will cut it in results."),
    "title_many": ("Content", "Keep one <title> per page. Remove the extra ones."),
    "title_duplicate": ("Content", "Give every page its own title, so Google knows which page to show."),
    "description_missing": ("Content", "Add <meta name=\"description\"> with 70 to 160 characters that sum up the page."),
    "description_short": ("Content", "Make the description 70 to 160 characters. Say what the reader gets."),
    "description_long": ("Content", "Cut the description to 160 characters, or Google cuts it."),
    "description_duplicate": ("Content", "Write a different description for each page."),
    "h1_missing": ("Content", "Add one <h1> with the page's main topic."),
    "h1_many": ("Content", "Keep one <h1> per page. Turn the others into <h2>."),
    "heading_skip": ("Content", "Don't skip heading levels: an <h2> comes before an <h3>."),
    "thin_content": ("Content", "Add more useful text. Pages with under 300 words rarely rank."),
    "img_alt": ("Content", "Add an alt text to each image that says what it shows. Use alt=\"\" for decoration."),
    "lang_missing": ("Content", "Add the language to the page: <html lang=\"en\">."),
    # technical
    "http_error": ("Technical", "Fix the page or redirect it (301) to a page that works."),
    "fetch_failed": ("Technical", "Check that the server is up and the address is right."),
    "redirect_chain": ("Technical", "Point the link straight to the final address. Each extra hop slows the page."),
    "canonical_missing": ("Technical", "Add <link rel=\"canonical\" href=\"...\"> with the page's own full address."),
    "canonical_other": ("Technical", "Check the canonical. It sends Google to another page, so this page won't rank."),
    "canonical_relative": ("Technical", "Use a full address (https://...) in the canonical link."),
    "noindex": ("Technical", "Remove noindex if this page should show in Google."),
    "viewport_missing": ("Technical", "Add <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">."),
    "not_https": ("Technical", "Serve the site over HTTPS. Get a free certificate (Let's Encrypt or cPanel AutoSSL)."),
    "http_no_redirect": ("Technical", "Redirect every http:// address to https:// with a 301."),
    "mixed_content": ("Technical", "Load scripts, styles and images over https:// too."),
    "schema_missing": ("Technical", "Add JSON-LD structured data (Organization, Article, Product, FAQPage...)."),
    "schema_invalid": ("Technical", "Fix the JSON-LD: it is not valid JSON. Test it at validator.schema.org."),
    "robots_missing": ("Technical", "Add /robots.txt with at least \"User-agent: *\" and a \"Sitemap:\" line."),
    "robots_blocks_all": ("Technical", "robots.txt blocks the whole site (Disallow: /). Remove it, or Google can't crawl."),
    "robots_no_sitemap": ("Technical", "Add \"Sitemap: https://your-site/sitemap.xml\" to robots.txt."),
    "sitemap_missing": ("Technical", "Add /sitemap.xml with every page you want in Google, and submit it in Search Console."),
    "sitemap_invalid": ("Technical", "Fix sitemap.xml: it is not valid XML."),
    "soft_404": ("Technical", "Make missing pages answer with status 404, not 200."),
    # links
    "broken_link": ("Links", "Fix or remove the link. It goes to a page that doesn't work."),
    "broken_external": ("Links", "Fix or remove the link to the other site. It doesn't work."),
    "link_redirect": ("Links", "Change the link to the final address, so it doesn't redirect."),
    # social
    "og_missing": ("Social", "Add Open Graph tags (og:title, og:description, og:image) for nice link previews."),
    "twitter_missing": ("Social", "Add <meta name=\"twitter:card\" content=\"summary_large_image\">."),
    # speed
    "slow": ("Speed", "Make the page answer faster: cache it, shrink images, use a CDN."),
    "heavy": ("Speed", "Make the HTML smaller. Move big inline scripts and styles to files."),
    "many_scripts": ("Speed", "Load fewer scripts. Join them, or load them with defer."),
    "img_size": ("Speed", "Give images width and height, so the page doesn't jump while it loads."),
    # AI search (GEO / AEO)
    "ai_blocked": ("AI search", "robots.txt blocks AI crawlers. Allow them if you want to show up in AI answers."),
    "llms_missing": ("AI search", "Add /llms.txt: a short Markdown summary of the site and its key pages for AI tools."),
    "faq_missing": ("AI search", "Answer common questions on the page and mark them up with FAQPage JSON-LD."),
}

AI_BOTS = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "PerplexityBot",
           "Google-Extended")


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


@dataclass
class Issue:
    check: str
    severity: str
    message: str
    page_url: str | None = None

    @property
    def category(self) -> str:
        return CHECKS[self.check][0]

    @property
    def tip(self) -> str:
        return CHECKS[self.check][1]


def check_page(url: str, res: Response, info: PageInfo | None) -> list[Issue]:
    """Problems on one page. ``info`` is None when the page is not readable HTML."""
    out: list[Issue] = []

    def add(check: str, severity: str, message: str) -> None:
        out.append(Issue(check, severity, message, url))

    if res.error:
        add("fetch_failed", ERROR, f"The page did not open: {res.error}.")
        return out
    if res.status >= 400:
        add("http_error", ERROR, f"The page answers with status {res.status}.")
        return out
    if len(res.redirects) > 1:
        add("redirect_chain", WARNING, f"{len(res.redirects)} redirects before the page opens.")
    if res.elapsed_ms > 3000:
        add("slow", WARNING, f"The page took {res.elapsed_ms / 1000:.1f} s to load.")
    elif res.elapsed_ms > 1500:
        add("slow", NOTICE, f"The page took {res.elapsed_ms / 1000:.1f} s to load.")
    if info is None:
        return out
    if res.size > 500 * 1024:
        add("heavy", WARNING, f"The HTML is {res.size // 1024} KB.")
    if urlparse(res.url).scheme != "https":
        add("not_https", ERROR, "The page is not on HTTPS.")
    noindex = "noindex" in info.meta.get("robots", "").lower() or "noindex" in res.headers.get("x-robots-tag", "").lower()
    if noindex:
        add("noindex", WARNING, "The page tells search engines not to index it (noindex).")

    # title and description
    title = info.title or ""
    if not title:
        add("title_missing", ERROR, "The page has no title.")
    elif len(title) < 30:
        add("title_short", WARNING, f"The title is short ({len(title)} characters): \"{title}\".")
    elif len(title) > 60:
        add("title_long", WARNING, f"The title is long ({len(title)} characters).")
    if info.titles > 1:
        add("title_many", WARNING, f"The page has {info.titles} titles.")
    desc = info.meta.get("description", "")
    if not desc:
        add("description_missing", WARNING, "The page has no meta description.")
    elif len(desc) < 70:
        add("description_short", NOTICE, f"The meta description is short ({len(desc)} characters).")
    elif len(desc) > 160:
        add("description_long", WARNING, f"The meta description is long ({len(desc)} characters).")

    # headings
    h1 = info.h1
    if not h1:
        add("h1_missing", ERROR, "The page has no H1 heading.")
    elif len(h1) > 1:
        add("h1_many", WARNING, f"The page has {len(h1)} H1 headings.")
    last = 0
    for level, text in info.headings:
        if last and level > last + 1:
            add("heading_skip", NOTICE, f"An H{level} (\"{text[:60]}\") comes right after an H{last}.")
            break
        last = level
    if info.words < 300 and not noindex:
        add("thin_content", WARNING if info.words < 100 else NOTICE, f"Only {info.words} words on the page.")
    if not info.lang:
        add("lang_missing", WARNING, "The <html> tag has no lang.")

    # images
    no_alt = [i for i in info.images if i["alt"] is None]
    if no_alt:
        add("img_alt", WARNING, f"{len(no_alt)} of {_n(len(info.images), 'image')} without alt text.")
    no_size = [i for i in info.images if not (i["width"] and i["height"])]
    if len(no_size) >= 3:
        add("img_size", NOTICE, f"{len(no_size)} images have no width and height.")

    # technical
    if "viewport" not in info.meta:
        add("viewport_missing", ERROR, "No viewport tag, so the page is not mobile friendly.")
    if info.canonical is None:
        add("canonical_missing", WARNING, "The page has no canonical link.")
    elif not urlparse(info.canonical).scheme:
        add("canonical_relative", NOTICE, f"The canonical is not a full address: {info.canonical}.")
    elif normalize(urljoin(res.url, info.canonical)) != normalize(res.url):
        add("canonical_other", NOTICE, f"The canonical points to another page: {info.canonical}.")
    if urlparse(res.url).scheme == "https":
        insecure = [s for s in info.scripts + info.styles + [i["src"] or "" for i in info.images]
                    if s.startswith("http://")]
        if insecure:
            add("mixed_content", WARNING, f"{_n(len(insecure), 'file')} load over http://, like {insecure[0]}.")
    if info.bad_json_ld:
        add("schema_invalid", ERROR, f"{info.bad_json_ld} JSON-LD block(s) are not valid JSON.")
    elif not info.json_ld and not info.microdata:
        add("schema_missing", NOTICE, "The page has no structured data.")

    # social
    missing = [k for k in ("og:title", "og:description", "og:image") if not info.meta.get(k)]
    if missing:
        add("og_missing", WARNING if len(missing) == 3 else NOTICE, "Missing " + ", ".join(missing) + ".")
    if "twitter:card" not in info.meta:
        add("twitter_missing", NOTICE, "No twitter:card tag.")

    # speed
    if len(info.scripts) > 15:
        add("many_scripts", NOTICE, f"The page loads {len(info.scripts)} script files.")
    return out


def has_faq(info: PageInfo) -> bool:
    def types(item: dict) -> list[str]:
        t = item.get("@type")
        return t if isinstance(t, list) else [t]

    return any("FAQPage" in types(item) or "QAPage" in types(item) for item in info.json_ld)


def check_robots(robots: Response | None, site: str) -> tuple[list[Issue], list[str]]:
    """Issues in robots.txt, and the sitemap addresses it names."""
    out: list[Issue] = []
    if robots is None or robots.error or robots.status >= 400:
        return [Issue("robots_missing", WARNING, "The site has no robots.txt.")], []
    groups: list[tuple[list[str], list[str]]] = []
    sitemaps: list[str] = []
    agents: list[str] = []
    rules: list[str] = []
    for raw in robots.text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "sitemap":
            sitemaps.append(urljoin(site, value))
        elif key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key in ("disallow", "allow"):
            rules.append(f"{key}:{value}")
    if agents:
        groups.append((agents, rules))
    for agents, rules in groups:
        if "*" in agents and "disallow:/" in rules and "allow:/" not in rules:
            out.append(Issue("robots_blocks_all", ERROR, "robots.txt blocks every crawler from the whole site."))
    blocked = [bot for bot in AI_BOTS
               if any(bot.lower() in agents and "disallow:/" in rules for agents, rules in groups)]
    if blocked:
        out.append(Issue("ai_blocked", NOTICE, "robots.txt blocks " + ", ".join(blocked) + "."))
    if not sitemaps:
        out.append(Issue("robots_no_sitemap", NOTICE, "robots.txt does not name a sitemap."))
    return out, sitemaps


def score(issues: list[Issue], pages: list[str]) -> tuple[int, dict[str, int], dict[str, int]]:
    """``(site score, score per category, score per page)``, each 0 to 100."""

    def calc(items: list[Issue]) -> int:
        per_page = {p: 100 for p in pages}
        site_penalty = 0
        for issue in items:
            if issue.page_url in per_page:
                per_page[issue.page_url] -= WEIGHTS[issue.severity]
            else:
                site_penalty += WEIGHTS[issue.severity]
        pages_avg = sum(max(0, s) for s in per_page.values()) / len(per_page) if per_page else 100
        return max(0, min(100, round(pages_avg - site_penalty)))

    page_scores = {}
    for p in pages:
        page_scores[p] = max(0, 100 - sum(WEIGHTS[i.severity] for i in issues if i.page_url == p))
    categories = {c: calc([i for i in issues if i.category == c]) for c in CATEGORIES}
    return calc(issues), categories, page_scores
