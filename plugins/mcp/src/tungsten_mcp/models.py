"""Tables of the MCP plugin."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
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
    #: set for tokens an app got by OAuth (its ``client_id``); None for tokens made on the screen
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    #: OAuth access tokens expire; the app swaps its refresh token for a new pair
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class McpOAuthClient(McpBase):
    """An AI app that registered itself (OAuth dynamic client registration)."""

    __tablename__ = "tungsten_mcp_oauth_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), unique=True)
    #: None for public clients (apps on a computer), which prove themselves with PKCE alone
    secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    redirect_uris: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class McpOAuthCode(McpBase):
    """A one-time code, given to the app after the user pressed Allow."""

    __tablename__ = "tungsten_mcp_oauth_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    client_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
