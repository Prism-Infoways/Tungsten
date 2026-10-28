"""Notifications: toast messages and the in-app notification bell.

    Notification("Saved").body("The product was updated.").success().send(ctx)
    Notification("New order").body("#ORD-0012 was placed").icon("shopping-cart").send_to_database(admins, ctx)
    Notification("Export ready").action("Download", url).broadcast(user, ctx)      # live toast in open tabs
    Notification("Invoice paid").body("INV-0042 was paid").send_to_mail(user, ctx)  # email via Auth(mailer=...)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Iterable

from .i18n import translate as __

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context

STATUS_ICONS = {
    "success": "circle-check",
    "danger": "circle-x",
    "warning": "triangle-alert",
    "info": "info",
}


class Notification:
    def __init__(self, title: str = "") -> None:
        self._title = title
        self._body: str | None = None
        self._status: str | None = None
        self._icon: str | None = None
        self._color: str | None = None
        self._duration: int | None = 5000
        self._actions: list[dict] = []

    @classmethod
    def make(cls, title: str = "") -> "Notification":
        return cls(title)

    def title(self, title: str) -> "Notification":
        self._title = title
        return self

    def body(self, body: str | None) -> "Notification":
        self._body = body
        return self

    def status(self, status: str) -> "Notification":
        self._status = status
        return self

    def success(self) -> "Notification":
        return self.status("success")

    def danger(self) -> "Notification":
        return self.status("danger")

    def warning(self) -> "Notification":
        return self.status("warning")

    def info(self) -> "Notification":
        return self.status("info")

    def icon(self, icon: str) -> "Notification":
        self._icon = icon
        return self

    def color(self, color: str) -> "Notification":
        self._color = color
        return self

    def duration(self, ms: int | None) -> "Notification":
        """Milliseconds before the toast hides. ``None`` keeps it until closed."""
        self._duration = ms
        return self

    def persistent(self) -> "Notification":
        return self.duration(None)

    def action(self, label: str, url: str, color: str = "primary", new_tab: bool = False) -> "Notification":
        """A link button inside the notification. ``new_tab=True`` opens it in a new tab."""
        item = {"label": label, "url": url, "color": color}
        if new_tab:
            item["new_tab"] = True
        self._actions.append(item)
        return self

    def to_dict(self, translate: bool = False) -> dict[str, Any]:
        """Plain data. ``translate=True`` puts title, body and action labels into the current language."""
        status = self._status
        tr = __ if translate else (lambda text: text)
        return {
            "title": tr(self._title),
            "body": tr(self._body) if self._body else self._body,
            "status": status,
            "icon": self._icon or STATUS_ICONS.get(status or "", "bell"),
            "color": self._color or status or "gray",
            "duration": self._duration,
            "actions": [{**a, "label": tr(a["label"])} for a in self._actions],
        }

    # ------------------------------------------------------------------ sending
    def send(self, ctx: "Context") -> "Notification":
        """Show as a toast on the current response (translated into the user's language)."""
        ctx.notify(self.to_dict(translate=True))
        return self

    def send_to_database(self, users: Any, ctx_or_db: Any) -> "Notification":
        """Store for the notification bell. ``users`` is a user, id or list of either.

        Stored as written, and translated when each user opens the bell."""
        from .models import DatabaseNotification

        db = getattr(ctx_or_db, "db", ctx_or_db)
        keys = [_user_key(user) for user in _as_list(users)]
        for key in keys:
            db.add(DatabaseNotification(user_id=key, data=self.to_dict()))
        db.commit()
        panel = _panel_of(ctx_or_db)
        if panel is not None and panel.notifications_live:
            for key in dict.fromkeys(keys):  # the open bells refresh at once instead of at the next poll
                panel.broadcaster.publish(key, {"type": "notifications"})
        return self

    def broadcast(self, users: Any, ctx_or_db: Any) -> "Notification":
        """Show as a toast right now in every open tab of ``users`` (a user, id or list), over the live socket.

        Nothing is stored: a user with no tab open never sees it. Pair it with :meth:`send_to_database`
        to keep a copy in the bell."""
        from .broadcast import Broadcaster

        panel = _panel_of(ctx_or_db)
        broadcaster: Broadcaster | None = getattr(panel, "broadcaster", None)
        if broadcaster is None or not panel.notifications_live:
            return self
        message = {"type": "toast", "toast": with_icon_svg(self.to_dict(translate=True))}
        for key in dict.fromkeys(_user_key(user) for user in _as_list(users)):
            broadcaster.publish(key, message)
        return self

    def send_to_mail(self, users: Any, ctx_or_db: Any, subject: str | None = None) -> "Notification":
        """Email the notification through the panel's mailer (``Auth(mailer=...)``).

        ``users`` is a user, a user id, an email address or a list of these. The title is the subject unless
        ``subject`` is given; the body and the action buttons (as full links) make the message. A mailer that
        takes an ``html`` argument also gets an HTML version. A failing mailer is logged and never stops the
        request."""
        from .support.evaluate import call

        panel = _panel_of(ctx_or_db)
        if panel is None:
            raise RuntimeError("send_to_mail needs a request context or a database session of a panel")
        auth = panel.auth
        db = getattr(ctx_or_db, "db", ctx_or_db)
        ctx = ctx_or_db if hasattr(ctx_or_db, "request") else None
        data = self.to_dict(translate=True)
        links = [(a["label"], _absolute(panel, ctx, a["url"])) for a in data["actions"]]
        text = "\n\n".join(part for part in [
            data["body"] or "",
            "\n".join(f"{label}: {url}" for label, url in links),
        ] if part) or data["title"]
        html = _mail_html(data["title"], data["body"], links)
        for user in _as_list(users):
            to = _email_of(auth, db, user)
            if not to:
                continue
            try:
                call(auth.mailer, to=to, subject=subject or data["title"], body=text, html=html, notification=data)
            except Exception:  # noqa: BLE001 - a mail server hiccup must not undo the user's work
                logging.getLogger("tungsten").exception("Could not email notification %r to %s", data["title"], to)
        return self


def with_icon_svg(data: dict[str, Any]) -> dict[str, Any]:
    """Toast data plus its icon drawn as ``<svg>``, so any icon of the panel's set shows in the browser."""
    from .support.icons import icon

    if not data.get("icon") or data.get("icon_svg"):
        return data
    return {**data, "icon_svg": str(icon(data["icon"], "h-4 w-4"))}


def _panel_of(ctx_or_db: Any) -> Any:
    panel = getattr(ctx_or_db, "panel", None)
    if panel is not None:
        return panel
    from .panel import Panel

    return Panel.of(getattr(ctx_or_db, "db", ctx_or_db)) or Panel.only()


def _absolute(panel: Any, ctx: Any, url: str) -> str:
    if not url.startswith("/") or url.startswith("//"):
        return url
    if panel.app_url or ctx is not None:
        return panel.absolute_url(ctx, url)
    return url


def _email_of(auth: Any, db: Any, user: Any) -> str | None:
    if isinstance(user, str) and "@" in user:
        return user
    if isinstance(user, (str, int)):
        if not auth.enabled:
            return None
        user = auth.find_by_id(db, user)
        if user is None:
            return None
    return getattr(user, auth.email_field, None) or None


def _mail_html(title: str, body: str | None, links: list[tuple[str, str]]) -> str:
    from markupsafe import escape

    buttons = "".join(
        f'<p><a href="{escape(url)}" style="display:inline-block;padding:10px 18px;border-radius:8px;'
        f'background:#4f46e5;color:#fff;text-decoration:none;font-weight:600">{escape(label)}</a></p>'
        for label, url in links)
    text = f'<p style="margin:0 0 16px;color:#374151;white-space:pre-line">{escape(body)}</p>' if body else ""
    return (f'<div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:24px">'
            f'<h1 style="font-size:18px;margin:0 0 12px;color:#111827">{escape(title)}</h1>{text}{buttons}</div>')


def _user_key(user: Any) -> str:
    """The user's primary key as text (the bell looks users up the same way), or the id given as is."""
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.exc import NoInspectionAvailable

    try:
        mapper = sa_inspect(type(user))
    except NoInspectionAvailable:
        return str(getattr(user, "id", user))
    return str(getattr(user, mapper.primary_key[0].key))


def _as_list(value: Any) -> Iterable:
    if isinstance(value, (list, tuple, set)):
        return value
    return [value]
