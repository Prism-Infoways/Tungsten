"""A small Markdown to HTML converter with no dependencies.

Used by :class:`~tungsten.forms.MarkdownEditor` to show the preview and to save HTML
next to the Markdown. It covers the everyday subset: headings, paragraphs, bold,
italic, strike-through, inline code, fenced code blocks, links, images, quotes,
bullet and numbered lists, task lists, tables and horizontal rules. The result is
passed through :func:`~tungsten.support.html.sanitize`, so user text can't add scripts.
The editor's live preview in the browser follows the same rules (``tungsten.js``).
"""

from __future__ import annotations

import re

from markupsafe import Markup, escape

from .html import sanitize

_FENCE = re.compile(r"^(```|~~~)\s*([\w+-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _inline(text: str) -> str:
    """Escape ``text`` and turn the inline marks into tags."""
    out: list[str] = []
    pos = 0
    # protect inline code first, so marks inside it are left alone
    for m in re.finditer(r"`([^`\n]+)`", text):
        out.append(_marks(text[pos:m.start()]))
        out.append(f"<code>{escape(m.group(1))}</code>")
        pos = m.end()
    out.append(_marks(text[pos:]))
    return "".join(out)


def _marks(text: str) -> str:
    links: list[str] = []

    def keep(html: str) -> str:
        links.append(html)
        return f"\x00{len(links) - 1}\x00"

    def image(m: re.Match) -> str:
        return keep(f'<img src="{escape(m.group(2))}" alt="{escape(m.group(1))}">')

    def link(m: re.Match) -> str:
        return keep(f'<a href="{escape(m.group(2))}">{_marks(m.group(1))}</a>')

    def bare(m: re.Match) -> str:
        return keep(f'<a href="{escape(m.group(1))}">{escape(m.group(1))}</a>')

    s = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", image, text)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
    s = re.sub(r"(?<![\w/])(https?://[^\s<]+[^\s<.,;:!?)])", bare, s)
    s = str(escape(s))
    s = re.sub(r"(?<![\w*])\*\*(?=\S)(.+?)(?<=\S)\*\*(?![\w*])", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w_])__(?=\S)(.+?)(?<=\S)__(?![\w_])", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", r"<em>\1</em>", s)
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", s)
    s = s.replace("  \n", "<br>\n")
    return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], s)


def _list_item(text: str) -> str:
    task = _TASK.match(text)
    if task:
        box = "&#9745;" if task.group(1) in "xX" else "&#9744;"
        return f"<li>{box} {_inline(task.group(2))}</li>"
    return f"<li>{_inline(text)}</li>"


def markdown_to_html(text: str | None) -> Markup:
    """Convert Markdown to safe HTML (a :class:`~markupsafe.Markup`)."""
    if not text:
        return Markup("")
    lines = str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    stack: list[tuple[str, int, bool]] = []  # open lists: (tag, indent, nested inside an item)
    quote: list[str] = []
    i = 0

    def flush_para() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(s.strip() for s in para))}</p>")
            para.clear()

    def close_lists(to_indent: int = -1) -> None:
        while stack and stack[-1][1] > to_indent:
            tag, _, nested = stack.pop()
            out.append(f"</{tag}></li>" if nested else f"</{tag}>")

    def flush_quote() -> None:
        if quote:
            out.append(f"<blockquote>{markdown_to_html(chr(10).join(quote))}</blockquote>")
            quote.clear()

    def flush_all() -> None:
        flush_para()
        close_lists()
        flush_quote()

    while i < len(lines):
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            flush_all()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith(fence.group(1)):
                code.append(lines[i])
                i += 1
            lang = f' class="language-{escape(fence.group(2))}"' if fence.group(2) else ""
            out.append(f"<pre><code{lang}>{escape(chr(10).join(code))}</code></pre>")
            i += 1
            continue
        if not line.strip():
            flush_all()
            i += 1
            continue
        if line.lstrip().startswith(">"):
            flush_para()
            close_lists()
            quote.append(line.lstrip()[1:].lstrip())
            i += 1
            continue
        flush_quote()
        if _HR.match(line):
            flush_para()
            close_lists()
            out.append("<hr>")
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_para()
            close_lists()
            out.append(f"<h{len(heading.group(1))}>{_inline(heading.group(2))}</h{len(heading.group(1))}>")
            i += 1
            continue
        # a table: a header row, a separator row, then rows
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush_para()
            close_lists()
            cells = lambda row: [c.strip() for c in row.strip().strip("|").split("|")]  # noqa: E731
            head = cells(line)
            i += 2
            body: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                body.append(cells(lines[i]))
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead>")
            if body:
                out.append("<tbody>" + "".join(
                    "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in body) + "</tbody>")
            out.append("</table>")
            continue
        item = _UL.match(line) or _OL.match(line)
        if item:
            flush_para()
            tag = "ul" if _UL.match(line) else "ol"
            indent = len(item.group(1).replace("\t", "    "))
            if stack and indent > stack[-1][1]:
                out[-1] = out[-1][:-5]  # keep the item open: the nested list belongs inside it
                out.append(f"<{tag}>")
                stack.append((tag, indent, True))
            else:
                close_lists(indent)
                if stack and stack[-1][1] == indent and stack[-1][0] != tag:
                    close_lists(indent - 1)
                if not stack or stack[-1][1] < indent:
                    out.append(f"<{tag}>")
                    stack.append((tag, indent, False))
            out.append(_list_item(item.group(2)))
            i += 1
            continue
        if stack and line.startswith(" "):  # a wrapped list line
            out[-1] = out[-1][:-5] + " " + _inline(line.strip()) + "</li>"
            i += 1
            continue
        close_lists()
        para.append(line)
        i += 1
    flush_all()
    return Markup(sanitize("\n".join(out)))


def markdown_text(text: str | None) -> str:
    """Markdown with the marks removed: for search indexes and short summaries."""
    html = markdown_to_html(text)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(html))).strip()
