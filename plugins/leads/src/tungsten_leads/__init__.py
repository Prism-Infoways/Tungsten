"""Leads plugin for Tungsten.

    from tungsten_leads import LeadsPlugin

    panel.plugin(LeadsPlugin())
    panel.create_tables(engine)   # also creates the leads tables

Adds a "Leads" menu with the lead list (stages, sources, owner, follow-ups,
a timeline of notes) and a "Lead fields" screen where admins add their own
form fields without code.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from tungsten import Plugin

from .fields import FIELD_TYPES, CustomFields
from .models import Lead, LeadActivity, LeadField, LeadsBase
from .resources import DEFAULT_SOURCES, DEFAULT_STATUSES, LeadFieldResource, LeadResource
from .service import add_activity, create_lead, find_lead, normalize_phone, on_lead_created
from .widgets import LeadStats

__version__ = "0.1.0"

_CORE_FIELDS = {"name", "email", "phone", "company", "notes"}


class LeadsPlugin(Plugin):
    """``LeadsPlugin(statuses=..., sources=..., capture_token=...)``.

    ``statuses`` maps a key to ``(label, color)``; ``sources`` maps a key to a label.
    With ``capture_token`` set, websites can POST leads to ``<panel>/api/leads``
    (send the token in the ``X-Leads-Token`` header).
    """

    id = "leads"
    metadata = LeadsBase.metadata

    def __init__(self, statuses: dict[str, tuple[str, str]] | None = None, sources: dict[str, str] | None = None,
                 capture_token: str | None = None, dashboard_widget: bool = True) -> None:
        self.statuses = dict(statuses or DEFAULT_STATUSES)
        self.sources = dict(sources or DEFAULT_SOURCES)
        self.capture_token = capture_token
        self.dashboard_widget = dashboard_widget

    def register(self, panel: Any) -> None:
        panel.resources([LeadResource, LeadFieldResource])
        panel.navigation_group("Leads", icon="contact")
        if self.dashboard_widget:
            panel.widgets([LeadStats])
        if self.capture_token:
            panel.routes(self._capture_route)

    def permissions(self) -> list[tuple[str, str]]:
        return []

    # ------------------------------------------------------------------ website form capture
    def _capture_route(self, app: Any, panel: Any) -> None:
        plugin = self

        @app.post("/api/leads")
        async def capture(request: Request):
            token = request.headers.get("x-leads-token", "")
            if not hmac.compare_digest(token, plugin.capture_token or ""):
                return JSONResponse({"error": "Wrong token"}, status_code=401)
            if request.headers.get("content-type", "").startswith("application/json"):
                payload = await request.json()
            else:
                payload = dict(await request.form())
            if not isinstance(payload, dict):
                return JSONResponse({"error": "Send a JSON object"}, status_code=422)
            if not any(payload.get(k) for k in ("name", "email", "phone")):
                return JSONResponse({"error": "Send a name, email or phone"}, status_code=422)

            def save(db: Any) -> int:
                extra = {k: v for k, v in payload.items() if k not in _CORE_FIELDS and k != "source"}
                lead = create_lead(db, name=payload.get("name"), email=payload.get("email"),
                                   phone=payload.get("phone"), company=payload.get("company"),
                                   notes=payload.get("notes"), source=str(payload.get("source") or "website"),
                                   custom_fields=extra)
                add_activity(db, lead, "Lead came from the website form", type="system")
                db.commit()
                return lead.id

            lead_id = await run_in_threadpool(panel.with_session, save)
            return JSONResponse({"id": lead_id}, status_code=201)


__all__ = [
    "CustomFields", "FIELD_TYPES", "Lead", "LeadActivity", "LeadField", "LeadFieldResource", "LeadResource",
    "LeadStats", "LeadsBase", "LeadsPlugin", "add_activity", "create_lead", "find_lead", "normalize_phone",
    "on_lead_created",
]
