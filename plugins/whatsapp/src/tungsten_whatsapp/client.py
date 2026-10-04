"""Talking to WhatsApp: the official Cloud API, and WhatsApp Web through a WAHA gateway.

Only the standard library is used. Tests swap ``transport`` for a fake.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable

GRAPH_HOST = "https://graph.facebook.com"
#: Graph API version for the Cloud API (Meta keeps each version for about two years)
GRAPH_VERSION = "v25.0"

#: ``transport(method, url, headers, body) -> (status, text)``
Transport = Callable[[str, str, dict, "bytes | None"], "tuple[int, str]"]


class WhatsAppError(Exception):
    """Sending failed. ``str(error)`` says why, in WhatsApp's own words when it gave any."""


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - admin-set URL
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WhatsAppError(f"Could not reach {url.split('?')[0]}: {getattr(exc, 'reason', exc)}") from exc


def _call(transport: Transport, method: str, url: str, headers: dict, payload: Any = None) -> Any:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json", **headers}
    if body is not None:
        headers["Content-Type"] = "application/json"
    status, text = transport(method, url, headers, body)
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {"message": text[:200]}
    if status >= 400:
        error = data.get("error") if isinstance(data, dict) else None
        if isinstance(error, dict):
            detail = (error.get("error_data") or {}).get("details")
            raise WhatsAppError(detail or error.get("message") or f"HTTP {status}")
        message = (data.get("message") or data.get("error")) if isinstance(data, dict) else None
        raise WhatsAppError(str(message or f"HTTP {status}"))
    return data


def to_digits(phone: str | None, country_code: str = "91") -> str:
    """``+91 98765-43210`` / ``98765 43210`` → ``919876543210`` (adds the country code to 10-digit numbers)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and country_code:
        digits = country_code + digits
    return digits


def click_to_chat_url(phone: str | None, text: str | None = None, country_code: str = "91") -> str:
    """A wa.me link that opens WhatsApp (app or web) with the chat ready."""
    from urllib.parse import quote

    url = f"https://wa.me/{to_digits(phone, country_code)}"
    return url + (f"?text={quote(text)}" if text else "")


class CloudClient:
    """WhatsApp Business Cloud API (Meta). Needs a phone number id and a permanent access token."""

    def __init__(self, phone_number_id: str, access_token: str, business_account_id: str | None = None,
                 version: str = GRAPH_VERSION, transport: Transport | None = None) -> None:
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.business_account_id = business_account_id
        self.version = version
        self.transport = transport or urllib_transport

    def _url(self, path: str) -> str:
        return f"{GRAPH_HOST}/{self.version}/{path}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def send_text(self, to: str, text: str) -> str:
        data = _call(self.transport, "POST", self._url(f"{self.phone_number_id}/messages"), self._headers(), {
            "messaging_product": "whatsapp", "recipient_type": "individual", "to": f"+{to}",
            "type": "text", "text": {"body": text, "preview_url": True},
        })
        return data["messages"][0]["id"]

    def send_template(self, to: str, name: str, language: str = "en", params: list[str] | None = None) -> str:
        template: dict[str, Any] = {"name": name, "language": {"code": language}}
        if params:
            template["components"] = [{"type": "body",
                                       "parameters": [{"type": "text", "text": str(p)} for p in params]}]
        data = _call(self.transport, "POST", self._url(f"{self.phone_number_id}/messages"), self._headers(), {
            "messaging_product": "whatsapp", "to": f"+{to}", "type": "template", "template": template,
        })
        return data["messages"][0]["id"]

    def templates(self) -> list[dict]:
        if not self.business_account_id:
            raise WhatsAppError("Add the WhatsApp Business Account ID to read templates.")
        data = _call(self.transport, "GET", self._url(
            f"{self.business_account_id}/message_templates?fields=name,language,status,category,components&limit=200"),
            self._headers())
        return data.get("data", [])

    def phone_info(self) -> dict:
        """The number as Meta sees it: ``status`` is CONNECTED and ``platform_type`` CLOUD_API once registered."""
        return _call(self.transport, "GET", self._url(
            f"{self.phone_number_id}?fields=display_phone_number,verified_name,quality_rating,status,platform_type,"
            "name_status"), self._headers())

    def register(self, pin: str) -> None:
        """Register the number for the Cloud API. ``pin`` becomes its two-step PIN (or must match the one set)."""
        _call(self.transport, "POST", self._url(f"{self.phone_number_id}/register"), self._headers(),
              {"messaging_product": "whatsapp", "pin": pin})

    def subscribe_app(self) -> None:
        """Ask Meta to send this WhatsApp account's messages to our app's webhook (safe to repeat)."""
        if not self.business_account_id:
            raise WhatsAppError("Add the WhatsApp Business Account ID first.")
        _call(self.transport, "POST", self._url(f"{self.business_account_id}/subscribed_apps"), self._headers())


class WebClient:
    """WhatsApp Web through a WAHA gateway (https://waha.devlike.pro), linked to a phone by QR code."""

    def __init__(self, base_url: str, api_key: str | None = None, session: str = "default",
                 transport: Transport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session or "default"
        self.transport = transport or urllib_transport

    def _headers(self) -> dict:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    def _call(self, method: str, path: str, payload: Any = None) -> Any:
        return _call(self.transport, method, f"{self.base_url}{path}", self._headers(), payload)

    def start(self, webhook_url: str) -> dict:
        """Create (or restart) the session and send its messages to ``webhook_url``."""
        config = {"webhooks": [{"url": webhook_url, "events": ["message", "session.status", "message.ack"]}]}
        try:
            return self._call("POST", "/api/sessions", {"name": self.session, "start": True, "config": config})
        except WhatsAppError:
            # the session is already there: update its webhook and start it
            self._call("PUT", f"/api/sessions/{self.session}", {"name": self.session, "config": config})
            return self._call("POST", f"/api/sessions/{self.session}/start")

    def status(self) -> dict:
        """``{"status": "WORKING" | "SCAN_QR_CODE" | "STARTING" | "STOPPED" | "FAILED", "me": {...}}``."""
        return self._call("GET", f"/api/sessions/{self.session}")

    def qr_data_uri(self) -> str:
        data = self._call("GET", f"/api/{self.session}/auth/qr?format=image")
        return f"data:{data.get('mimetype', 'image/png')};base64,{data.get('data', '')}"

    def logout(self) -> None:
        self._call("POST", f"/api/sessions/{self.session}/logout")

    def send_text(self, to: str, text: str) -> str:
        data = self._call("POST", "/api/sendText", {"session": self.session, "chatId": f"{to}@c.us", "text": text})
        message_id = data.get("id") if isinstance(data, dict) else None
        if isinstance(message_id, dict):
            message_id = message_id.get("_serialized") or message_id.get("id")
        return str(message_id or "")
