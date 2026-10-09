"""SEO, GEO and AEO checks for a post, with a score out of 100 and a tip for each miss.

* SEO: classic search (Google, Bing): title, description, keyword, links, images.
* GEO (generative engine optimization): what AI search (ChatGPT, Perplexity, Google
  AI Overviews) can quote: a short summary, key points, sources, a named author, facts.
* AEO (answer engine optimization): direct answers: FAQs, question headings, steps.

``analyze(data)`` takes the post's fields as a dict (the editor's live form state),
``analyze_post(post)`` takes a saved :class:`~tungsten_blog.models.BlogPost`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .text import items, read_html, slugify, strip_tags, words

QUESTION_WORDS = (
    "what", "why", "how", "when", "where", "who", "which", "can", "does", "do", "is", "are",
    "should", "will", "kya", "kaise", "kyun", "kab", "kahan", "kaun",
)


@dataclass
class Check:
    ok: bool
    label: str
    tip: str = ""
    weight: int = 1


@dataclass
class Section:
    key: str
    title: str
    checks: list[Check] = field(default_factory=list)

    def add(self, ok: Any, label: str, tip: str = "", weight: int = 1) -> None:
        self.checks.append(Check(bool(ok), label, tip, weight))

    @property
    def score(self) -> int:
        total = sum(c.weight for c in self.checks)
        return round(100 * sum(c.weight for c in self.checks if c.ok) / total) if total else 0

    @property
    def grade(self) -> str:
        return "good" if self.score >= 80 else "fair" if self.score >= 50 else "poor"


@dataclass
class Report:
    sections: list[Section]

    @property
    def score(self) -> int:
        return round(sum(s.score for s in self.sections) / len(self.sections)) if self.sections else 0

    def __getitem__(self, key: str) -> Section:
        return next(s for s in self.sections if s.key == key)

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            **{s.key: {"score": s.score, "checks": [{"ok": c.ok, "label": c.label, "tip": c.tip} for c in s.checks]}
               for s in self.sections},
        }


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _has_keyword(text: str, keyword: str) -> bool:
    return bool(keyword) and keyword.lower() in text.lower()


def _is_question(text: str) -> bool:
    t = text.strip().lower()
    return t.endswith("?") or t.split(" ", 1)[0] in QUESTION_WORDS


def _is_url(value: Any) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def analyze(data: dict, site_host: str | None = None) -> Report:
    title = _text(data.get("title"))
    meta_title = _text(data.get("meta_title")) or title
    description = _text(data.get("meta_description")) or _text(data.get("excerpt"))
    keyword = _text(data.get("focus_keyword"))
    slug = _text(data.get("slug")) or slugify(title)
    content = str(data.get("content") or "")
    plain = strip_tags(content)
    word_total = len(words(plain))
    page = read_html(content)
    summary = _text(data.get("summary"))
    key_points = items(data.get("key_points"), "text")
    sources = [s for s in items(data.get("sources"), "url") if _is_url(s["url"])]
    faqs = items(data.get("faqs"), "question", "answer")
    steps = items(data.get("howto_steps"), "text")
    subheads = [text for level, text in page.headings if level in (2, 3)]
    first_para = page.paragraphs[0] if page.paragraphs else plain[:600]
    external = [u for u in page.links if _is_url(u) and (not site_host or urlparse(u).netloc != site_host)]
    internal = [u for u in page.links if u not in external and not u.startswith(("mailto:", "tel:", "#"))]

    # ------------------------------------------------------------------ SEO
    seo = Section("seo", "SEO")
    seo.add(30 <= len(meta_title) <= 60, f"Title is {len(meta_title)} characters",
            "Keep the SEO title between 30 and 60 characters so Google shows it in full.", 2)
    seo.add(120 <= len(description) <= 160, f"Meta description is {len(description)} characters",
            "Write a meta description of 120 to 160 characters that makes people want to click.", 2)
    seo.add(keyword, "Focus keyword is set", "Pick the one search phrase this post should rank for.", 2)
    if keyword:
        seo.add(_has_keyword(meta_title, keyword), "Keyword is in the title", "Use the focus keyword in the SEO title.", 2)
        seo.add(_has_keyword(description, keyword), "Keyword is in the meta description",
                "Use the focus keyword in the meta description.")
        seo.add(_has_keyword(first_para, keyword), "Keyword is in the first paragraph",
                "Use the focus keyword early, in the first paragraph.")
        seo.add(slugify(keyword) in slug, "Keyword is in the URL", "Put the focus keyword in the slug.")
        seo.add(any(_has_keyword(h, keyword) for h in subheads), "Keyword is in a subheading",
                "Use the focus keyword in at least one H2 or H3 subheading.")
    seo.add(0 < len(slug) <= 75, "URL is short", "Keep the slug short: a few words joined by hyphens.")
    seo.add(word_total >= 600, f"Post has {word_total} words",
            "Aim for 600 words or more so the post covers the topic in depth.", 2)
    seo.add(len(subheads) >= 2, "Post has subheadings", "Break the post up with H2 and H3 subheadings.")
    seo.add(data.get("cover_image") and _text(data.get("cover_alt")), "Cover image has alt text",
            "Add a cover image and describe it in the alt text.")
    seo.add(page.images_without_alt == 0, "All images have alt text", "Give every image in the post alt text.")
    seo.add(internal, "Links to your other pages", "Link to at least one of your other posts or pages.")
    seo.add(not data.get("noindex"), "Search engines may index it", "Turn off \"Hide from search engines\".", 2)

    # ------------------------------------------------------------------ GEO
    geo = Section("geo", "GEO")
    summary_words = len(words(summary))
    geo.add(20 <= summary_words <= 80, "Has a short summary (TL;DR)",
            "Write a 2 to 3 sentence summary (20 to 80 words). AI search quotes it as the answer.", 3)
    geo.add(len(key_points) >= 3, f"Has {len(key_points)} key points",
            "Add 3 to 6 key points: short facts an AI can lift as they are.", 2)
    geo.add(len(sources) >= 2 or len(external) >= 2, "Cites sources",
            "Add at least 2 sources (studies, docs, official pages). Cited posts are trusted and quoted more.", 2)
    geo.add(data.get("author_id") or data.get("author"), "Has a named author",
            "Pick an author. A real name with a bio shows expertise (E-E-A-T).", 2)
    geo.add(re.search(r"\d", plain), "Has facts and numbers",
            "Add concrete numbers, dates or stats. AI answers prefer specific facts.")
    geo.add(page.lists or page.tables, "Has lists or tables", "Use a bullet list or a table: easy to read and to quote.")
    long_paras = [p for p in page.paragraphs if len(words(p)) > 120]
    geo.add(not long_paras, "Paragraphs are short", "Split paragraphs longer than about 120 words.")
    geo.add(_text(data.get("excerpt")), "Has an excerpt", "Add an excerpt: it shows on the blog list and in feeds.")

    # ------------------------------------------------------------------ AEO
    aeo = Section("aeo", "AEO")
    aeo.add(len(faqs) >= 3, f"Has {len(faqs)} FAQs", "Add 3 or more questions people ask, each with a direct answer.", 3)
    if faqs:
        long_answers = [f for f in faqs if len(words(strip_tags(f["answer"]))) > 80]
        aeo.add(not long_answers, "FAQ answers are short",
                "Keep each FAQ answer to about 40 to 60 words: one clear answer first, then detail.")
    questions = [h for h in subheads if _is_question(h)]
    aeo.add(questions, "Subheadings ask questions",
            "Write some H2/H3 subheadings as questions (\"What is ...?\", \"How do I ...?\").", 2)
    lead = re.split(r"(?<=[.!?])\s", summary or first_para, maxsplit=1)[0]
    aeo.add(lead and len(words(lead)) <= 30, "Opens with a direct answer",
            "Start the summary (or first paragraph) with one short sentence that answers the main question.", 2)
    if _text(data.get("howto_title")) or steps:
        aeo.add(len(steps) >= 2 and _text(data.get("howto_title")), "How-to has a title and steps",
                "Give the how-to a title and at least 2 steps.")
    aeo.add(page.lists, "Has a list answer", "Answer \"best\", \"top\" or \"steps\" questions with a list.")

    return Report([seo, geo, aeo])


def post_data(post: Any) -> dict:
    """The fields of a saved post, as :func:`analyze` expects them."""
    names = ("title", "slug", "excerpt", "content", "cover_image", "cover_alt", "meta_title", "meta_description",
             "focus_keyword", "noindex", "summary", "key_points", "sources", "faqs", "howto_title", "howto_steps",
             "author_id")
    return {name: getattr(post, name, None) for name in names}


def analyze_post(post: Any, site_host: str | None = None) -> Report:
    return analyze(post_data(post), site_host)
