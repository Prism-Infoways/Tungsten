"""Sending and receiving WhatsApp messages, and keeping them on the lead's timeline."""

from __future__ import annotations

import datetime as dt
import re
import secrets
from typing import Any

from sqlalchemy import select
from tungsten_leads import Lead, add_activity, create_lead, find_lead

from .client import CloudClient, Transport, WebClient, WhatsAppError, to_digits
from .models import WhatsAppMessage, WhatsAppSettings, WhatsAppTemplate

STATUS_ORDER = {"sent": 1, "delivered": 2, "read": 3}


def get_settings(db: Any) -> WhatsAppSettings:
    row = db.scalars(select(WhatsAppSettings)).first()
    if row is None:
        # saved right away, so the tokens shown on the setup page stay the same
        row = WhatsAppSettings(verify_token=secrets.token_urlsafe(24), web_webhook_token=secrets.token_urlsafe(24))
        db.add(row)
        db.commit()
    return row


def client_for(settings: WhatsAppSettings, transport: Transport | None = None) -> CloudClient | WebClient | None:
    if settings.channel == "cloud" and settings.phone_number_id and settings.access_token:
        return CloudClient(settings.phone_number_id, settings.access_token, settings.business_account_id,
                           transport=transport)
    if settings.channel == "web" and settings.gateway_url:
        return WebClient(settings.gateway_url, settings.gateway_api_key, settings.gateway_session,
                         transport=transport)
    return None


def fill(text: str, lead: Lead | None) -> str:
    """Put the lead's details into ``{name}``, ``{first_name}``, ``{phone}``, ``{email}``, ``{company}``."""
    if lead is None:
        return text
    values = {"name": lead.name or "", "first_name": (lead.name or "").split(" ")[0], "phone": lead.phone or "",
              "email": lead.email or "", "company": lead.company or ""}
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), text)


def template_text(template: WhatsAppTemplate | None, params: list[str]) -> str:
    if template is None:
        return ""
    return re.sub(r"\{\{(\d+)\}\}", lambda m: params[int(m.group(1)) - 1] if int(m.group(1)) <= len(params)
                  else m.group(0), template.body)


def send(db: Any, *, phone: str, text: str | None = None, template: str | None = None, language: str = "en",
         params: list[str] | None = None, lead: Lead | None = None, user_id: str | None = None,
         transport: Transport | None = None) -> WhatsAppMessage:
    """Send a text (or, on the Cloud API, a template) and save it. Raises ``WhatsAppError`` if it failed."""
    settings = get_settings(db)
    client = client_for(settings, transport)
    if client is None:
        raise WhatsAppError("WhatsApp is not set up yet. Open WhatsApp setup first.")
    to = to_digits(phone, settings.country_code)
    if len(to) < 8:
        raise WhatsAppError(f"{phone or 'This number'} doesn't look like a phone number.")
    params = [str(p) for p in params or []]
    if template:
        if not isinstance(client, CloudClient):
            raise WhatsAppError("Templates work with the WhatsApp Cloud API only.")
        row = db.scalars(select(WhatsAppTemplate).where(WhatsAppTemplate.name == template,
                                                        WhatsAppTemplate.language == language)).first()
        body = template_text(row, params) or f"Template {template}"
    else:
        body = text or ""
        if not body.strip():
            raise WhatsAppError("Write a message first.")
    message = WhatsAppMessage(lead_id=lead.id if lead else None, phone=to, direction="out",
                              channel=settings.channel, body=body, template=template, user_id=user_id)
    db.add(message)
    try:
        if template:
            message.external_id = client.send_template(to, template, language, params)
        else:
            message.external_id = client.send_text(to, body)
        message.status = "sent"
    except WhatsAppError as exc:
        message.status, message.error = "failed", str(exc)
        db.flush()
        raise
    if lead is not None:
        add_activity(db, lead, f"Sent: {body}", type="whatsapp", user_id=user_id)
    db.flush()
    return message


def receive(db: Any, settings: WhatsAppSettings, *, phone: str, body: str, name: str | None = None,
            external_id: str | None = None, channel: str = "cloud") -> WhatsAppMessage | None:
    """Save an incoming message, on the lead with this number (made if needed and allowed)."""
    phone = to_digits(phone, settings.country_code)
    if external_id and db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.external_id == external_id)).first():
        return None  # already saved: WhatsApp sometimes sends the same message twice
    lead = find_lead(db, phone=phone)
    if lead is None and settings.create_leads:
        lead = create_lead(db, name=name or f"+{phone}", phone=f"+{phone}", source="whatsapp",
                           notes=body[:500] if body else None)
        add_activity(db, lead, "Lead started a WhatsApp chat", type="system")
    message = WhatsAppMessage(lead_id=lead.id if lead else None, phone=phone, direction="in", channel=channel,
                              body=body, status="received", external_id=external_id)
    db.add(message)
    if lead is not None:
        add_activity(db, lead, f"Received: {body}", type="whatsapp")
    db.flush()
    return message


def update_status(db: Any, external_id: str, status: str, error: str | None = None) -> None:
    message = db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.external_id == external_id)).first()
    if message is None:
        return
    if status == "failed":
        message.status, message.error = "failed", error
    elif STATUS_ORDER.get(status, 0) > STATUS_ORDER.get(message.status, 0):
        message.status = status


def _cloud_body(msg: dict) -> str:
    kind = msg.get("type")
    if kind == "text":
        return msg.get("text", {}).get("body", "")
    if kind == "button":
        return msg.get("button", {}).get("text", "")
    if kind == "interactive":
        reply = msg.get("interactive", {})
        return (reply.get("button_reply") or reply.get("list_reply") or {}).get("title", "")
    if kind in ("image", "video", "document", "audio", "sticker"):
        caption = msg.get(kind, {}).get("caption")
        return f"[{kind}]" + (f" {caption}" if caption else "")
    if kind == "location":
        loc = msg.get("location", {})
        return f"[location] {loc.get('latitude')}, {loc.get('longitude')}"
    return f"[{kind}]"


def handle_cloud_webhook(db: Any, payload: dict) -> int:
    """Messages and delivery updates from the Cloud API. Returns how many messages were saved."""
    if payload.get("object") != "whatsapp_business_account":
        return 0
    settings = get_settings(db)
    saved = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                saved += receive(db, settings, phone=msg.get("from", ""), body=_cloud_body(msg),
                                 name=names.get(msg.get("from")), external_id=msg.get("id"), channel="cloud") is not None
            for st in value.get("statuses", []):
                errors = st.get("errors") or [{}]
                update_status(db, st.get("id", ""), st.get("status", ""),
                              (errors[0].get("error_data") or {}).get("details") or errors[0].get("title"))
    return saved


def handle_web_webhook(db: Any, payload: dict) -> int:
    """Events from the WAHA gateway: new messages, delivery updates, and the link status."""
    settings = get_settings(db)
    event, data = payload.get("event"), payload.get("payload") or {}
    if event == "session.status":
        settings.web_status = data.get("status")
        me = payload.get("me") or data.get("me") or {}
        if me.get("id"):
            settings.web_phone = str(me["id"]).split("@")[0]
        return 0
    if event == "message.ack":
        ack = {1: "sent", 2: "delivered", 3: "read", 4: "read"}.get(data.get("ack"))
        if ack:
            update_status(db, str(data.get("id", "")), ack)
        return 0
    if event != "message" or data.get("fromMe"):
        return 0
    chat = str(data.get("from", ""))
    if not chat.endswith("@c.us"):
        return 0  # groups and broadcasts are not leads
    name = (data.get("_data") or {}).get("notifyName") or (data.get("_data") or {}).get("pushName")
    body = data.get("body") or ("[media]" if data.get("hasMedia") else "")
    return receive(db, settings, phone=chat.split("@")[0], body=body, name=name,
                   external_id=str(data.get("id") or "") or None, channel="web") is not None


def sync_templates(db: Any, client: CloudClient) -> int:
    rows = client.templates()
    for row in db.scalars(select(WhatsAppTemplate)).all():
        db.delete(row)
    for row in rows:
        body = next((c.get("text", "") for c in row.get("components", []) if c.get("type") == "BODY"), "")
        db.add(WhatsAppTemplate(name=row.get("name", ""), language=row.get("language", "en"),
                                status=row.get("status"), category=row.get("category"), body=body,
                                params=len(set(re.findall(r"\{\{(\d+)\}\}", body)))))
    db.flush()
    return len(rows)


def welcome(db: Any, lead: Lead, transport: Transport | None = None) -> WhatsAppMessage | None:
    """Send the welcome message to a new lead, if it is switched on for the lead's source."""
    settings = db.scalars(select(WhatsAppSettings)).first()
    if settings is None or not settings.welcome_enabled or not lead.phone:
        return None
    if settings.welcome_sources and lead.source not in settings.welcome_sources:
        return None
    try:
        if settings.channel == "cloud" and settings.welcome_template:
            tpl = db.scalars(select(WhatsAppTemplate).where(WhatsAppTemplate.name == settings.welcome_template)).first()
            params = [lead.name.split(" ")[0]] if tpl is not None and tpl.params else []
            return send(db, phone=lead.phone, template=settings.welcome_template, language=settings.welcome_language,
                        params=params, lead=lead, transport=transport)
        if settings.welcome_text:
            return send(db, phone=lead.phone, text=fill(settings.welcome_text, lead), lead=lead, transport=transport)
    except WhatsAppError as exc:
        add_activity(db, lead, f"Welcome WhatsApp not sent: {exc}", type="system")
    return None


def last_incoming_at(db: Any, phone: str) -> dt.datetime | None:
    return db.scalars(select(WhatsAppMessage.created_at).where(
        WhatsAppMessage.phone == phone, WhatsAppMessage.direction == "in")
        .order_by(WhatsAppMessage.created_at.desc())).first()
