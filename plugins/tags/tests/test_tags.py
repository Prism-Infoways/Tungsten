from __future__ import annotations

import datetime as dt

from conftest import Product
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker
from tungsten_finance.models import Contact, Invoice
from tungsten_hr.models import Employee
from tungsten_leads.models import Lead
from tungsten_tags import Tag, Tagging, TagsPlugin, clean_name, clean_names
from tungsten_tickets import Ticket, create_ticket

from tungsten import Auth, Panel


def bulk(admin, host, name, records, **data):
    return admin.post("/admin/_tw/action", {"_tw_host": f"resource:{host}", "_tw_scope": "bulk", "_tw_name": name,
                                            "records": [str(r) for r in records], **data})


def tag_id(db, name, group=""):
    return db.scalar(select(Tag.id).where(Tag.key == name.casefold(), Tag.type == group))


def taggings(db, kind):
    rows = db.execute(select(Tagging.taggable_id, Tag.name).join(Tag).where(Tagging.taggable_type == kind)
                      .order_by(Tagging.taggable_id, Tag.name)).all()
    return [(int(i), n) for i, n in rows]


# ---------------------------------------------------------------------- names
def test_clean_names():
    assert clean_name("  New \t  customer\n ") == "New customer"
    assert clean_name("bad\x00name\x1b") == "badname"
    assert clean_name("   ") is None and clean_name(None) is None
    assert len(clean_name("x" * 80)) == 50
    assert clean_names(["VIP", "vip", " Vip ", "", None, "ग्राहक"]) == ["VIP", "ग्राहक"]
    assert clean_names("hot, cold ,hot") == ["hot", "cold"]


# ---------------------------------------------------------------------- pages
def test_pages_load(admin):
    for url in ("/admin/tags", "/admin/tags/create", "/admin/leads", "/admin/leads/create", "/admin/tickets",
                "/admin/tickets/create", "/admin/employees", "/admin/employees/create", "/admin/invoices",
                "/admin/invoices/create", "/admin/finance-contacts/create", "/admin/expenses", "/admin/products",
                "/admin/products/create"):
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[:500])
    assert "Sync tags" in admin.get("/admin/tags").text
    assert "Add tags" in admin.get("/admin/leads").text


# ---------------------------------------------------------------------- own resource (tag tables only)
def test_create_and_edit_with_tags(admin, panel):
    admin.get("/admin/products/create")
    r = admin.post("/admin/products/create", {"name": "Chair", "tungsten_tags": ["Sale", "sale ", "  New   arrival "]})
    assert r.status_code == 204, r.text
    with panel.db() as db:
        assert taggings(db, "products") == [(1, "New arrival"), (1, "Sale")]
        assert db.scalars(select(Tag.type).distinct()).all() == ["product"]  # its own group
    edit = admin.get("/admin/products/1/edit").text
    assert "New arrival" in edit and "Sale" in edit
    r = admin.post("/admin/products/1/edit", {"name": "Chair", "tungsten_tags": ["SALE"]})
    assert "Saved" in r.headers.get("HX-Trigger", ""), r.text
    with panel.db() as db:
        assert taggings(db, "products") == [(1, "Sale")]  # the existing spelling wins
        assert db.scalar(select(Tag.id).where(Tag.name == "New arrival")) is not None  # unused tags stay


def test_list_filter_any_and_all(admin, panel, tags):
    with panel.db() as db:
        for name, names in (("Chair", ["Sale", "Wood"]), ("Table", ["Wood"]), ("Lamp", [])):
            product = Product(name=name)
            db.add(product)
            db.flush()
            tags.set_tags(db, product, names)
        db.commit()
        sale, wood = tag_id(db, "sale", "product"), tag_id(db, "wood", "product")
    page = admin.get("/admin/products").text
    assert "Chair" in page and "Lamp" in page and "Wood" in page
    page = admin.get(f"/admin/products?_f=1&filters.tags.values={wood}").text
    assert "Chair" in page and "Table" in page and "Lamp" not in page
    page = admin.get(f"/admin/products?_f=1&filters.tags.values={wood}&filters.tags.values={sale}"
                     "&filters.tags.match=all").text
    assert "Chair" in page and "Table" not in page
    page = admin.get(f"/admin/products?_f=1&filters.tags.values={wood}&filters.tags.values={sale}").text
    assert "Chair" in page and "Table" in page  # "any" is the default


def test_limits_and_closed_list(admin, panel):
    panel.get_plugin("tags").max_tags = 2
    admin.get("/admin/products/create")
    r = admin.post("/admin/products/create", {"name": "Chair", "tungsten_tags": ["a", "b", "c"]})
    assert "at most 2 tags" in r.text
    panel.get_plugin("tags").allow_new = False
    r = admin.post("/admin/products/create", {"name": "Chair", "tungsten_tags": ["Brand new"]})
    assert "Unknown tag: Brand new" in r.text
    with panel.db() as db:
        assert db.scalar(select(Product.id)) is None and db.scalar(select(Tag.id)) is None


def test_deleted_record_loses_tags_and_reused_id_starts_clean(admin, panel, tags):
    with panel.db() as db:
        first = Product(name="Old")
        db.add(first)
        db.flush()
        tags.set_tags(db, first, ["Sale"])
        db.commit()
        db.delete(first)
        db.commit()
        assert taggings(db, "products") == []
        again = Product(name="New")  # SQLite gives it the same id
        db.add(again)
        db.commit()
        assert again.id == first.id and tags.tags_for(db, again) == []


# ---------------------------------------------------------------------- leads and tickets (JSON column)
def test_leads_keep_their_column_and_mirror_it(admin, panel):
    with panel.db() as db:
        db.add(Tag(name="VIP", key="vip", type="", color="danger"))
        db.commit()
        db.add(Lead(name="Amit", tags=["vip", "hot", "HOT", " "]))
        db.commit()
        lead = db.scalars(select(Lead)).one()
        assert lead.tags == ["VIP", "hot"]  # existing spelling, no repeats
        assert taggings(db, "tungsten_leads") == [(1, "VIP"), (1, "hot")]
        lead.tags = ["hot"]
        db.commit()
        assert taggings(db, "tungsten_leads") == [(1, "hot")]
        lead.tags = None
        db.commit()
        assert taggings(db, "tungsten_leads") == []
    admin.get("/admin/leads/create")
    r = admin.post("/admin/leads/create", {"name": "Neha", "status": "new", "source": "manual", "tags": ["Vip"]})
    assert r.status_code == 204, r.text
    with panel.db() as db:
        assert db.scalars(select(Lead).where(Lead.name == "Neha")).one().tags == ["VIP"]
        vip = tag_id(db, "vip")
    page = admin.get("/admin/leads").text
    assert "Neha" in page and "Amit" in page
    page = admin.get(f"/admin/leads?_f=1&filters.tags.values={vip}").text
    assert "Neha" in page and "Amit" not in page
    assert "bg-danger-50" in page  # the tag's color


def test_tickets_from_the_api_get_tags(panel):
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        ticket = create_ticket(db, subject="Refund", requester_email="a@x.com")
        ticket.tags = ["Billing", "billing"]
        db.commit()
        assert ticket.tags == ["Billing"]
        assert taggings(db, "tungsten_tickets") == [(ticket.id, "Billing")]
        assert db.scalar(select(Ticket.tags)) == ["Billing"]


def test_bulk_add_and_remove_on_leads_and_employees(admin, panel):
    with panel.db() as db:
        db.add_all([Lead(name="A", tags=["old"]), Lead(name="B")])
        db.add_all([Employee(first_name="Ravi", joined_on=dt.date(2025, 1, 1)),
                    Employee(first_name="Sara", joined_on=dt.date(2025, 1, 1))])
        db.commit()
    admin.get("/admin/leads")
    r = bulk(admin, "leads", "add_tags", [1, 2], tags=["Webinar", "OLD"])
    assert "Tags added" in r.headers.get("HX-Trigger", ""), r.text
    with panel.db() as db:
        assert [lead.tags for lead in db.scalars(select(Lead).order_by(Lead.id))] == [["old", "Webinar"],
                                                                                      ["Webinar", "old"]]
        webinar = tag_id(db, "webinar")
    r = bulk(admin, "leads", "remove_tags", [1, 2], tags=[str(webinar)])
    assert "Tags removed" in r.headers.get("HX-Trigger", ""), r.text
    with panel.db() as db:
        assert [lead.tags for lead in db.scalars(select(Lead).order_by(Lead.id))] == [["old"], ["old"]]
    admin.get("/admin/employees")
    r = bulk(admin, "employees", "add_tags", [1, 2], tags=["Night shift"])
    assert "Tags added" in r.headers.get("HX-Trigger", ""), r.text
    with panel.db() as db:
        assert taggings(db, "tungsten_hr_employees") == [(1, "Night shift"), (2, "Night shift")]
    view = admin.get("/admin/employees/1").text
    assert "Night shift" in view


# ---------------------------------------------------------------------- the Tags page
def test_rename_merge_and_delete_update_every_record(admin, panel, tags):
    with panel.db() as db:
        db.add_all([Lead(name="A", tags=["vip", "Hot"]), Lead(name="B", tags=["V.I.P."])])
        db.add(Contact(name="Acme"))
        db.commit()
        tags.set_tags(db, db.scalars(select(Contact)).one(), ["vip"])
        db.commit()
        vip, dotted, hot = tag_id(db, "vip"), tag_id(db, "v.i.p."), tag_id(db, "hot")
    admin.get(f"/admin/tags/{vip}/edit")
    r = admin.post(f"/admin/tags/{vip}/edit", {"name": "VIP", "color": "danger", "sort": "0"})
    assert "Saved" in r.headers.get("HX-Trigger", ""), r.text
    with panel.db() as db:
        assert db.scalars(select(Lead.tags).order_by(Lead.id)).all() == [["VIP", "Hot"], ["V.I.P."]]
    admin.get("/admin/tags")
    r = bulk(admin, "tags", "merge", [vip, dotted], into=str(vip))
    assert "Tags merged" in r.headers.get("HX-Trigger", ""), r.text
    with panel.db() as db:
        assert db.scalars(select(Lead.tags).order_by(Lead.id)).all() == [["VIP", "Hot"], ["VIP"]]
        assert db.get(Tag, dotted) is None
        assert taggings(db, "tungsten_leads") == [(1, "Hot"), (1, "VIP"), (2, "VIP")]
        assert taggings(db, "tungsten_fin_contacts") == [(1, "VIP")]
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:tags", "_tw_scope": "page", "_tw_name": "delete",
                                         "_tw_record": str(hot)})
    assert r.status_code == 204, r.text
    with panel.db() as db:
        assert db.get(Tag, hot) is None
        assert db.scalars(select(Lead.tags).order_by(Lead.id)).all() == [["VIP"], ["VIP"]]
        assert taggings(db, "tungsten_leads") == [(1, "VIP"), (2, "VIP")]


def test_duplicate_tag_names_are_refused(admin, panel):
    admin.get("/admin/tags/create")
    r = admin.post("/admin/tags/create", {"name": " VIP ", "color": "danger", "sort": "0"})
    assert r.status_code == 204, r.text
    r = admin.post("/admin/tags/create", {"name": "vip", "color": "gray", "sort": "0"})
    assert "already exists" in r.text
    r = admin.post("/admin/tags/create", {"name": "vip", "color": "gray", "type": "Industry", "sort": "0"})
    assert r.status_code == 204, r.text  # another group may reuse the name
    with panel.db() as db:
        assert db.execute(select(Tag.name, Tag.key, Tag.type).order_by(Tag.id)).all() == [
            ("VIP", "vip", ""), ("vip", "vip", "Industry")]


def test_tag_page_shows_where_it_is_used(admin, panel, tags):
    with panel.db() as db:
        db.add(Lead(name="A", tags=["VIP"]))
        db.add(Contact(name="Acme"))
        db.flush()
        invoice = Invoice(kind="invoice", contact_id=1, issue_date=dt.date(2026, 10, 1))
        bill = Invoice(kind="bill", contact_id=1, issue_date=dt.date(2026, 10, 1))
        db.add_all([invoice, bill])
        db.flush()
        tags.set_tags(db, invoice, ["VIP"])
        db.commit()
        vip = tag_id(db, "vip")
    page = admin.get(f"/admin/tags/{vip}").text
    used = page[page.index('<ul class="divide-y'):]
    used = used[:used.index("</ul>")]
    assert "Leads" in used and "Invoices" in used and "Bills" not in used and used.count("1 record<") == 2
    assert f"/admin/leads?_f=1&amp;filters.tags.values={vip}" in page
    assert "2 records" in admin.get("/admin/tags").text


def test_sync_copies_old_tags_and_drops_orphans(admin, panel):
    with panel.db() as db:
        # rows written before the plugin was added (no model events)
        db.execute(insert(Lead.__table__), [{"name": "Old", "status": "new", "source": "manual", "tags": ["Legacy"]}])
        db.execute(insert(Tag.__table__), [{"name": "Gone", "key": "gone", "type": "", "color": "gray", "sort": 0}])
        db.execute(insert(Tagging.__table__), [{"tag_id": 1, "taggable_type": "tungsten_hr_employees",
                                                "taggable_id": "99"}])
        db.commit()
    admin.get("/admin/tags")
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:tags", "_tw_scope": "page", "_tw_name": "sync"})
    assert r.status_code == 204 and r.headers.get("HX-Refresh") == "true", r.text
    with panel.db() as db:
        assert taggings(db, "tungsten_leads") == [(1, "Legacy")]
        assert taggings(db, "tungsten_hr_employees") == []


# ---------------------------------------------------------------------- safety
def test_a_panel_without_the_plugin_is_untouched(tmp_path, panel):
    """The resource classes were extended above; another panel without tags must not see or need them."""
    from tungsten_leads import LeadsPlugin

    from conftest import Base, User

    engine = create_engine(f"sqlite:///{tmp_path / 'plain.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    plain = Panel(path="/admin", session_factory=factory, secret_key="test", auth=Auth(User))
    plain.plugin(LeadsPlugin())
    plain.create_tables(engine)  # no tag tables here
    with factory() as db:
        db.add(Lead(name="Amit", tags=["vip"]))
        db.commit()
        lead = db.scalars(select(Lead)).one()
        assert lead.tags == ["vip"]
        db.delete(lead)
        db.commit()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from conftest import PanelClient, hash_password

    with factory() as db:
        db.add(User(name="A", email="admin@example.com", password=hash_password("password")))
        db.commit()
    app = FastAPI()
    plain.mount(app)
    client = PanelClient(TestClient(app))
    client.login()
    for url in ("/admin/leads", "/admin/leads/create"):
        r = client.get(url)
        assert r.status_code == 200 and "Add tags" not in r.text and "tungsten_tags" not in r.text


def test_attach_checks_the_model(panel, tags):
    import pytest

    from tungsten import Resource

    class Broken(Resource):
        model = Product

    with pytest.raises(ValueError):
        tags.attach(Broken, column="nope")
    assert isinstance(tags, TagsPlugin)
