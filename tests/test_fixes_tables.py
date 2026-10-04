"""Tests for table fixes: image shapes, filter layout/defaults, column search, groups, summaries, reorder."""

from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select

from examples.shop.models import Category, Product
from examples.shop.resources import CategoryResource, ProductResource
from tungsten.tables import (
    DateFilter,
    Filter,
    Group,
    ImageColumn,
    QueryBuilder,
    RelationshipConstraint,
    SelectFilter,
    Sum,
    Table,
    TernaryFilter,
    TextColumn,
    TextConstraint,
    TrashedFilter,
)

from .conftest import db_session
from .test_panel import table


def patch_table(monkeypatch, resource, change):
    """Run ``change(table)`` after the resource builds its table."""
    original = resource.table.__func__
    monkeypatch.setattr(resource, "table", classmethod(lambda cls, t: change(original(cls, t))))


def total(r) -> int:
    m = re.search(r'of <span class="font-medium">(\d+)</span> results', r.text)
    return int(m.group(1)) if m else 0


def live_products(panel, *where):
    with db_session(panel) as db:
        return list(db.scalars(select(Product).where(Product.deleted_at.is_(None), *where)))


# ---------------------------------------------------------------------- 1. ImageColumn.square()
def test_image_column_square(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.columns(t._columns + [
        ImageColumn("images").label("Square").square().default_image_url("/sq.png"),
        ImageColumn("images").label("Round").circular().default_image_url("/round.png"),
    ]))
    r = table(admin, "resource:products")
    assert re.search(r'class="rounded-none object-cover', r.text)
    assert re.search(r'class="rounded-full object-cover', r.text)
    col = ImageColumn("x").square().circular()
    assert col._circular and not col._square


# ---------------------------------------------------------------------- 2. stored options
def test_filter_columns_lays_out_fields(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource,
                lambda t: t.filters(t._filters + [DateFilter("created_at").columns(2)]))
    r = table(admin, "resource:products")
    assert 'style="grid-template-columns: repeat(2, minmax(0, 1fr))"' in r.text
    assert Filter("x").grid_style() == ""


def test_column_search_global_and_individual(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.columns([
        TextColumn("name").searchable(),
        TextColumn("sku").label("SKU").searchable(is_global=False, is_individual=True),
    ]))
    product = live_products(panel)[0]
    # the SKU is left out of the main search box
    r = table(admin, "resource:products", search=product.sku)
    assert product.name not in r.text
    # ...but has its own search box under its heading
    r = table(admin, "resource:products")
    assert 'name="col_search.sku"' in r.text
    r = table(admin, "resource:products", **{"col_search.sku": product.sku})
    assert total(r) == 1 and product.name in r.text
    assert f"SKU: “{product.sku}”" in r.text  # shown as an active filter chip
    assert f"col_search.sku={product.sku}" in r.headers["HX-Replace-Url"]
    # a table with only individual search has no main search box
    patch_table(monkeypatch, ProductResource, lambda t: t.columns([
        TextColumn("name").searchable(is_global=False, is_individual=True)]))
    r = table(admin, "resource:products")
    assert 'name="search"' not in r.text and 'name="col_search.name"' in r.text


def test_dead_export_option_removed():
    assert not hasattr(Table(), "_export")


def test_collapsible_groups(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.groups([Group("category.name").collapsible()]))
    r = table(admin, "resource:products", group="category.name")
    assert 'data-tw-group="0"' in r.text and 'x-show="!collapsed.includes(0)"' in r.text
    patch_table(monkeypatch, ProductResource, lambda t: t.groups([Group("category.name")]))
    r = table(admin, "resource:products", group="category.name")
    assert "data-tw-group" not in r.text


# ---------------------------------------------------------------------- 3. to-many detection
def test_relationship_constraint_detects_to_many(admin, monkeypatch):
    class FakeTable:
        model = Product

    builder = QueryBuilder().constraints([RelationshipConstraint("category"), RelationshipConstraint("tags"),
                                          RelationshipConstraint("brand").multiple()])
    builder.bind_options(FakeTable())
    category, tags, brand = builder._constraints
    assert "count_gte" not in category.get_operators()
    assert "count_gte" in tags.get_operators()
    assert "count_gte" in brand.get_operators()  # multiple() still wins
    # in a real table, a count rule on a to-one relationship is ignored
    patch_table(monkeypatch, ProductResource, lambda t: t.filters([
        QueryBuilder().constraints([RelationshipConstraint("category")])]))
    r = table(admin, "resource:products", _f="1", **{
        "filters.query.g.0.0.c": "category", "filters.query.g.0.0.op": "count_gte", "filters.query.g.0.0.v": "5"})
    assert 'title="Not applied yet"' in r.text


# ---------------------------------------------------------------------- 4. filter defaults
def test_date_filter_default(admin, panel, monkeypatch):
    since = dt.date.today() - dt.timedelta(days=30)
    patch_table(monkeypatch, ProductResource, lambda t: t.filters([
        DateFilter("created_at").label("Created").default(lambda: {"from": since})]))
    r = table(admin, "resource:products", per_page="100")
    expected = live_products(panel, Product.created_at >= since)
    assert total(r) == len(expected)
    assert f"Created from {since}" in r.text
    assert DateFilter("d").default((since, dt.datetime(2030, 1, 2, 5))).default_data() == {
        "from": since.isoformat(), "until": "2030-01-02"}
    # "Clear filters" does not bring the default back
    r = table(admin, "resource:products", _f="1", _reset="1")
    assert total(r) == len(live_products(panel))


def test_other_filter_defaults(admin, panel, monkeypatch):
    import enum

    class Status(enum.Enum):
        PUBLISHED = "published"

    assert SelectFilter("s").options(Status).default(Status.PUBLISHED).default_data() == {"value": "published"}
    assert SelectFilter("s").multiple().default(["a", "b"]).default_data() == {"values": ["a", "b"]}
    assert TernaryFilter("t").default(False).default_data() == {"value": "0"}
    assert TrashedFilter().default(True).default_data() == {"value": "with"}
    assert TrashedFilter().default("only").default_data() == {"value": "only"}

    patch_table(monkeypatch, ProductResource, lambda t: t.filters([
        TrashedFilter().default("only"),
        QueryBuilder().constraints([TextConstraint("status")]).default([{"c": "status", "op": "equals", "v": "draft"}]),
    ]))
    with db_session(panel) as db:
        p = db.scalars(select(Product).where(Product.status == "draft")).first()
        p.deleted_at = dt.datetime.now()
        db.commit()
        expected = len(db.scalars(select(Product).where(Product.deleted_at.is_not(None),
                                                        Product.status == "draft")).all())
    r = table(admin, "resource:products", per_page="100")
    assert total(r) == expected
    assert "Only deleted records" in r.text and "Status equals “draft”" in r.text


# ---------------------------------------------------------------------- 5. summaries of state() columns
def test_summarize_state_column(admin, panel, monkeypatch):
    patch_table(monkeypatch, CategoryResource, lambda t: t.columns([
        TextColumn("name"),
        TextColumn("products_count").state(lambda record: len(record.products)).summarize(Sum("Products")),
    ]))
    with db_session(panel) as db:
        count = sum(len(c.products) for c in db.scalars(select(Category)))
    r = table(admin, "resource:categories")
    assert r.status_code == 200
    assert re.search(rf"Products:</span> <span[^>]*>{count}<", r.text)


# ---------------------------------------------------------------------- 6. reorder with hidden rows
def test_reorder_keeps_hidden_rows_in_place(admin, panel):
    with db_session(panel) as db:
        ids = [c.id for c in db.scalars(select(Category).order_by(Category.sort, Category.id))]
    assert len(ids) >= 4
    # only rows 1 and 3 are on screen (a search is active); the user swaps them
    keys = [str(ids[2]), str(ids[0])]
    r = admin.post("/admin/_tw/reorder", {"host": "resource:categories", "keys": keys})
    assert "Order saved" in r.headers["HX-Trigger"]
    with db_session(panel) as db:
        rows = db.scalars(select(Category).order_by(Category.sort, Category.id)).all()
    assert [c.id for c in rows] == [ids[2], ids[1], ids[0]] + ids[3:]
    assert [c.sort for c in rows] == list(range(1, len(ids) + 1))


# ---------------------------------------------------------------------- 7. menus inside a table are not cut off
def test_table_menus_float_above_the_table(admin):
    # the table box scrolls sideways (overflow-x-auto), which also cuts off a menu hanging below the last rows,
    # so menus open in the browser's top layer next to their trigger (twDropdown in tungsten.js)
    html = table(admin, "resource:products").text
    assert html.count("x-data=\"twDropdown('end')\"") >= 2 and 'x-ref="panel"' in html  # row menus + Columns
    assert "closest('a, button:not([disabled])') && (open = false)" in html  # picking an item closes the menu
    js = admin.get("/admin/assets/tungsten.js").text
    assert 'Alpine.data("twDropdown"' in js and 'panel.setAttribute("popover", "manual")' in js
