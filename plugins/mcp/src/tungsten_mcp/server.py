"""The MCP endpoint: JSON-RPC 2.0 over "Streamable HTTP" (one POST per message, JSON answers).

Only what tool servers need: ``initialize``, ``ping``, ``tools/list`` and ``tools/call``.
No server-sent events, so no long-lived connections on shared hosting.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from tungsten.context import Context
from tungsten.i18n import reset_locale, set_locale

from .models import McpToken, hash_token
from .tools import ToolError, Tools

log = logging.getLogger("tungsten.mcp")

#: newest first; we answer with the client's version when we know it
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603


def _error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _result(id_: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


class Unauthorized(Exception):
    pass


class McpServer:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.tools = Tools(plugin)

    # ------------------------------------------------------------------ http
    async def handle_http(self, request: Request) -> Response:
        try:
            body = json.loads(await request.body() or b"null")
        except ValueError:
            return JSONResponse(_error(None, PARSE_ERROR, "Parse error"), status_code=400)
        messages = body if isinstance(body, list) else [body]
        if not messages or not all(isinstance(m, dict) for m in messages):
            return JSONResponse(_error(None, INVALID_REQUEST, "Invalid request"), status_code=400)
        token = _bearer(request)
        try:
            answers = await self._run(request, lambda db: self._handle_all(db, request, token, messages))
        except Unauthorized as exc:
            return JSONResponse({"error": "unauthorized", "error_description": str(exc)}, status_code=401,
                                headers={"WWW-Authenticate": 'Bearer realm="tungsten-mcp"'})
        answers = [a for a in answers if a is not None]
        if not answers:  # only notifications
            return Response(status_code=202)
        return JSONResponse(answers if isinstance(body, list) else answers[0])

    async def _run(self, request: Request, fn: Any) -> Any:
        panel = self.plugin.panel
        if panel.is_async:
            async with panel.session_factory() as adb:
                return await adb.run_sync(fn)

        def sync() -> Any:
            with panel.session_factory() as db:
                return fn(db)

        return await run_in_threadpool(sync)

    # ------------------------------------------------------------------ auth
    def authenticate(self, db: Any, request: Request, token: str | None) -> tuple[Context, McpToken]:
        panel = self.plugin.panel
        if not token:
            raise Unauthorized("Send your MCP token as: Authorization: Bearer <token>")
        row = db.scalars(select(McpToken).where(McpToken.token_hash == hash_token(token))).first()
        if row is None:
            raise Unauthorized("This token is not valid. Make a new one in the panel under AI access (MCP).")
        db.info["tungsten_panel"] = panel
        ctx = Context(panel, request, db)
        if panel.auth.enabled:
            user = panel.auth.find_by_id(db, row.user_id) if row.user_id is not None else None
            if user is None or not panel.auth.is_active(user):
                raise Unauthorized("The user of this token no longer exists or is switched off.")
            ctx.user = user
            if not panel.auth.allowed(ctx, user):
                raise Unauthorized("The user of this token may not use the panel.")
        if panel.tenancy.enabled and request.headers.get("x-tenant"):
            ctx.session[panel.tenancy.session_key] = request.headers["x-tenant"]
        ctx.tenant = panel.tenancy.resolve(ctx)
        now = dt.datetime.now()
        if row.last_used_at is None or now - row.last_used_at > dt.timedelta(minutes=1):
            row.last_used_at = now
            db.commit()
        return ctx, row

    # ------------------------------------------------------------------ json-rpc
    def _handle_all(self, db: Any, request: Request, token: str | None, messages: list[dict]) -> list:
        ctx, row = self.authenticate(db, request, token)
        tokens = set_locale(self.plugin.panel.resolve_locale(ctx), self.plugin.panel.translator)
        try:
            return [self.handle(ctx, row, m) for m in messages]
        finally:
            reset_locale(tokens)

    def can_write(self, row: McpToken) -> bool:
        return bool(row.can_write) and not self.plugin.read_only

    def handle(self, ctx: Context, row: McpToken, message: dict) -> dict | None:
        id_ = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return None if "id" not in message else _error(id_, INVALID_REQUEST, "Invalid request")
        if "id" not in message:  # a notification, e.g. notifications/initialized
            return None
        if not isinstance(params, dict):
            return _error(id_, INVALID_PARAMS, "params must be an object")
        if method == "initialize":
            wanted = params.get("protocolVersion")
            return _result(id_, {
                "protocolVersion": wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "tungsten-mcp", "title": self.plugin.server_title(), "version": _version()},
                "instructions": self.plugin.instructions_for(self.can_write(row)),
            })
        if method == "ping":
            return _result(id_, {})
        if method == "tools/list":
            return _result(id_, {"tools": self.tools.definitions(ctx, self.can_write(row))})
        if method == "tools/call":
            return self.call_tool(ctx, row, id_, params)
        return _error(id_, METHOD_NOT_FOUND, f"Method not found: {method}")

    def call_tool(self, ctx: Context, row: McpToken, id_: Any, params: dict) -> dict:
        name = params.get("name")
        args = params.get("arguments") or {}
        allowed = Tools.READ + (Tools.WRITE if self.can_write(row) else ())
        if name in Tools.WRITE and name not in allowed:
            return _result(id_, _tool_error("This token can only read. Make a token with \"Allow changes\" "
                                            "switched on to create, update or delete records."))
        if name not in allowed:
            return _error(id_, INVALID_PARAMS, f"Unknown tool: {name}")
        if not isinstance(args, dict):
            return _error(id_, INVALID_PARAMS, "arguments must be an object")
        try:
            result = self.tools.call(ctx, name, args)
        except ToolError as exc:
            ctx.db.rollback()
            return _result(id_, _tool_error(str(exc), exc.details))
        except TypeError as exc:  # wrong or missing arguments
            ctx.db.rollback()
            return _result(id_, _tool_error(f"Wrong arguments for {name}: {exc}"))
        except PermissionError as exc:
            ctx.db.rollback()
            return _result(id_, _tool_error(str(exc) or "Not allowed."))
        except Exception:
            ctx.db.rollback()
            log.exception("MCP tool %s failed", name)
            return _result(id_, _tool_error(f"{name} failed on the server. The error is in the server log."))
        return _result(id_, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                             "structuredContent": result, "isError": False})


def _tool_error(message: str, details: Any = None) -> dict:
    payload = {"error": message, **(details or {})}
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], "isError": True}


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


def _version() -> str:
    from . import __version__

    return __version__
