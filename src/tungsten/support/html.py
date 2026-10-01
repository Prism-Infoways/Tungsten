"""Small HTML helpers: attribute rendering and a safe-HTML sanitizer."""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from typing import Any

from markupsafe import Markup

ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "del", "div", "em", "h1", "h2", "h3", "h4",
    "hr", "i", "li", "ol", "p", "pre", "s", "span", "strike", "strong", "u", "ul",
    "figure", "figcaption", "img", "table", "thead", "tbody", "tr", "td", "th", "sub", "sup",
}
ALLOWED_ATTRS = {"a": {"href", "title", "target", "rel"}, "img": {"src", "alt", "width", "height"}}
VOID = {"br", "hr", "img"}
DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "template"}


def attrs(values: dict[str, Any] | None) -> Markup:
    """Render a dict as HTML attributes. ``True`` renders a bare attribute."""
    if not values:
        return Markup("")
    out = []
    for key, val in values.items():
        if val is None or val is False:
            continue
        if val is True:
            out.append(escape(key))
        else:
            out.append(f'{escape(key)}="{escape(str(val))}"')
    return Markup(" ".join(out))


def _safe_url(url: str) -> bool:
    u = url.strip().lower()
    return not (u.startswith("javascript:") or u.startswith("vbscript:") or u.startswith("data:text"))


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs_):
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED_TAGS:
            return
        allowed = ALLOWED_ATTRS.get(tag, set())
        parts = [tag]
        for k, v in attrs_:
            if k in allowed and v is not None:
                if k in ("href", "src") and not _safe_url(v):
                    continue
                parts.append(f'{k}="{escape(v)}"')
        self.out.append("<" + " ".join(parts) + ">")

    def handle_startendtag(self, tag, attrs_):
        self.handle_starttag(tag, attrs_)

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED_TAGS or tag in VOID:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data))


def sanitize(html: str | None) -> str:
    """Strip any tags/attributes that are not on a small allow-list."""
    if not html:
        return ""
    p = _Sanitizer()
    p.feed(str(html))
    p.close()
    return "".join(p.out)
