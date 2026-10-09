"""schema.org JSON-LD for blog pages (one ``@graph`` per page)."""

from __future__ import annotations

import json
from typing import Any

from markupsafe import Markup

from .text import items, strip_tags, word_count


def _iso(value: Any) -> str | None:
    return value.replace(microsecond=0).isoformat() if value is not None else None


def to_script(graph: list[dict]) -> Markup:
    """A ``<script type="application/ld+json">`` tag, safe to place in the page."""
    data = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=1)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Markup(f'<script type="application/ld+json">{data}</script>')


def website(site: Any) -> dict:
    out = {"@type": "WebSite", "@id": f"{site.url}/#website", "url": f"{site.url}/", "name": site.name,
           "inLanguage": site.language}
    if site.description:
        out["description"] = site.description
    out["publisher"] = {"@id": f"{site.url}/#organization"}
    return out


def organization(site: Any) -> dict:
    out: dict[str, Any] = {"@type": "Organization", "@id": f"{site.url}/#organization", "name": site.name,
                           "url": f"{site.url}/"}
    if site.logo:
        out["logo"] = {"@type": "ImageObject", "url": site.logo}
    if site.same_as:
        out["sameAs"] = list(site.same_as)
    return out


def person(site: Any, author: Any) -> dict:
    out: dict[str, Any] = {"@type": "Person", "@id": f"{site.author_url(author)}#person", "name": author.name,
                           "url": site.author_url(author)}
    if author.job_title:
        out["jobTitle"] = author.job_title
    if author.bio:
        out["description"] = strip_tags(author.bio)
    if author.avatar:
        out["image"] = site.media_url(author.avatar)
    links = [p["url"] for p in items(author.profiles, "url")]
    if author.website:
        links.insert(0, author.website)
    if links:
        out["sameAs"] = links
    return out


def breadcrumbs(crumbs: list[tuple[str, str]]) -> dict:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": i, "name": name, "item": url}
                            for i, (name, url) in enumerate(crumbs, start=1)],
    }


def article(site: Any, post: Any, url: str) -> dict:
    out: dict[str, Any] = {
        "@type": "BlogPosting",
        "@id": f"{url}#article",
        "headline": post.title[:110],
        "url": url,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "datePublished": _iso(post.published_at or post.created_at),
        "dateModified": _iso(post.updated_at or post.published_at),
        "inLanguage": site.language,
        "wordCount": word_count(post.content),
        "isPartOf": {"@id": f"{site.url}/#website"},
        "publisher": {"@id": f"{site.url}/#organization"},
    }
    description = post.meta_description or post.excerpt or post.summary
    if description:
        out["description"] = strip_tags(description)
    if post.summary:
        out["abstract"] = strip_tags(post.summary)
    image = site.media_url(post.og_image or post.cover_image)
    if image:
        out["image"] = {"@type": "ImageObject", "url": image, **({"caption": post.cover_alt} if post.cover_alt else {})}
    if post.author is not None:
        out["author"] = {"@id": f"{site.author_url(post.author)}#person"}
    if post.category is not None:
        out["articleSection"] = post.category.name
    keywords = [t.name for t in post.tags]
    if post.focus_keyword:
        keywords.insert(0, post.focus_keyword)
    if keywords:
        out["keywords"] = ", ".join(dict.fromkeys(keywords))
    points = [p["text"] for p in items(post.key_points, "text")]
    if points:
        # speakable: the parts voice assistants and answer engines read out
        out["speakable"] = {"@type": "SpeakableSpecification", "cssSelector": [".blog-summary", ".blog-key-points"]}
    sources = [s for s in items(post.sources, "url")]
    if sources:
        out["citation"] = [{"@type": "CreativeWork", "name": s.get("title") or s["url"], "url": s["url"]}
                           for s in sources]
    return out


def faq_page(post: Any, url: str) -> dict | None:
    faqs = items(post.faqs, "question", "answer")
    if not faqs:
        return None
    return {
        "@type": "FAQPage",
        "@id": f"{url}#faq",
        "mainEntity": [{"@type": "Question", "name": strip_tags(f["question"]),
                        "acceptedAnswer": {"@type": "Answer", "text": strip_tags(f["answer"])}} for f in faqs],
    }


def how_to(site: Any, post: Any, url: str) -> dict | None:
    steps = items(post.howto_steps, "text")
    if not steps or not post.howto_title:
        return None
    out: dict[str, Any] = {
        "@type": "HowTo",
        "@id": f"{url}#howto",
        "name": post.howto_title,
        "step": [{"@type": "HowToStep", "position": i, "name": s.get("name") or f"Step {i}",
                  "text": strip_tags(s["text"]), "url": f"{url}#step-{i}"} for i, s in enumerate(steps, start=1)],
    }
    image = site.media_url(post.cover_image)
    if image:
        out["image"] = image
    return out


def post_graph(site: Any, post: Any, url: str, crumbs: list[tuple[str, str]]) -> list[dict]:
    graph = [article(site, post, url), breadcrumbs(crumbs), website(site), organization(site)]
    if post.author is not None:
        graph.append(person(site, post.author))
    for extra in (faq_page(post, url), how_to(site, post, url)):
        if extra:
            graph.append(extra)
    return graph


def list_graph(site: Any, title: str, url: str, posts: list, crumbs: list[tuple[str, str]],
               description: str | None = None) -> list[dict]:
    page: dict[str, Any] = {
        "@type": "CollectionPage",
        "@id": url,
        "url": url,
        "name": title,
        "isPartOf": {"@id": f"{site.url}/#website"},
        "inLanguage": site.language,
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [{"@type": "ListItem", "position": i, "url": site.post_url(p), "name": p.title}
                                for i, p in enumerate(posts, start=1)],
        },
    }
    if description:
        page["description"] = description
    return [page, breadcrumbs(crumbs), website(site), organization(site)]
