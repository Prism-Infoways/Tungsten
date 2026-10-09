"""Text helpers: slugs, reading time, and a light read of the post's HTML."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+(?:['’-]\w+)*", re.UNICODE)


def slugify(value: Any) -> str:
    """``"Hello, World!"`` → ``"hello-world"``. Hindi and other scripts are kept as they are."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = "".join(ch if ch.isalnum() or unicodedata.category(ch).startswith("M") else "-" for ch in text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def strip_tags(value: Any) -> str:
    """Plain text of an HTML string, with spaces between blocks."""
    text = re.sub(r"<(br|/p|/h[1-6]|/li|/div|/tr|/blockquote)\b[^>]*>", " ", str(value or ""), flags=re.IGNORECASE)
    return _SPACE_RE.sub(" ", html.unescape(_TAG_RE.sub("", text))).strip()


def words(value: Any) -> list[str]:
    return _WORD_RE.findall(str(value or ""))


def word_count(value: Any) -> int:
    return len(words(strip_tags(value)))


def reading_minutes(value: Any, wpm: int = 220) -> int:
    return max(1, round(word_count(value) / wpm))


def shorten(text: Any, limit: int = 160) -> str:
    """Cut ``text`` at a word boundary, with an ellipsis when cut."""
    text = _SPACE_RE.sub(" ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",.;:-")
    return f"{cut}…"


def items(rows: Any, *keys: str) -> list[dict]:
    """Repeater rows that have every one of ``keys`` filled in."""
    out = []
    for row in rows or []:
        if isinstance(row, dict) and all(str(row.get(k) or "").strip() for k in keys):
            out.append({k: v for k, v in row.items() if not str(k).startswith("__")})
    return out


@dataclass
class HtmlReport:
    """What the scorer needs to know about the post's HTML."""

    headings: list[tuple[int, str]] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)
    images: int = 0
    images_without_alt: int = 0
    links: list[str] = field(default_factory=list)
    lists: int = 0
    tables: int = 0


class _Reader(HTMLParser):
    BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "td", "th", "blockquote", "figcaption"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.report = HtmlReport()
        self._stack: list[tuple[str, list[str]]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img":
            self.report.images += 1
            if not (a.get("alt") or "").strip():
                self.report.images_without_alt += 1
        elif tag == "a" and a.get("href"):
            self.report.links.append(a["href"])
        elif tag in ("ul", "ol"):
            self.report.lists += 1
        elif tag == "table":
            self.report.tables += 1
        if tag in self.BLOCKS:
            self._stack.append((tag, []))

    def handle_endtag(self, tag):
        if tag not in self.BLOCKS:
            return
        while self._stack:
            open_tag, parts = self._stack.pop()
            text = _SPACE_RE.sub(" ", "".join(parts)).strip()
            if self._stack and text:
                self._stack[-1][1].append(" " + text + " ")
            if open_tag == tag:
                if text:
                    if tag in ("h1", "h2", "h3", "h4"):
                        self.report.headings.append((int(tag[1]), text))
                    elif tag == "p":
                        self.report.paragraphs.append(text)
                return

    def handle_data(self, data):
        if self._stack:
            self._stack[-1][1].append(data)


def read_html(value: Any) -> HtmlReport:
    reader = _Reader()
    reader.feed(str(value or ""))
    reader.close()
    return reader.report


_HEADING_RE = re.compile(r"<h([23])(\s[^>]*)?>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)


def with_heading_ids(content: Any) -> tuple[str, list[dict]]:
    """Give each ``<h2>``/``<h3>`` an ``id`` (for links to a section) and return the table of contents."""
    toc: list[dict] = []
    used: set[str] = set()

    def add_id(match: re.Match) -> str:
        level, attrs, inner = match.group(1), match.group(2) or "", match.group(3)
        text = strip_tags(inner)
        found = re.search(r'\bid="([^"]+)"', attrs)
        anchor = found.group(1) if found else (slugify(text)[:60] or "section")
        base, n = anchor, 2
        while anchor in used:
            anchor, n = f"{base}-{n}", n + 1
        used.add(anchor)
        toc.append({"level": int(level), "text": text, "id": anchor})
        if found:
            return match.group(0)
        return f'<h{level}{attrs} id="{html.escape(anchor)}">{inner}</h{level}>'

    return _HEADING_RE.sub(add_id, str(content or "")), toc
