"""MCP over stdin/stdout, for apps that start the server as a command (``python -m myapp.mcp_stdio``).

One JSON-RPC message (or batch) per line in, one answer per line out. Every message runs as one user, picked by
whoever starts the command, like a token made for them: their roles, policies and tenancy apply.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

from .server import INVALID_REQUEST, PARSE_ERROR, _error


def serve(plugin: Any, user: Any = None, *, can_write: bool = False, stdin: Any = None, stdout: Any = None,
          tenant: Any = None) -> None:
    """Answer messages from ``stdin`` until it closes. ``user`` is a user or a user id."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    panel = plugin.panel
    auth = panel.auth
    user_id = None if user is None else (auth.user_id(user) if not isinstance(user, (str, int)) else str(user))
    row = SimpleNamespace(can_write=can_write)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        answer = handle_line(plugin, line, user_id, row, tenant)
        if answer is not None:
            stdout.write(json.dumps(answer, ensure_ascii=False) + "\n")
            stdout.flush()


def handle_line(plugin: Any, line: str, user_id: str | None, row: Any, tenant: Any = None) -> Any:
    """The answer to one line (None for notifications only)."""
    from tungsten.jobs import background_context

    try:
        body = json.loads(line)
    except ValueError:
        return _error(None, PARSE_ERROR, "Parse error")
    messages = body if isinstance(body, list) else [body]
    if not messages or not all(isinstance(m, dict) for m in messages):
        return _error(None, INVALID_REQUEST, "Invalid request")

    def run(db: Any) -> list:
        ctx = background_context(plugin.panel, db, user_id, tenant)
        if plugin.panel.auth.enabled and ctx.user is None:
            return [_error(m.get("id"), INVALID_REQUEST, "The MCP user no longer exists or is switched off.")
                    for m in messages if "id" in m]
        plugin.authenticated(ctx)
        return [plugin.server.handle(ctx, row, m) for m in messages]

    answers = [a for a in plugin.panel.with_session(run) if a is not None]
    if not answers:
        return None
    return answers if isinstance(body, list) else answers[0]
