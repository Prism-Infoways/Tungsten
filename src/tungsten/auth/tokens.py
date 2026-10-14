"""Personal API tokens, like Laravel Sanctum.

Turn them on with ``Auth(User, api_tokens=True, api_abilities=["orders:read", "orders:write"])``.
Users make and revoke tokens on the "API tokens" page (linked from their
profile). Protect your own FastAPI routes with :meth:`Panel.api_user`::

    @app.get("/api/orders")
    def orders(user=Depends(panel.api_user("orders:read"))):
        ...

Clients send ``Authorization: Bearer <token>``. Only a SHA-256 hash of each
token is stored, so a token is shown once, right after it is made.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from typing import TYPE_CHECKING, Any, Callable

from fastapi import HTTPException, Request
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

if TYPE_CHECKING:  # pragma: no cover
    from ..panel import Panel

PREFIX = "tw_"
#: ``last_used_at`` is written at most this often, so busy clients don't write on every call
TOUCH_SECONDS = 60


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ability_options(panel: "Panel") -> dict[str, str]:
    """``{ability: label}`` from ``Auth(api_abilities=...)``."""
    raw = panel.auth.api_abilities
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    return {str(a): str(a) for a in raw}


def create(db: Any, panel: "Panel", user: Any, name: str, abilities: list[str] | None = None,
           expires_at: dt.datetime | None = None) -> tuple[Any, str]:
    """Make a token for ``user``. Returns ``(row, plain_token)``; keep the plain token, it can't be shown again."""
    from ..models import ApiToken

    plain = PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(user_id=panel.auth.user_id(user), name=(name or "").strip()[:100] or "Token",
                   token_hash=hash_token(plain), abilities=list(abilities if abilities is not None else ["*"]),
                   expires_at=expires_at)
    db.add(row)
    db.commit()
    return row, plain


def for_user(db: Any, panel: "Panel", user: Any) -> list:
    from ..models import ApiToken

    uid = panel.auth.user_id(user)
    return list(db.scalars(select(ApiToken).where(ApiToken.user_id == uid).order_by(ApiToken.id.desc())))


def revoke(db: Any, panel: "Panel", user: Any, token_id: Any) -> bool:
    from ..models import ApiToken

    try:
        tid = int(token_id)
    except (TypeError, ValueError):
        return False
    row = db.get(ApiToken, tid)
    if row is None or row.user_id != panel.auth.user_id(user):
        return False
    db.delete(row)
    db.commit()
    return True


def authenticate(db: Any, panel: "Panel", plain: str) -> tuple[Any, Any] | None:
    """``(user, token)`` for a valid, unexpired token of an active user, else ``None``."""
    from ..models import ApiToken

    plain = (plain or "").strip()
    if not plain.startswith(PREFIX):
        return None
    token = db.scalars(select(ApiToken).where(ApiToken.token_hash == hash_token(plain))).first()
    if token is None:
        return None
    now = dt.datetime.now()
    if token.expires_at is not None and token.expires_at <= now:
        return None
    auth = panel.auth
    user = auth.find_by_id(db, token.user_id)
    if user is None or not auth.is_active(user):
        return None
    if token.last_used_at is None or (now - token.last_used_at).total_seconds() >= TOUCH_SECONDS:
        token.last_used_at = now
        db.commit()
        db.refresh(user)
    db.refresh(token)
    db.expunge(user)  # the route gets plain, already loaded objects; its own DB session is separate
    db.expunge(token)
    return user, token


def bearer(request: Any) -> str:
    header = request.headers.get("authorization") or ""
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def dependency(panel: "Panel", abilities: tuple[str, ...]) -> Callable:
    """A FastAPI dependency giving the token's user (401 without a valid token, 403 without an ability)."""
    async def api_user(request: Request) -> Any:
        plain = bearer(request)
        found = None
        if plain:
            if panel.is_async:
                async with panel.session_factory() as adb:
                    found = await adb.run_sync(lambda db: authenticate(db, panel, plain))
            else:
                def run() -> Any:
                    with panel.session_factory() as db:
                        return authenticate(db, panel, plain)

                found = await run_in_threadpool(run)
        if found is None:
            raise HTTPException(status_code=401, detail="Invalid or missing API token.",
                                headers={"WWW-Authenticate": "Bearer"})
        user, token = found
        missing = [a for a in abilities if not token.can(a)]
        if missing:
            raise HTTPException(status_code=403, detail=f"This token can't {missing[0]}.")
        request.state.tungsten_token = token
        request.state.tungsten_user = user
        return user

    return api_user


__all__ = ["ability_options", "authenticate", "create", "dependency", "for_user", "hash_token", "revoke"]
