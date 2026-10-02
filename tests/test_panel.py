"""End-to-end tests of the demo panel over HTTP."""

from __future__ import annotations

import datetime as dt
import json
import re

from sqlalchemy import func, select

from examples.shop.models import Category, Customer, Order, OrderStatus, Product, User
from tungsten.models import DatabaseNotification, Role, RoleAssignment

from .conftest import PanelClient, db_session

# ---------------------------------------------------------------------- auth


def test_guest_is_redirected_to_login(client):
    r = client.get("/admin/products", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/admin/login")
    r = client.get("/admin/_tw/table?host=resource:products", htmx=True, follow_redirects=False)
    assert r.headers["HX-Redirect"].startswith("/admin/login")


def test_login_errors_and_success(client):
    client.get("/admin/login")
    r = client.client.post("/admin/login", data={"_token": client.token, "email": "admin@example.com", "password": "bad"})
    assert "These credentials do not match our records." in r.text
    r = client.login()
    assert r.status_code == 303 and r.headers["location"] == "/admin/"
    assert "Welcome back, Kuldeep!" in client.get("/admin/").text


def test_post_without_csrf_token_is_rejected(admin):
    admin.token = "wrong"
    r = admin.post("/admin/categories/1/edit", {"name": "x"})
    assert r.status_code == 419


def test_users_without_panel_access_cannot_login(client, panel):
    with db_session(panel) as db:
        user = db.scalars(select(User).where(User.is_admin.is_(False))).first()
        email = user.email
    r = client.login(email=email)
    assert r.status_code == 200
    assert "do not match" in r.text


def test_password_reset_flow(client, panel):
    client.get("/admin/forgot-password")
    r = client.client.post("/admin/forgot-password", data={"_token": client.token, "email": "admin@example.com"})
    assert "reset link is on its way" in r.text
    mail = panel.test_mails[-1]
    token_url = re.search(r"(/admin/reset-password/\S+)", mail["body"]).group(1)
    client.get(token_url)
    r = client.client.post(token_url, data={"_token": client.token, "password": "short", "password_confirmation": "x"})
    assert "at least 8" in r.text
    r = client.client.post(token_url, data={"_token": client.token, "password": "newpassword",
                                            "password_confirmation": "newpassword"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.login(password="newpassword").status_code == 303
    assert "invalid or has expired" in client.get(token_url).text


def test_profile_update(admin, panel):
    r = admin.get("/admin/profile")
    assert "Profile information" in r.text
    r = admin.post("/admin/profile", {"name": "Kuldeep G", "email": "admin@example.com", "current_password": "nope",
                                      "new_password": "newpassword", "new_password_confirmation": "newpassword",
                                      "_tw_kind": "host", "_tw_host": "profile", "_tw_op": "edit"})
    assert "The current password is incorrect." in r.text
    r = admin.post("/admin/profile", {"name": "Kuldeep G", "email": "admin@example.com"})
    assert "Profile saved" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert db.scalars(select(User).where(User.email == "admin@example.com")).one().name == "Kuldeep G"


# ---------------------------------------------------------------------- pages & navigation


def test_all_main_pages_render(admin):
    for url in ["/admin/", "/admin/users", "/admin/products", "/admin/orders", "/admin/customers", "/admin/categories",
                "/admin/brands", "/admin/roles", "/admin/users/create", "/admin/products/create", "/admin/orders/create",
                "/admin/products/1/edit", "/admin/products/1", "/admin/orders/1/edit", "/admin/customers/1/edit",
                "/admin/roles/1/edit", "/admin/reports", "/admin/system-settings", "/admin/profile"]:
        r = admin.get(url)
        assert r.status_code == 200, url


def test_navigation_has_groups_badges_and_children(admin):
    html = admin.get("/admin/products").text
    assert "Catalog" in html and "Roles &amp; Permissions" in html
    assert 'aria-current="page"' in html
    assert ">Categories<" in html  # nested under Products
    assert "Documentation" in html  # added by the plugin


def test_missing_records_give_404(admin):
    assert admin.get("/admin/products/9999/edit").status_code == 404
    assert admin.get("/admin/nope").status_code == 404


# ---------------------------------------------------------------------- tables


def table(admin, host, **params):
    from urllib.parse import urlencode

    return admin.get("/admin/_tw/table?" + urlencode({"host": host, **params}, doseq=True), htmx=True)


def test_table_search_sort_paginate(admin):
    r = table(admin, "resource:products", search="watch")
    assert "Smart Watch" in r.text and "Denim Jeans" not in r.text
    assert r.headers["HX-Replace-Url"].startswith("/admin/products?search=watch")
    r = table(admin, "resource:products", sort="price", direction="asc", per_page=10)
    names = re.findall(r'font-medium[^>]*>\s*<span[^>]*>([^<]+)</span>', r.text)
    assert "Showing <span class=\"font-medium\">1</span> to <span class=\"font-medium\">10</span>" in r.text
    r = table(admin, "resource:products", page=2)
    assert "Showing <span class=\"font-medium\">11</span>" in r.text
    assert names is not None


def test_table_search_through_relationship(admin):
    r = table(admin, "resource:orders", search="ORD-0001")
    assert "ORD-0001" in r.text
    with_rel = table(admin, "resource:customers", search="mail.com")
    assert "Showing" in with_rel.text


def test_table_filters(admin, panel):
    with db_session(panel) as db:
        clothing = db.scalars(select(Category).where(Category.name == "Clothing")).one()
        count = db.scalar(select(func.count()).select_from(Product).where(Product.category_id == clothing.id))
    r = table(admin, "resource:products", **{"_f": "1", "filters.category.value": str(clothing.id)})
    assert f"of <span class=\"font-medium\">{count}</span> results" in r.text
    assert "Category: Clothing" in r.text  # active filter chip
    with db_session(panel) as db:
        paid = db.scalar(select(func.count()).select_from(Order).where(Order.status == OrderStatus.PAID))
    r = table(admin, "resource:orders", **{"_f": "1", "filters.status.values": "paid"})
    assert f"of <span class=\"font-medium\">{paid}</span> results" in r.text
    assert "Status: Paid" in r.text


def test_table_summaries_and_grouping(admin):
    r = table(admin, "resource:products")
    assert "Sum:" in r.text
    r = table(admin, "resource:products", group="category.name")
    assert "Group by category name" in r.text
    assert re.search(r'colspan="\d+"[^>]*>Accessories<', r.text)


def test_column_toggle_is_remembered(admin):
    r = table(admin, "resource:users", _cols="1", cols=["created_at", "department"])
    assert ">Department<" in r.text
    r = table(admin, "resource:users")
    assert ">Department<" in r.text


def test_toggle_column_saves(admin, panel):
    with db_session(panel) as db:
        cat = db.get(Category, 1)
        before = cat.is_visible
    r = admin.post("/admin/_tw/toggle", {"host": "resource:categories", "record": "1", "column": "is_visible"})
    assert r.status_code == 204
    with db_session(panel) as db:
        assert db.get(Category, 1).is_visible is (not before)


# ---------------------------------------------------------------------- crud


def test_create_validation_and_success(admin, panel):
    admin.get("/admin/categories")
    base = {"_tw_kind": "host", "_tw_host": "resource:brands", "_tw_op": "create"}
    r = admin.post("/admin/products/create", {"name": "", "sku": "PRE-001", "price": "x"})
    assert "The product name field is required." in r.text
    assert "has already been taken" in r.text
    assert "must be a number" in r.text
    r = admin.post("/admin/products/create", {
        "name": "Test Hoodie", "sku": "HOD-1", "price": "999", "stock": "4", "category_id": "1", "status": "published",
        "tags": ["1", "2"], "keywords": ["warm"], "attributes.0.key": "fabric", "attributes.0.value": "fleece",
        "sizes": ["M", "L"],
    })
    assert r.status_code == 204, r.text
    assert re.match(r"/admin/products/\d+/edit", r.headers["HX-Redirect"])
    with db_session(panel) as db:
        p = db.scalars(select(Product).where(Product.sku == "HOD-1")).one()
        assert p.price == 999 and p.stock == 4 and [t.id for t in p.tags] == [1, 2]
        assert p.attributes == {"fabric": "fleece"} and p.sizes == ["M", "L"] and p.keywords == ["warm"]
    assert base


def test_edit_updates_record(admin, panel):
    r = admin.post("/admin/customers/1/edit", {"name": "New Name", "email": "new@mail.com", "state": "Gujarat",
                                               "city": "Surat"})
    assert r.status_code == 200 and "Saved" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        c = db.get(Customer, 1)
        assert (c.name, c.city) == ("New Name", "Surat")


def test_dependent_field_refresh_endpoint(admin):
    r = admin.post("/admin/_tw/form", {"_tw_kind": "host", "_tw_host": "resource:customers", "_tw_op": "edit",
                                       "_tw_record": "1", "_tw_form_id": "tw-record-form", "name": "x",
                                       "state": "Karnataka", "city": "Pune"}, trigger="state")
    assert 'id="tw-record-form"' in r.text
    assert "Bengaluru" in r.text and "Pune</option>" not in r.text


def test_order_repeater_saves_items_and_total(admin, panel):
    data = {"number": "ORD-T1", "customer_id": "1", "status": "pending",
            "items.0.__row": "1", "items.0.product_id": "1", "items.0.quantity": "2", "items.0.unit_price": "100",
            "items.1.__row": "1", "items.1.product_id": "2", "items.1.quantity": "1", "items.1.unit_price": "50"}
    r = admin.post("/admin/orders/create", data)
    assert r.status_code == 204, r.text
    with db_session(panel) as db:
        order = db.scalars(select(Order).where(Order.number == "ORD-T1")).one()
        assert [(i.product_id, i.quantity) for i in order.items] == [(1, 2), (2, 1)]
        assert order.total == 250
        oid, first_item = order.id, order.items[0].id
        # the admin got a database notification
        assert db.scalar(select(func.count()).select_from(DatabaseNotification)) >= 1
    # edit: drop the second row, change the first
    r = admin.post(f"/admin/orders/{oid}/edit", {"number": "ORD-T1", "customer_id": "1", "status": "paid",
                                                 "items.0.__row": "1", "items.0.__key": str(first_item),
                                                 "items.0.product_id": "1", "items.0.quantity": "3",
                                                 "items.0.unit_price": "100"})
    assert r.status_code == 200
    with db_session(panel) as db:
        order = db.get(Order, oid)
        assert len(order.items) == 1 and order.items[0].id == first_item and order.total == 300
        assert order.status is OrderStatus.PAID


def test_repeater_live_price_from_product(admin):
    r = admin.post("/admin/_tw/form", {"_tw_kind": "host", "_tw_host": "resource:orders", "_tw_op": "create",
                                       "items.0.__row": "1", "items.0.product_id": "7", "items.0.quantity": "1",
                                       "items.0.unit_price": ""}, trigger="items.0.product_id")
    assert 'name="items.0.unit_price" value="6999.00"' in r.text


def test_wizard_next_validates(admin):
    r = admin.post("/admin/_tw/form", {"_tw_kind": "host", "_tw_host": "resource:users", "_tw_op": "create",
                                       "_tw_ui_action": "wizard.next:wizard0", "name": ""})
    assert "The full name field is required." in r.text
    r = admin.post("/admin/_tw/form", {"_tw_kind": "host", "_tw_host": "resource:users", "_tw_op": "create",
                                       "_tw_ui_action": "wizard.next:wizard0", "name": "A B", "email": "ab@x.com",
                                       "username": "ab", "password": "password1", "is_active": "1"})
    assert 'name="_tw_ui.wizard0" value="1"' in r.text


def test_user_create_hashes_password_and_assigns_roles(admin, panel):
    with db_session(panel) as db:
        editor = db.scalars(select(Role).where(Role.name == "Editor")).one().id
    r = admin.post("/admin/users/create", {"name": "Neo User", "email": "neo@x.com", "username": "neo",
                                           "password": "password1", "is_active": "1", "roles": [str(editor)]})
    assert r.status_code == 204, r.text
    with db_session(panel) as db:
        user = db.scalars(select(User).where(User.email == "neo@x.com")).one()
        assert user.password.startswith("pbkdf2_sha256$")
        assert db.scalars(select(RoleAssignment.role_id).where(RoleAssignment.user_id == str(user.id))).all() == [editor]


def test_file_upload_through_refresh(admin, panel, tmp_path):
    png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
           b"\x00\x00\x00\rIDATx\xdac\xfc\xcf\xc0P\x0f\x00\x04\x85\x01\x80\x84\xa9\x8c!\x00\x00\x00\x00IEND\xaeB`\x82")
    r = admin.client.post("/admin/_tw/form", data={"_tw_kind": "host", "_tw_host": "resource:products", "_tw_op": "edit",
                                                   "_tw_record": "1", "name": "x"},
                          files={"images.__upload": ("pic.png", png, "image/png")},
                          headers={"HX-Request": "true", "X-CSRF-Token": admin.token})
    stored = re.search(r'name="images" value="([^"]+\.png)"', r.text).group(1)
    assert (tmp_path / "storage" / stored).exists()
    assert admin.get(f"/admin/storage/{stored}").headers["content-type"] == "image/png"
    r = admin.client.post("/admin/_tw/form", data={"_tw_kind": "host", "_tw_host": "resource:products", "_tw_op": "edit",
                                                   "_tw_record": "1"},
                          files={"images.__upload": ("evil.html", b"<script>", "text/html")},
                          headers={"HX-Request": "true", "X-CSRF-Token": admin.token})
    assert "The file type is not allowed." in r.text


# ---------------------------------------------------------------------- actions


def action(admin, method="post", **data):
    data = {f"_tw_{k}" if k in ("host", "scope", "name", "record") else k: v for k, v in data.items()}
    if method == "get":
        from urllib.parse import urlencode

        return admin.get("/admin/_tw/action?" + urlencode(data, doseq=True), htmx=True)
    return admin.post("/admin/_tw/action", data)


def test_delete_action_modal_and_soft_delete_restore(admin, panel):
    r = action(admin, "get", host="resource:products", scope="row", name="delete", record="1")
    assert "Delete product" in r.text and "cannot be undone" in r.text
    r = action(admin, host="resource:products", scope="row", name="delete", record="1")
    trig = json.loads(r.headers["HX-Trigger"])
    assert "tw-refresh" in trig and trig["tw-notify"][0]["title"] == "Deleted"
    with db_session(panel) as db:
        assert db.get(Product, 1).deleted_at is not None
    assert "Premium T-Shirt" not in table(admin, "resource:products", search="premium").text
    r = table(admin, "resource:products", search="premium", **{"_f": "1", "filters.trashed.value": "only"})
    assert "Premium T-Shirt" in r.text and "opacity-60" in r.text
    action(admin, host="resource:products", scope="row", name="restore", record="1")
    with db_session(panel) as db:
        assert db.get(Product, 1).deleted_at is None


def test_custom_row_action_with_visibility(admin, panel):
    with db_session(panel) as db:
        order = db.scalars(select(Order).where(Order.status == OrderStatus.PENDING)).first()
        shipped = db.scalars(select(Order).where(Order.status == OrderStatus.SHIPPED)).first()
    r = action(admin, host="resource:orders", scope="row", name="ship", record=str(order.id))
    assert "Order shipped" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert db.get(Order, order.id).status is OrderStatus.SHIPPED
    r = action(admin, host="resource:orders", scope="row", name="ship", record=str(shipped.id))
    assert r.status_code == 204 and "Not allowed" in r.headers["HX-Trigger"]


def test_bulk_actions(admin, panel):
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:users", "_tw_scope": "bulk", "_tw_name": "deactivate",
                                         "records": ["2", "3"]})
    assert "Users deactivated" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert not db.get(User, 2).is_active and not db.get(User, 3).is_active
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:products", "_tw_scope": "bulk", "_tw_name": "delete",
                                         "records": ["2", "3"]})
    assert "tw-deselect" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert db.get(Product, 2).deleted_at is not None


def test_action_with_form_validates(admin, panel):
    r = action(admin, host="resource:users", scope="page", name="reset_password", record="2", password="short")
    assert "at least 8" in r.text
    r = action(admin, host="resource:users", scope="page", name="reset_password", record="2", password="longenough")
    assert r.headers.get("HX-Refresh") == "true"
    with db_session(panel) as db:
        assert db.get(User, 2).password.startswith("pbkdf2_sha256$")


def test_simple_resource_modal_create_edit(admin, panel):
    r = action(admin, "get", host="resource:categories", scope="table", name="create")
    assert "Page not found" in r.headers["HX-Trigger"]  # simple resources put Create in the page header
    r = action(admin, "get", host="resource:categories", scope="page", name="create")
    assert 'name="name"' in r.text and "Create" in r.text
    r = admin.post("/admin/_tw/form", {"_tw_kind": "action", "_tw_host": "resource:categories", "_tw_scope": "page",
                                       "_tw_name": "create", "_tw_form_id": "tw-action-form", "name": "Kids Wear",
                                       "slug": ""}, trigger="name")
    assert 'value="kids-wear"' in r.text
    r = action(admin, host="resource:categories", scope="page", name="create", name_="x")
    assert "field is required" in r.text
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:categories", "_tw_scope": "page", "_tw_name": "create",
                                         "name": "Kids Wear", "slug": "kids-wear", "is_visible": "1"})
    assert r.headers["HX-Refresh"] == "true"  # page actions reload the page; the toast is flashed
    assert "Created" in admin.get("/admin/categories").text
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:categories", "_tw_scope": "row", "_tw_name": "edit",
                                         "_tw_record": "1", "name": "Clothes", "slug": "clothes"})
    assert "Saved" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert db.get(Category, 1).name == "Clothes"


def test_relation_manager_create_and_table(admin, panel):
    host = "relation:customers:1:orders"
    r = table(admin, host)
    assert "ORD-" in r.text
    r = admin.post("/admin/_tw/action", {"_tw_host": host, "_tw_scope": "table", "_tw_name": "create",
                                         "number": "ORD-REL", "status": "paid", "total": "10"})
    assert "Created" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        order = db.scalars(select(Order).where(Order.number == "ORD-REL")).one()
        assert order.customer_id == 1


def test_replicate_action(admin, panel):
    r = action(admin, host="resource:products", scope="row", name="replicate", record="3")
    assert "Replicated" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert db.scalar(select(func.count()).select_from(Product).where(Product.name == db.get(Product, 3).name)) == 2


# ---------------------------------------------------------------------- import / export


def test_export_csv_respects_filters(admin):
    r = admin.get("/admin/_tw/export?host=resource:products&format=csv&search=watch")
    assert r.headers["content-disposition"] == 'attachment; filename="products.csv"'
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Product,SKU") and len(lines) == 2 and "Smart Watch" in lines[1]
    r = admin.get("/admin/_tw/export?host=resource:products&format=xlsx&keys=1&keys=2")
    assert r.content[:2] == b"PK"


def test_export_action_redirects_to_download(admin):
    r = action(admin, host="resource:products", scope="table", name="export", format="csv", columns=["name", "sku"],
               state="search=watch")
    assert r.headers["HX-Redirect"].startswith("/admin/_tw/export?search=watch")


def test_import_action(admin, panel, tmp_path):
    csv_bytes = b"name,sku,price,stock,status,category\nNew Cap,CAP-1,499,10,published,Accessories\n" \
                b"Bad Row,,abc,1,draft,Nope\nPremium T-Shirt v2,PRE-001,1399,5,published,Clothing\n"
    r = admin.client.post("/admin/_tw/form", data={"_tw_kind": "action", "_tw_host": "resource:products",
                                                   "_tw_scope": "table", "_tw_name": "import"},
                          files={"file.__upload": ("products.csv", csv_bytes, "text/csv")},
                          headers={"HX-Request": "true", "X-CSRF-Token": admin.token})
    stored = re.search(r'name="file" value="([^"]+)"', r.text).group(1)
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:products", "_tw_scope": "table", "_tw_name": "import",
                                         "file": stored})
    note = json.loads(r.headers["HX-Trigger"])["tw-notify"][0]
    assert note["body"] == "1 created, 1 updated, 1 failed."
    assert note["actions"][0]["label"] == "Download failed rows"
    with db_session(panel) as db:
        assert db.scalars(select(Product).where(Product.sku == "CAP-1")).one().category.name == "Accessories"
        assert db.scalars(select(Product).where(Product.sku == "PRE-001")).one().price == 1399


# ---------------------------------------------------------------------- search, notifications, widgets


def test_global_search(admin):
    r = admin.get("/admin/_tw/search?q=smart", htmx=True)
    assert "Smart Watch" in r.text and "Category: Electronics" in r.text
    r = admin.get("/admin/_tw/search?q=report", htmx=True)
    assert "Reports" in r.text  # navigation items are searchable too
    assert "No results" in admin.get("/admin/_tw/search?q=zzzz", htmx=True).text


def test_notification_bell(admin, panel):
    from tungsten import Notification

    with db_session(panel) as db:
        Notification("Hello").body("World").success().send_to_database(1, db)
    assert ">1<" in admin.get("/admin/_tw/notifications/badge", htmx=True).text
    r = admin.get("/admin/_tw/notifications", htmx=True)
    assert "Hello" in r.text and "1 new" in r.text
    admin.post("/admin/_tw/notifications", {})
    assert admin.get("/admin/_tw/notifications/badge", htmx=True).text.strip() == ""


def test_widgets_render(admin, panel):
    for w in panel.all_widgets():
        r = admin.get(f"/admin/_tw/widget/{w.get_id()}", htmx=True)
        assert r.status_code == 200, w
    r = admin.get("/admin/_tw/widget/revenue-chart?filter=3", htmx=True)
    assert "data-tw-chart" in r.text and "Last 3 months" in r.text


def test_custom_page_form_save(admin, tmp_path):
    r = admin.get("/admin/system-settings")
    assert 'value="Tungsten Store"' in r.text
    r = admin.post("/admin/system-settings", {"store_name": "My Shop", "support_email": "bad", "currency": "INR"})
    assert "valid email" in r.text
    r = admin.post("/admin/system-settings", {"store_name": "My Shop", "support_email": "a@b.co", "currency": "INR",
                                              "extra.0.key": "k", "extra.0.value": "v"})
    assert "Saved" in r.headers["HX-Trigger"]
    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["store_name"] == "My Shop" and saved["extra"] == {"k": "v"}


# ---------------------------------------------------------------------- roles & permissions


def login_as_role(app_and_panel, role_name: str) -> PanelClient:
    from fastapi.testclient import TestClient

    from tungsten.auth import hash_password

    app, panel = app_and_panel
    with db_session(panel) as db:
        user = User(name=f"{role_name} Person", email=f"{role_name.lower()}@x.com", password=hash_password("password"),
                    is_admin=True, is_active=True, email_verified_at=dt.datetime.now())
        db.add(user)
        db.flush()
        role = db.scalars(select(Role).where(Role.name == role_name)).one()
        db.add(RoleAssignment(role_id=role.id, user_id=str(user.id)))
        db.commit()
    c = PanelClient(TestClient(app))
    assert c.login(email=f"{role_name.lower()}@x.com").status_code == 303
    c.get("/admin/")
    return c


def test_viewer_role_is_read_only(app_and_panel):
    viewer = login_as_role(app_and_panel, "Viewer")
    nav = viewer.get("/admin/").text
    assert "/admin/products" in nav and "/admin/users\"" not in nav and "/admin/roles" not in nav
    assert viewer.get("/admin/users").status_code == 403
    html = viewer.get("/admin/products").text
    assert "Create product" not in html and 'title="Delete"' not in html
    assert viewer.get("/admin/products/1/edit").status_code == 403
    r = action(viewer, host="resource:products", scope="row", name="delete", record="1")
    assert "Not allowed" in r.headers["HX-Trigger"]
    assert viewer.get("/admin/system-settings").status_code == 403


def test_editor_can_edit_products_not_delete(app_and_panel):
    editor = login_as_role(app_and_panel, "Editor")
    assert editor.get("/admin/products/1/edit").status_code == 200
    r = action(editor, host="resource:products", scope="row", name="delete", record="1")
    assert "Not allowed" in r.headers["HX-Trigger"]


def test_roles_resource_permission_matrix(admin):
    html = admin.get("/admin/roles/2/edit").text
    assert "Search permissions" in html and 'value="products.delete"' in html
    r = admin.post("/admin/roles/2/edit", {"name": "Admin", "color": "info", "permissions": ["products.view_any", "*"]})
    assert "Saved" in r.headers["HX-Trigger"]


def test_many_to_many_attach_detach(admin, panel):
    from examples.shop.models import Tag

    host = "relation:products:1:tags"
    with db_session(panel) as db:
        p = db.get(Product, 1)
        have = {t.id for t in p.tags}
        other = next(t.id for t in db.scalars(select(Tag)) if t.id not in have)
    r = action(admin, "get", host=host, scope="table", name="attach")
    assert f'value="{other}"' in r.text and all(f'<option value="{h}"' not in r.text for h in have)
    r = admin.post("/admin/_tw/action", {"_tw_host": host, "_tw_scope": "table", "_tw_name": "attach",
                                         "records": [str(other)]})
    assert "Attached" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert other in {t.id for t in db.get(Product, 1).tags}
    r = action(admin, host=host, scope="row", name="detach", record=str(other))
    assert "Detached" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert other not in {t.id for t in db.get(Product, 1).tags}
        assert db.get(Tag, other) is not None  # detach keeps the tag
    r = admin.post("/admin/_tw/action", {"_tw_host": host, "_tw_scope": "table", "_tw_name": "create", "name": "fresh"})
    assert "Created" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        assert "fresh" in {t.name for t in db.get(Product, 1).tags}
