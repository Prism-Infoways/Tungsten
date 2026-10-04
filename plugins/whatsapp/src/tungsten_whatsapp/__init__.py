"""WhatsApp for Tungsten leads.

    from tungsten_leads import LeadsPlugin
    from tungsten_whatsapp import WhatsAppPlugin

    panel.plugin(LeadsPlugin())
    panel.plugin(WhatsAppPlugin())
    panel.create_tables(engine)

Open "WhatsApp setup" in the panel and pick how to send:

- **Links only**: the WhatsApp button opens WhatsApp (app or web) with the chat ready. No setup.
- **Cloud API**: Meta's official API. Send texts and templates, get replies and delivery ticks.
- **WhatsApp Web**: your own number, linked by QR code through a WAHA gateway.

Every message sent or received shows on the lead's timeline. New chats can become leads,
and new leads can get a welcome message.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
from tungsten import Plugin

from .client import CloudClient, Transport, WebClient, WhatsAppError, click_to_chat_url, to_digits
from .models import WhatsAppBase, WhatsAppMessage, WhatsAppSettings, WhatsAppTemplate
from .pages import WhatsAppSetupPage
from .resources import WhatsAppMessageResource, WhatsAppTemplateResource, whatsapp_action, whatsapp_bulk_action
from .service import get_settings, handle_cloud_webhook, handle_web_webhook, receive, send, welcome

__version__ = "0.1.0"


class WhatsAppPlugin(Plugin):
    """``WhatsAppPlugin(public_url=None, welcome=True)``.

    - ``public_url``: this site's address for webhook links. Defaults to the panel's ``app_url``,
      then to the address in the browser.
    - ``welcome``: send the welcome message (when switched on in the panel) to new leads.
    - ``transport``: swap the HTTP layer (tests).
    """

    id = "whatsapp"
    metadata = WhatsAppBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, public_url: str | None = None, welcome: bool = True,
                 transport: Transport | None = None) -> None:
        self.public_url = public_url.rstrip("/") if public_url else None
        self.welcome = welcome
        self.transport = transport
        self.panel: Any = None

    def register(self, panel: Any) -> None:
        leads = panel.get_plugin("leads")
        if leads is None:
            raise RuntimeError("Add LeadsPlugin() to the panel before WhatsAppPlugin().")
        self.panel = panel
        panel.pages([WhatsAppSetupPage])
        panel.resources([WhatsAppMessageResource, WhatsAppTemplateResource])
        panel.routes(self._routes)
        leads.add_lead_action(whatsapp_action)
        leads.add_lead_bulk_action(whatsapp_bulk_action)
        if self.welcome:
            leads.on_lead_created("whatsapp.welcome", self._welcome)

    def _welcome(self, db: Any, lead: Any) -> None:
        welcome(db, lead, transport=self.transport)

    def webhook_url(self, request: Request, name: str, **query: str) -> str:
        if self.public_url:
            base = self.public_url
        elif self.panel.app_url:
            base = self.panel.app_url
        else:
            proto = request.headers.get("x-forwarded-proto") or request.url.scheme
            base = f"{proto}://{request.headers.get('host') or request.url.netloc}"
        return base + self.panel.url("whatsapp", name) + (f"?{urlencode(query)}" if query else "")

    def _routes(self, app: Any, panel: Any) -> None:
        @app.get("/whatsapp/webhook")
        async def verify(request: Request):
            """Meta checks the Cloud API webhook once: echo the challenge if the token matches."""
            params = request.query_params
            token = await run_in_threadpool(panel.with_session, lambda db: get_settings(db).verify_token)
            if params.get("hub.mode") == "subscribe" and hmac.compare_digest(params.get("hub.verify_token", ""), token):
                return PlainTextResponse(params.get("hub.challenge", ""))
            return PlainTextResponse("Wrong verify token", status_code=403)

        @app.post("/whatsapp/webhook")
        async def cloud_webhook(request: Request):
            body = await request.body()
            signature = request.headers.get("x-hub-signature-256", "")

            def process(db: Any) -> int:
                secret = get_settings(db).app_secret or ""
                expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
                if not secret or not hmac.compare_digest(expected, signature):
                    return 403
                try:
                    payload = json.loads(body or b"{}")
                except ValueError:
                    return 400
                handle_cloud_webhook(db, payload)
                db.commit()
                return 200

            status = await run_in_threadpool(panel.with_session, process)
            return JSONResponse({"ok": status == 200}, status_code=status)

        @app.post("/whatsapp/web-webhook")
        async def web_webhook(request: Request):
            body = await request.body()
            token = request.query_params.get("token", "")

            def process(db: Any) -> int:
                if not hmac.compare_digest(token, get_settings(db).web_webhook_token):
                    return 403
                try:
                    payload = json.loads(body or b"{}")
                except ValueError:
                    return 400
                handle_web_webhook(db, payload, transport=self.transport)
                db.commit()
                return 200

            status = await run_in_threadpool(panel.with_session, process)
            return JSONResponse({"ok": status == 200}, status_code=status)


__all__ = [
    "CloudClient", "WebClient", "WhatsAppBase", "WhatsAppError", "WhatsAppMessage", "WhatsAppMessageResource",
    "WhatsAppPlugin", "WhatsAppSettings", "WhatsAppSetupPage", "WhatsAppTemplate", "WhatsAppTemplateResource",
    "click_to_chat_url", "receive", "send", "to_digits",
]
