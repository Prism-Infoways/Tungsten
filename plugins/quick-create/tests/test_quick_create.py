from __future__ import annotations

import json

import pytest
from conftest import Note, Product, client_for
from tungsten_quick_create import QuickCreatePlugin


def toasts(response) -> list[dict]:
    trigger = json.loads(response.headers.get("HX-Trigger") or "{}")
    return trigger.get("tw-notify") or []


def events(response) -> dict:
    return json.loads(response.headers.get("HX-Trigger") or "{}")


# ---------------------------------------------------------------------- the button
def test_button_lists_creatable_resources(admin):
    html = admin.get("/admin/").text
    assert "data-tw-quick-create" in html
    assert "/admin/_quick-create/products" in html
    assert "/admin/_quick-create/notes" in html  # modal-only resources too
    assert "/admin/_quick-create/logs" not in html  # no create page
    assert "/admin/_quick-create/hidden-logs" not in html  # quick_create = False


def test_button_respects_permissions(client):
    assert client.login("ravi@example.com").status_code == 303
    html = client.get("/admin/").text
    assert "/admin/_quick-create/products" not in html  # policy says admins only
    assert "/admin/_quick-create/notes" in html


def test_no_button_when_nothing_to_create(make_panel):
    panel = make_panel(include=["products"])
    client = client_for(panel)
    client.login("ravi@example.com")
    assert "data-tw-quick-create" not in client.get("/admin/").text


def test_signed_out_users_see_no_button_and_get_login(client):
    r = client.get("/admin/_quick-create/products", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/admin/login" in r.headers["location"]


def test_include_sets_the_order(make_panel):
    panel = make_panel(include=["notes", "products", "missing"])
    client = client_for(panel)
    client.login()
    html = client.get("/admin/").text
    assert html.index("_quick-create/notes") < html.index("_quick-create/products")


def test_exclude_by_class_or_slug(make_panel):
    from conftest import NoteResource

    client = client_for(make_panel(exclude=[NoteResource, "products"]))
    client.login()
    assert "data-tw-quick-create" not in client.get("/admin/").text


def test_groups_and_search_box(make_panel):
    client = client_for(make_panel(search_from=2))
    client.login()
    html = client.get("/admin/").text
    assert "Shop" in html  # products sit in the "Shop" group
    assert 'x-model="q"' in html
    client = client_for(make_panel(search_from=50, group=False))
    client.login()
    assert 'x-model="q"' not in client.get("/admin/").text


def test_bad_width_is_refused():
    with pytest.raises(ValueError):
        QuickCreatePlugin(width="huge")


# ---------------------------------------------------------------------- links from other plugins
def test_links_from_other_plugins(panel):
    plugin = panel.get_plugin("quick-create")
    plugin.add_link("event", "Event", "/admin/calendar?new=1", icon="calendar")
    plugin.add_link("upload", "Upload file", lambda ctx: "/admin/media/upload")
    plugin.add_link("secret", "Secret", "/admin/secret", visible=lambda user: user.email == "nobody@example.com")
    plugin.add_link("broken", "Broken", lambda ctx: 1 / 0)
    client = client_for(panel)
    client.login()
    html = client.get("/admin/").text
    assert "/admin/calendar?new=1" in html
    assert "/admin/media/upload" in html
    assert "/admin/secret" not in html
    assert "Broken" not in html  # a failing link is skipped, the page still works
    plugin.remove_link("event")
    assert "/admin/calendar?new=1" not in client.get("/admin/").text


# ---------------------------------------------------------------------- the form
def test_open_form_in_side_panel(admin):
    r = admin.get("/admin/_quick-create/products", htmx=True)
    assert r.status_code == 200
    assert "tw-quick-create-form" in r.text
    assert 'hx-post="/admin/_quick-create/products"' in r.text
    assert "Create &amp; create another" in r.text or "Create & create another" in r.text
    assert "justify-end" in r.text  # slide over


def test_create_closes_and_refreshes(admin, panel):
    r = admin.post("/admin/_quick-create/products", {"name": "Pen", "sku": "P-1"})
    assert r.status_code == 200
    ev = events(r)
    assert "tw-close-modal" in ev and "tw-refresh" in ev
    toast = toasts(r)[0]
    assert toast["status"] == "success"
    assert toast["actions"][0]["url"].startswith("/admin/products/")
    with panel.db() as db:
        assert db.query(Product).filter_by(name="Pen").one().sku == "P-1"


def test_validation_errors_keep_the_form_open(admin, panel):
    r = admin.post("/admin/_quick-create/products", {"name": "", "sku": "X"})
    assert r.status_code == 200
    assert "tw-quick-create-form" in r.text
    assert 'value="X"' in r.text  # typed data is kept
    with panel.db() as db:
        assert db.query(Product).count() == 0


def test_hook_validation_error_shows_on_the_field(admin, panel):
    r = admin.post("/admin/_quick-create/products", {"name": "Pen", "sku": "BAD"})
    assert "This SKU is blocked." in r.text
    with panel.db() as db:
        assert db.query(Product).count() == 0


def test_database_error_is_a_toast_not_a_crash(admin, panel):
    admin.post("/admin/_quick-create/products", {"name": "Pen"})
    r = admin.post("/admin/_quick-create/products", {"name": "Pen"})  # unique name
    assert r.status_code == 200
    assert toasts(r)[0]["status"] == "danger"
    assert "tw-quick-create-form" in r.text
    with panel.db() as db:
        assert db.query(Product).count() == 1


def test_create_another_reopens_an_empty_form(admin, panel):
    r = admin.post("/admin/_quick-create/notes", {"text": "first", "_tw_another": "1"})
    assert "tw-close-modal" not in events(r)
    assert "tw-refresh" in events(r)
    assert "tw-quick-create-form" in r.text and "first" not in r.text
    with panel.db() as db:
        assert db.query(Note).count() == 1


def test_simple_resource_has_no_record_link(admin):
    r = admin.post("/admin/_quick-create/notes", {"text": "hello"})
    assert not toasts(r)[0].get("actions")


def test_open_after_create_goes_to_the_record(make_panel):
    client = client_for(make_panel(open_after_create=True))
    client.login()
    client.get("/admin/")
    r = client.post("/admin/_quick-create/products", {"name": "Pen"})
    assert r.headers["HX-Redirect"].startswith("/admin/products/")


def test_forbidden_and_unknown(client):
    client.login("ravi@example.com")
    client.get("/admin/")
    r = client.get("/admin/_quick-create/products", htmx=True)
    assert r.status_code == 204 and toasts(r)[0]["status"] == "danger"
    r = client.post("/admin/_quick-create/products", {"name": "Sneaky"})
    assert r.status_code == 204
    for slug in ("logs", "hidden-logs", "nope"):
        assert client.get(f"/admin/_quick-create/{slug}", htmx=True).status_code == 204


def test_post_needs_csrf(admin, panel):
    admin.token = "wrong"
    r = admin.post("/admin/_quick-create/products", {"name": "Pen"})
    assert r.status_code == 419
    with panel.db() as db:
        assert db.query(Product).count() == 0


def test_live_form_refresh_works_in_the_panel(admin):
    """Fields that update live post to the core form endpoint with the resource as host."""
    r = admin.post("/admin/_tw/form", {"_tw_kind": "host", "_tw_host": "resource:products", "_tw_op": "create",
                                       "_tw_record": "", "_tw_form_id": "tw-quick-create-form", "name": "Pen"})
    assert r.status_code == 200
    assert 'id="tw-quick-create-form"' in r.text


def test_broken_policy_hides_only_that_entry(make_panel):
    from conftest import NoteResource

    class Boom:
        @staticmethod
        def create(user):
            raise RuntimeError("policy bug")

    NoteResource.policy = Boom
    try:
        client = client_for(make_panel())
        client.login()
        html = client.get("/admin/").text
        assert "_quick-create/products" in html
        assert "_quick-create/notes" not in html
    finally:
        NoteResource.policy = None


# ---------------------------------------------------------------------- with other plugins
OFFICIAL = [("tungsten_leads", "LeadsPlugin"), ("tungsten_tickets", "TicketsPlugin"), ("tungsten_hr", "HRPlugin"),
            ("tungsten_finance", "FinancePlugin"), ("tungsten_blog", "BlogPlugin"),
            ("tungsten_seo_audit", "SeoAuditPlugin"), ("tungsten_security_audit", "SecurityAuditPlugin")]


@pytest.fixture()
def full_panel(make_panel):
    import importlib

    panel = make_panel()
    added = []
    for module, name in OFFICIAL:
        try:
            plugin_class = getattr(importlib.import_module(module), name)
        except ImportError:
            continue
        panel.plugin(plugin_class())
        added.append(module)
    if not added:
        pytest.skip("no other official plugins installed")
    panel.create_tables(panel.db.kw["bind"])
    return panel


def test_every_official_plugin_form_opens(full_panel):
    client = client_for(full_panel)
    client.login()
    html = client.get("/admin/").text
    slugs = [r.get_slug() for r in full_panel.get_plugin("quick-create").resources()]
    assert len(slugs) > 5
    for slug in slugs:
        assert f"/admin/_quick-create/{slug}" in html
        r = client.get(f"/admin/_quick-create/{slug}", htmx=True)
        assert r.status_code == 200, slug
        assert "tw-quick-create-form" in r.text, slug


def test_create_ticket_and_lead_from_anywhere(full_panel):
    pytest.importorskip("tungsten_tickets")
    pytest.importorskip("tungsten_leads")
    from tungsten_leads import Lead
    from tungsten_tickets import Ticket

    client = client_for(full_panel)
    client.login()
    client.get("/admin/")
    r = client.post("/admin/_quick-create/tickets", {"subject": "Printer broken", "status": "open",
                                                     "priority": "normal"})
    assert toasts(r)[0]["status"] == "success", r.text[:500]
    r = client.post("/admin/_quick-create/leads", {"name": "Meena", "status": "new", "source": "website"})
    assert toasts(r)[0]["status"] == "success", r.text[:500]
    with full_panel.db() as db:
        ticket = db.query(Ticket).one()
        assert ticket.number and ticket.due_at is not None  # the plugin's own hooks ran
        assert db.query(Lead).one().name == "Meena"
