"""Opening pages: a small HTTP client that keeps each redirect, and an HTML reader."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse

USER_AGENT = "TungstenSEOAudit/0.1 (+https://tungsten.prisminfoways.com/docs/seo-audit.html)"
#: pages bigger than this are cut (the size is still counted)
MAX_BYTES = 3 * 1024 * 1024


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    #: (url, status) of every redirect on the way, first one first
    redirects: list[tuple[str, int]] = field(default_factory=list)
    elapsed_ms: int = 0
    size: int = 0
    error: str | None = None

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")

    @property
    def is_html(self) -> bool:
        return "html" in self.headers.get("content-type", "html")


#: ``transport(method, url, headers) -> (status, headers, body)`` makes one request without following
#: redirects. Swap it in tests.
Transport = Callable[[str, str, dict], tuple[int, dict, bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def urllib_transport(method: str, url: str, headers: dict) -> tuple[int, dict, bytes]:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with opener.open(req, timeout=15) as res:
            return res.status, {k.lower(): v for k, v in res.headers.items()}, res.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read(MAX_BYTES + 1)


def fetch(url: str, transport: Transport | None = None, method: str = "GET", max_redirects: int = 8) -> Response:
    """Open ``url`` and follow redirects by hand, so each hop is kept."""
    send = transport or urllib_transport
    redirects: list[tuple[str, int]] = []
    started = time.monotonic()
    current = url
    for _ in range(max_redirects + 1):
        try:
            status, headers, body = send(method, current, {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
        except Exception as exc:  # DNS, timeout, refused, bad certificate...
            return Response(current, 0, redirects=redirects, error=str(getattr(exc, "reason", exc)) or "No answer",
                            elapsed_ms=int((time.monotonic() - started) * 1000))
        headers = {k.lower(): v for k, v in headers.items()}
        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            redirects.append((current, status))
            current = urljoin(current, headers["location"])
            continue
        return Response(current, status, headers, body[:MAX_BYTES], redirects,
                        int((time.monotonic() - started) * 1000), len(body))
    return Response(current, 0, redirects=redirects, error="Too many redirects",
                    elapsed_ms=int((time.monotonic() - started) * 1000))


def normalize(url: str) -> str:
    """Same page, same string: no #fragment, lower-case host, "/" for an empty path."""
    url = urldefrag(url)[0]
    p = urlparse(url)
    return p._replace(netloc=p.netloc.lower(), path=p.path or "/").geturl()


@dataclass
class PageInfo:
    """What the audit reads from one HTML page."""

    lang: str | None = None
    title: str | None = None
    titles: int = 0
    meta: dict[str, str] = field(default_factory=dict)
    canonical: str | None = None
    headings: list[tuple[int, str]] = field(default_factory=list)
    images: list[dict[str, str | None]] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # (href, rel)
    hreflang: list[str] = field(default_factory=list)
    json_ld: list[dict] = field(default_factory=list)
    bad_json_ld: int = 0
    microdata: bool = False
    scripts: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    words: int = 0
    text: str = ""

    @property
    def h1(self) -> list[str]:
        return [t for level, t in self.headings if level == 1]


class _Reader(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.info = PageInfo()
        self._stack: list[str] = []
        self._text: list[str] = []
        self._heading: tuple[int, list[str]] | None = None
        self._title: list[str] | None = None
        self._json_ld: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        info = self.info
        if "itemscope" in a:
            info.microdata = True
        if tag == "html":
            info.lang = a.get("lang") or None
        elif tag == "title" and not any(t == "svg" for t in self._stack):
            info.titles += 1
            self._title = []
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if key and key not in info.meta:
                info.meta[key] = a.get("content", "").strip()
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            if "canonical" in rel and info.canonical is None:
                info.canonical = a.get("href", "").strip()
            if "alternate" in rel and a.get("hreflang"):
                info.hreflang.append(a["hreflang"])
            if "stylesheet" in rel and a.get("href"):
                info.styles.append(a["href"])
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = (int(tag[1]), [])
        elif tag == "img":
            info.images.append({"src": a.get("src") or a.get("data-src"), "alt": attrs_get(attrs, "alt"),
                                "loading": a.get("loading"), "width": a.get("width"), "height": a.get("height")})
        elif tag == "a" and a.get("href"):
            info.links.append((a["href"].strip(), a.get("rel", "").lower()))
        elif tag == "script":
            if a.get("type", "").lower() == "application/ld+json":
                self._json_ld = []
            elif a.get("src"):
                info.scripts.append(a["src"])
        if tag not in ("meta", "link", "img", "br", "hr", "input", "source", "area", "base", "col", "wbr"):
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title is not None:
            if self.info.title is None:
                self.info.title = " ".join("".join(self._title).split())
            self._title = None
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            self.info.headings.append((self._heading[0], " ".join("".join(self._heading[1]).split())))
            self._heading = None
        elif tag == "script" and self._json_ld is not None:
            raw = "".join(self._json_ld).strip()
            self._json_ld = None
            try:
                data = json.loads(raw)
            except ValueError:
                self.info.bad_json_ld += 1
            else:
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    graph = item.get("@graph")
                    if isinstance(graph, list):
                        self.info.json_ld.extend(g for g in graph if isinstance(g, dict))
                    else:
                        self.info.json_ld.append(item)
        if tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass

    def handle_data(self, data: str) -> None:
        if self._json_ld is not None:
            self._json_ld.append(data)
            return
        if self._title is not None:
            self._title.append(data)
            return
        if self._heading:
            self._heading[1].append(data)
        if not any(t in self.SKIP for t in self._stack) and "head" not in self._stack:
            self._text.append(data)


def attrs_get(attrs: list, name: str) -> str | None:
    """An attribute's value, None when it is missing (``alt=""`` gives "")."""
    for k, v in attrs:
        if k.lower() == name:
            return v or ""
    return None


def read_html(html: str) -> PageInfo:
    reader = _Reader()
    try:
        reader.feed(html)
        reader.close()
    except Exception:  # broken HTML: keep what was read
        pass
    text = " ".join(" ".join(reader._text).split())
    reader.info.text = text
    reader.info.words = len(text.split())
    return reader.info
