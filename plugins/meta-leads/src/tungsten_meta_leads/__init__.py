"""Facebook and Instagram lead forms for Tungsten.

    from tungsten_leads import LeadsPlugin
    from tungsten_meta_leads import MetaLeadsPlugin

    panel.plugin(LeadsPlugin())
    panel.plugin(MetaLeadsPlugin())       # or MetaLeadsPlugin(app_id=..., app_secret=...)
    panel.create_tables(engine)

Then open "Facebook & Instagram" in the panel, add the Meta app keys and press
Connect Facebook. Pages, lead forms and the webhook are set up for you, and
every new lead lands in Leads with its answers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from tungsten import Plugin

from .graph import Graph, GraphError, Transport, signature_ok
from .models import MetaBase, MetaForm, MetaLeadLog, MetaPage, MetaSettings
from .pages import MetaSetupPage
from .resources import MetaFormResource, MetaLeadLogResource
from .sync import (
    connect,
    get_settings,
    handle_webhook,
    map_answers,
    refresh_forms,
    subscribe_app,
    sync_form,
)

__version__ = "0.1.0"


class MetaLeadsPlugin(Plugin):
    """``MetaLeadsPlugin(app_id=None, app_secret=None, public_url=None, ...)``.

    - ``app_id`` / ``app_secret``: your Meta app's keys. Leave them out to type them in the panel instead.
    - ``public_url``: this site's address (``https://admin.example.com``) for the Facebook login and webhook
      links. Defaults to the panel's ``app_url``, then to the address in the browser.
    - ``auto_create_fields``: add a lead field for every lead form question that has none.
    - ``default_status``: status of new leads when the form doesn't set one.
    - ``sync_limit``: how many recent leads per form "Sync" reads.
    """

    id = "meta-leads"
    metadata = MetaBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, app_id: str | None = None, app_secret: str | None = None, public_url: str | None = None,
                 graph_version: str = "v21.0", auto_create_fields: bool = True, default_status: str = "new",
                 sync_limit: int = 500, transport: Transport | None = None) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.public_url = public_url.rstrip("/") if public_url else None
        self.graph_version = graph_version
        self.auto_create_fields = auto_create_fields
        self.default_status = default_status
        self.sync_limit = sync_limit
        self.transport = transport
        self.panel: Any = None

    def register(self, panel: Any) -> None:
        if panel.get_plugin("leads") is None:
            raise RuntimeError("Add LeadsPlugin() to the panel before MetaLeadsPlugin().")
        self.panel = panel
        panel.pages([MetaSetupPage])
        panel.resources([MetaFormResource, MetaLeadLogResource])
        panel.routes(self._routes)

    # ------------------------------------------------------------------ helpers
    def keys(self, db: Any) -> tuple[str | None, str | None]:
        """App ID and secret: from the code if given, else from the setup page."""
        if self.app_id and self.app_secret:
            return self.app_id, self.app_secret
        settings = get_settings(db)
        return self.app_id or settings.app_id, self.app_secret or settings.app_secret

    def graph(self, db: Any) -> Graph:
        return Graph(self.graph_version, app_secret=self.keys(db)[1], transport=self.transport)

    def base_url(self, request: Request) -> str:
        if self.public_url:
            return self.public_url
        if self.panel is not None and self.panel.app_url:
            return self.panel.app_url
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        return f"{proto}://{request.headers.get('host') or request.url.netloc}"

    def redirect_uri(self, request: Request) -> str:
        return self.base_url(request) + self.panel.url("meta", "callback")

    def webhook_url(self, request: Request) -> str:
        return self.base_url(request) + self.panel.url("meta", "webhook")

    # ------------------------------------------------------------------ routes
    def _routes(self, app: Any, panel: Any) -> None:
        plugin = self
        setup_url = panel.url(MetaSetupPage.get_slug())

        @app.get("/meta/callback")
        async def callback(request: Request):
            """Facebook sends the user back here after they allow access."""
            if request.session.get(panel.auth.session_key()) is None and panel.auth.enabled:
                return RedirectResponse(panel.url("login"), status_code=303)
            if request.query_params.get("error"):
                return RedirectResponse(f"{setup_url}?meta=denied", status_code=303)
            state = request.session.pop("tw_meta_state", None)
            if not state or state != request.query_params.get("state"):
                return RedirectResponse(f"{setup_url}?meta=state", status_code=303)
            code = request.query_params.get("code", "")
            redirect_uri, webhook = plugin.redirect_uri(request), plugin.webhook_url(request)

            def finish(db: Any) -> str | None:
                app_id, app_secret = plugin.keys(db)
                if not (app_id and app_secret):
                    return "Add your Meta App ID and App secret first."
                graph = plugin.graph(db)
                try:
                    connect(db, graph, app_id=app_id, app_secret=app_secret, code=code, redirect_uri=redirect_uri)
                    db.commit()
                    subscribe_app(db, graph, app_id=app_id, app_secret=app_secret, callback_url=webhook)
                    refresh_forms(db, graph, auto_create_fields=plugin.auto_create_fields)
                    db.commit()
                except GraphError as exc:
                    db.rollback()
                    return str(exc)
                return None

            error = await run_in_threadpool(panel.with_session, finish)
            query = {"meta": "error", "reason": error} if error else {"meta": "connected"}
            return RedirectResponse(f"{setup_url}?{urlencode(query)}", status_code=303)

        @app.get("/meta/webhook")
        async def verify(request: Request):
            """Meta checks the webhook once: echo the challenge if the token matches."""
            params = request.query_params
            token = await run_in_threadpool(panel.with_session, lambda db: get_settings(db).verify_token)
            if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == token:
                return PlainTextResponse(params.get("hub.challenge", ""))
            return PlainTextResponse("Wrong verify token", status_code=403)

        @app.post("/meta/webhook")
        async def webhook(request: Request):
            body = await request.body()
            signature = request.headers.get("x-hub-signature-256")

            def process(db: Any) -> int:
                _, app_secret = plugin.keys(db)
                if not signature_ok(app_secret or "", body, signature):
                    return 403
                try:
                    payload = json.loads(body or b"{}")
                except ValueError:
                    return 400
                handle_webhook(db, plugin.graph(db), payload, default_status=plugin.default_status)
                db.commit()
                return 200

            status = await run_in_threadpool(panel.with_session, process)
            return JSONResponse({"ok": status == 200}, status_code=status)


__all__ = [
    "Graph", "GraphError", "MetaBase", "MetaForm", "MetaFormResource", "MetaLeadLog", "MetaLeadLogResource",
    "MetaLeadsPlugin", "MetaPage", "MetaSettings", "MetaSetupPage", "map_answers", "sync_form",
]
