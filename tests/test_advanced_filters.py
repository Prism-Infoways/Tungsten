"""Advanced filters: per-column operator filters, guessed constraints and relative date operators."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from examples.shop.models import Order, OrderStatus, Product, Tag
from examples.shop.resources import OrderResource, ProductResource
from tungsten.tables import (
    AdvancedFilter,
    BooleanConstraint,
    DateConstraint,
    NumberConstraint,
    QueryBuilder,
    RelationshipConstraint,
    SelectConstraint,
    TextConstraint,
    constraint_for,
)
from tungsten.tables.query_builder import date_range

from .conftest import db_session
from .test_fixes_tables import live_products, patch_table, total
from .test_panel import table


def adv(admin, host="resource:products", **params):
    return table(admin, host, _f="1", per_page="100", **{f"filters.{k}": v for k, v in params.items()})


# ---------------------------------------------------------------------- guessing constraints
def test_constraint_for_guesses_from_column_types():
    assert isinstance(constraint_for(Product, "name"), TextConstraint)
    stock = constraint_for(Product, "stock")
    assert isinstance(stock, NumberConstraint) and stock._integer
    price = constraint_for(Product, "price")
    assert isinstance(price, NumberConstraint) and not price._integer
    assert isinstance(constraint_for(Product, "is_featured"), BooleanConstraint)
    assert isinstance(constraint_for(Product, "created_at"), DateConstraint)
    assert isinstance(constraint_for(Product, "available_from"), DateConstraint)
    assert isinstance(constraint_for(Product, "category.name"), TextConstraint)
    status = constraint_for(Order, "status")
    assert isinstance(status, SelectConstraint) and status._options is OrderStatus
    tags = constraint_for(Product, "tags")
    assert isinstance(tags, RelationshipConstraint) and tags._title == "name"
    # computed, JSON and unknown names can't be filtered
    for name in ("state", "sizes", "nope", "category.nope", "tags.name.x"):
        assert constraint_for(Product, name) is None


# ---------------------------------------------------------------------- one advanced filter
def test_text_filter_operators(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.filters([AdvancedFilter.text("name")]))
    r = adv(admin, **{"name.op": "starts_with", "name.v": "smart"})
    expected = [p for p in live_products(panel) if p.name.lower().startswith("smart")]
    assert expected and total(r) == len(expected)
    assert "Name starts with “smart”" in r.text
    # a value with no operator uses the default one (contains)
    r = adv(admin, **{"name.v": "watch"})
    assert total(r) == len([p for p in live_products(panel) if "watch" in p.name.lower()])
    # an operator that needs a value, without one, is not applied
    r = adv(admin, **{"name.op": "equals"})
    assert total(r) == len(live_products(panel))
    assert 'title="Not applied yet"' in r.text


def test_number_filter_between_and_not_between(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.filters([AdvancedFilter("price")]))
    r = adv(admin, **{"price.op": "between", "price.v": "5000", "price.v2": "1000"})
    inside = [p for p in live_products(panel) if Decimal(1000) <= p.price <= Decimal(5000)]
    assert total(r) == len(inside)
    r = adv(admin, **{"price.op": "not_between", "price.v": "1000", "price.v2": "5000"})
    assert total(r) == len(live_products(panel)) - len(inside)
    # bad number: ignored
    r = adv(admin, **{"price.op": "gt", "price.v": "abc"})
    assert total(r) == len(live_products(panel))


def test_boolean_select_and_relationship_filters(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.filters([
        AdvancedFilter.boolean("is_featured").label("Featured"),
        AdvancedFilter.select("status", {"draft": "Draft", "published": "Published"}),
        AdvancedFilter.relationship("tags", "name"),
    ]))
    r = adv(admin, **{"is_featured.op": "true"})
    assert total(r) == len(live_products(panel, Product.is_featured.is_(True)))
    assert "Featured is true" in r.text
    r = adv(admin, **{"status.op": "is_not", "status.v": "draft"})
    assert total(r) == len(live_products(panel, Product.status != "draft"))
    with db_session(panel) as db:
        tag = db.scalars(select(Tag)).first()
        tag_id, tag_name = tag.id, tag.name
    r = adv(admin, **{"tags.op": "in", "tags.vs": str(tag_id)})
    assert total(r) == len(live_products(panel, Product.tags.any(Tag.id == tag_id)))
    assert f"Tags is any of {tag_name}" in r.text
    # all three together are ANDed
    r = adv(admin, **{"is_featured.op": "false", "status.op": "is", "status.v": "published"})
    assert total(r) == len(live_products(panel, Product.is_featured.is_not(True), Product.status == "published"))


def test_enum_select_filter_guessed(admin, panel, monkeypatch):
    patch_table(monkeypatch, OrderResource, lambda t: t.filters([AdvancedFilter("status")]))
    r = adv(admin, "resource:orders", **{"status.op": "in", "status.vs": ["paid", "shipped"]})
    with db_session(panel) as db:
        expected = len(db.scalars(select(Order).where(Order.status.in_([OrderStatus.PAID, OrderStatus.SHIPPED]))).all())
    assert total(r) == expected


def test_date_filter_relative_operators(admin, panel, monkeypatch):
    today = dt.date.today()
    with db_session(panel) as db:
        products = db.scalars(select(Product).where(Product.deleted_at.is_(None)).order_by(Product.id)).all()
        products[0].created_at = dt.datetime.combine(today, dt.time(10))
        products[1].created_at = dt.datetime.combine(today - dt.timedelta(days=1), dt.time(23, 59))
        products[2].created_at = dt.datetime.combine(today + dt.timedelta(days=3), dt.time(1))
        for p in products[3:]:
            p.created_at = dt.datetime(2001, 1, 1)
        db.commit()
    patch_table(monkeypatch, ProductResource, lambda t: t.filters([AdvancedFilter.date("created_at").label("Created")]))
    assert total(adv(admin, **{"created_at.op": "today"})) == 1
    assert total(adv(admin, **{"created_at.op": "yesterday"})) == 1
    assert total(adv(admin, **{"created_at.op": "last_days", "created_at.v": "7"})) == 2
    assert total(adv(admin, **{"created_at.op": "next_days", "created_at.v": "7"})) == 2
    assert total(adv(admin, **{"created_at.op": "future"})) == 1
    assert total(adv(admin, **{"created_at.op": "this_year"})) == len([
        p for p in products[:3] if (p.created_at.year == today.year)])
    assert total(adv(admin, **{"created_at.op": "not_on", "created_at.v": today.isoformat()})) == len(products) - 1
    r = adv(admin, **{"created_at.op": "last_months", "created_at.v": "2"})
    assert "Created is in the last 2 months" in r.text
    # a huge N doesn't crash: it just has no start
    assert total(adv(admin, **{"created_at.op": "last_years", "created_at.v": "99999999"})) == len(products) - 1
    assert total(adv(admin, **{"created_at.op": "between", "created_at.v": "9999-12-31", "created_at.v2": "9999-12-31"})) == len(products)


def test_date_range_helper():
    day = dt.date(2026, 3, 31)  # a Tuesday
    assert date_range("this_week", today=day) == (dt.date(2026, 3, 30), dt.date(2026, 4, 6))
    assert date_range("last_month", today=day) == (dt.date(2026, 2, 1), dt.date(2026, 3, 1))
    assert date_range("this_month", today=dt.date(2026, 12, 5)) == (dt.date(2026, 12, 1), dt.date(2027, 1, 1))
    assert date_range("last_months", 1, today=day) == (dt.date(2026, 2, 28), dt.date(2026, 4, 1))
    assert date_range("last_year", today=day) == (dt.date(2025, 1, 1), dt.date(2026, 1, 1))
    assert date_range("past", today=day) == (None, day)


def test_operators_limit_default_and_render(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.filters([
        AdvancedFilter.number("stock", integer=True).operators(["gte", "lte"]).default({"op": "gte", "v": 10}),
    ]))
    r = table(admin, "resource:products", per_page="100")
    assert total(r) == len(live_products(panel, Product.stock >= 10))
    assert 'data-tw-advanced-filter="stock"' in r.text
    assert 'value="lte"' in r.text and 'value="between"' not in r.text
    assert "Stock is at least 10" in r.text
    # an operator that was not offered is ignored
    r = adv(admin, **{"stock.op": "eq", "stock.v": "1"})
    assert total(r) == len(live_products(panel))


def test_unknown_column_raises(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.filters([AdvancedFilter("state")]))
    with pytest.raises(ValueError, match="Can't guess a filter"):
        table(admin, "resource:products")


# ---------------------------------------------------------------------- whole-table helpers
def test_table_advanced_filters_adds_one_per_column(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.advanced_filters(exclude=["sku"]))
    r = table(admin, "resource:products")
    for name in ("name", "category__name", "price", "stock", "tags__name", "created_at"):
        assert f'data-tw-advanced-filter="{name}"' in r.text
    assert 'data-tw-advanced-filter="sku"' not in r.text
    assert 'data-tw-advanced-filter="state"' not in r.text  # computed column
    r = adv(admin, **{"category__name.op": "equals", "category__name.v": "electronics"})
    from sqlalchemy import func

    from examples.shop.models import Category

    assert total(r) == len(live_products(panel, Product.category.has(func.lower(Category.name) == "electronics")))
    # the guessed filter takes the column label
    assert "Category equals “electronics”" in r.text


def test_query_builder_auto_constraints(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.filters([
        QueryBuilder().constraints([NumberConstraint("price").label("Cost")]).auto_constraints(exclude=["sku"])]))
    r = table(admin, "resource:products", _f="1", per_page="100", **{
        "filters.query.g.0.0.c": "stock", "filters.query.g.0.0.op": "lt", "filters.query.g.0.0.v": "20",
        "filters.query.g.1.0.c": "price", "filters.query.g.1.0.op": "gt", "filters.query.g.1.0.v": "50000",
    })
    expected = [p for p in live_products(panel) if p.stock < 20 or p.price > 50000]
    assert total(r) == len(expected)
    assert "Cost is greater than 50000" in r.text  # your constraint wins over the guessed one
    assert ":sku" not in r.text and ":state" not in r.text
