"""Saved views without the web layer: cleaning a table address, and reading and writing views."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode

from sqlalchemy import or_, select

from .models import SavedView, SavedViewDefault

#: table settings a view keeps; anything else in the address (page number, open panels...) is dropped
STATE_KEYS = frozenset({"tab", "search", "sort", "direction", "per_page", "group", "_f"})
STATE_PREFIXES = ("filters.", "col_search.")
MAX_NAME = 80
MAX_QUERY = 4000
MAX_PAIRS = 200
COLORS = ("gray", "primary", "info", "success", "warning", "danger")


class ViewError(ValueError):
    """A view can't be saved; the message is shown to the user."""


@dataclass
class Preset:
    """A view written in code that every user sees on one resource."""

    key: str
    resource: str
    name: str
    query: str
    icon: str | None = None
    color: str = "gray"
    #: ``fn(ctx, user)`` returning False hides the preset from that user
    visible: Callable | None = None


@dataclass
class ViewItem:
    """One chip in the views bar, for templates and for other plugins."""

    key: str
    name: str
    query: str
    url: str
    icon: str | None = None
    color: str = "gray"
    shared: bool = False
    mine: bool = False
    editable: bool = False
    preset: bool = False
    is_default: bool = False
    match: str = ""
    id: int | None = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------- the address
def query_pairs(raw: Any) -> list[tuple[str, str]]:
    """The table settings in a query string (``?a=1&b=2``), in order, without empty values."""
    if raw is None:
        return []
    if not isinstance(raw, str):  # starlette QueryParams / a dict / a list of pairs
        items = raw.multi_items() if hasattr(raw, "multi_items") else (raw.items() if isinstance(raw, dict) else raw)
        raw = urlencode([(str(k), str(v)) for k, v in items])
    raw = raw.strip().lstrip("?")
    if len(raw) > MAX_QUERY * 3:  # far past anything a real table makes; don't parse it
        raise ViewError("These filters are too long to save.")
    out = []
    for key, value in parse_qsl(raw, keep_blank_values=False):
        if key in STATE_KEYS or key.startswith(STATE_PREFIXES):
            out.append((key, value))
    if any(k.startswith("filters.") for k, _ in out) and not any(k == "_f" for k, _ in out):
        out.append(("_f", "1"))  # the table only reads filters from the address when _f is there
    seen_f = False
    deduped = []
    for key, value in out:
        if key == "_f":
            if seen_f:
                continue
            seen_f, value = True, "1"
        deduped.append((key, value))
    if len(deduped) > MAX_PAIRS:
        raise ViewError("These filters are too long to save.")
    return deduped


def clean_query(raw: Any) -> str:
    query = urlencode(query_pairs(raw))
    if len(query) > MAX_QUERY:
        raise ViewError("These filters are too long to save.")
    return query


def match_key(raw: Any) -> str:
    """Two addresses with the same key show the same table (order and page don't matter)."""
    try:
        pairs = query_pairs(raw)
    except ViewError:
        return ""
    pairs = [(k, v) for k, v in pairs if k != "_f"]
    return json.dumps(sorted(pairs), separators=(",", ":"), ensure_ascii=False)


def expand(query: str, user_id: str, today: dt.date | None = None) -> str:
    """Fill ``{me}`` (the signed-in user's id) and ``{today}`` in a view's values."""
    if "%7B" not in query and "{" not in query:
        return query
    day = (today or dt.date.today()).isoformat()
    pairs = [(k, v.replace("{me}", user_id).replace("{today}", day)) for k, v in parse_qsl(query)]
    return urlencode(pairs)


def clean_name(name: Any) -> str:
    name = " ".join(str(name or "").split())
    if not name:
        raise ViewError("Give the view a name.")
    if len(name) > MAX_NAME:
        raise ViewError(f"Keep the name under {MAX_NAME} letters.")
    return name


# ---------------------------------------------------------------------- reading and writing
def views_query(user_id: str, tenant_key: str, resource: str):
    """The user's own views plus the ones others shared, for one resource."""
    return (select(SavedView)
            .where(SavedView.resource == resource, SavedView.tenant_key == tenant_key,
                   or_(SavedView.user_id == user_id, SavedView.is_shared.is_(True)))
            .order_by(SavedView.sort, SavedView.id))


def count_own(db: Any, user_id: str, tenant_key: str, resource: str) -> int:
    from sqlalchemy import func

    return int(db.scalar(select(func.count()).select_from(SavedView).where(
        SavedView.user_id == user_id, SavedView.tenant_key == tenant_key, SavedView.resource == resource)) or 0)


def name_taken(db: Any, user_id: str, tenant_key: str, resource: str, name: str, skip_id: int | None = None) -> bool:
    rows = db.scalars(select(SavedView).where(
        SavedView.user_id == user_id, SavedView.tenant_key == tenant_key, SavedView.resource == resource)).all()
    return any(r.name.casefold() == name.casefold() and r.id != skip_id for r in rows)


def get_default(db: Any, user_id: str, tenant_key: str, resource: str) -> SavedViewDefault | None:
    return db.scalars(select(SavedViewDefault).where(
        SavedViewDefault.user_id == user_id, SavedViewDefault.tenant_key == tenant_key,
        SavedViewDefault.resource == resource)).first()


def set_default(db: Any, user_id: str, tenant_key: str, resource: str, view_key: str | None) -> None:
    """Make ``view_key`` the user's default for the resource (``None``: open the plain list)."""
    row = get_default(db, user_id, tenant_key, resource)
    if not view_key:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(SavedViewDefault(user_id=user_id, tenant_key=tenant_key, resource=resource, view_key=view_key))
    else:
        row.view_key = view_key


def forget_view(db: Any, view: SavedView) -> None:
    """Delete a view and every user's default that pointed at it."""
    for row in db.scalars(select(SavedViewDefault).where(SavedViewDefault.view_key == str(view.id))).all():
        db.delete(row)
    db.delete(view)
