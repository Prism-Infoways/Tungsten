"""Install your Tungsten panel like an app, on phones and computers.

    from tungsten_pwa import PWAPlugin

    panel.plugin(PWAPlugin())

The plugin adds a web app manifest, app icons, a service worker and an
offline page. Pages are never cached: they always come from the server, so
logins, CSRF and permissions work as before and nobody sees old or someone
else's data. Only CSS, JavaScript, images and fonts are cached, which makes
the panel open faster.

Other plugins can add app shortcuts (the menu shown on a long press of the
app icon) with a ``pwa_shortcuts(panel)`` method, or by calling
``panel.get_plugin("pwa").add_shortcut(...)``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from markupsafe import Markup, escape

from tungsten import Plugin
from tungsten.i18n import __
from tungsten.support.colors import DEFAULT_COLORS, resolve_palette
from tungsten.support.icons import icon

__all__ = ["PWAPlugin"]
__version__ = "0.1.0"

log = logging.getLogger("tungsten.pwa")

HERE = Path(__file__).parent
DISPLAYS = ("standalone", "fullscreen", "minimal-ui", "browser")
#: pages and the manifest must always be fresh
NO_CACHE = {"Cache-Control": "no-cache"}
BASE = "/_tw/pwa"


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _file_hash(name: str) -> str:
    try:
        return hashlib.sha1((HERE / "static" / name).read_bytes()).hexdigest()[:10]
    except OSError:  # pragma: no cover
        return __version__


class PWAPlugin(Plugin):
    id = "pwa"
    static = HERE / "static"
    templates = HERE / "templates"

    def __init__(
        self,
        *,
        name: str | None = None,
        short_name: str | None = None,
        description: str | None = None,
        theme_color: str | None = None,
        background_color: str = "#ffffff",
        display: str = "standalone",
        start_path: str = "",
        icons: Iterable[dict] | None = None,
        apple_touch_icon: str | None = None,
        shortcuts: Iterable[Any] = (),
        categories: Iterable[str] = ("business", "productivity"),
        precache: Iterable[str] = (),
        install_button: bool = True,
        offline_banner: bool = True,
        offline_title: str = "You are offline",
        offline_text: str = "Check your internet connection. This page opens again by itself when you are back online.",
        uninstall: bool = False,
    ) -> None:
        if display not in DISPLAYS:
            raise ValueError(f"display must be one of {', '.join(DISPLAYS)}, not {display!r}")
        for label, value in (("theme_color", theme_color), ("background_color", background_color)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{label} must be a CSS color such as '#f97316'")
        self.name = name
        self.short_name = short_name
        self.description = description
        self.theme_color = theme_color
        self.background_color = background_color
        self.display = display
        self.start_path = start_path.strip("/")
        self.icons = [dict(i) for i in icons] if icons is not None else None
        for i in self.icons or []:
            if not i.get("src"):
                raise ValueError("every icon needs a 'src', e.g. {'src': '/static/icon-512.png', 'sizes': '512x512'}")
        self.apple_touch_icon = apple_touch_icon
        self.categories = list(categories)
        self.precache = list(precache)
        self.install_button = install_button
        self.offline_banner = offline_banner
        self.offline_title = offline_title
        self.offline_text = offline_text
        #: True serves a service worker that removes itself and its caches from every browser that has it
        self.uninstall = uninstall
        self._shortcuts: list[Any] = list(shortcuts)
        self.panel: Any = None
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ plugin
    def register(self, panel: Any) -> None:
        self.panel = panel
        panel.routes(self._routes)
        if self.uninstall:
            return
        panel.render_hook("head.end", self._head)
        if self.install_button:
            panel.render_hook("topbar.end", self._install_button)
        if self.offline_banner:
            panel.render_hook("body.end", self._offline_bar)

    def add_shortcut(self, label: str, url: str, description: str | None = None,
                     icon: str | None = None) -> PWAPlugin:
        """Add an app shortcut. ``url`` is a panel path (``"orders/create"``) or a full path (``"/admin/orders"``)."""
        self._shortcuts.append({"name": label, "url": url, "description": description, "icon": icon})
        self._cache.clear()
        return self

    # ------------------------------------------------------------------ urls
    @property
    def scope(self) -> str:
        return self.panel.url("")

    def url(self, name: str) -> str:
        return f"{self.panel.path}{BASE}/{name}"

    def file_url(self, name: str, versioned: bool = False) -> str:
        url = self.panel.plugin_asset(self.id, name)
        return f"{url}?v={_file_hash(name)}" if versioned else url

    def _panel_url(self, url: str) -> str:
        if url.startswith(("/", "http://", "https://")):
            return url
        path, _, query = url.partition("?")
        return self.panel.url(path) + (f"?{query}" if query else "")

    # ------------------------------------------------------------------ values
    def get_theme_color(self) -> str:
        if self.theme_color:
            return self.theme_color
        try:
            value = {**DEFAULT_COLORS, **(self.panel.colors or {})}["primary"]
            return _hex(resolve_palette(value)[500])
        except Exception:  # an odd color value must never break the panel
            log.warning("tungsten-pwa: could not read the primary color, using orange", exc_info=True)
            return "#f97316"

    def get_icons(self) -> list[dict]:
        if self.icons is not None:
            return [{k: v for k, v in i.items() if v is not None} for i in self.icons]
        return [
            {"src": self.file_url("icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": self.file_url("icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": self.file_url("icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ]

    def get_apple_touch_icon(self) -> str:
        if self.apple_touch_icon:
            return self.apple_touch_icon
        if self.icons:
            return self.icons[0]["src"]
        return self.file_url("apple-touch-icon.png")

    def _small_icon(self) -> str:
        if self.icons:
            return self.icons[0]["src"]
        return self.file_url("icon-192.png")

    def get_shortcuts(self) -> list[dict]:
        """Shortcuts from the plugin options, ``add_shortcut`` and other plugins' ``pwa_shortcuts(panel)``."""
        items: list[Any] = list(self._shortcuts)
        for plugin in getattr(self.panel, "_plugins", []):
            if plugin is self:
                continue
            fn = getattr(plugin, "pwa_shortcuts", None)
            if fn is None:
                continue
            try:
                found = fn(self.panel) if callable(fn) else fn
                items.extend(found or [])
            except Exception:  # one broken plugin must not break the app for everyone
                log.warning("tungsten-pwa: %s.pwa_shortcuts() failed", type(plugin).__name__, exc_info=True)
        out: list[dict] = []
        seen: set[str] = set()
        for item in items:
            entry = self._shortcut(item)
            if entry is None or entry["url"] in seen:
                continue
            seen.add(entry["url"])
            out.append(entry)
        return out

    def _shortcut(self, item: Any) -> dict | None:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            item = {"name": item[0], "url": item[1], "description": item[2] if len(item) > 2 else None}
        if not isinstance(item, dict):
            log.warning("tungsten-pwa: skipped shortcut %r: use (label, url) or a dict", item)
            return None
        name = str(item.get("name") or item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not url:
            log.warning("tungsten-pwa: skipped shortcut %r: it needs a name and a url", item)
            return None
        entry: dict[str, Any] = {"name": name, "url": self._panel_url(url)}
        if item.get("short_name"):
            entry["short_name"] = str(item["short_name"])
        if item.get("description"):
            entry["description"] = str(item["description"])
        src = item.get("icon") if isinstance(item.get("icon"), str) and "/" in item.get("icon", "") else None
        entry["icons"] = [{"src": src or self._small_icon(), "sizes": item.get("icon_sizes") or ("any" if src else "192x192")}]
        return entry

    # ------------------------------------------------------------------ documents
    def manifest(self) -> dict:
        if "manifest" not in self._cache:
            panel = self.panel
            name = self.name or panel.brand_name
            data: dict[str, Any] = {
                "id": self.scope,
                "name": name,
                "short_name": self.short_name or name,
                "start_url": self._panel_url(self.start_path) if self.start_path else self.scope,
                "scope": self.scope,
                "display": self.display,
                "background_color": self.background_color,
                "theme_color": self.get_theme_color(),
                "lang": str(panel.locale).replace("_", "-"),
                "icons": self.get_icons(),
            }
            if self.description or panel.brand_tagline:
                data["description"] = self.description or panel.brand_tagline
            if self.categories:
                data["categories"] = self.categories
            shortcuts = self.get_shortcuts()
            if shortcuts:
                data["shortcuts"] = shortcuts
            self._cache["manifest"] = data
        return self._cache["manifest"]

    def precache_urls(self) -> list[str]:
        panel = self.panel
        urls = [panel.asset(a) for a in ("tungsten.css", "tungsten.js", "vendor/htmx.min.js", "vendor/alpine.min.js")]
        favicon = panel.favicon or panel.asset("favicon.svg")
        if favicon.startswith("/") and not favicon.startswith("//"):
            urls.append(favicon)
        urls.append(self._small_icon())
        urls += [self._panel_url(u) for u in self.precache]
        out: list[str] = []
        for u in urls:
            if u.startswith("/") and not u.startswith("//") and u not in out:
                out.append(u)
        return out

    def service_worker(self) -> str:
        if "sw" not in self._cache:
            source = (HERE / "static" / "sw.js").read_text(encoding="utf-8")
            config: dict[str, Any] = {
                "cachePrefix": f"tungsten-pwa-{self.panel.id}-",
                "offline": self.url("offline"),
                "sw": self.url("sw.js"),
                "uninstall": self.uninstall,
                "precache": [] if self.uninstall else self.precache_urls(),
                "offlineHash": hashlib.sha1(self.offline_html().encode()).hexdigest()[:10],
            }
            # a new version (new assets, settings or plugin) makes browsers install the worker again
            config["version"] = hashlib.sha1((source + json.dumps(config, sort_keys=True)).encode()).hexdigest()[:12]
            # "<" is escaped so no setting can end the script early
            prelude = "self.TW_PWA = " + json.dumps(config).replace("<", "\\u003c") + ";\n"
            self._cache["sw"] = prelude + source
        return self._cache["sw"]

    def offline_html(self) -> str:
        if "offline" not in self._cache:
            panel = self.panel
            self._cache["offline"] = panel.renderer.render(
                "tungsten_pwa/offline.html",
                lang=str(panel.locale).replace("_", "-"),
                app_name=self.name or panel.brand_name,
                title=self.offline_title,
                text=self.offline_text,
                retry="Try again",
                icon=self._small_icon(),
                theme_color=self.get_theme_color(),
                background_color=self.background_color,
            )
        return self._cache["offline"]

    # ------------------------------------------------------------------ html hooks
    def _head(self) -> Markup:
        if "head" not in self._cache:
            name = escape(self.short_name or self.name or self.panel.brand_name)
            self._cache["head"] = Markup(
                f'<link rel="manifest" href="{escape(self.url("manifest.webmanifest"))}">'
                f'<meta name="theme-color" content="{escape(self.get_theme_color())}">'
                '<meta name="mobile-web-app-capable" content="yes">'
                '<meta name="apple-mobile-web-app-capable" content="yes">'
                f'<meta name="apple-mobile-web-app-title" content="{name}">'
                '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
                f'<link rel="apple-touch-icon" href="{escape(self.get_apple_touch_icon())}">'
                f'<script defer src="{escape(self.file_url("pwa.js", versioned=True))}" '
                f'data-sw="{escape(self.url("sw.js"))}" data-scope="{escape(self.scope)}"></script>'
            )
        return self._cache["head"]

    def _install_button(self, user: Any = None) -> Markup:
        label = escape(__("Install app"))
        return Markup(
            f'<button type="button" data-tw-pwa-install style="display:none" '
            f'class="tw-icon-btn h-10 w-10 text-gray-500 dark:text-gray-400" title="{label}" aria-label="{label}">'
            f'{icon("monitor-down", "h-5 w-5")}</button>'
        )

    def _offline_bar(self) -> Markup:
        text = escape(__("You are offline. Changes can't be saved until you are back online."))
        return Markup(
            '<div id="tw-pwa-offline" role="status" aria-live="polite" style="display:none;position:fixed;z-index:70;'
            'left:50%;bottom:16px;transform:translateX(-50%);max-width:calc(100% - 32px);align-items:center;gap:8px;'
            'padding:8px 14px;border-radius:9999px;background:#18181b;color:#fff;font-size:14px;'
            'box-shadow:0 10px 25px -5px rgb(0 0 0 / .3)">'
            f'{icon("wifi-off", "h-4 w-4")}<span>{text}</span></div>'
        )

    # ------------------------------------------------------------------ routes
    def _routes(self, app: Any, panel: Any) -> None:
        from starlette.responses import HTMLResponse, Response

        plugin = self

        @app.get(f"{BASE}/manifest.webmanifest", include_in_schema=False)
        async def pwa_manifest():
            if plugin.uninstall:
                return Response(status_code=404)
            body = json.dumps(plugin.manifest(), ensure_ascii=False, separators=(",", ":"))
            return Response(body, media_type="application/manifest+json", headers=NO_CACHE)

        @app.get(f"{BASE}/sw.js", include_in_schema=False)
        async def pwa_service_worker():
            return Response(plugin.service_worker(), media_type="text/javascript",
                            headers={**NO_CACHE, "Service-Worker-Allowed": plugin.scope})

        @app.get(f"{BASE}/offline", include_in_schema=False)
        async def pwa_offline():
            return HTMLResponse(plugin.offline_html(), headers={**NO_CACHE, "X-Robots-Tag": "noindex"})
