"""The few network calls the audit makes: your own site's headers, its certificate, and OSV for packages.

Kept in one small class so tests (and offline setups) can swap it out.
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

OSV_URL = "https://api.osv.dev/v1/querybatch"
USER_AGENT = "tungsten-security-audit"


@dataclass
class Page:
    status: int
    #: header names in lower case
    headers: dict[str, str]
    cookies: list[str] = field(default_factory=list)
    url: str = ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Net:
    timeout = 8

    def get(self, url: str, headers: dict[str, str] | None = None) -> Page:
        """GET without following redirects. Raises ``OSError`` when the site can't be reached."""
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            response = opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:  # 3xx/4xx/5xx still carry headers
            response = exc
        with response:
            raw = response.headers
            return Page(status=response.status if hasattr(response, "status") else response.code,
                        headers={k.lower(): v for k, v in raw.items()},
                        cookies=raw.get_all("Set-Cookie") or [], url=url)

    def cert_days_left(self, url: str) -> float:
        """Days until the site's TLS certificate ends. Raises ``ssl.SSLError`` for a certificate that isn't valid."""
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port or 443
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=self.timeout) as sock, \
                context.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
        ends = ssl.cert_time_to_seconds(cert["notAfter"])
        return (ends - time.time()) / 86400

    def osv(self, packages: list[tuple[str, str]]) -> dict[tuple[str, str], list[str]]:
        """Known vulnerability ids for each ``(name, version)``, from osv.dev. Only names and versions are sent."""
        out: dict[tuple[str, str], list[str]] = {}
        for start in range(0, len(packages), 500):
            chunk = packages[start:start + 500]
            body = json.dumps({"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v}
                                           for n, v in chunk]}).encode()
            request = urllib.request.Request(OSV_URL, data=body, method="POST",
                                             headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                results = json.load(response).get("results", [])
            for pkg, result in zip(chunk, results):
                ids = [v["id"] for v in (result or {}).get("vulns", []) if v.get("id")]
                if ids:
                    out[pkg] = ids
        return out
