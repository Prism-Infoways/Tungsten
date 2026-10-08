from __future__ import annotations

from sqlalchemy import select

from tungsten_leads import Lead, LeadActivity, LeadField, create_lead, find_lead, on_lead_created


def test_tables_and_pages(admin, panel):
    for url in ("/admin/leads", "/admin/leads/create", "/admin/lead-fields", "/admin/"):
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[:500])
    assert "Leads" in admin.get("/admin/leads").text


def test_custom_fields_show_validate_and_save(admin, panel):
    with panel.db() as db:
        db.add_all([
            LeadField(label="Budget", key="budget", type="number", required=True, sort=1),
            LeadField(label="Course", key="course", type="select", options=["BCA", "MBA"], sort=2),
            LeadField(label="Hidden", key="hidden", type="text", is_active=False),
        ])
        db.commit()
    page = admin.get("/admin/leads/create").text
    assert "Budget" in page and "MBA" in page and "Hidden" not in page

    r = admin.post("/admin/leads/create", {"name": "Ravi", "status": "new", "source": "manual"})
    assert "The budget field is required." in r.text

    r = admin.post("/admin/leads/create", {
        "name": "Ravi", "phone": "+91 98765 43210", "status": "new", "source": "manual",
        "custom_fields.budget": "50000", "custom_fields.course": "MBA",
    })
    assert r.status_code == 204, r.text
    with panel.db() as db:
        lead = db.scalars(select(Lead)).one()
        assert lead.custom_fields == {"budget": 50000, "course": "MBA"}
        assert [a.type for a in lead.activities] == ["system"]
        lead_id = lead.id

    edit = admin.get(f"/admin/leads/{lead_id}/edit").text
    assert 'value="50000"' in edit


def test_lead_fields_screen_lists_types(admin, panel):
    with panel.db() as db:
        db.add(LeadField(label="Area", key="area", type="select", options=["North", "South"]))
        db.commit()
    page = admin.get("/admin/lead-fields").text
    assert "Area" in page and "Dropdown" in page and "North, South" in page
    assert "Area" in admin.get("/admin/leads/create").text


def test_create_lead_service_skips_duplicates_and_calls_listeners(panel):
    seen = []
    on_lead_created(lambda db, lead: seen.append(lead.name))
    with panel.db() as db:
        a = create_lead(db, name="Meta person", phone="+91 98765-43210", source="meta", external_id="fb-1")
        b = create_lead(db, name="Again", source="meta", external_id="fb-1")
        db.commit()
        assert a.id == b.id and a.phone == "+919876543210"
        assert find_lead(db, phone="9876543210").id == a.id
    assert seen == ["Meta person"]


def test_capture_api(client, panel):
    r = client.client.post("/admin/api/leads", json={"name": "Web"}, headers={"X-Leads-Token": "nope"})
    assert r.status_code == 401
    r = client.client.post("/admin/api/leads", json={"name": "Web Lead", "email": "WEB@x.com", "city": "Pune"},
                           headers={"X-Leads-Token": "secret-token"})
    assert r.status_code == 201, r.text
    with panel.db() as db:
        lead = db.get(Lead, r.json()["id"])
        assert lead.source == "website" and lead.email == "web@x.com" and lead.custom_fields == {"city": "Pune"}
        assert db.scalars(select(LeadActivity)).first().lead_id == lead.id

    # the same external_id twice (a form that posts again) is one lead, with one "came from the website" note
    post = lambda: client.client.post("/admin/api/leads", json={"name": "Amit", "phone": "+919812345678",
                                                               "external_id": "kundli-7", "city": "Pune"},
                                      headers={"X-Leads-Token": "secret-token"})
    first, again = post(), post()
    assert first.status_code == 201 and again.json()["id"] == first.json()["id"]
    with panel.db() as db:
        lead = db.get(Lead, first.json()["id"])
        assert lead.external_id == "kundli-7" and lead.custom_fields == {"city": "Pune"}
        assert len([a for a in db.scalars(select(LeadActivity)) if a.lead_id == lead.id]) == 1
