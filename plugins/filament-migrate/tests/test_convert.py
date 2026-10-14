"""The sample Filament 3 shop converts to a Tungsten admin that runs on the same database."""

from __future__ import annotations

import ast

from conftest import laravel_hash, seed


def test_every_generated_file_is_valid_python(shop3):
    for rel, content in shop3.result.files.items():
        if rel.endswith(".py"):
            ast.parse(content, filename=rel)


def test_summary(shop3):
    s = shop3.result.summary
    assert s == {"models": 7, "resources": 4, "relation_managers": 1}
    assert sorted(shop3.result.files) == [
        "MIGRATION_REPORT.md", "__init__.py", "app.py", "models.py", "resources/__init__.py",
        "resources/customer_resource.py", "resources/order_resource.py", "resources/product_resource.py",
        "resources/tag_resource.py",
    ]


def test_models_follow_the_migrations(shop3):
    models = shop3.import_("models")
    cols = models.Product.__table__.columns
    # added by a later migration, renamed, kept in order
    assert "sku" in cols and "quantity" in cols and "stock" not in cols
    assert cols["price"].type.precision == 10 and cols["price"].type.scale == 2
    assert cols["category_id"].nullable is True
    assert [fk.target_fullname for fk in cols["category_id"].foreign_keys] == ["categories.id"]
    # dropped column and dropped table
    assert "gender" not in models.Customer.__table__.columns
    assert "temp_imports" not in models.Base.metadata.tables
    # foreignIdFor(Product::class)
    assert [fk.target_fullname for fk in models.OrderItem.__table__.columns["product_id"].foreign_keys] == ["products.id"]
    # pivot for belongsToMany, with the primary key from $table->primary([...])
    pivot = models.Base.metadata.tables["product_tag"]
    assert {c.name for c in pivot.primary_key} == {"product_id", "tag_id"}


def test_relations_pair_up(shop3):
    from sqlalchemy.orm import configure_mappers

    models = shop3.import_("models")
    configure_mappers()
    assert models.Order.customer.property.back_populates == "orders"
    assert models.Customer.orders.property.back_populates == "customer"
    assert models.Product.tags.property.back_populates == "products"
    assert models.OrderItem.product.property.back_populates is None  # Product has no items() relation


def test_enum_keeps_labels_and_colors(shop3):
    models = shop3.import_("models")
    assert models.OrderStatus.Processing.value == "processing"
    assert models.OrderStatus.Processing.label() == "In progress"
    assert models.OrderStatus.Shipped.label() == "Sent"
    assert models.OrderStatus.colors()["cancelled"] == "danger"


def test_form_and_table_code(shop3):
    src = shop3.file("resources/product_resource.py")
    assert "TextInput('name').required().max_length(255).live(on_blur=True)" in src
    assert ".after_state_updated(lambda set, state: set('slug', slug(state)))" in src
    assert "from tungsten_filament.runtime import slug" in src
    assert "Select('category_id').relationship('category', 'name').searchable().preload()" in src
    assert ".visible(lambda get: bool(get('category_id')))" in src
    assert "KeyValue('options').hidden(lambda operation: operation == 'create')" in src
    assert "DatePicker('published_at').label('Availability').default(dt.datetime.now)" in src
    assert "TextInput('quantity').numeric().default(0).integer().min_value(0)" in src
    assert "TextColumn('price').money('USD').sortable()" in src
    assert "TextColumn('published_at').date('%d/%m/%Y').toggleable(hidden_by_default=True)" in src
    assert "lambda state: ('danger' if (state < 10) else 'success')" in src
    assert "Filter('in_stock').query(lambda query, model: query.where(model.quantity > 0))" in src
    assert "Filter('cheap')" not in src  # its query could not be converted, so it is left out
    assert "TrashedFilter()" in src
    assert ".empty_state(heading='No products yet')" in src
    assert "global_search_attributes = ['name', 'sku']" in src
    assert "pages = ('index', 'create', 'edit')" in src

    order = shop3.file("resources/order_resource.py")
    assert "Repeater('items').relationship(order_column='sort')" in order
    assert "ToggleButtons('status').options(OrderStatus).required()" in order
    assert ".default(lambda: (str('OR-') + str(random.randint(100000, 999999))))" in order
    assert "lambda db: {r.id: r.name for r in db.scalars(select(Product).order_by(Product.name))}" in order
    assert "SelectFilter('status').options(OrderStatus).multiple()" in order
    # a column cast to a PHP enum shows its label, and its color as a badge
    assert ("TextColumn('status')\n                    .format_state_using(lambda state: OrderStatus(state).label() "
            "if state in OrderStatus._value2member_map_ else state)") in order
    assert '.color(lambda state: OrderStatus.colors().get(getattr(state, "value", state), "gray"))' in order


def test_relation_manager_and_simple_resource(shop3):
    customer = shop3.file("resources/customer_resource.py")
    assert "class OrdersRelationManager(RelationManager):" in customer
    assert "relationship = 'orders'" in customer
    assert "record_title_attribute = 'number'" in customer
    assert "relations = [OrdersRelationManager]" in customer
    assert "label = 'Client'" in customer
    assert "Select('status').options(OrderStatus).default('new').required()" in customer
    assert ".summarize(Sum())" in customer
    assert "pages = " not in customer  # index, create, edit and view: the default
    assert "simple = True" in shop3.file("resources/tag_resource.py")


def test_report_lists_what_needs_a_human(shop3):
    report = shop3.file("MIGRATION_REPORT.md")
    for text in [
        "createOptionForm() uses a value that was not converted",
        "Filament ViewField has no Tungsten match",
        "custom action 'publish' not converted",
        "filter 'cheap' left out",
        "getNavigationBadge() not converted",
        "page code not converted (CreateProduct: mutateFormDataBeforeCreate)",
        "relation Customer.comments: morphMany is not converted yet",
        "Page `Settings`",
        "Widget `StatsOverview`",
        "Filament plugin `FilamentShieldPlugin`: roles and permissions are built in",
        "Filament plugin `FancyPlugin`: no Tungsten match yet",
        "Policy `OrderPolicy`",
    ]:
        assert text in report, text
    # getEloquentQuery() that only lifts the soft-delete scope is what Tungsten does anyway
    assert "getEloquentQuery" not in report
    assert "recordTitleAttribute" not in report


def test_app_reads_the_laravel_env(shop3):
    app = shop3.file("app.py")
    assert "laravel_database_url(LARAVEL_PATH)" in app
    assert "brand_name='Acme Admin'" in app
    assert "colors={'primary': 'amber'}" in app
    assert "navigation_groups=['Shop', 'Settings']" in app
    assert "secret123" not in app and "APP_KEY" not in app.replace("laravel_secret_key", "")


def test_admin_runs_on_the_laravel_database(admin):
    for url in ["/admin/products", "/admin/products/create", "/admin/orders", "/admin/orders/create",
                "/admin/customers", "/admin/customers/create", "/admin/tags"]:
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[:500])
    assert "Red shoe" in admin.get("/admin/products").text
    orders = admin.get("/admin/orders").text
    assert "OR-1001" in orders and "In progress" in orders
    assert "Bob Buyer" in admin.get("/admin/customers").text


def test_edit_pages_and_relation_manager(admin):
    r = admin.get("/admin/products/1/edit")
    assert r.status_code == 200 and "red-shoe" in r.text
    r = admin.get("/admin/orders/1/edit")
    assert r.status_code == 200
    r = admin.get("/admin/customers/1/edit")
    assert r.status_code == 200 and "OR-1001" in r.text  # the orders relation manager


def test_wrong_password_is_refused(shop3):
    from conftest import PanelClient
    from fastapi.testclient import TestClient

    seed(shop3)
    client = PanelClient(TestClient(shop3.import_("app").app))
    assert client.login("ann@acme.test", "nope").status_code != 303


def test_new_passwords_stay_laravel_compatible():
    import bcrypt
    from tungsten_filament import LaravelHasher

    h = LaravelHasher(rounds=4)
    hashed = h.hash("pa55word")
    assert hashed.startswith("$2y$04$")
    assert bcrypt.checkpw(b"pa55word", ("$2b$" + hashed[4:]).encode())
    assert h.verify("pa55word", laravel_hash("pa55word"))
    assert not h.verify("wrong", hashed)
    assert not h.verify("x", None)
    # Tungsten's own hashes keep working
    from tungsten import hash_password

    assert h.verify("abc", hash_password("abc", iterations=1000))


def _db(conv):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    return Session(create_engine(f"sqlite:///{conv.root / 'database' / 'database.sqlite'}"))


def test_create_and_edit_save_to_the_laravel_tables(admin, shop3):
    from sqlalchemy import select

    models = shop3.import_("models")
    admin.get("/admin/products/create")
    r = admin.post("/admin/products/create", {
        "name": "Blue boot", "slug": "blue-boot", "price": "25.50", "quantity": "7", "is_visible": "1",
        "category_id": "1", "tags": ["1"], "published_at": "2026-10-01",
    })
    assert r.status_code == 204, r.text[:800]
    with _db(shop3) as db:
        p = db.scalars(select(models.Product).where(models.Product.slug == "blue-boot")).one()
        assert float(p.price) == 25.5 and p.quantity == 7 and p.category.name == "Shoes"
        assert [t.name for t in p.tags] == ["Hot"]
        assert p.created_at is not None and p.updated_at is not None  # Laravel timestamps are filled

    # the integer + min:0 rules from Filament still apply
    r = admin.post("/admin/products/create", {"name": "Bad", "slug": "bad", "price": "1", "quantity": "-3"})
    assert r.status_code != 204

    admin.get("/admin/customers/1/edit")
    r = admin.post("/admin/customers/1/edit", {"name": "Bob Renamed", "email": "bob@example.com"})
    assert r.status_code == 200, r.text[:800]
    with _db(shop3) as db:
        assert db.get(models.Customer, 1).name == "Bob Renamed"


def test_trashed_products_are_hidden(admin, shop3):
    import datetime as dt

    models = shop3.import_("models")
    with _db(shop3) as db:
        db.get(models.Product, 1).deleted_at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).replace(tzinfo=None)
        db.commit()
    assert "Red shoe" not in admin.get("/admin/products").text


def test_order_with_repeater_items(admin, shop3):
    from sqlalchemy import select

    models = shop3.import_("models")
    admin.get("/admin/orders/create")
    r = admin.post("/admin/orders/create", {
        "number": "OR-2002", "customer_id": "1", "status": "shipped",
        "items.0.product_id": "1", "items.0.qty": "2", "items.0.unit_price": "10",
        "items.1.product_id": "1", "items.1.qty": "1", "items.1.unit_price": "9",
    })
    assert r.status_code == 204, r.text[:800]
    with _db(shop3) as db:
        order = db.scalars(select(models.Order).where(models.Order.number == "OR-2002")).one()
        assert order.status == "shipped" and order.customer.name == "Bob Buyer"
        assert [(i.qty, i.sort) for i in sorted(order.items, key=lambda i: i.sort)] == [(2, 0), (1, 1)]


def test_tables_can_come_from_the_live_database(shop3, tmp_path):
    """No migrations in the repo? --database-url reads the tables from the database itself."""
    import shutil

    from tungsten_filament import build

    seed(shop3)
    shutil.rmtree(shop3.root / "database" / "migrations")
    url = f"sqlite:///{shop3.root / 'database' / 'database.sqlite'}"
    without = build(shop3.root, tmp_path / "a")
    assert without.summary["models"] == 0
    assert "not found in the migrations" in without.files["MIGRATION_REPORT.md"]
    result = build(shop3.root, tmp_path / "b", database_url_override=url)
    assert result.summary == {"models": 7, "resources": 4, "relation_managers": 1}
    models_src = result.files["models.py"]
    assert "price = mapped_column(Numeric(10, 2), nullable=False" in models_src
    assert "category_id = mapped_column(Integer, ForeignKey('categories.id'), nullable=True)" in models_src


def test_long_text_keeps_its_size_on_mysql(shop3):
    from sqlalchemy.dialects import mysql, sqlite
    from sqlalchemy.schema import CreateColumn

    models = shop3.import_("models")
    col = models.Product.__table__.columns["description"]  # $table->longText('description')
    assert str(CreateColumn(col).compile(dialect=mysql.dialect())).startswith("description LONGTEXT")
    assert str(CreateColumn(col).compile(dialect=sqlite.dialect())).startswith("description TEXT")
    assert "description = mapped_column(LongText" in shop3.file("models.py")
