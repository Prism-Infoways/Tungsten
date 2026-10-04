"""Jinja2 rendering for Tungsten templates."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, PackageLoader, Template, select_autoescape
from markupsafe import Markup

from .forms.base import grid_class, span_class
from .i18n import current_locale, is_rtl, js_translations, translate
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


class _PackageLoader(PackageLoader):
    """Built-in templates never change while the app runs, so skip the per-render file check."""

    def get_source(self, environment: Environment, template: str) -> tuple[str, str, Any]:
        source, filename, _ = super().get_source(environment, template)
        return source, filename, lambda: True


class _Template(Template):
    """Faster ``{% import %}``: Jinja diffs the globals against a slow ChainMap on every import."""

    _tw_keys: frozenset | None = None

    def _get_default_module(self, ctx: Any = None) -> Any:
        if ctx is not None:
            if self._tw_keys is None:
                self._tw_keys = frozenset(self.globals)
            if ctx.globals_keys - self._tw_keys:  # rare: fall back to Jinja's own handling
                return super()._get_default_module(ctx)
        if self._module is None:
            self._module = self.make_module()
        return self._module


class Renderer:
    def __init__(self, template_dirs: Iterable[str | Path] = ()) -> None:
        loaders = [FileSystemLoader([str(p) for p in template_dirs])] if template_dirs else []
        loaders.append(_PackageLoader("tungsten", "templates"))
        self._loader = ChoiceLoader(loaders)
        self.env = Environment(
            loader=self._loader,
            autoescape=select_autoescape(["html", "xml"], default_for_string=True),
            trim_blocks=True,
            lstrip_blocks=True,
            extensions=["jinja2.ext.do"],
            cache_size=1000,
        )
        self.env.template_class = _Template
        self.env.globals.update(
            icon=icon,
            attrs=attrs,
            colors=colors,
            grid_class=grid_class,
            span_class=span_class,
            tojson_attr=_tojson_attr,
            __=translate,
            _=translate,
            current_locale=current_locale,
            is_rtl=is_rtl,
            js_translations=js_translations,
        )
        self.env.filters["number"] = _format_number
        self.env.filters["attr_json"] = _tojson_attr
        self.env.filters["ord_value"] = lambda ch: ord(str(ch)[0]) if ch else 0

    def add_dir(self, path: str | Path) -> None:
        """Look for templates in ``path`` too: after your own ``template_dirs``, before the built-in ones."""
        self._loader.loaders.insert(len(self._loader.loaders) - 1, FileSystemLoader(str(path)))
        if self.env.cache is not None:
            self.env.cache.clear()

    def render(self, name: str, **context: Any) -> Markup:
        return Markup(self.env.get_template(name).render(**context))

    def render_string(self, source: str, **context: Any) -> Markup:
        return Markup(self.env.from_string(source).render(**context))


@lru_cache(maxsize=1)
def default_renderer() -> Renderer:
    return Renderer()
