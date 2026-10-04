"""Connecting to Meta, reading lead forms, and turning Meta leads into Tungsten leads."""

from __future__ import annotations

import datetime as dt
import re
import secrets
from typing import Any

from sqlalchemy import select
from tungsten_leads import LeadField, add_activity, create_lead, find_lead

from .graph import Graph, GraphError
from .models import MetaForm, MetaLeadLog, MetaPage, MetaSettings

#: what we ask the Facebook user to allow
SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_metadata", "pages_manage_ads",
          "leads_retrieval", "business_management", "ads_management", "ads_read"]
LEAD_FIELDS = "id,created_time,field_data,form_id,ad_id,platform,is_organic"

#: targets a Meta answer can go to, besides a lead field key
CORE_TARGETS = {"name", "first_name", "last_name", "email", "phone", "company", "notes"}

#: Meta's standard question keys and where they go by default
DEFAULT_MAP = {
    "full_name": "name",
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
    "phone_number": "phone",
    "phone": "phone",
    "company_name": "company",
}


def get_settings(db: Any) -> MetaSettings:
    row = db.scalars(select(MetaSettings)).first()
    if row is None:
        # saved right away, so the verify token shown on the setup page stays the same
        row = MetaSettings(verify_token=secrets.token_urlsafe(24))
        db.add(row)
        db.commit()
    return row


def field_key(text: str) -> str:
    """``What's your budget?`` → ``whats_your_budget``."""
    key = re.sub(r"[^a-z0-9]+", "_", text.lower().replace("'", "")).strip("_")[:60] or "answer"
    return key if key[0].isalpha() else f"q_{key}"[:60]


# ---------------------------------------------------------------------- connect
def connect(db: Any, graph: Graph, *, app_id: str, app_secret: str, code: str, redirect_uri: str) -> list[MetaPage]:
    """Finish the Facebook login: save a long-lived token, the pages, and subscribe each page to leads."""
    short = graph.get("oauth/access_token", client_id=app_id, client_secret=app_secret,
                      redirect_uri=redirect_uri, code=code)["access_token"]
    long = graph.get("oauth/access_token", grant_type="fb_exchange_token", client_id=app_id,
                     client_secret=app_secret, fb_exchange_token=short).get("access_token", short)
    me = graph.get("me", fields="id,name", access_token=long)
    settings = get_settings(db)
    settings.user_token, settings.user_name, settings.connected_at = long, me.get("name"), dt.datetime.now()

    pages = []
    for row in graph.paginate("me/accounts", fields="id,name,access_token", access_token=long, limit=200):
        page = db.scalars(select(MetaPage).where(MetaPage.page_id == row["id"])).first() or MetaPage(page_id=row["id"])
        page.name, page.access_token = row.get("name", ""), row.get("access_token", "")
        db.add(page)
        subscribe_page(graph, page)
        pages.append(page)
    db.flush()
    return pages


def subscribe_page(graph: Graph, page: MetaPage) -> None:
    """Ask Meta to send this page's new leads to our webhook."""
    try:
        graph.post(f"{page.page_id}/subscribed_apps", subscribed_fields="leadgen", access_token=page.access_token)
        page.subscribed, page.error = True, None
    except GraphError as exc:
        page.subscribed, page.error = False, str(exc)


def subscribe_app(db: Any, graph: Graph, *, app_id: str, app_secret: str, callback_url: str) -> bool:
    """Point the Meta app's page webhook at ``callback_url`` (Meta calls it once to check it)."""
    settings = get_settings(db)
    try:
        graph.post(f"{app_id}/subscriptions", object="page", callback_url=callback_url, fields="leadgen",
                   verify_token=settings.verify_token, include_values="true",
                   access_token=f"{app_id}|{app_secret}")
        settings.webhook_ok, settings.webhook_error = True, None
    except GraphError as exc:
        settings.webhook_ok, settings.webhook_error = False, str(exc)
    return settings.webhook_ok


def disconnect(db: Any) -> None:
    settings = get_settings(db)
    settings.user_token = settings.user_name = settings.connected_at = None
    for page in db.scalars(select(MetaPage)).all():
        db.delete(page)


# ---------------------------------------------------------------------- forms
def refresh_forms(db: Any, graph: Graph, *, auto_create_fields: bool = True) -> list[MetaForm]:
    """Read the lead forms of every connected page, keeping each form's own settings."""
    forms = []
    for page in db.scalars(select(MetaPage)).all():
        try:
            rows = list(graph.paginate(f"{page.page_id}/leadgen_forms", fields="id,name,status,questions",
                                       access_token=page.access_token, limit=500))
        except GraphError as exc:
            page.error = str(exc)
            continue
        for row in rows:
            form = db.scalars(select(MetaForm).where(MetaForm.form_id == row["id"])).first()
            if form is None:
                form = MetaForm(form_id=row["id"], enabled=True)
                db.add(form)
            form.page_id, form.page_name = page.page_id, page.name
            form.name, form.status = row.get("name", ""), row.get("status")
            form.questions = row.get("questions") or []
            form.field_map = default_map(form.questions, form.field_map)
            if auto_create_fields:
                ensure_lead_fields(db, form)
            forms.append(form)
    db.flush()
    return forms


def default_map(questions: list[dict], current: dict | None = None) -> dict[str, str]:
    """Keep the admin's choices; add new questions with a sensible target."""
    mapping = dict(current or {})
    for q in questions:
        key = q.get("key")
        if key and key not in mapping:
            mapping[key] = DEFAULT_MAP.get(key) or DEFAULT_MAP.get(str(q.get("type", "")).lower()) or field_key(key)
    return mapping


def ensure_lead_fields(db: Any, form: MetaForm) -> None:
    """Add a lead field for every answer that goes to a field that doesn't exist yet."""
    existing = set(db.scalars(select(LeadField.key)).all())
    by_key = {q.get("key"): q for q in form.questions or []}
    for meta_key, target in (form.field_map or {}).items():
        if not target or target in CORE_TARGETS or target in existing:
            continue
        q = by_key.get(meta_key, {})
        options = [o.get("value") for o in q.get("options") or [] if o.get("value")]
        db.add(LeadField(label=(q.get("label") or meta_key.replace("_", " ").capitalize())[:100], key=target,
                         type="select" if options else "text", options=options or None, sort=100))
        existing.add(target)


# ---------------------------------------------------------------------- leads
def map_answers(field_data: list[dict], field_map: dict | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split Meta's answers into lead columns and custom field values."""
    mapping = {**DEFAULT_MAP, **(field_map or {})}
    core: dict[str, Any] = {}
    custom: dict[str, Any] = {}
    for item in field_data or []:
        values = [v for v in item.get("values") or [] if v not in (None, "")]
        if not values:
            continue
        key = item.get("name", "")
        target = mapping.get(key, field_key(key))
        if not target:
            continue
        value = values[0] if len(values) == 1 else values
        if target in CORE_TARGETS:
            core[target] = ", ".join(values) if isinstance(value, list) else value
        else:
            custom[target] = value
    first, last = core.pop("first_name", None), core.pop("last_name", None)
    if not core.get("name") and (first or last):
        core["name"] = " ".join(p for p in (first, last) if p)
    return core, custom


def save_lead(db: Any, data: dict[str, Any], *, form: MetaForm | None, page_id: str | None, via: str,
              default_status: str = "new") -> MetaLeadLog:
    """Turn one Meta lead (as Graph returns it) into a Tungsten lead, once."""
    leadgen_id = str(data.get("id"))
    external_id = f"meta:{leadgen_id}"
    log = MetaLeadLog(leadgen_id=leadgen_id, form_id=form.form_id if form else data.get("form_id"),
                      page_id=page_id, via=via)
    db.add(log)
    existing = find_lead(db, external_id=external_id)
    if existing is not None:
        log.status, log.lead_id = "duplicate", existing.id
        return log
    if form is not None and not form.enabled:
        log.status, log.error = "skipped", "This form is switched off."
        return log
    core, custom = map_answers(data.get("field_data", []), form.field_map if form else None)
    lead = create_lead(db, source="meta", status=(form.default_status if form else None) or default_status,
                       assigned_to=form.assign_to if form else None, external_id=external_id,
                       custom_fields=custom, **core)
    where = f'form "{form.name}"' if form else "a Meta lead form"
    platform = {"fb": "Facebook", "ig": "Instagram"}.get(str(data.get("platform")), data.get("platform"))
    extra = ", ".join(p for p in (f"on {platform}" if platform else "", f"ad {data['ad_id']}" if data.get("ad_id") else "") if p)
    add_activity(db, lead, f"Came from {where}" + (f" ({extra})" if extra else ""), type="system")
    log.status, log.lead_id = "imported", lead.id
    if form is not None:
        form.leads_imported = (form.leads_imported or 0) + 1
        form.last_lead_at = dt.datetime.now()
    return log


def import_leadgen(db: Any, graph: Graph, *, leadgen_id: str, page_id: str | None, form_id: str | None,
                   via: str = "webhook", default_status: str = "new") -> MetaLeadLog:
    """Fetch one lead by id (from a webhook) and save it."""
    page = db.scalars(select(MetaPage).where(MetaPage.page_id == str(page_id))).first() if page_id else None
    form = db.scalars(select(MetaForm).where(MetaForm.form_id == str(form_id))).first() if form_id else None
    if page is None:
        log = MetaLeadLog(leadgen_id=str(leadgen_id), form_id=form_id, page_id=page_id, via=via, status="failed",
                          error="This page is not connected. Connect it on the Facebook & Instagram setup page.")
        db.add(log)
        return log
    try:
        data = graph.get(str(leadgen_id), fields=LEAD_FIELDS, access_token=page.access_token)
    except GraphError as exc:
        log = MetaLeadLog(leadgen_id=str(leadgen_id), form_id=form_id, page_id=page_id, via=via, status="failed",
                          error=str(exc))
        db.add(log)
        return log
    return save_lead(db, data, form=form, page_id=page.page_id, via=via, default_status=default_status)


def handle_webhook(db: Any, graph: Graph, payload: dict[str, Any], default_status: str = "new") -> list[MetaLeadLog]:
    """Process a webhook call from Meta (``object: page``, ``field: leadgen``)."""
    logs = []
    if payload.get("object") != "page":
        return logs
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            value = change.get("value", {})
            logs.append(import_leadgen(db, graph, leadgen_id=value.get("leadgen_id"),
                                       page_id=value.get("page_id") or entry.get("id"),
                                       form_id=value.get("form_id"), default_status=default_status))
    if any(log.status in ("imported", "duplicate") for log in logs):
        # a real lead came in: the app is live and the webhook works (also when it was set by hand in Meta)
        settings = get_settings(db)
        settings.last_webhook_at, settings.webhook_ok, settings.webhook_error = dt.datetime.now(), True, None
    return logs


def sync_form(db: Any, graph: Graph, form: MetaForm, *, limit: int = 500, default_status: str = "new") -> int:
    """Read the form's recent leads from Meta and save the ones we don't have. Returns how many were new."""
    page = db.scalars(select(MetaPage).where(MetaPage.page_id == form.page_id)).first()
    if page is None:
        raise GraphError("The page of this form is not connected.")
    new = 0
    for data in graph.paginate(f"{form.form_id}/leads", fields=LEAD_FIELDS, access_token=page.access_token,
                               limit=limit):
        if find_lead(db, external_id=f"meta:{data.get('id')}") is not None:
            continue
        log = save_lead(db, data, form=form, page_id=page.page_id, via="sync", default_status=default_status)
        new += log.status == "imported"
    form.last_synced_at = dt.datetime.now()
    db.flush()
    return new
