"""MCP resources (documents the AI reads) and prompts (ready-made workflows), beside the tools.

    McpPlugin(
        documents=[McpResource("docs://doc-format", "Doc format", Path("docs/format.md"))],
        prompts=[McpPrompt("set-up-company", "Set up a company: {name}", arguments=["name"])],
    )
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tungsten.support.evaluate import call


@dataclass
class McpResource:
    """A document the AI app can list and read (``resources/list``, ``resources/read``).

    ``content`` is text, bytes, a :class:`~pathlib.Path` (read on each request) or a function. A function
    can ask for ``ctx``, ``db``, ``user`` and ``tenant`` and returns text or bytes. ``can`` (same arguments)
    hides the resource from users who may not read it.
    """

    uri: str
    name: str
    content: Any
    description: str | None = None
    mime_type: str = "text/markdown"
    title: str | None = None
    can: Callable | None = None

    def allowed(self, ctx: Any) -> bool:
        return self.can is None or bool(call(self.can, **_available(ctx)))

    def listing(self) -> dict:
        out = {"uri": self.uri, "name": self.name, "mimeType": self.mime_type}
        if self.title:
            out["title"] = self.title
        if self.description:
            out["description"] = self.description
        return out

    def read(self, ctx: Any) -> dict:
        value = self.content
        if isinstance(value, Path):
            value = value.read_bytes() if not self.mime_type.startswith("text/") else value.read_text("utf-8")
        elif callable(value):
            value = call(value, **_available(ctx))
        out: dict[str, Any] = {"uri": self.uri, "mimeType": self.mime_type}
        if isinstance(value, bytes):
            out["blob"] = base64.b64encode(value).decode()
        else:
            out["text"] = "" if value is None else str(value)
        return out


@dataclass
class PromptArgument:
    name: str
    description: str | None = None
    required: bool = True


@dataclass
class McpPrompt:
    """A ready-made workflow the AI app offers to the user (``prompts/list``, ``prompts/get``).

    ``text`` is a template where ``{argument}`` is replaced by the argument's value, or a function that can
    ask for ``ctx``, ``db``, ``user``, ``tenant``, ``arguments`` and each argument by name. A function may
    return text, or a list of ``{"role": "user" | "assistant", "content": "..."}`` messages.
    """

    name: str
    text: Any
    description: str | None = None
    arguments: list[PromptArgument | str] = field(default_factory=list)
    title: str | None = None
    can: Callable | None = None

    def __post_init__(self) -> None:
        self.arguments = [a if isinstance(a, PromptArgument) else PromptArgument(a) for a in self.arguments]

    def allowed(self, ctx: Any) -> bool:
        return self.can is None or bool(call(self.can, **_available(ctx)))

    def listing(self) -> dict:
        out: dict[str, Any] = {"name": self.name}
        if self.title:
            out["title"] = self.title
        if self.description:
            out["description"] = self.description
        if self.arguments:
            out["arguments"] = [{"name": a.name, **({"description": a.description} if a.description else {}),
                                 "required": a.required} for a in self.arguments]
        return out

    def missing(self, arguments: dict) -> list[str]:
        return [a.name for a in self.arguments if a.required and not str(arguments.get(a.name) or "").strip()]

    def render(self, ctx: Any, arguments: dict) -> dict:
        args = {a.name: str(arguments.get(a.name) or "") for a in self.arguments}
        if callable(self.text):
            value = call(self.text, **_available(ctx), arguments=args, **args)
        else:
            value = str(self.text)
            for name, v in args.items():
                value = value.replace("{" + name + "}", v)
        if isinstance(value, str):
            messages = [{"role": "user", "content": value}]
        else:
            messages = list(value or [])
        out: dict[str, Any] = {"messages": [
            {"role": m.get("role", "user"), "content": {"type": "text", "text": str(m.get("content", ""))}}
            for m in messages]}
        if self.description:
            out["description"] = self.description
        return out


def _available(ctx: Any) -> dict:
    return {"ctx": ctx, "db": ctx.db, "user": ctx.user, "tenant": ctx.tenant}


def check_unique(items: Iterable[Any], key: str, what: str) -> None:
    seen: set[str] = set()
    for item in items:
        value = getattr(item, key)
        if value in seen:
            raise ValueError(f"Two MCP {what} have the same {key}: {value!r}")
        seen.add(value)
