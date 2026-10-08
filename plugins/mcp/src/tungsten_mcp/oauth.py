"""OAuth 2.1 for the MCP server, as the MCP authorization spec asks.

An AI app (Claude, Cursor ...) finds the server's metadata, registers itself, sends the user
to the panel's login and an "Allow" page, then swaps the one-time code (with PKCE) for an
access token and a refresh token. Tokens are rows of :class:`McpToken`, so they show on the
"AI access (MCP)" screen and can be revoked there.

Endpoints (the panel at ``/admin``):

- ``/.well-known/oauth-protected-resource/admin/mcp`` and ``/admin/.well-known/oauth-protected-resource``
- ``/.well-known/oauth-authorization-server/admin`` (also ``/.well-known/oauth-authorization-server``,
  ``/admin/.well-known/oauth-authorization-server`` and the ``openid-configuration`` forms)
- ``/admin/oauth/register``, ``/admin/oauth/authorize``, ``/admin/oauth/token``
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets
from typing import Any
from urllib.parse import urlencode, urlparse

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from markupsafe import Markup
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from tungsten import Notification, Page
from tungsten.actions import Action
from tungsten.forms import Toggle

from .models import McpOAuthClient, McpOAuthCode, McpToken, hash_token, new_token

SESSION_KEY = "tw_mcp_oauth"
READ, WRITE = "mcp:read", "mcp:write"
CODE_MINUTES = 10
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _now() -> dt.datetime:
    return dt.datetime.now()


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("mcp")


def _error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status, headers=NO_STORE)


def redirect_ok(uri: Any) -> bool:
    """https anywhere, http only on this computer (localhost), or an app's own scheme (cursor://...)."""
    if not isinstance(uri, str) or len(uri) > 2000:
        return False
    parts = urlparse(uri)
    if parts.fragment or not parts.scheme:
        return False
    if parts.scheme == "https":
        return bool(parts.netloc)
    if parts.scheme == "http":
        return parts.hostname in ("localhost", "127.0.0.1", "::1")
    return parts.scheme not in ("javascript", "data", "file", "vbscript")


def with_query(uri: str, **params: Any) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return uri + ("&" if "?" in uri else "?") + query


def pkce_ok(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(expected, challenge)


class OAuth:
    """The OAuth endpoints of one :class:`~tungsten_mcp.McpPlugin`."""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    # ------------------------------------------------------------------ urls
    def issuer(self, request: Request) -> str:
        return self.plugin.base_url(request) + (self.plugin.panel.path or "")

    def resource_metadata_url(self, request: Request) -> str:
        """The address the 401 sends apps to: under the panel, not at the site root.

        On shared hosting the web server often hands the app only the panel's path (a cPanel Python app
        with base URI ``/admin``), and a root address then answers from the static site instead. RFC 9728
        lets the challenge name any address, and the root ones stay registered for apps that build the
        address themselves.
        """
        return self.plugin.base_url(request) + self.plugin.panel.url(
            ".well-known/oauth-protected-resource", self.plugin.path.strip("/"))

    def protected_resource(self, request: Request) -> dict:
        return {
            "resource": self.plugin.endpoint_url(request),
            "authorization_servers": [self.issuer(request)],
            "bearer_methods_supported": ["header"],
            "scopes_supported": self.scopes(),
            "resource_name": self.plugin.server_title(),
        }

    def server_metadata(self, request: Request) -> dict:
        issuer = self.issuer(request)
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
            "scopes_supported": self.scopes(),
            "service_documentation": "https://tungsten.prisminfoways.com/docs/mcp.html",
        }

    def scopes(self) -> list[str]:
        return [READ] if self.plugin.read_only else [READ, WRITE]

    # ------------------------------------------------------------------ routes
    def well_known_routes(self, app: Any, prefix: str = "") -> None:
        """Metadata routes. ``prefix`` is the panel path when they go on the main app."""
        oauth = self
        mcp_path = self.plugin.path

        async def resource(request: Request):
            return JSONResponse(oauth.protected_resource(request))

        async def server(request: Request):
            return JSONResponse(oauth.server_metadata(request))

        for path in {f"/.well-known/oauth-protected-resource{prefix}{mcp_path}",
                     f"/.well-known/oauth-protected-resource{prefix}"}:
            app.add_api_route(path, resource, methods=["GET"], include_in_schema=False)
        for path in {f"/.well-known/oauth-authorization-server{prefix}", f"/.well-known/openid-configuration{prefix}"}:
            app.add_api_route(path, server, methods=["GET"], include_in_schema=False)

    def routes(self, app: Any, panel: Any) -> None:
        self.well_known_routes(app)
        app.add_api_route("/oauth/register", self.register, methods=["POST"], include_in_schema=False)
        app.add_api_route("/oauth/authorize", self.authorize, methods=["GET"], include_in_schema=False)
        app.add_api_route("/oauth/token", self.token, methods=["POST"], include_in_schema=False)

    async def _db(self, fn: Any) -> Any:
        return await run_sync_db(self.plugin.panel, fn)

    # ------------------------------------------------------------------ registration (RFC 7591)
    async def register(self, request: Request) -> Response:
        if not self.plugin.allow_registration:
            return _error("access_denied", "This server doesn't take new apps.", 403)
        try:
            body = await request.json()
        except ValueError:
            return _error("invalid_client_metadata", "Send the app details as JSON.")
        if not isinstance(body, dict):
            return _error("invalid_client_metadata", "Send the app details as a JSON object.")
        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not uris or len(uris) > 10 or not all(redirect_ok(u) for u in uris):
            return _error("invalid_redirect_uri", "redirect_uris must be https, http://localhost or an app link.")
        method = body.get("token_endpoint_auth_method") or "client_secret_basic"
        if method not in ("none", "client_secret_post", "client_secret_basic"):
            return _error("invalid_client_metadata", f"token_endpoint_auth_method {method!r} is not supported.")
        grants = body.get("grant_types") or ["authorization_code"]
        if not isinstance(grants, list) or "authorization_code" not in grants:
            return _error("invalid_client_metadata", "grant_types must include authorization_code.")
        name = str(body.get("client_name") or "AI app")[:200]
        client_id = "mcp_" + secrets.token_urlsafe(18)
        secret = secrets.token_urlsafe(32) if method != "none" else None

        def save(db: Any) -> None:
            db.add(McpOAuthClient(client_id=client_id, name=name, redirect_uris=list(uris),
                                  secret_hash=hash_token(secret) if secret else None))
            db.commit()

        await self._db(save)
        out = {
            "client_id": client_id,
            "client_id_issued_at": int(_now().timestamp()),
            "client_name": name,
            "redirect_uris": uris,
            "token_endpoint_auth_method": method,
            "grant_types": [g for g in grants if g in ("authorization_code", "refresh_token")],
            "response_types": ["code"],
        }
        if secret:
            out.update(client_secret=secret, client_secret_expires_at=0)
        return JSONResponse(out, status_code=201, headers=NO_STORE)

    # ------------------------------------------------------------------ authorize
    async def authorize(self, request: Request) -> Response:
        q = request.query_params
        client_id, redirect_uri = q.get("client_id", ""), q.get("redirect_uri", "")
        client = await self._db(lambda db: db.scalars(select(McpOAuthClient)
                                                      .where(McpOAuthClient.client_id == client_id)).first())
        # a bad app or return address gets a page, never a redirect (it could be anyone's site)
        if client is None:
            return self._page(400, "Unknown app", "This app is not registered here. Remove the server in the app "
                                                  "and add it again.")
        if not redirect_uri and len(client.redirect_uris) == 1:
            redirect_uri = client.redirect_uris[0]
        if redirect_uri not in client.redirect_uris:
            return self._page(400, "Wrong return address", "The app asked to come back to an address it didn't "
                                                           "register.")
        state = q.get("state")

        def fail(error: str, description: str) -> Response:
            return RedirectResponse(with_query(redirect_uri, error=error, error_description=description, state=state,
                                               iss=self.issuer(request)), status_code=302)

        if q.get("response_type") != "code":
            return fail("unsupported_response_type", "Only response_type=code is supported.")
        challenge = q.get("code_challenge") or ""
        if q.get("code_challenge_method") != "S256" or not 43 <= len(challenge) <= 128:
            return fail("invalid_request", "PKCE with code_challenge_method=S256 is required.")
        scopes = set((q.get("scope") or "").split())
        unknown = scopes - {READ, WRITE}
        if unknown:
            return fail("invalid_scope", f"Unknown scope: {' '.join(sorted(unknown))}.")
        request.session[SESSION_KEY] = {
            "client_id": client.client_id, "client_name": client.name, "redirect_uri": redirect_uri,
            "state": state, "challenge": challenge,
            # no scope asked: the user picks; only mcp:read asked: read only
            "write": (WRITE in scopes or not scopes) and not self.plugin.read_only,
            "write_default": WRITE in scopes,
        }
        return RedirectResponse(self.plugin.panel.url(AuthorizePage.slug), status_code=303)

    def _page(self, status: int, title: str, message: str) -> HTMLResponse:
        return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>{title}</title>"
                            f"<body style='font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
                            f"<h1 style='font-size:1.25rem'>{title}</h1><p>{message}</p>", status_code=status)

    # ------------------------------------------------------------------ token
    async def token(self, request: Request) -> Response:
        form = await request.form()
        data = {k: str(v) for k, v in form.items()}
        basic = request.headers.get("authorization", "")
        if basic.lower().startswith("basic "):
            try:
                cid, _, secret = base64.b64decode(basic[6:]).decode().partition(":")
            except (ValueError, UnicodeDecodeError):
                return _error("invalid_client", "Bad Basic header.", 401)
            from urllib.parse import unquote_plus

            data.setdefault("client_id", unquote_plus(cid))
            data["client_secret"] = unquote_plus(secret)
        grant = data.get("grant_type")
        if grant not in ("authorization_code", "refresh_token"):
            return _error("unsupported_grant_type", "Use authorization_code or refresh_token.")
        return await self._db(lambda db: self._token(db, grant, data))

    def _token(self, db: Any, grant: str, data: dict) -> Response:
        client = db.scalars(select(McpOAuthClient).where(McpOAuthClient.client_id == data.get("client_id", ""))).first()
        if client is None:
            return _error("invalid_client", "Unknown client_id.", 401)
        if client.secret_hash and not hmac.compare_digest(client.secret_hash, hash_token(data.get("client_secret", ""))):
            return _error("invalid_client", "Wrong client_secret.", 401)
        lifetime = dt.timedelta(seconds=self.plugin.token_seconds)
        if grant == "authorization_code":
            code = db.scalars(select(McpOAuthCode).where(McpOAuthCode.code_hash == hash_token(data.get("code", "")))
                              ).first()
            if code is None or code.client_id != client.client_id or code.expires_at < _now():
                return _error("invalid_grant", "The code is wrong, used or expired.")
            db.delete(code)  # one use only, even when the checks below fail
            db.commit()
            if data.get("redirect_uri", code.redirect_uri) != code.redirect_uri:
                return _error("invalid_grant", "redirect_uri doesn't match.")
            if not pkce_ok(data.get("code_verifier", ""), code.code_challenge):
                return _error("invalid_grant", "code_verifier doesn't match the code_challenge.")
            row = McpToken(name=client.name[:100], user_id=code.user_id, client_id=client.client_id,
                           can_write=code.can_write, token_hash="", hint="")
            db.add(row)
        else:
            row = db.scalars(select(McpToken).where(McpToken.refresh_hash == hash_token(data.get("refresh_token", ""))
                                                    )).first()
            if row is None or row.client_id != client.client_id:
                return _error("invalid_grant", "The refresh token is wrong or was revoked.")
        access, refresh = new_token(), new_token()
        row.token_hash, row.hint, row.refresh_hash = hash_token(access), access[:12], hash_token(refresh)
        row.expires_at = _now() + lifetime
        db.commit()
        scope = f"{READ} {WRITE}" if row.can_write else READ
        return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": int(lifetime.total_seconds()),
                             "refresh_token": refresh, "scope": scope}, headers=NO_STORE)


# ---------------------------------------------------------------------- the "Allow" page
def _pending(ctx: Any) -> dict | None:
    return ctx.session.get(SESSION_KEY)


def _finish(ctx: Any, params: dict) -> Response:
    ctx.session.pop(SESSION_KEY, None)
    return ctx.go(with_query(params["redirect_uri"], **params["extra"]))


def allow(ctx: Any, can_write: bool) -> Response:
    pending = _pending(ctx)
    if not pending:
        Notification("Nothing to approve").body("Start again from your AI app.").warning().send(ctx)
        return ctx.finalize(Response(status_code=204))
    for old in ctx.db.scalars(select(McpOAuthCode).where(McpOAuthCode.expires_at < _now())):
        ctx.db.delete(old)
    code = secrets.token_urlsafe(32)
    ctx.db.add(McpOAuthCode(code_hash=hash_token(code), client_id=pending["client_id"],
                            user_id=ctx.panel.auth.user_id(ctx.user) if ctx.user is not None else None,
                            redirect_uri=pending["redirect_uri"], code_challenge=pending["challenge"],
                            can_write=bool(can_write) and pending["write"],
                            expires_at=_now() + dt.timedelta(minutes=CODE_MINUTES)))
    ctx.db.commit()
    issuer = _plugin(ctx).oauth.issuer(ctx.request)
    return _finish(ctx, {"redirect_uri": pending["redirect_uri"],
                         "extra": {"code": code, "state": pending["state"], "iss": issuer}})


def deny(ctx: Any) -> Response:
    pending = _pending(ctx)
    if not pending:
        return ctx.go(ctx.panel.url())
    issuer = _plugin(ctx).oauth.issuer(ctx.request)
    return _finish(ctx, {"redirect_uri": pending["redirect_uri"],
                         "extra": {"error": "access_denied", "error_description": "The user said no.",
                                   "state": pending["state"], "iss": issuer}})


class AuthorizePage(Page):
    """Shown after the panel login: which app wants in, and Allow / Deny."""

    slug = "mcp-authorize"
    title = "Connect an AI app"
    icon = "bot"
    show_in_navigation = False
    save_label = "Allow"

    @classmethod
    def get_subheading(cls, ctx):
        return None

    @classmethod
    def content(cls, ctx):
        pending = _pending(ctx)
        user = ctx.panel.auth.display_name(ctx.user) if ctx.user is not None else None
        host = urlparse(pending["redirect_uri"]).netloc or urlparse(pending["redirect_uri"]).scheme if pending else ""
        return Markup(ctx.panel.renderer.render("tungsten_mcp/authorize.html", ctx=ctx, pending=pending, user=user,
                                                host=host))

    @classmethod
    def form(cls, form):
        return form.columns(1).schema([
            Toggle("can_write").label("Allow changes")
            .helper_text("Let the app create, change and delete records. Off: it can only read.")
            .visible(lambda ctx: bool((_pending(ctx) or {}).get("write"))),
        ])

    @classmethod
    def mount(cls, ctx):
        return {"can_write": bool((_pending(ctx) or {}).get("write_default"))}

    @classmethod
    def save(cls, ctx, data):
        return allow(ctx, bool(data.get("can_write")))

    @classmethod
    def header_actions(cls, ctx):
        return [Action("deny").label("Deny").color("gray").outlined().visible(_pending(ctx) is not None)
                .action(lambda ctx: deny(ctx))]


async def run_sync_db(panel: Any, fn: Any) -> Any:
    if panel.is_async:
        async with panel.session_factory() as adb:
            return await adb.run_sync(fn)

    def sync() -> Any:
        with panel.session_factory() as db:
            return fn(db)

    return await run_in_threadpool(sync)
