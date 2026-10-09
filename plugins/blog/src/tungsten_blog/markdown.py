"""Turn a post into Markdown, for ``/blog/<slug>.md`` and ``llms.txt``: the easiest form for AI tools to read."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from .text import items, strip_tags


class _Markdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.lists: list[list[Any]] = []  # [kind, counter]
        self.href: list[str | None] = []
        self.pre = False
        self.skip = 0

    def write(self, text: str) -> None:
        self.out.append(text)

    def block(self) -> None:
        self.write("\n\n")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self.block()
            self.write("#" * int(tag[1]) + " ")
        elif tag in ("p", "div", "figure", "table"):
            self.block()
        elif tag == "br":
            self.write("  \n")
        elif tag in ("strong", "b"):
            self.write("**")
        elif tag in ("em", "i"):
            self.write("*")
        elif tag == "code" and not self.pre:
            self.write("`")
        elif tag == "pre":
            self.pre = True
            self.block()
            self.write("```\n")
        elif tag == "blockquote":
            self.block()
            self.write("> ")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            if len(self.lists) == 1:
                self.block()
        elif tag == "li":
            indent = "  " * (len(self.lists) - 1)
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.write(f"\n{indent}{self.lists[-1][1]}. ")
            else:
                self.write(f"\n{indent}- ")
        elif tag == "a":
            self.href.append(a.get("href"))
            self.write("[")
        elif tag == "img":
            self.write(f"![{a.get('alt') or ''}]({a.get('src') or ''})")
        elif tag == "tr":
            self.write("\n|")
        elif tag in ("td", "th"):
            self.write(" ")
        elif tag == "hr":
            self.block()
            self.write("---")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("strong", "b"):
            self.write("**")
        elif tag in ("em", "i"):
            self.write("*")
        elif tag == "code" and not self.pre:
            self.write("`")
        elif tag == "pre":
            self.pre = False
            self.write("\n```")
            self.block()
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            if not self.lists:
                self.block()
        elif tag == "a":
            href = self.href.pop() if self.href else None
            self.write(f"]({href})" if href else "]")
        elif tag in ("td", "th"):
            self.write(" |")
        elif tag in ("h1", "h2", "h3", "h4", "p", "blockquote", "table"):
            self.block()

    def handle_data(self, data):
        if self.skip:
            return
        self.write(data if self.pre else re.sub(r"\s+", " ", data))


def html_to_markdown(value: Any) -> str:
    parser = _Markdown()
    parser.feed(str(value or ""))
    parser.close()
    text = "".join(parser.out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def post_markdown(site: Any, post: Any) -> str:
    """The whole post as Markdown, with its summary, key points, steps, FAQs and sources."""
    lines = [f"# {post.title}", ""]
    meta = []
    if post.author is not None:
        meta.append(f"By {post.author.name}")
    if post.published_at:
        meta.append(post.published_at.strftime("%Y-%m-%d"))
    if post.updated_at and post.published_at and post.updated_at.date() > post.published_at.date():
        meta.append(f"updated {post.updated_at:%Y-%m-%d}")
    meta.append(site.post_url(post))
    lines += [" · ".join(meta), ""]
    if post.summary:
        lines += [f"> **Summary:** {strip_tags(post.summary)}", ""]
    points = items(post.key_points, "text")
    if points:
        lines += ["## Key points", ""] + [f"- {strip_tags(p['text'])}" for p in points] + [""]
    body = html_to_markdown(post.content)
    if body:
        lines += [body, ""]
    steps = items(post.howto_steps, "text")
    if steps and post.howto_title:
        lines += [f"## {post.howto_title}", ""]
        for i, step in enumerate(steps, start=1):
            name = f"**{step['name']}**: " if step.get("name") else ""
            lines.append(f"{i}. {name}{strip_tags(step['text'])}")
        lines.append("")
    faqs = items(post.faqs, "question", "answer")
    if faqs:
        lines += ["## Frequently asked questions", ""]
        for faq in faqs:
            lines += [f"### {strip_tags(faq['question'])}", "", strip_tags(faq["answer"]), ""]
    sources = items(post.sources, "url")
    if sources:
        lines += ["## Sources", ""] + [f"- [{s.get('title') or s['url']}]({s['url']})" for s in sources] + [""]
    return "\n".join(lines).strip() + "\n"
