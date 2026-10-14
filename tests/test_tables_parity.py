"""Filament parity for tables: filter layouts, deferred filters, session memory, simple and cursor
pagination, card layouts, column groups and the Range summary."""

from __future__ import annotations

import html
import re

import pytest
from sqlalchemy import select

from examples.shop.models import Category, Product
from examples.shop.resources import ProductResource
from tungsten.tables import ColumnGroup, Range, SelectFilter, Sum, Table, TextColumn

from .conftest import db_session
from .test_fixes_tables import live_products, patch_table, total
from .test_panel import table


def keys(r) -> list[str]:
    return re.findall(r'<tr [^>]*data-key="([^"]+)"', r.text)


# ---------------------------------------------------------------------- filter layouts
@pytest.mark.parametrize("layout", ["modal", "dropdown"])
def test_filters_in_a_modal_or_dropdown(admin, monkeypatch, layout):
    patch_table(monkeypatch, ProductResource, lambda t: t.filters(t._filters, layout=layout))
    r = table(admin, "resource:products")
    assert f'data-tw-filters="{layout}"' in r.text
    assert "<aside" not in r.text  # no side panel
    assert "Apply filters" in r.text  # these layouts wait for Apply by default
    assert 'name="_applied"' in r.text
    assert f'data-tw-filters="{layout}"' in admin.get("/admin/products").text  # the full page too


def test_filters_layout_is_checked():
    with pytest.raises(ValueError):
        Table().filters([], layout="sideways")
    assert Table().filters([SelectFilter("x")], layout="modal").has_deferred_filters()
    assert not Table().filters([SelectFilter("x")]).has_deferred_filters()
    assert Table().filters([SelectFilter("x")]).deferred_filters().has_deferred_filters()
    assert not Table().filters([SelectFilter("x")], layout="modal").deferred_filters(False).has_deferred_filters()


def test_deferred_filters_wait_for_apply(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.filters(t._filters).deferred_filters())
    everything = len(live_products(panel))
    drafts = len(live_products(panel, Product.status == "draft"))
    assert 0 < drafts < everything
    picked = {"_f": "1", "filters.status.value": "draft", "per_page": "100"}
    # picked in the form but not applied yet: the table still shows every record
    r = table(admin, "resource:products", _applied="", **picked)
    assert total(r) == everything
    # the form is drawn from the applied values, so the unapplied pick is dropped
    assert 'name="_applied" value=""' in r.text
    # Apply runs it
    r = table(admin, "resource:products", _applied="", _apply="1", **picked)
    assert total(r) == drafts
    assert 'name="_applied" value="filters.status.value=draft"' in r.text
    # later requests (search, sort, per page) keep the applied filter, not what is in the form
    r = table(admin, "resource:products", _applied="filters.status.value=draft",
              **{"_f": "1", "filters.status.value": "published", "per_page": "100"})
    assert total(r) == drafts
    # links (sort, pages) carry the applied filter
    assert "filters.status.value=draft" in html.unescape(r.text)


# ---------------------------------------------------------------------- session memory
def test_filters_search_and_sort_are_remembered(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.persist_in_session())
    drafts = live_products(panel, Product.status == "draft")
    table(admin, "resource:products", _f="1", **{"filters.status.value": "draft", "sort": "price",
                                                  "direction": "desc", "per_page": "100"})
    # opening the table again with nothing in the URL brings the same view back
    r = table(admin, "resource:products")
    assert total(r) == len(drafts)
    assert 'name="sort" value="price"' in r.text
    page = admin.get("/admin/products")
    assert total(page) == len(drafts)
    # clearing the filters is remembered too
    table(admin, "resource:products", _f="1", _reset="1")
    assert total(table(admin, "resource:products")) == len(live_products(panel))


def test_search_is_remembered_on_its_own(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.persist_search_in_session())
    table(admin, "resource:products", search="watch")
    r = table(admin, "resource:products")
    assert "Smart Watch" in r.text and "Denim Jeans" not in r.text
    assert 'value="watch"' in r.text


def test_big_filter_state_is_not_kept_in_the_cookie(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.persist_in_session())
    rules = {f"filters.query.g.0.{i}.{part}": value for i in range(40)
             for part, value in (("c", "name"), ("op", "contains"), ("v", "x" * 30))}
    table(admin, "resource:products", _f="1", search="watch", **rules)
    r = table(admin, "resource:products")
    assert 'value="watch"' in r.text  # the search is still remembered
    assert "Not applied yet" not in r.text and "x" * 30 not in r.text


def test_nothing_is_remembered_by_default(admin):
    table(admin, "resource:products", search="watch")
    r = table(admin, "resource:products")
    assert "Denim Jeans" in r.text or total(r) > 1


# ---------------------------------------------------------------------- pagination modes
def nav_button(r, label: str) -> str | None:
    """The URL behind the pagination button ``label``, or ``None`` when it is disabled."""
    nav = r.text[r.text.index("data-tw-pagination="):]
    for m in re.finditer(r"<button (?:(?!</button>).)*</button>", nav, re.S):
        button = m.group(0)
        if re.search(rf"(>|</span>){label}(<|$)", button):
            if re.search(r"\sdisabled(?=[\s>]|$)", button.split(">", 1)[0]):
                return None
            url = re.search(r'hx-get="([^"]+)"', button)
            return html.unescape(url.group(1)) if url else None
    return None


def walk(admin, r, label: str) -> tuple[list[list[str]], object]:
    """Follow a pagination button until it is disabled: the pages seen and the last response."""
    pages = [keys(r)]
    for _ in range(40):
        url = nav_button(r, label)
        if url is None:
            return pages, r
        r = admin.get(url, htmx=True)
        pages.append(keys(r))
    raise AssertionError("too many pages")


def test_simple_pagination_skips_the_count(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.paginated([10], mode="simple"))
    r = table(admin, "resource:products")
    assert 'data-tw-pagination="simple"' in r.text
    assert "results" not in r.text  # no total
    assert nav_button(r, "Previous") is None
    pages, last = walk(admin, r, "Next")
    assert all(len(p) == 10 for p in pages[:-1]) and 0 < len(pages[-1]) <= 10
    flat = [k for p in pages for k in p]
    assert len(flat) == len(set(flat)) == len(live_products(panel))
    back, _ = walk(admin, last, "Previous")
    assert back == list(reversed(pages))
    # a page past the end (rows were deleted) goes back to the first page
    assert keys(table(admin, "resource:products", page="999")) == pages[0]


@pytest.mark.parametrize("sort", [None, ("price", "desc"), ("category.name", "asc"), ("created_at", "desc")])
def test_cursor_pagination_walks_every_record_once(admin, monkeypatch, sort):
    params = {"sort": sort[0], "direction": sort[1]} if sort else {}
    # the same order as page-number paging
    with monkeypatch.context() as m:
        patch_table(m, ProductResource, lambda t: t.paginated([100]))
        expected = keys(table(admin, "resource:products", **params))
    patch_table(monkeypatch, ProductResource, lambda t: t.paginated([7], mode="cursor"))
    first = table(admin, "resource:products", **params)
    assert 'data-tw-pagination="cursor"' in first.text and "results" not in first.text
    assert nav_button(first, "Previous") is None
    forward, last = walk(admin, first, "Next")
    assert [k for p in forward for k in p] == expected
    assert all(len(p) == 7 for p in forward[:-1])
    back, _ = walk(admin, last, "Previous")
    assert back == list(reversed(forward))


def test_cursor_pagination_survives_a_bad_cursor(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.paginated([5], mode="cursor"))
    good = keys(table(admin, "resource:products"))
    assert keys(table(admin, "resource:products", cursor="not-a-cursor")) == good


def test_cursor_mode_falls_back_for_custom_sorts(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.paginated([5], mode="cursor").columns([
        TextColumn("name").sortable(query=lambda query, direction, model: query.order_by(model.name)),
    ]))
    r = table(admin, "resource:products", sort="name")
    assert 'data-tw-pagination="simple"' in r.text


def test_pagination_mode_is_checked():
    with pytest.raises(ValueError):
        Table().pagination_mode("infinite")
    assert Table().simple_pagination()._pagination_mode == "simple"
    assert Table().cursor_pagination()._pagination_mode == "cursor"


# ---------------------------------------------------------------------- card and stacked layouts
def test_content_grid_shows_cards(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.content_grid({"md": 2, "xl": 3}))
    r = table(admin, "resource:products")
    assert "data-tw-grid" in r.text
    assert "md:grid-cols-2 xl:grid-cols-3" in r.text
    assert "<table" not in r.text
    assert "Smart Watch" in r.text or len(re.findall(r'data-key="', r.text)) == 10


def test_stacked_on_mobile(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.stacked_on_mobile())
    r = table(admin, "resource:products")
    assert "data-tw-stacked" in r.text
    assert 'data-label="Product"' in r.text
    assert "max-md:before:content-[attr(data-label)]" in r.text
    plain = Table()
    assert plain._stacked_on_mobile is False


# ---------------------------------------------------------------------- column groups
def test_column_groups(admin, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.columns([
        TextColumn("name"),
        ColumnGroup("Pricing", [TextColumn("price"), TextColumn("stock")]).align_start(),
        TextColumn("sku"),
    ]))
    r = table(admin, "resource:products")
    assert re.search(r'<th colspan="2" class="[^"]*text-start[^"]*">Pricing</th>', r.text)
    t = Table().columns([TextColumn("a"), ColumnGroup("G", [TextColumn("b"), TextColumn("c")]), TextColumn("d")])
    assert [c.name for c in t._columns] == ["a", "b", "c", "d"]
    spans = [(g["group"].get_label() if g["group"] else None, g["span"]) for g in t.column_group_headers(t._columns)]
    assert spans == [(None, 1), ("G", 2), (None, 1)]
    assert Table().columns([TextColumn("a")]).column_group_headers([]) == []


# ---------------------------------------------------------------------- Range summary
def test_range_summary(admin, panel, monkeypatch):
    patch_table(monkeypatch, ProductResource, lambda t: t.columns([
        TextColumn("name"),
        TextColumn("price").summarize([Sum(), Range().money("₹", 0)]),
        TextColumn("stock_state").state(lambda record: record.stock).summarize(Range()),
    ]))
    r = table(admin, "resource:products")
    prices = [p.price for p in live_products(panel)]
    stocks = [p.stock for p in live_products(panel)]
    assert "Range:" in r.text
    assert f"₹{min(prices):,.0f}\u00a0– ₹{max(prices):,.0f}" in r.text
    assert f"{min(stocks):,}\u00a0– {max(stocks):,}" in r.text
    assert Range().format((3, 3)) == "3"
    assert Range().separator(" to ").format((1, 9)) == "1 to 9"
    assert Range().compute([4, None, 2, 9]) == (2, 9)
    assert Range().compute([None]) is None


def test_relation_sort_cursor_handles_empty_values(admin, panel, monkeypatch):
    # products without a category sort last (empty values) and are still reached by cursor
    with db_session(panel) as db:
        product = db.scalars(select(Product).where(Product.deleted_at.is_(None))).first()
        product.category_id = None
        db.commit()
        key = str(product.id)
        assert db.scalars(select(Category)).first() is not None
    patch_table(monkeypatch, ProductResource, lambda t: t.paginated([6], mode="cursor"))
    first = table(admin, "resource:products", sort="category.name", direction="asc")
    flat = [k for p in walk(admin, first, "Next")[0] for k in p]
    assert key in flat and len(flat) == len(set(flat)) == len(live_products(panel))
