"""Per-request context object passed through Tungsten (``ctx`` in closures)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from .notifications import Notification
    from .panel import Panel


class Context:
    """Everything a handler needs: the panel, request, DB session, user and tenant."""

    def __init__(self, panel: "Panel", request: Request, db: "Session") -> None:
        self.panel = panel
        self.request = request
        self.db = db
        self.user: Any = None
        self.tenant: Any = None
        self.notifications: list[dict] = []
        self.events: dict[str, Any] = {}
        self.redirect_to: str | None = None
        self._permissions: set[str] | None = None

    # ------------------------------------------------------------------ helpers
    @property
    def filters(self) -> dict[str, Any]:
        """Dashboard filter values (from the dashboard's ``filters_form``)."""
        if not hasattr(self, "_filters"):
            dashboard = self.panel.dashboard
            self._filters = dashboard.get_filters(self) if dashboard is not None else {}
        return self._filters

    @property
    def session(self) -> dict:
        return self.request.session

    @property
    def is_htmx(self) -> bool:
        return self.request.headers.get("HX-Request") == "true"

    def url(self, *parts: Any, **query: Any) -> str:
        return self.panel.url(*parts, **query)

    def can(self, permission: str, record: Any = None) -> bool:
        return self.panel.auth.check(self, permission, record)

    def notify(self, notification: "Notification | dict") -> None:
        data = notification if isinstance(notification, dict) else notification.to_dict()
        self.notifications.append(data)

    def dispatch(self, event: str, detail: Any = None) -> None:
        """Fire a browser event (``HX-Trigger``) after the response arrives."""
        self.events[event] = detail if detail is not None else True

    def redirect(self, url: str) -> None:
        self.redirect_to = url

    # ------------------------------------------------------------------ responses
    def flash(self) -> None:
        """Keep pending notifications for the next full page load."""
        if self.notifications:
            pending = self.session.get("tw_flash", [])
            self.session["tw_flash"] = pending + self.notifications
            self.notifications = []

    def pop_flash(self) -> list[dict]:
        return self.session.pop("tw_flash", []) if "session" in self.request.scope else []

    def finalize(self, response: Response) -> Response:
        """Attach notifications/events as ``HX-Trigger`` (partial) or flash them (redirect)."""
        redirecting = (
            response.status_code in (301, 302, 303, 307, 308)
            or "HX-Redirect" in response.headers
            or "HX-Refresh" in response.headers
            or "HX-Location" in response.headers
        )
        if redirecting:
            self.flash()
        events = dict(self.events)
        if self.notifications:
            events["tw-notify"] = self.notifications
            self.notifications = []
        if events:
            response.headers["HX-Trigger"] = json.dumps(events, default=str)
        return response

    def html(self, content: str, status_code: int = 200, headers: dict | None = None) -> HTMLResponse:
        return self.finalize(HTMLResponse(str(content), status_code=status_code, headers=headers))  # type: ignore[return-value]

    def go(self, url: str) -> Response:
        """Redirect, using ``HX-Redirect`` for HTMX requests."""
        if self.is_htmx:
            return self.finalize(Response(status_code=204, headers={"HX-Redirect": url}))
        return self.finalize(RedirectResponse(url, status_code=303))

    def refresh(self) -> Response:
        if self.is_htmx:
            return self.finalize(Response(status_code=204, headers={"HX-Refresh": "true"}))
        return self.finalize(RedirectResponse(self.request.headers.get("referer") or self.panel.url(), status_code=303))

    def render(self, template: str, **context: Any) -> HTMLResponse:
        if not self.is_htmx:
            self.flash()  # a full page shows pending toasts itself; HX-Trigger only works for HTMX requests
        return self.html(self.panel.render_page(self, template, **context))
