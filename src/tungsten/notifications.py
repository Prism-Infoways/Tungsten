"""Notifications: toast messages and the in-app notification bell.

    Notification("Saved").body("The product was updated.").success().send(ctx)
    Notification("New order").body("#ORD-0012 was placed").icon("shopping-cart").send_to_database(admins, ctx)
"""

from __future__ import annotations

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

    def action(self, label: str, url: str, color: str = "primary") -> "Notification":
        """A link button inside the notification."""
        self._actions.append({"label": label, "url": url, "color": color})
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
        for user in _as_list(users):
            db.add(DatabaseNotification(user_id=_user_key(user), data=self.to_dict()))
        db.commit()
        return self


def with_icon_svg(data: dict[str, Any]) -> dict[str, Any]:
    """Toast data plus its icon drawn as ``<svg>``, so any icon of the panel's set shows in the browser."""
    from .support.icons import icon

    if not data.get("icon") or data.get("icon_svg"):
        return data
    return {**data, "icon_svg": str(icon(data["icon"], "h-4 w-4"))}


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
