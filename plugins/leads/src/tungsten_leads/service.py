"""Functions other code (and other plugins) use to add leads.

    from tungsten_leads import create_lead

    lead = create_lead(db, name="Amit", phone="+919876543210", source="website",
                       custom_fields={"budget": 50000})
    db.commit()
"""

from __future__ import annotations

import re
from typing import Any, Callable

from sqlalchemy import select

from .models import Lead, LeadActivity

#: functions called as ``fn(db, lead)`` after a lead is added by ``create_lead``
_listeners: list[Callable[[Any, Lead], None]] = []


def on_lead_created(fn: Callable[[Any, Lead], None]) -> Callable[[Any, Lead], None]:
    """Run ``fn(db, lead)`` whenever ``create_lead`` adds a new lead (a welcome WhatsApp message...)."""
    if fn not in _listeners:
        _listeners.append(fn)
    return fn


def normalize_phone(phone: str | None) -> str | None:
    """Keep the leading ``+`` and the digits: ``+91 98765-43210`` → ``+919876543210``."""
    if not phone:
        return None
    phone = str(phone).strip()
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    return ("+" if phone.startswith("+") else "") + digits


def find_lead(db: Any, *, external_id: str | None = None, phone: str | None = None,
              email: str | None = None) -> Lead | None:
    """Find a lead by its outside id, phone (last 10 digits) or email, in that order."""
    if external_id:
        lead = db.scalars(select(Lead).where(Lead.external_id == str(external_id))).first()
        if lead is not None:
            return lead
    phone = normalize_phone(phone)
    if phone:
        tail = re.sub(r"\D", "", phone)[-10:]
        lead = db.scalars(select(Lead).where(Lead.phone.like(f"%{tail}")).order_by(Lead.id.desc())).first()
        if lead is not None:
            return lead
    if email:
        return db.scalars(select(Lead).where(Lead.email == email.strip().lower()).order_by(Lead.id.desc())).first()
    return None


def create_lead(db: Any, *, name: str | None = None, email: str | None = None, phone: str | None = None,
                source: str = "manual", status: str = "new", company: str | None = None,
                notes: str | None = None, custom_fields: dict | None = None, external_id: str | None = None,
                assigned_to: str | None = None, skip_duplicates: bool = True, **extra: Any) -> Lead:
    """Add a lead and return it. With an ``external_id`` that is already saved, return that lead instead.

    The session is flushed, not committed: call ``db.commit()`` yourself.
    """
    if skip_duplicates and external_id:
        existing = find_lead(db, external_id=external_id)
        if existing is not None:
            return existing
    email = email.strip().lower() if email else None
    phone = normalize_phone(phone)
    lead = Lead(
        name=(name or "").strip() or email or phone or "Unknown",
        email=email,
        phone=phone,
        company=company,
        source=source,
        status=status,
        notes=notes,
        custom_fields=dict(custom_fields or {}),
        external_id=str(external_id) if external_id else None,
        assigned_to=assigned_to,
        **extra,
    )
    db.add(lead)
    db.flush()
    for fn in list(_listeners):
        fn(db, lead)
    return lead


def add_activity(db: Any, lead: Lead, body: str, type: str = "note", user_id: str | None = None) -> LeadActivity:
    """Add a line to the lead's timeline (``type`` is note, call, email, meeting, whatsapp or system)."""
    activity = LeadActivity(lead_id=lead.id, type=type, body=body, user_id=user_id)
    db.add(activity)
    db.flush()
    return activity
