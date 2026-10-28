"""Let AI assistants (Claude and other MCP apps) work with your Tungsten panel.

    from tungsten_mcp import McpPlugin

    panel.plugin(McpPlugin())
    panel.create_tables(engine)

Open "AI access (MCP)" in the panel, make a token, and press "How to connect". The panel's
resources then show up in the AI app as tools: list, search, read, and (with a token that
allows changes) create, update and delete records. Every call runs as the token's user, so
their roles, policies and tenancy apply, and writes go through the resource's form.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from tungsten import Plugin

from .extras import McpPrompt, McpResource, PromptArgument, check_unique
from .models import McpBase, McpOAuthClient, McpOAuthCode, McpToken, hash_token, new_token
from .oauth import AuthorizePage, OAuth
from .resources import McpTokenResource
from .server import McpServer
from .tools import SENSITIVE, ToolError, Tools

__version__ = "0.1.4"

DEFAULT_INSTRUCTIONS = (
    "These tools work with the records of a Tungsten admin panel. Start with list_resources, then "
    "describe_resource to see a resource's columns and form fields. list_records finds records "
    "(search, filters, sort, paging); get_record reads one. Each record has _id, _title and a _url "
    "link to it in the panel."
)


class McpPlugin(Plugin):
    """``McpPlugin(path="/mcp", read_only=False, resources=None, exclude=(), hidden_fields=(), max_limit=100)``.

    - ``path``: where the MCP server answers, under the panel (``/admin/mcp``).
    - ``read_only``: no create, update or delete tools for any token.
    - ``resources``: only these resources (slugs or classes). Default: all of them.
    - ``exclude``: resources to leave out (slugs or classes).
    - ``hidden_fields``: columns never sent, as ``"email"`` (every resource) or ``"customers.email"``.
      Passwords, tokens, secrets and API keys are always hidden.
    - ``max_limit``: most records one ``list_records`` call returns.
    - ``name``/``instructions``: what the AI app is told about this server.
    - ``public_url``: this site's address for the URL in "How to connect". Default: the panel's
      ``app_url``, then the address in the browser.
    - ``oauth``: let apps connect by logging in (OAuth 2.1 with PKCE), besides tokens made on
      the screen. Needs a panel with login. ``allow_registration=False`` stops new apps.
    - ``token_minutes``: how long an OAuth access token works before the app refreshes it.
    - ``tools``: a :class:`Tools` subclass, to add tools of your own beside the record ones.
    - ``documents``: :class:`McpResource` items the AI can read (MCP "resources", e.g. a format guide).
    - ``prompts``: :class:`McpPrompt` items, ready-made workflows the AI app offers.
    - ``public_path``: serve MCP at this address of the main app instead of under the panel (e.g. ``"/mcp/x"``
      to keep an old address). Needs ``panel.mount(app)``.
    - ``tokens_label``: what messages call the token screen. Default: its menu label ("AI access (MCP)").
    - ``on_authenticated(ctx)``: runs for every MCP request after the token's user is loaded (the panel's
      ``Auth.load_user`` runs too).

    For apps that start a server as a command, :meth:`run_stdio` serves MCP over stdin/stdout.
    """

    id = "mcp"
    metadata = McpBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, path: str = "/mcp", *, read_only: bool = False, resources: Iterable[Any] | None = None,
                 exclude: Iterable[Any] = (), hidden_fields: Iterable[str] = (), max_limit: int = 100,
                 name: str | None = None, instructions: str | None = None, public_url: str | None = None,
                 oauth: bool = True, allow_registration: bool = True, token_minutes: int = 60,
                 tools: type[Tools] = Tools, documents: Iterable[McpResource] = (),
                 prompts: Iterable[McpPrompt] = (), public_path: str | None = None, tokens_label: str | None = None,
                 on_authenticated: Any = None) -> None:
        self.path = "/" + path.strip("/")
        self.public_path = "/" + public_path.strip("/") if public_path else None
        self._tokens_label = tokens_label
        self.on_authenticated = on_authenticated
        self.read_only = read_only
        self.only = {_slug(r) for r in resources} if resources is not None else None
        self.exclude = {_slug(r) for r in exclude} | {McpTokenResource.get_slug()}
        self.hidden_fields = set(hidden_fields)
        self.max_limit = max_limit
        self.name = name
        self.instructions = instructions
        self.public_url = public_url.rstrip("/") if public_url else None
        self.oauth_wanted = oauth
        self.allow_registration = allow_registration
        self.token_seconds = token_minutes * 60
        self.documents = list(documents)
        self.prompts = list(prompts)
        check_unique(self.documents, "uri", "resources")
        check_unique(self.prompts, "name", "prompts")
        self.panel: Any = None
        self.server = McpServer(self, tools)
        self.oauth = OAuth(self)

    def register(self, panel: Any) -> None:
        from .models import set_clock

        self.panel = panel
        if hasattr(panel, "now"):
            set_clock(panel.now)  # token times in the panel's time zone
        panel.resources([McpTokenResource])
        panel.routes(self._routes)
        if self.oauth_enabled:
            panel.pages([AuthorizePage])
            panel.routes(self.oauth.routes)

    @property
    def oauth_enabled(self) -> bool:
        return bool(self.oauth_wanted and self.panel is not None and self.panel.auth.enabled)

    def mount(self, app: Any, panel: Any) -> None:
        # MCP apps look for the OAuth metadata at the site root, e.g. /.well-known/oauth-authorization-server/admin
        if self.oauth_enabled and panel.path:
            self.oauth.well_known_routes(app, prefix=panel.path)
            self.oauth.well_known_routes(app)  # older apps drop the path
        if self.public_path:
            self._endpoint_routes(app, self.public_path)
            if self.oauth_enabled:
                self.oauth.public_resource_route(app)

    def _routes(self, app: Any, panel: Any) -> None:
        if not self.public_path:
            self._endpoint_routes(app, self.path)

    def _endpoint_routes(self, app: Any, path: str) -> None:
        server = self.server

        @app.post(path)
        async def mcp(request: Request):
            return await server.handle_http(request)

        @app.get(path)
        async def mcp_get(request: Request):
            # no server-sent events stream: clients fall back to plain POSTs
            return JSONResponse({"error": "Use POST for MCP messages."}, status_code=405, headers={"Allow": "POST"})

    # ------------------------------------------------------------------ settings
    def exposes(self, resource: Any) -> bool:
        slug = resource.get_slug()
        if slug in self.exclude:
            return False
        return self.only is None or slug in self.only

    def hidden_for(self, resource: Any) -> set[str]:
        slug = resource.get_slug()
        out = set()
        for item in self.hidden_fields:
            owner, _, column = item.rpartition(".")
            if not owner or owner == slug:
                out.add(column)
        return out

    def base_url(self, request: Request) -> str:
        """``https://host`` of this site (no panel path)."""
        base = self.public_url or self.panel.app_url
        if not base:
            proto = request.headers.get("x-forwarded-proto") or request.url.scheme
            base = f"{proto}://{request.headers.get('host') or request.url.netloc}"
        return base.rstrip("/")

    def endpoint_url(self, request: Request) -> str:
        if self.public_path:
            return self.base_url(request) + self.public_path
        return self.base_url(request) + self.panel.url(self.path.strip("/"))

    def tokens_label(self) -> str:
        """What messages call the token screen: ``tokens_label``, or the screen's menu label."""
        if self._tokens_label:
            return self._tokens_label
        resource = next((r for r in self.panel.get_resources() if issubclass(r, McpTokenResource)), None) \
            if self.panel is not None else None
        try:
            return str(resource.get_navigation_label()) if resource is not None else McpTokenResource.navigation_label
        except Exception:  # noqa: BLE001 - a label that needs a request
            return McpTokenResource.navigation_label

    def authenticated(self, ctx: Any) -> None:
        if self.on_authenticated is not None:
            from tungsten.support.evaluate import call

            call(self.on_authenticated, ctx=ctx, user=ctx.user, panel=self.panel)

    def run_stdio(self, user: Any = None, *, can_write: bool = False, stdin: Any = None, stdout: Any = None,
                  tenant: Any = None) -> None:
        """Serve MCP over stdin/stdout (one JSON message per line) as ``user`` (an id or a user), until stdin
        closes. For apps that start the server as a command::

            # app/mcp_stdio.py
            from app.admin import panel
            panel.get_plugin("mcp").run_stdio(user=1, can_write=True)
        """
        from .stdio import serve

        serve(self, user, can_write=can_write, stdin=stdin, stdout=stdout, tenant=tenant)

    def server_title(self) -> str:
        return self.name or f"{self.panel.brand_name} admin"

    def instructions_for(self, can_write: bool) -> str:
        if self.instructions:
            return self.instructions + self._plugin_notes()
        text = DEFAULT_INSTRUCTIONS
        if can_write:
            text += (" create_record, update_record and delete_record change data: confirm with the user "
                     "before changing or deleting records they did not ask about.")
        else:
            text += " This connection can only read."
        return text + self._plugin_notes()

    def _plugin_notes(self) -> str:
        """Notes from other plugins with an ``mcp_instructions()`` method (e.g. "this is the live panel")."""
        notes = []
        for plugin in getattr(self.panel, "_plugins", []):
            fn = getattr(plugin, "mcp_instructions", None)
            if plugin is self or not callable(fn):
                continue
            try:
                note = fn()
            except Exception:
                logging.getLogger("tungsten.mcp").exception("%s.mcp_instructions() failed", type(plugin).__name__)
                continue
            if note:
                notes.append(" " + str(note).strip())
        return "".join(notes)


def _slug(resource: Any) -> str:
    return resource if isinstance(resource, str) else resource.get_slug()


__all__ = [
    "SENSITIVE",
    "AuthorizePage",
    "McpOAuthClient",
    "McpOAuthCode",
    "McpPlugin",
    "McpPrompt",
    "McpResource",
    "McpServer",
    "McpToken",
    "McpTokenResource",
    "OAuth",
    "PromptArgument",
    "ToolError",
    "Tools",
    "__version__",
    "hash_token",
    "new_token",
]
