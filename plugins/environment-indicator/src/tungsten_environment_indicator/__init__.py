"""Environment indicator for Tungsten: a Local / Staging / Live badge, so nobody works on live by mistake.

    from tungsten_environment_indicator import EnvironmentIndicatorPlugin

    panel.plugin(EnvironmentIndicatorPlugin())

The environment comes from ``TUNGSTEN_ENV``, ``APP_ENV``, ``ENVIRONMENT``, ``ENV``, ``FASTAPI_ENV`` or
``PYTHON_ENV``. With none of them set, a panel opened on ``localhost`` is Local and anything else is
Live, so a forgotten setting never hides the Live warning.

It adds a colored badge to the top bar and the sign-in page, a thin colored line on top of every
page, and ``[Live]`` in front of the browser tab title. Other plugins can show the same badge::

    from tungsten_environment_indicator import environment_of

    env = environment_of(panel, ctx)   # None when the plugin is not installed
    if env and env.is_production: ...
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from typing import Any

from markupsafe import Markup, escape

from tungsten import Plugin
from tungsten.i18n import translate as __
from tungsten.support.evaluate import call

from .environment import (
    COLORS,
    ENV_VARS,
    FALLBACK_COLOR,
    LABELS,
    PALETTE,
    Environment,
    color_value,
    default_label,
    from_env_vars,
    git_branch,
    host_of,
    is_local_host,
    normalise,
    text_color_for,
)

__version__ = "0.1.0"
__all__ = ["ENV_VARS", "PALETTE", "Environment", "EnvironmentIndicatorPlugin", "environment_of"]

log = logging.getLogger("tungsten.environment_indicator")

PLUGIN_ID = "environment-indicator"


class EnvironmentIndicatorPlugin(Plugin):
    """``EnvironmentIndicatorPlugin(environment=None, ...)``.

    - ``environment``: the name (``"local"``, ``"staging"``, ``"production"``...) or ``fn() -> name``.
      ``None`` reads the environment variables, then guesses from the address (localhost is Local).
    - ``label`` / ``color``: change the text or color for the current environment.
    - ``labels`` / ``colors``: per environment, e.g. ``colors={"staging": "orange", "qa": "#0ea5e9"}``.
    - ``visible``: ``True``, ``False`` or ``fn(user, ctx) -> bool``, e.g. only for admins.
    - ``hide_in``: environments that show nothing, e.g. ``("production",)`` for a customer panel.
    - ``badge``, ``border``, ``title_prefix``, ``login``: turn single parts off.
    - ``git_branch``: show the branch in the badge (read from ``.git/HEAD``, no command runs).
    - ``border_width``: the colored line's height in pixels (0 to 12).
    """

    id = PLUGIN_ID

    def __init__(self, environment: str | Callable[[], str] | None = None, *, label: str | None = None,
                 color: str | None = None, labels: dict[str, str] | None = None,
                 colors: dict[str, str] | None = None, visible: bool | Callable[..., bool] = True,
                 hide_in: Iterable[str] = (), badge: bool = True, border: bool = True, title_prefix: bool = True,
                 login: bool = True, git_branch: bool = False, border_width: int = 3) -> None:
        if environment is not None and not callable(environment) and not normalise(environment):
            raise ValueError("environment must be a name like 'local' or 'production', or None to detect it")
        self.environment = environment
        self.label = label
        # check every color now, so a typo fails at start-up and not on the first page
        self.color = color_value(color) if color is not None else None
        self.labels = {normalise(k): str(v) for k, v in (labels or {}).items()}
        self.colors = {normalise(k): color_value(v) for k, v in (colors or {}).items()}
        self.visible = visible
        self.hide_in = {normalise(name) for name in ([hide_in] if isinstance(hide_in, str) else hide_in)}
        self.show_badge = badge
        self.show_border = border
        self.show_title_prefix = title_prefix
        self.show_login = login
        self.show_git_branch = git_branch
        try:
            self.border_width = max(0, min(12, int(border_width)))
        except (TypeError, ValueError):
            raise ValueError("border_width must be a whole number of pixels") from None
        self.panel: Any = None
        #: your main app, seen by ``panel.mount(app)``, for the debug warning
        self.app: Any = None
        self._fixed: str | None = None
        self._branch: str | None = None
        self._branch_read = False

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        panel.render_hook("head.end", self._head)
        panel.render_hook("body.start", self._border)
        panel.render_hook("topbar.end", self._topbar)
        panel.render_hook("auth.login.form.after", self._login)

    def boot(self, panel: Any) -> None:
        self.refresh()

    def mount(self, app: Any, panel: Any) -> None:
        self.app = app

    def refresh(self) -> None:
        """Read the environment and git branch again (they are read once and kept)."""
        self._fixed = None
        self._branch_read = False
        self._fixed = self._configured_name()
        self._read_branch()

    # ------------------------------------------------------------------ what to show
    def _configured_name(self) -> str:
        """The name from ``environment=`` or the environment variables; ``""`` if neither says."""
        value = self.environment
        if callable(value):
            try:
                value = value()
            except Exception:
                log.exception("environment= callback failed; guessing the environment instead")
                value = None
        return normalise(value) or from_env_vars()

    def _read_branch(self) -> None:
        if self.show_git_branch and not self._branch_read:
            self._branch = git_branch()
            self._branch_read = True

    def name(self, ctx: Any = None) -> str:
        if self._fixed is None:
            self.refresh()
        if self._fixed:
            return self._fixed
        request_host = self._request_host(getattr(ctx, "request", None))
        app_url = getattr(self.panel, "app_url", None)
        if is_local_host(request_host) or (request_host is None and is_local_host(host_of(app_url))):
            return "local"
        # nothing set and not on this machine: assume live, the safe guess
        return "production"

    @staticmethod
    def _request_host(request: Any) -> str | None:
        """The host the browser asked for; ``None`` without a request.

        Behind a proxy (nginx, Apache, a load balancer) the app often sees ``Host: 127.0.0.1``, so a
        forwarded request only counts as local when its forwarded host is local too.
        """
        if request is None:
            return None
        try:
            headers = request.headers
            forwarded_host = headers.get("x-forwarded-host") or ""
            if forwarded_host:
                return forwarded_host.split(",")[0].strip()
            if headers.get("forwarded") or headers.get("x-forwarded-for") or headers.get("x-real-ip"):
                return ""  # proxied, and we can't see the real host: not local
            return headers.get("host") or request.url.hostname or ""
        except Exception:  # noqa: BLE001 - a fake or broken request should never break the page
            return ""

    def current(self, ctx: Any = None) -> Environment:
        """The environment this request runs in, with its label and colors."""
        name = self.name(ctx)
        if self.label is not None:
            label = str(self.label)
        else:
            label = self.labels.get(name) or default_label(name)
        color = self.color or self.colors.get(name) or PALETTE[COLORS.get(name, FALLBACK_COLOR)]
        self._read_branch()
        debug = bool(getattr(self.app, "debug", False)) if self.app is not None else False
        return Environment(name=name, label=label, color=color, text_color=text_color_for(color),
                           branch=self._branch if self.show_git_branch else None, debug=debug)

    def is_visible(self, ctx: Any = None, user: Any = None) -> bool:
        if self.name(ctx) in self.hide_in:
            return False
        if callable(self.visible):
            if user is None:
                user = getattr(ctx, "user", None)
            try:
                return bool(call(self.visible, user=user, ctx=ctx, panel=self.panel))
            except Exception:
                # showing the badge by mistake is better than hiding a Live warning by mistake
                log.exception("visible= callback failed; showing the environment badge")
                return True
        return bool(self.visible)

    # ------------------------------------------------------------------ HTML other plugins can use too
    def title_prefix(self, ctx: Any = None) -> str:
        return f"[{self.current(ctx).label}] "

    def tooltip(self, env: Environment) -> str:
        parts = [__("Environment: :name", name=env.label)]
        if env.branch:
            parts.append(__("Branch: :branch", branch=env.branch))
        if env.debug and env.is_production:
            parts.append(__("Debug mode is on. Turn it off on live."))
        return " · ".join(parts)

    def badge(self, ctx: Any = None, *, size: str = "sm") -> Markup:
        """The badge as HTML. ``size`` is ``"sm"`` (top bar) or ``"lg"`` (sign-in page, banners)."""
        env = self.current(ctx)
        extra = f" · {env.branch}" if env.branch else ""
        warning = (" · " + __("debug on")) if env.debug and env.is_production else ""
        font, pad = ("13px", "4px 12px") if size == "lg" else ("12px", "2px 10px")
        style = (f"display:inline-flex;align-items:center;gap:6px;min-width:0;padding:{pad};"
                 f"border-radius:9999px;background:{env.color};color:{env.text_color};font-size:{font};"
                 "font-weight:600;line-height:20px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"
                 "box-shadow:0 1px 2px rgb(0 0 0 / .15)")
        dot = (f'<span aria-hidden="true" style="flex:none;width:6px;height:6px;border-radius:9999px;'
               f'background:{env.text_color};opacity:.85"></span>')
        tip = self.tooltip(env)
        return Markup(f'<span class="tw-env-badge" data-environment="{escape(env.name)}" role="status" '
                      f'title="{escape(tip)}" aria-label="{escape(tip)}" style="{style}">{dot}'
                      f'<span style="overflow:hidden;text-overflow:ellipsis">{escape(env.label)}'
                      f'<span class="tw-env-extra">{escape(extra)}</span>{escape(warning)}</span></span>')

    def mcp_instructions(self) -> str:
        """Read by the MCP plugin, so AI assistants know when they are working on live data."""
        env = self.current()
        if env.is_production:
            return (f"This panel is the {env.label} (production) environment: changes affect real data and "
                    "real customers. Be careful and confirm before changing or deleting anything.")
        return f"This panel is the {env.label} environment ({env.name}), not live."

    # ------------------------------------------------------------------ render hooks
    def _safe(self, ctx: Any, part: Callable[[Any], str]) -> Markup:
        try:
            if not self.is_visible(ctx):
                return Markup("")
            return Markup(part(ctx))
        except Exception:  # never break a page because of the badge
            log.exception("Environment indicator failed to render")
            return Markup("")

    def _head(self, ctx: Any) -> Markup:
        def part(ctx: Any) -> str:
            # small screens: a short badge, so the top bar's own buttons keep their place
            style = ("<style>.tw-env-badge{max-width:15rem}@media (max-width:640px){.tw-env-badge{max-width:7.5rem}"
                     ".tw-env-badge .tw-env-extra{display:none}}</style>")
            if not self.show_title_prefix:
                return style
            prefix = json.dumps(self.title_prefix(ctx)).replace("<", "\\u003c").replace(">", "\\u003e")
            # keeps the prefix after htmx page swaps and title changes, without adding it twice
            return style + ("<script>(function(){var p=" + prefix + ";function f(){var t=document.title||'';"
                    "if(t.indexOf(p)!==0){document.title=p+t;}}f();"
                    "document.addEventListener('htmx:afterSettle',f);"
                    "document.addEventListener('DOMContentLoaded',function(){var el=document.querySelector("
                    "'head > title');if(el&&window.MutationObserver){new MutationObserver(f).observe(el,"
                    "{childList:true,characterData:true,subtree:true});}f();});})();</script>")

        return self._safe(ctx, part)

    def _border(self, ctx: Any) -> Markup:
        if not self.show_border or not self.border_width:
            return Markup("")

        def part(ctx: Any) -> str:
            env = self.current(ctx)
            return (f'<div class="tw-env-border" aria-hidden="true" style="position:fixed;top:0;left:0;right:0;'
                    f'height:{self.border_width}px;background:{env.color};z-index:2147483000;'
                    'pointer-events:none"></div>')

        return self._safe(ctx, part)

    def _topbar(self, ctx: Any) -> Markup:
        if not self.show_badge:
            return Markup("")
        return self._safe(ctx, lambda ctx: str(self.badge(ctx)))

    def _login(self, ctx: Any) -> Markup:
        if not self.show_login:
            return Markup("")

        def part(ctx: Any) -> str:
            return ('<p style="margin:0;display:flex;flex-wrap:wrap;align-items:center;justify-content:center;'
                    f'gap:8px;font-size:13px"><span style="opacity:.75">{escape(__("You are signing in to"))}</span> '
                    f'{self.badge(ctx, size="lg")}</p>')

        return self._safe(ctx, part)


def environment_of(panel: Any, ctx: Any = None) -> Environment | None:
    """The panel's environment, or ``None`` when the environment indicator plugin is not installed."""
    get = getattr(panel, "get_plugin", None)
    plugin = get(PLUGIN_ID) if get else None
    if not isinstance(plugin, EnvironmentIndicatorPlugin):
        return None
    return plugin.current(ctx)


# keep the defaults importable for people who want to build on them
DEFAULT_LABELS = dict(LABELS)
DEFAULT_COLORS = {name: PALETTE[color] for name, color in COLORS.items()}
