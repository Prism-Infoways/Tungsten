"""Small HTML helpers: attribute rendering and a safe-HTML sanitizer."""

from __future__ import annotations

import json
import re
from html import escape
from html.parser import HTMLParser
from typing import Any, Callable

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


#: tabs, new lines, spaces and control characters: browsers drop them from a URL's scheme
_URL_JUNK = re.compile(r"[\x00-\x20\x7f]+")


def _safe_url(url: str) -> bool:
    u = _URL_JUNK.sub("", url).lower()
    return not (u.startswith("javascript:") or u.startswith("vbscript:") or u.startswith("data:text"))


#: content types of the rich editor's own Trix attachments (see :class:`tungsten.forms.RichEditor`)
MENTION_TYPE = "application/vnd.tungsten.mention"
BLOCK_TYPE = "application/vnd.tungsten.block"
_CLASS_TOKEN = re.compile(r"^(attachment(--[a-z0-9-]+)?|attachment__[a-z-]+|tw-mention|tw-block)$")
_BLOCK_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _json_safe(value: Any, depth: int = 0) -> Any:
    """Plain JSON data only (no surprises from a crafted attachment)."""
    if depth > 6:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:10000]
    if isinstance(value, list):
        return [_json_safe(v, depth + 1) for v in value[:200]]
    if isinstance(value, dict):
        return {str(k)[:100]: _json_safe(v, depth + 1) for k, v in list(value.items())[:100]}
    return None


def default_attachment_content(data: dict) -> str:
    """The HTML Trix shows for a mention or block attachment. Always built here, never taken from input."""
    if data.get("contentType") == MENTION_TYPE:
        return f'<span class="tw-mention">{escape(data.get("mentionTrigger", "@") + data.get("mentionLabel", ""))}</span>'
    return f'<span class="tw-block">{escape(data.get("blockLabel") or data.get("blockId") or "")}</span>'


def clean_attachment(raw: str | None, content_for: Callable[[dict], str] | None = None) -> dict | None:
    """Rebuild a Trix ``data-trix-attachment`` value from known, safe keys only."""
    try:
        data = json.loads(raw or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    kind = data.get("contentType")
    if kind == MENTION_TYPE:
        trigger = str(data.get("mentionTrigger") or "@")[:1]
        out = {"contentType": kind, "mentionId": str(data.get("mentionId", ""))[:200],
               "mentionLabel": str(data.get("mentionLabel", ""))[:200], "mentionTrigger": trigger}
    elif kind == BLOCK_TYPE:
        block_id = str(data.get("blockId", ""))
        if not _BLOCK_ID.match(block_id):
            return None
        config = data.get("blockConfig")
        out = {"contentType": kind, "blockId": block_id, "blockLabel": str(data.get("blockLabel", ""))[:200],
               "blockConfig": _json_safe(config) if isinstance(config, dict) else {}}
    else:  # an uploaded file or image
        out = {}
        for key in ("url", "href"):
            if isinstance(data.get(key), str) and _safe_url(data[key]):
                out[key] = data[key]
        for key in ("filename", "contentType"):
            if isinstance(data.get(key), str):
                out[key] = data[key][:255]
        for key in ("filesize", "width", "height"):
            if isinstance(data.get(key), (int, float)) and not isinstance(data.get(key), bool):
                out[key] = data[key]
        return out
    out["content"] = (content_for or default_attachment_content)(out)
    return out


class _Sanitizer(HTMLParser):
    def __init__(self, attachments: bool = False, content_for: Callable[[dict], str] | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.attachments = attachments
        self.content_for = content_for

    def _attachment_attrs(self, tag: str, attrs_: list) -> list[str]:
        """Extra attributes the rich editor needs on its Trix attachments (``attachments=True``)."""
        parts = []
        if tag == "figure":
            for k, v in attrs_:
                if k == "data-trix-attachment":
                    data = clean_attachment(v, self.content_for)
                    if data is not None:
                        parts.append(f'data-trix-attachment="{escape(json.dumps(data))}"')
                elif k == "data-trix-content-type" and v and re.match(r"^[\w.+/-]{1,100}$", v):
                    parts.append(f'data-trix-content-type="{escape(v)}"')
        if tag in ("figure", "figcaption", "span") or tag == "img":
            for k, v in attrs_:
                if k == "class" and v:
                    tokens = [t for t in v.split() if _CLASS_TOKEN.match(t)]
                    if tokens:
                        parts.append(f'class="{escape(" ".join(tokens))}"')
        return parts

    def handle_starttag(self, tag, attrs_):
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED_TAGS:
            return
        allowed = ALLOWED_ATTRS.get(tag, set())
        parts = [tag]
        if self.attachments:
            parts += self._attachment_attrs(tag, attrs_)
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


def sanitize(html: str | None, attachments: bool = False, content_for: Callable[[dict], str] | None = None) -> str:
    """Strip any tags/attributes that are not on a small allow-list.

    ``attachments=True`` also keeps the rich editor's Trix attachments (images, files,
    mentions and blocks), rebuilt from known keys; ``content_for(data)`` gives the
    (already safe) HTML shown for a mention or block.
    """
    if not html:
        return ""
    p = _Sanitizer(attachments, content_for)
    p.feed(str(html))
    p.close()
    return "".join(p.out)
