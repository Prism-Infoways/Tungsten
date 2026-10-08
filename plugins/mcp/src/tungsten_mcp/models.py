"""Tables of the MCP plugin."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: every token starts with this, so a leaked one is easy to spot in logs and code
TOKEN_PREFIX = "tgmcp_"


def _now() -> dt.datetime:
    return dt.datetime.now()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class McpBase(DeclarativeBase):
    pass


class McpToken(McpBase):
    """An access token for one AI client. Only its hash is kept; the token itself is shown once."""

    __tablename__ = "tungsten_mcp_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    #: the panel user the AI acts as (their roles and permissions apply); None when the panel has no login
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    #: first characters of the token, to tell tokens apart in the list
    hint: Mapped[str] = mapped_column(String(16))
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
