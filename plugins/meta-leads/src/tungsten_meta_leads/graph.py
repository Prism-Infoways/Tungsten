"""A small client for Meta's Graph API, using only the standard library."""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterator

GRAPH_HOST = "https://graph.facebook.com"
DIALOG_HOST = "https://www.facebook.com"

#: ``transport(method, url, body) -> (status, text)``; swap it in tests
Transport = Callable[[str, str, "bytes | None"], "tuple[int, str]"]


class GraphError(Exception):
    """Meta said no. ``str(error)`` is Meta's own message."""


def urllib_transport(method: str, url: str, body: bytes | None) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https host
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def signature_ok(app_secret: str, body: bytes, header: str | None) -> bool:
    """Check the ``X-Hub-Signature-256`` header Meta puts on webhook calls."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


class Graph:
    def __init__(self, version: str = "v21.0", app_secret: str | None = None,
                 transport: Transport | None = None) -> None:
        self.version = version
        self.app_secret = app_secret
        self.transport = transport or urllib_transport

    def url(self, path: str) -> str:
        if path.startswith("https://"):
            return path
        return f"{GRAPH_HOST}/{self.version}/{path.lstrip('/')}"

    def dialog_url(self, app_id: str, redirect_uri: str, state: str, scopes: list[str]) -> str:
        query = urllib.parse.urlencode({"client_id": app_id, "redirect_uri": redirect_uri, "state": state,
                                        "scope": ",".join(scopes), "response_type": "code"})
        return f"{DIALOG_HOST}/{self.version}/dialog/oauth?{query}"

    def _params(self, params: dict[str, Any] | None) -> dict[str, str]:
        out = {k: (json.dumps(v) if isinstance(v, (list, dict)) else str(v))
               for k, v in (params or {}).items() if v is not None}
        token = out.get("access_token")
        if token and self.app_secret and "|" not in token:
            out["appsecret_proof"] = hmac.new(self.app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
        return out

    def request(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.url(path)
        data = self._params(params)
        body = None
        if method == "GET":
            if data:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(data)
        else:
            body = urllib.parse.urlencode(data).encode()
        status, text = self.transport(method, url, body)
        try:
            payload = json.loads(text) if text else {}
        except ValueError:
            raise GraphError(f"Meta sent an unreadable answer (HTTP {status}).") from None
        if status >= 400 or (isinstance(payload, dict) and "error" in payload):
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            raise GraphError(error.get("error_user_msg") or error.get("message") or f"HTTP {status}")
        return payload if isinstance(payload, dict) else {"data": payload}

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self.request("GET", path, params)

    def post(self, path: str, **params: Any) -> dict[str, Any]:
        return self.request("POST", path, params)

    def paginate(self, path: str, limit: int = 500, **params: Any) -> Iterator[dict[str, Any]]:
        """Yield rows of ``data`` across pages, at most ``limit`` rows."""
        page = self.get(path, **params)
        count = 0
        while True:
            for row in page.get("data", []):
                yield row
                count += 1
                if count >= limit:
                    return
            following = page.get("paging", {}).get("next")
            if not following:
                return
            page = self.request("GET", following)
