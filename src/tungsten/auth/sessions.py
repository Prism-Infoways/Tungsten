"""Sign-ins the server knows about, so signing out ends a session for every copy of its cookie (issue #103).

The session cookie is signed, not stored, so without this a saved copy of it keeps working after logout until it
expires. ``Auth.login`` starts a server-side session and keeps its id in the cookie; every request checks it is
still there; ``Auth.logout`` deletes it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import secrets
import time
from typing import Any, Protocol

log = logging.getLogger("tungsten.auth")


class SessionStore(Protocol):
    """Where sign-ins are kept. Swap it with ``Auth(sessions=...)`` (e.g. Redis); ``Auth(sessions=False)`` turns
    server-side sessions off."""

    def start(self, db: Any, user_id: str) -> str:
        """Record a new sign-in for ``user_id`` and return its id ("" when it could not be recorded)."""

    def alive(self, db: Any, session_id: str, user_id: str, max_age: float | None) -> bool | None:
        """True while the sign-in exists (and is younger than ``max_age`` seconds). None when the store can't tell."""

    def end(self, db: Any, session_id: str) -> None:
        """Forget the sign-in (signing out)."""

    def end_all(self, db: Any, user_id: str) -> None:
        """Forget every sign-in of ``user_id`` (e.g. after a password change)."""


def _hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


class DatabaseSessions:
    """Sign-ins in Tungsten's ``tungsten_sessions`` table (made by ``panel.create_tables(engine)``).

    Until that table exists, sessions work as before (cookie only) and a warning is logged once.
    """

    def __init__(self) -> None:
        self._ready: bool | None = None
        self._checked_at = 0.0
        self._warned = False

    def _table_ready(self, db: Any) -> bool:
        if self._ready:
            return True
        now = time.monotonic()
        if self._ready is False and now - self._checked_at < 60:
            return False
        from sqlalchemy import inspect as sa_inspect

        from ..models import AuthSession

        self._checked_at = now
        try:
            self._ready = bool(sa_inspect(db.get_bind()).has_table(AuthSession.__tablename__))
        except Exception:  # noqa: BLE001 - no way to look: keep the old behaviour
            self._ready = False
        if not self._ready and not self._warned:
            self._warned = True
            log.warning("Table %s is missing: signing out does not end other copies of a session cookie. "
                        "Run panel.create_tables(engine) once.", AuthSession.__tablename__)
        return self._ready

    def start(self, db: Any, user_id: str) -> str:
        if not self._table_ready(db):
            return ""
        from ..models import AuthSession

        session_id = secrets.token_urlsafe(32)
        db.add(AuthSession(id=_hash(session_id), user_id=str(user_id)))
        db.commit()
        return session_id

    def alive(self, db: Any, session_id: str, user_id: str, max_age: float | None) -> bool | None:
        if not self._table_ready(db):
            return None
        from ..models import AuthSession

        row = db.get(AuthSession, _hash(session_id)) if session_id else None
        if row is None or row.user_id != str(user_id):
            return False
        if max_age and row.created_at and row.created_at < dt.datetime.now() - dt.timedelta(seconds=max_age):
            return False
        return True

    def end(self, db: Any, session_id: str) -> None:
        if not session_id or not self._table_ready(db):
            return
        from ..models import AuthSession

        row = db.get(AuthSession, _hash(session_id))
        if row is not None:
            db.delete(row)
            db.commit()

    def end_all(self, db: Any, user_id: str) -> None:
        if not self._table_ready(db):
            return
        from sqlalchemy import delete

        from ..models import AuthSession

        db.execute(delete(AuthSession).where(AuthSession.user_id == str(user_id)))
        db.commit()
