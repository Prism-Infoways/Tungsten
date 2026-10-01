"""Jinja2 rendering for Tungsten templates."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, select_autoescape
from markupsafe import Markup

from .forms.base import grid_class, span_class
from .support import colors
from .support.html import attrs
from .support.icons import icon


def _tojson_attr(value: Any) -> Markup:
    """JSON safe to place inside a single- or double-quoted HTML attribute."""
    from html import escape

    return Markup(escape(json.dumps(value, default=str), quote=True))


def _format_number(value: Any, decimals: int = 0) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


class Renderer:
    def __init__(self, template_dirs: Iterable[str | Path] = ()) -> None:
        loaders = [FileSystemLoader([str(p) for p in template_dirs])] if template_dirs else []
        loaders.append(PackageLoader("tungsten", "templates"))
        self.env = Environment(
            loader=ChoiceLoader(loaders),
            autoescape=select_autoescape(["html", "xml"], default_for_string=True),
            trim_blocks=True,
            lstrip_blocks=True,
            extensions=["jinja2.ext.do"],
        )
        self.env.globals.update(
            icon=icon,
            attrs=attrs,
            colors=colors,
            grid_class=grid_class,
            span_class=span_class,
            tojson_attr=_tojson_attr,
        )
        self.env.filters["number"] = _format_number
        self.env.filters["attr_json"] = _tojson_attr
        self.env.filters["ord_value"] = lambda ch: ord(str(ch)[0]) if ch else 0

    def render(self, name: str, **context: Any) -> Markup:
        return Markup(self.env.get_template(name).render(**context))

    def render_string(self, source: str, **context: Any) -> Markup:
        return Markup(self.env.from_string(source).render(**context))


@lru_cache(maxsize=1)
def default_renderer() -> Renderer:
    return Renderer()
