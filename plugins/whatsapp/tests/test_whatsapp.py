from __future__ import annotations

import hashlib
import hmac
import json

from sqlalchemy import select
from tungsten_leads import Lead, LeadActivity, create_lead

from tungsten_whatsapp import WhatsAppMessage, WhatsAppSettings, click_to_chat_url, to_digits

ACTION = "/admin/_tw/action"


def configure(panel, **values):
    from tungsten_whatsapp.service import get_settings

    def run(db):
        settings = get_settings(db)
        for k, v in values.items():
            setattr(settings, k, v)
        db.commit()

    panel.with_session(run)


def cloud(panel, http):
    configure(panel, channel="cloud", phone_number_id="PN1", access_token="TOKEN", app_secret="shh",
              business_account_id="WABA1")
    http.routes["POST PN1/messages"] = lambda body: {"messages": [{"id": f"wamid.{len(http.calls)}"}]}


def web(panel, http):
    configure(panel, channel="web", gateway_url="http://waha:3000", gateway_api_key="k", gateway_session="default")
    http.routes["POST /api/sendText"] = lambda body: {"id": {"_serialized": f"true_{body['chatId']}_X1"}}


def add_lead(panel, **kw):
    def run(db):
        lead = create_lead(db, **{"name": "Amit Sharma", "phone": "98765 43210", **kw})
        db.commit()
        return lead.id

    return panel.with_session(run)


def test_numbers_and_links():
    assert to_digits("+91 98765-43210") == "919876543210"
    assert to_digits("98765 43210") == "919876543210"
    assert to_digits("09876543210") == "919876543210"
    assert to_digits("0044 20 7946 0958") == "442079460958"
    assert click_to_chat_url("98765 43210", "Hi there") == "https://wa.me/919876543210?text=Hi%20there"


def test_links_only_mode_opens_whatsapp(admin, panel):
    lead_id = add_lead(panel)
    assert 'href="https://wa.me/919876543210"' in admin.get(f"/admin/leads/{lead_id}").text
    assert "https://wa.me/919876543210" in admin.get("/admin/leads").text


def test_send_from_lead_on_cloud_api(admin, panel, http):
    cloud(panel, http)
    lead_id = add_lead(panel)
    modal = admin.get(f"{ACTION}?_tw_host=resource:leads&_tw_scope=row&_tw_name=whatsapp&_tw_record={lead_id}",
                      headers={"HX-Request": "true"})
    assert 'name="message"' in modal.text and "24 hours" in modal.text
    r = admin.post(ACTION, {"_tw_host": "resource:leads", "_tw_scope": "row", "_tw_name": "whatsapp",
                            "_tw_record": str(lead_id), "message": "Hi {first_name}, here is the brochure"})
    assert r.status_code == 200 and "WhatsApp sent" in r.headers.get("HX-Trigger", ""), r.text[:300]
    method, path, body, headers = http.calls[-1]
    assert path == "PN1/messages" and body["to"] == "+919876543210"
    assert body["text"]["body"] == "Hi Amit, here is the brochure" and headers["Authorization"] == "Bearer TOKEN"
    with panel.db() as db:
        msg = db.scalars(select(WhatsAppMessage)).one()
        assert (msg.direction, msg.status, msg.lead_id) == ("out", "sent", lead_id)
        assert db.scalars(select(LeadActivity).where(LeadActivity.type == "whatsapp")).one().body.startswith("Sent:")


def test_cloud_error_is_kept_and_shown(admin, panel, http):
    cloud(panel, http)
    http.routes["POST PN1/messages"] = (400, {"error": {"message": "(#131047) Re-engagement message",
                                                        "error_data": {"details": "More than 24 hours have passed"}}})
    lead_id = add_lead(panel)
    r = admin.post(ACTION, {"_tw_host": "resource:leads", "_tw_scope": "row", "_tw_name": "whatsapp",
                            "_tw_record": str(lead_id), "message": "Hello"})
    assert "More than 24 hours have passed" in r.headers.get("HX-Trigger", "")
    with panel.db() as db:
        msg = db.scalars(select(WhatsAppMessage)).one()
        assert msg.status == "failed" and "24 hours" in msg.error


def test_cloud_webhook_verify_incoming_and_ticks(admin, panel, http, client):
    cloud(panel, http)
    with panel.db() as db:
        token = db.scalars(select(WhatsAppSettings)).one().verify_token
    r = client.client.get(f"/admin/whatsapp/webhook?hub.mode=subscribe&hub.verify_token={token}&hub.challenge=7")
    assert r.text == "7"

    def post(payload, secret=b"shh"):
        body = json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        return client.client.post("/admin/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sig})

    incoming = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"wa_id": "919811112222", "profile": {"name": "Priya Patel"}}],
        "messages": [{"from": "919811112222", "id": "wamid.IN1", "type": "text", "text": {"body": "Price?"}}]}}]}]}
    assert post(incoming, b"wrong").status_code == 403
    assert post(incoming).status_code == 200
    assert post(incoming).status_code == 200  # the same message again is ignored
    with panel.db() as db:
        lead = db.scalars(select(Lead)).one()
        assert (lead.name, lead.phone, lead.source) == ("Priya Patel", "+919811112222", "whatsapp")
        assert db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.direction == "in")).one().body == "Price?"
        lead_id = lead.id

    admin.post(ACTION, {"_tw_host": "resource:leads", "_tw_scope": "row", "_tw_name": "whatsapp",
                        "_tw_record": str(lead_id), "message": "It is 5000"})
    with panel.db() as db:
        wamid = db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.direction == "out")).one().external_id
    ticks = {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "statuses": [{"id": wamid, "status": "read"}, {"id": wamid, "status": "delivered"}]}}]}]}
    post(ticks)
    with panel.db() as db:
        assert db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.external_id == wamid)).one().status == "read"


def gateway(http, status="SCAN_QR_CODE"):
    """A fake WAHA gateway that remembers its one session."""
    state: dict = {"session": None}

    def create(body):
        state["session"] = {"name": body["name"], "status": status, "config": body["config"]}
        return state["session"]

    def update(body):
        state["session"] = {**state["session"], "config": body["config"]}
        return state["session"]

    http.routes.update({
        "POST /api/sessions": create,
        "PUT /api/sessions/default": update,
        "GET /api/sessions/default": lambda body: state["session"] or (404, {"message": "Session not found"}),
        "GET /api/default/auth/qr": {"mimetype": "image/png", "data": "QRDATA"},
    })
    return state


def test_web_link_phone_and_incoming(admin, panel, http, client):
    web(panel, http)
    state = gateway(http)
    link = f"{ACTION}?_tw_host=page:whatsapp&_tw_scope=page&_tw_name=link"
    modal = admin.get(link, headers={"HX-Request": "true"})
    assert "data:image/png;base64,QRDATA" in modal.text
    assert 'hx-trigger="every 15s"' in modal.text and 'hx-select="#tw-wa-qr"' in modal.text  # a fresh code by itself
    start = next(c for c in http.calls if c[1] == "/api/sessions")
    hook = start[2]["config"]["webhooks"][0]["url"]
    assert hook.startswith("https://crm.example.com/admin/whatsapp/web-webhook?token=") and start[3]["X-Api-Key"] == "k"

    admin.get(link, headers={"HX-Request": "true"})  # the code refreshing must not restart the session
    assert [c[0] for c in http.calls if c[1].startswith("/api/sessions")] == ["GET", "POST", "GET", "GET", "GET"]

    state["session"].update(status="STARTING")  # logging in right after the scan: no code to show
    calls = len(http.calls)
    box = admin.get(link, headers={"HX-Request": "true"}).text
    assert "Connecting to WhatsApp" in box and 'hx-trigger="every 15s"' in box
    assert not [c for c in http.calls[calls:] if c[1].endswith("/auth/qr")]
    http.routes["GET /api/default/auth/qr"] = (422, {"message": "Session status is not as expected"})
    state["session"].update(status="SCAN_QR_CODE")
    box = admin.get(link, headers={"HX-Request": "true"}).text
    assert "Session status is not as expected" in box and 'hx-trigger="every 15s"' in box  # keeps asking

    state["session"].update(status="WORKING", me={"id": "919900001111@c.us"})
    box = admin.get(link, headers={"HX-Request": "true"}).text
    assert "Linked to +919900001111" in box and "every 15s" not in box
    admin.post(ACTION, {"_tw_host": "page:whatsapp", "_tw_scope": "page", "_tw_name": "link"})
    with panel.db() as db:
        settings = db.scalars(select(WhatsAppSettings)).one()
        assert settings.web_status == "WORKING" and settings.web_phone == "919900001111"

    path = hook.split("crm.example.com", 1)[1]
    event = {"event": "message", "session": "default", "payload": {
        "id": "false_919822223333@c.us_ABC", "from": "919822223333@c.us", "fromMe": False, "body": "Hi, need a website",
        "_data": {"notifyName": "Rahul"}}}
    assert client.client.post("/admin/whatsapp/web-webhook?token=nope", json=event).status_code == 403
    assert client.client.post(path, json=event).status_code == 200
    group = {"event": "message", "payload": {"id": "g1", "from": "1203@g.us", "body": "group chat"}}
    client.client.post(path, json=group)
    with panel.db() as db:
        lead = db.scalars(select(Lead)).one()
        assert (lead.name, lead.phone) == ("Rahul", "+919822223333")

    # WhatsApp hides many numbers behind an @lid id: the number comes from the event, or else from the gateway
    hidden = {"event": "message", "payload": {"id": "L1", "from": "123456789@lid", "body": "Hello",
                                              "_data": {"key": {"remoteJidAlt": "919833334444@s.whatsapp.net"},
                                                        "pushName": "Sita"}}}
    client.client.post(path, json=hidden)
    http.routes["GET /api/default/lids/987654321"] = {"lid": "987654321@lid", "pn": "919855556666@c.us"}
    gows = {"event": "message", "payload": {"id": "L2", "from": "987654321@lid", "body": "Hi",
                                            "_data": {"Info": {"PushName": "Gita"}}}}
    client.client.post(path, json=gows)
    http.routes["GET /api/default/lids/555"] = {"lid": "555@lid", "pn": None}  # not in the phone's contacts
    client.client.post(path, json={"event": "message", "payload": {"id": "L3", "from": "555@lid", "body": "Price?",
                                                                    "_data": {"notifyName": "Mohan"}}})
    with panel.db() as db:
        phones = {lead.name: lead.phone for lead in db.scalars(select(Lead))}
        assert phones["Sita"] == "+919833334444" and phones["Gita"] == "+919855556666" and "Mohan" not in phones
        hidden_msg = db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.external_id == "L3")).one()
        assert (hidden_msg.phone, hidden_msg.body) == ("", "[Mohan (555@lid)] Price?")
    assert "Number hidden" in admin.get("/admin/whatsapp-messages").text

    lead_id = add_lead(panel, name="Ravi Kumar", phone="9000000009")
    admin.post(ACTION, {"_tw_host": "resource:leads", "_tw_scope": "row", "_tw_name": "whatsapp",
                        "_tw_record": str(lead_id), "message": "Hello"})
    with panel.db() as db:
        sent = db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.direction == "out")).one()
    client.client.post(path, json={"event": "message.ack", "payload": {"id": sent.external_id, "ack": -1,
                                                                        "ackName": "ERROR"}})
    with panel.db() as db:
        assert db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.direction == "out")).one().status == "failed"


def test_gateway_session_is_only_changed_when_needed(http):
    from tungsten_whatsapp.client import WEB_EVENTS, WebClient

    client = WebClient("http://waha:3000", "k", "default", transport=http)
    hook = "https://crm.example.com/admin/whatsapp/web-webhook?token=t"
    other = {"url": "https://n8n.example.com/hook", "events": ["message"]}
    session = {"name": "default", "status": "WORKING", "config": {"webhooks": [other, {"url": hook, "events": list(WEB_EVENTS)}]}}
    http.routes["GET /api/sessions/default"] = session
    assert client.start(hook)["status"] == "WORKING"
    assert [c[0] for c in http.calls] == ["GET"]  # a linked phone is left alone

    old = {"url": "http://old-address/admin/whatsapp/web-webhook?token=t", "events": ["message"]}
    http.routes["GET /api/sessions/default"] = {**session, "status": "STOPPED", "config": {"webhooks": [other, old]}}
    http.routes["PUT /api/sessions/default"] = lambda body: {"status": "STOPPED", "config": body["config"]}
    http.routes["POST /api/sessions/default/start"] = {"status": "STARTING"}
    client.start(hook)
    put = next(c for c in http.calls if c[0] == "PUT")
    assert put[2]["config"]["webhooks"] == [other, {"url": hook, "events": list(WEB_EVENTS)}]
    assert http.calls[-1][1] == "/api/sessions/default/start"


def test_welcome_message_for_new_leads(panel, http):
    web(panel, http)
    configure(panel, welcome_enabled=True, welcome_sources=["meta"], welcome_text="Hi {first_name}, thanks!")
    add_lead(panel, source="manual")
    assert not [c for c in http.calls if c[1] == "/api/sendText"]
    lead_id = add_lead(panel, name="Neha Gupta", phone="+91 99999 88888", source="meta")
    sent = [c for c in http.calls if c[1] == "/api/sendText"]
    assert len(sent) == 1 and sent[0][2] == {"session": "default", "chatId": "919999988888@c.us",
                                             "text": "Hi Neha, thanks!"}
    with panel.db() as db:
        assert db.scalars(select(WhatsAppMessage)).one().lead_id == lead_id


def test_bulk_send(admin, panel, http):
    web(panel, http)
    a, b = add_lead(panel, name="A One", phone="9000000001"), add_lead(panel, name="B Two", phone="9000000002")
    add_lead(panel, name="No Phone", phone=None)
    r = admin.post(ACTION, {"_tw_host": "resource:leads", "_tw_scope": "bulk", "_tw_name": "whatsapp",
                            "records": [str(a), str(b)], "message": "Hello {first_name}"})
    assert "2 sent" in r.headers.get("HX-Trigger", ""), r.text[:300]
    texts = sorted(c[2]["text"] for c in http.calls if c[1] == "/api/sendText")
    assert texts == ["Hello A", "Hello B"]


def test_setup_page_keeps_secrets(admin, panel):
    assert admin.get("/admin/whatsapp").status_code == 200
    configure(panel, channel="cloud", access_token="KEEP", app_secret="KEEP2")
    r = admin.post("/admin/whatsapp", {"channel": "cloud", "country_code": "+91", "phone_number_id": "PN9",
                                       "business_account_id": "", "access_token": "", "app_secret": ""})
    assert "The whatsapp business account id field is required." in r.text  # needed for replies now
    r = admin.post("/admin/whatsapp", {"channel": "cloud", "country_code": "+91", "phone_number_id": "PN9",
                                       "business_account_id": "WABA9", "access_token": "", "app_secret": ""})
    assert r.headers.get("HX-Redirect") == "/admin/whatsapp", r.text[:300]  # reload: the next buttons show now
    assert "Register number" in admin.get("/admin/whatsapp").text
    r = admin.post("/admin/whatsapp", {"channel": "cloud", "country_code": "+91", "phone_number_id": "PN9",
                                       "business_account_id": "WABA9", "access_token": "", "app_secret": "",
                                       "create_leads": "1"})
    assert r.status_code == 200 and "HX-Redirect" not in r.headers  # nothing at the top changed
    with panel.db() as db:
        s = db.scalars(select(WhatsAppSettings)).one()
        assert (s.phone_number_id, s.access_token, s.app_secret, s.country_code) == ("PN9", "KEEP", "KEEP2", "91")

    configure(panel, channel=None, gateway_api_key=None)
    r = admin.post("/admin/whatsapp", {"channel": "web", "gateway_url": "http://waha:3000", "gateway_api_key": "",
                                       "gateway_session": "default"})
    with panel.db() as db:
        assert db.scalars(select(WhatsAppSettings)).one().channel == "web"  # some gateways run without a key
    configure(panel, channel="cloud")
    page = admin.get("/admin/whatsapp").text
    assert "KEEP" not in page and "/admin/whatsapp/webhook" in page
    for url in ("/admin/whatsapp-messages", "/admin/whatsapp-templates"):
        assert admin.get(url).status_code == 200, url


def test_setup_guide_and_cloud_checks(admin, panel, http):
    cloud(panel, http)
    page = admin.get("/admin/whatsapp").text
    for name in ("guide", "check", "register", "templates"):
        assert f'"_tw_name": "{name}"' in page, name
    guide = admin.get(f"{ACTION}?_tw_host=page:whatsapp&_tw_scope=page&_tw_name=guide", headers={"HX-Request": "true"})
    assert "Connect with customers through WhatsApp" in guide.text and "init-waha" in guide.text
    assert "https://crm.example.com/admin/whatsapp/webhook" in guide.text and 'type="submit"' not in guide.text

    http.routes.update({
        "GET PN1": {"display_phone_number": "+91 98765 00000", "verified_name": "Prism", "status": "PENDING",
                    "platform_type": "NOT_APPLICABLE"},
        "POST WABA1/subscribed_apps": {"success": True},
        "POST PN1/register": {"success": True},
    })
    r = admin.post(ACTION, {"_tw_host": "page:whatsapp", "_tw_scope": "page", "_tw_name": "check"})
    assert "Number not registered yet" in r.headers["HX-Trigger"]

    r = admin.post(ACTION, {"_tw_host": "page:whatsapp", "_tw_scope": "page", "_tw_name": "register", "pin": "12ab"})
    assert "Type 6 digits." in r.text
    admin.post(ACTION, {"_tw_host": "page:whatsapp", "_tw_scope": "page", "_tw_name": "register", "pin": "123456"})
    register = next(c for c in http.calls if c[1] == "PN1/register")
    assert register[2] == {"messaging_product": "whatsapp", "pin": "123456"}

    # registered, but replies could not be turned on: say both, so nobody registers again
    http.routes["POST WABA1/subscribed_apps"] = (400, {"error": {"message": "No permission"}})
    r = admin.post(ACTION, {"_tw_host": "page:whatsapp", "_tw_scope": "page", "_tw_name": "register", "pin": "123456"})
    assert 'type="submit"' not in r.text and "Number registered, replies not on yet" in admin.get("/admin/whatsapp").text
    http.routes["POST WABA1/subscribed_apps"] = {"success": True}

    http.routes["GET PN1"] = {"display_phone_number": "+91 98765 00000", "verified_name": "Prism",
                              "status": "CONNECTED", "platform_type": "CLOUD_API"}
    admin.post(ACTION, {"_tw_host": "page:whatsapp", "_tw_scope": "page", "_tw_name": "check"})
    assert "WhatsApp is connected" in admin.get("/admin/whatsapp").text  # flashed for the reloaded page
    assert [c[1] for c in http.calls].count("WABA1/subscribed_apps") == 4


def test_link_phone_opens_a_popup(admin, panel, http):
    web(panel, http)
    page = admin.get("/admin/whatsapp").text
    button = page[page.index('"_tw_name": "link"') - 300:page.index('"_tw_name": "link"')]
    assert 'hx-get="/admin/_tw/action"' in button


def test_cloud_templates_and_usernames(admin, panel, http, client):
    cloud(panel, http)
    pages = iter([
        {"data": [{"name": "hello", "language": "hi", "status": "PENDING", "components": [
            {"type": "BODY", "text": "Namaste {{first_name}}"}]},
                  {"name": "hello", "language": "en_US", "status": "APPROVED", "components": [
            {"type": "BODY", "text": "Hi {{first_name}}, your order {{order}} is ready"}]}],
         "paging": {"next": "https://graph.facebook.com/v25.0/WABA1/message_templates?after=X"}},
        {"data": [{"name": "promo", "language": "hi", "status": "APPROVED", "components": [
            {"type": "BODY", "text": "Namaste {{1}}"}]}]},
    ])
    http.routes["GET WABA1/message_templates"] = lambda body: next(pages)
    admin.get("/admin/whatsapp")
    r = admin.post(ACTION, {"_tw_host": "page:whatsapp", "_tw_scope": "page", "_tw_name": "templates"})
    assert "3 templates" in r.headers.get("HX-Trigger", "") + admin.get("/admin/whatsapp").text  # both pages read

    lead_id = add_lead(panel)
    admin.post(ACTION, {"_tw_host": "resource:leads", "_tw_scope": "row", "_tw_name": "whatsapp",
                        "_tw_record": str(lead_id), "template": "hello", "params": "Amit | 42"})
    template = http.calls[-1][2]["template"]
    assert template["language"] == {"code": "en_US"}  # the approved translation, not the pending one
    assert template["components"][0]["parameters"] == [
        {"type": "text", "text": "Amit", "parameter_name": "first_name"},
        {"type": "text", "text": "42", "parameter_name": "order"}]
    with panel.db() as db:
        assert db.scalars(select(WhatsAppMessage)).one().body == "Hi Amit, your order 42 is ready"

    # people with a WhatsApp username may come without their number: keep the message, make no lead
    body = json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "contacts": [{"user_id": "IN.123", "profile": {"name": "Anon"}}],
        "messages": [{"from_user_id": "IN.123", "id": "wamid.U1", "type": "text", "text": {"body": "Hey"}}]}}]}]}).encode()
    sig = "sha256=" + hmac.new(b"shh", body, hashlib.sha256).hexdigest()
    assert client.client.post("/admin/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sig}).status_code == 200
    with panel.db() as db:
        assert db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.direction == "in")).one().body == "[Anon (IN.123)] Hey"
        assert len(db.scalars(select(Lead)).all()) == 1


def test_adding_the_app_secret_reloads_the_page(admin, panel):
    configure(panel, channel="cloud", phone_number_id="PN1", access_token="TOKEN", business_account_id="WABA1")
    assert "Keys missing" in admin.get("/admin/whatsapp").text
    r = admin.post("/admin/whatsapp", {"channel": "cloud", "country_code": "+91", "phone_number_id": "PN1",
                                       "business_account_id": "WABA1", "access_token": "", "app_secret": "shh"})
    assert r.headers.get("HX-Redirect") == "/admin/whatsapp", r.text[:300]
    assert "Keys missing" not in admin.get("/admin/whatsapp").text
