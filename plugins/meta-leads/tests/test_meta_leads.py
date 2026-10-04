from __future__ import annotations

import hashlib
import hmac
import json
import re
import urllib.parse

from sqlalchemy import select
from tungsten_leads import Lead, LeadField

from tungsten_meta_leads import MetaForm, MetaLeadLog, MetaPage, MetaSettings, map_answers

FORM_QUESTIONS = [
    {"key": "full_name", "label": "Full name", "type": "FULL_NAME"},
    {"key": "phone_number", "label": "Phone", "type": "PHONE"},
    {"key": "which_course?", "label": "Which course?", "type": "CUSTOM",
     "options": [{"key": "mba", "value": "MBA"}, {"key": "bca", "value": "BCA"}]},
]


def lead_payload(lead_id="L1", name="Amit Sharma", course="MBA"):
    return {"id": lead_id, "created_time": "2026-10-04T10:00:00+0000", "form_id": "F1", "platform": "ig",
            "field_data": [{"name": "full_name", "values": [name]},
                           {"name": "phone_number", "values": ["+919876543210"]},
                           {"name": "which_course?", "values": [course]}]}


def fake_meta(graph):
    graph.routes.update({
        "GET oauth/access_token": lambda p: {"access_token": "LONG" if p.get("grant_type") else "SHORT"},
        "GET me": {"id": "U1", "name": "Asha on Facebook"},
        "GET me/accounts": {"data": [{"id": "P1", "name": "Prism Page", "access_token": "PAGE-TOKEN"}]},
        "POST P1/subscribed_apps": {"success": True},
        "POST 111/subscriptions": {"success": True},
        "GET P1/leadgen_forms": {"data": [{"id": "F1", "name": "Admissions form", "status": "ACTIVE",
                                           "questions": FORM_QUESTIONS}]},
        "GET L1": lead_payload(),
        "GET F1/leads": {"data": [lead_payload("L1"), lead_payload("L2", "Priya Patel", "BCA")]},
    })


def connect_facebook(admin, graph):
    fake_meta(graph)
    page = admin.get("/admin/meta-leads").text
    link = re.search(r'href="(https://www\.facebook\.com/[^"]+)"', page).group(1).replace("&amp;", "&")
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(link).query))
    assert query["client_id"] == "111" and "leads_retrieval" in query["scope"]
    assert query["redirect_uri"] == "https://crm.example.com/admin/meta/callback"
    return admin.client.get(f"/admin/meta/callback?code=abc&state={query['state']}", follow_redirects=False)


def test_map_answers_splits_core_and_custom():
    core, custom = map_answers([
        {"name": "first_name", "values": ["Amit"]}, {"name": "last_name", "values": ["Shah"]},
        {"name": "email", "values": ["a@x.com"]}, {"name": "budget", "values": ["50k"]},
        {"name": "ignore_me", "values": ["x"]}, {"name": "slots", "values": ["Morning", "Evening"]},
    ], {"ignore_me": ""})
    assert core == {"name": "Amit Shah", "email": "a@x.com"}
    assert custom == {"budget": "50k", "slots": ["Morning", "Evening"]}


def test_one_click_connect_sets_up_everything(admin, panel, graph):
    r = connect_facebook(admin, graph)
    assert r.status_code == 303 and r.headers["location"].endswith("meta=connected"), r.headers["location"]
    with panel.db() as db:
        settings = db.scalars(select(MetaSettings)).one()
        assert settings.user_token == "LONG" and settings.webhook_ok
        page = db.scalars(select(MetaPage)).one()
        assert page.subscribed and page.access_token == "PAGE-TOKEN"
        form = db.scalars(select(MetaForm)).one()
        assert form.field_map == {"full_name": "name", "phone_number": "phone", "which_course?": "which_course"}
        field = db.scalars(select(LeadField).where(LeadField.key == "which_course")).one()
        assert field.type == "select" and field.options == ["MBA", "BCA"] and field.label == "Which course?"
    sub = next(c for c in graph.calls if c[1] == "111/subscriptions")[2]
    assert sub["callback_url"] == "https://crm.example.com/admin/meta/webhook" and sub["access_token"] == "111|shh"
    page = admin.get("/admin/meta-leads?meta=connected").text
    assert "Prism Page" in page and "Receiving leads" in page and "Asha on Facebook" in page


def test_callback_rejects_wrong_state(admin, graph):
    admin.get("/admin/meta-leads")
    r = admin.client.get("/admin/meta/callback?code=abc&state=forged", follow_redirects=False)
    assert r.headers["location"].endswith("meta=state")
    assert not graph.calls


def test_webhook_verify_and_signed_lead(admin, panel, graph, client):
    connect_facebook(admin, graph)
    with panel.db() as db:
        token = db.scalars(select(MetaSettings)).one().verify_token
    r = client.client.get(f"/admin/meta/webhook?hub.mode=subscribe&hub.verify_token={token}&hub.challenge=42")
    assert r.text == "42"
    assert client.client.get("/admin/meta/webhook?hub.mode=subscribe&hub.verify_token=no&hub.challenge=1").status_code == 403

    body = json.dumps({"object": "page", "entry": [{"id": "P1", "changes": [
        {"field": "leadgen", "value": {"leadgen_id": "L1", "page_id": "P1", "form_id": "F1"}}]}]}).encode()
    bad = client.client.post("/admin/meta/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=00"})
    assert bad.status_code == 403
    sig = "sha256=" + hmac.new(b"shh", body, hashlib.sha256).hexdigest()
    for _ in range(2):  # Meta may send the same lead twice
        r = client.client.post("/admin/meta/webhook", content=body, headers={"X-Hub-Signature-256": sig})
        assert r.status_code == 200
    with panel.db() as db:
        lead = db.scalars(select(Lead)).one()
        assert (lead.name, lead.phone, lead.source) == ("Amit Sharma", "+919876543210", "meta")
        assert lead.custom_fields == {"which_course": "MBA"} and lead.external_id == "meta:L1"
        assert "Admissions form" in lead.activities[0].body
        assert [log.status for log in db.scalars(select(MetaLeadLog).order_by(MetaLeadLog.id))] == ["imported", "duplicate"]
        assert db.scalars(select(MetaForm)).one().leads_imported == 1
    get_lead = next(c for c in graph.calls if c[1] == "L1")[2]
    assert get_lead["access_token"] == "PAGE-TOKEN" and "appsecret_proof" in get_lead


def test_sync_button_and_switched_off_form(admin, panel, graph):
    connect_facebook(admin, graph)
    with panel.db() as db:
        db.scalars(select(MetaForm)).one().default_status = "contacted"
        db.commit()
    r = admin.post("/admin/_tw/action", {"_tw_host": "page:meta-leads", "_tw_scope": "page", "_tw_name": "sync"})
    assert r.status_code in (200, 204), r.text
    assert "2 new leads" in admin.get("/admin/meta-leads").text  # the toast shows on the next page
    with panel.db() as db:
        leads = db.scalars(select(Lead)).all()
        assert sorted(lead.name for lead in leads) == ["Amit Sharma", "Priya Patel"]
        assert {lead.status for lead in leads} == {"contacted"}
        form = db.scalars(select(MetaForm)).one()
        form.enabled = False
        db.commit()

    graph.routes["GET F1/leads"] = {"data": [lead_payload("L3", "Neha")]}
    admin.post("/admin/_tw/action", {"_tw_host": "page:meta-leads", "_tw_scope": "page", "_tw_name": "sync"})
    with panel.db() as db:
        assert db.scalars(select(Lead).where(Lead.name == "Neha")).first() is None


def test_graph_error_is_shown(admin, panel, graph):
    connect_facebook(admin, graph)
    graph.routes["GET P1/leadgen_forms"] = (400, {"error": {"message": "Token expired"}})
    graph.routes["GET F1/leads"] = (400, {"error": {"message": "Token expired"}})
    r = admin.post("/admin/_tw/action", {"_tw_host": "page:meta-leads", "_tw_scope": "page", "_tw_name": "sync"})
    assert "Token expired" in r.headers.get("HX-Trigger", "") + r.text + admin.get("/admin/meta-leads").text


def test_screens_render(admin, panel, graph):
    connect_facebook(admin, graph)
    for url in ("/admin/meta-leads", "/admin/meta-forms", "/admin/meta-lead-log"):
        assert admin.get(url).status_code == 200, url
    with panel.db() as db:
        form_id = db.scalars(select(MetaForm)).one().id
    edit = admin.get(f"/admin/meta-forms/{form_id}/edit").text
    assert "which_course?" in edit and "Answers go to" in edit
