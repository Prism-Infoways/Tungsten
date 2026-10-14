"""Security headers for every panel response (HSTS, X-Frame-Options, CSP...).

On by default. Change them with ``Panel(security_headers=..., content_security_policy=...)``,
or put :class:`SecurityHeadersMiddleware` on your own app to cover the whole site::

    app.add_middleware(SecurityHeadersMiddleware)
"""

from __future__ import annotations

from typing import Any

#: Works with everything the panel ships: Alpine.js needs ``'unsafe-eval'``, the theme script and
#: htmx need inline code, Google Fonts serve the font. Images may come from any https host (avatars, logos).
DEFAULT_CSP: dict[str, list[str]] = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
    "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
    "font-src": ["'self'", "data:", "https://fonts.gstatic.com"],
    "img-src": ["'self'", "data:", "blob:", "https:"],
    "media-src": ["'self'", "data:", "blob:", "https:"],
    "connect-src": ["'self'"],
    "frame-src": ["'self'"],
    "worker-src": ["'self'", "blob:"],
    "manifest-src": ["'self'"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "frame-ancestors": ["'self'"],
}

DEFAULT_HEADERS: dict[str, str] = {
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

HSTS = "max-age=31536000; includeSubDomains"


def build_csp(policy: Any = True) -> str | None:
    """Turn ``Panel(content_security_policy=...)`` into a header value.

    ``True`` is :data:`DEFAULT_CSP`; a string is used as is; a dict adds sources to the default
    (``{"script-src": ["https://cdn.example.com"]}``), and a ``None`` value removes a directive;
    ``False`` sends no CSP.
    """
    if policy is False or policy is None:
        return None
    if isinstance(policy, str):
        return policy.strip() or None
    directives = {k: list(v) for k, v in DEFAULT_CSP.items()}
    if isinstance(policy, dict):
        for name, sources in policy.items():
            if sources is None:
                directives.pop(name, None)
                continue
            extra = [sources] if isinstance(sources, str) else list(sources)
            current = directives.setdefault(name, [])
            current.extend(s for s in extra if s not in current)
    return "; ".join(f"{name} {' '.join(sources)}".strip() for name, sources in directives.items())


def build_headers(headers: Any = True, csp: Any = True) -> dict[str, str]:
    """``Panel(security_headers=...)``: ``True`` for the defaults, a dict to add/replace (``None`` drops one)."""
    if headers is False or headers is None:
        out: dict[str, str] = {}
    else:
        out = dict(DEFAULT_HEADERS)
        if isinstance(headers, dict):
            for name, value in headers.items():
                if value is None:
                    out.pop(name, None)
                else:
                    out[name] = str(value)
    value = build_csp(csp)
    if value:
        out["Content-Security-Policy"] = value
    return out


class SecurityHeadersMiddleware:
    """ASGI middleware adding security headers to every HTTP response.

    A header the app already set (say a stricter CSP on one route) is kept.
    ``Strict-Transport-Security`` is only sent over HTTPS (or always with ``hsts="always"``),
    so local ``http://`` development keeps working; ``hsts=False`` turns it off.
    """

    def __init__(self, app: Any, headers: Any = True, content_security_policy: Any = True,
                 hsts: Any = True) -> None:
        self.app = app
        self.headers = [(k.lower().encode("latin-1"), v.encode("latin-1"))
                        for k, v in build_headers(headers, content_security_policy).items()]
        self.hsts = hsts

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        secure = scope.get("scheme") == "https" or self.hsts == "always"
        if not secure:
            for name, value in scope.get("headers") or []:
                if name == b"x-forwarded-proto" and value.split(b",")[0].strip() == b"https":
                    secure = True  # behind a proxy that ends TLS
                    break

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                raw = list(message.get("headers") or [])
                present = {name.lower() for name, _ in raw}
                raw.extend((k, v) for k, v in self.headers if k not in present)
                if self.hsts and secure and b"strict-transport-security" not in present:
                    raw.append((b"strict-transport-security", HSTS.encode()))
                message["headers"] = raw
            await send(message)

        await self.app(scope, receive, send_with_headers)


__all__ = ["DEFAULT_CSP", "DEFAULT_HEADERS", "SecurityHeadersMiddleware", "build_csp", "build_headers"]
