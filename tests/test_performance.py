"""Lightweight pages: compression, long-lived asset caching and on-demand libraries."""

import json
import re

from tungsten.panel import VENDOR_FILES, asset_version


def test_pages_are_gzipped(admin):
    r = admin.get("/admin/products", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"


def test_assets_cached_with_content_hash(admin):
    html = admin.get("/admin/").text
    url = re.search(r'src="([^"]*tungsten\.js\?v=([0-9a-f]+))"', html)
    assert url and url.group(2) == asset_version("tungsten.js")
    r = admin.client.get(url.group(1))
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]


def test_big_libraries_load_on_demand(admin):
    html = admin.get("/admin/").text
    head = html.split("</head>")[0]
    for name in ("chart.umd.min.js", "trix.umd.min.js", "tom-select.complete.min.js", "sortable.min.js", "qrcode.js"):
        assert f"<script defer src=\"/admin/assets/vendor/{name}" not in head
    attr = re.search(r"data-tw-vendor='([^']+)'", head).group(1)
    vendor = json.loads(attr.replace("&#34;", '"').replace("&quot;", '"'))
    assert set(vendor) == set(VENDOR_FILES)
    for url in vendor.values():
        assert admin.client.get(url).status_code == 200


# ---------------------------------------------------------------- fewer queries, cheaper rendering
from contextlib import contextmanager  # noqa: E402

from markupsafe import Markup  # noqa: E402
from sqlalchemy import event  # noqa: E402


@contextmanager
def count_queries(panel):
    engine = panel._engine()
    engine = getattr(engine, "sync_engine", engine)
    seen: list[str] = []

    def listener(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", listener)


def test_state_column_named_after_a_relationship_is_eager_loaded(admin, panel):
    # the orders table has TextColumn("items").state(lambda record: sum(i.quantity for i in record.items))
    with count_queries(panel) as seen:
        r = admin.get("/admin/orders")
    assert r.status_code == 200
    item_loads = [s for s in seen if "FROM order_items" in s]
    assert len(item_loads) == 1, item_loads  # one IN (...) query, not one per row


def test_user_roles_are_read_once_per_request(admin, panel):
    with count_queries(panel) as seen:
        assert admin.get("/admin/products").status_code == 200
    assert len([s for s in seen if "FROM tungsten_roles" in s]) == 1


def test_footer_summaries_share_one_query(admin, panel):
    # the products table sums price and stock
    with count_queries(panel) as seen:
        assert admin.get("/admin/products").status_code == 200
    sums = [s for s in seen if s.lstrip().upper().startswith("SELECT SUM(")]
    assert len(sums) == 1, sums
    html = admin.get("/admin/products").text
    assert html.count("Sum:") >= 2


def _text_cell(**over):
    v = dict(entries=[{"text": "Hello", "full": None, "color": None, "icon": None, "prefix": None, "suffix": None}],
             more=0, badge=False, icon_position="before", icon_color=None, weight="", size="text-sm", mono=False,
             copyable=False, as_list=False, url=None, new_tab=False, avatar=None, avatar_circular=True,
             description=None, description_position="below", tooltip=None, align="", justify="", classes="",
             placeholder=None)
    v.update(over)
    return v


def test_plain_text_cells_match_the_template_exactly():
    import itertools

    from tungsten.rendering import Renderer
    from tungsten.tables.columns import _is_plain_text, _plain_text_cell

    renderer = Renderer()
    entry = {"text": "<b>A&B</b>", "full": "Full \"title\"", "color": "danger", "icon": None, "prefix": "$<",
             "suffix": "!"}
    plain = {"text": Markup("<i>ok</i>"), "full": None, "color": None, "icon": None, "prefix": None, "suffix": None}
    options = {
        "entries": [[], [plain], [entry, plain, {**plain, "text": 42}]],
        "url": [None, "/x?a=1&b=<2>"],
        "new_tab": [False, True],
        "description": [None, "D<>"],
        "description_position": ["below", "above", "inline"],
        "tooltip": [None, 'T"q'],
        "placeholder": [None, "-", 0],
        "more": [0, 3],
        "mono": [False, True],
    }
    keys = list(options)
    for values in itertools.product(*options.values()):
        v = _text_cell(**dict(zip(keys, values)))
        assert _is_plain_text(v)
        assert str(_plain_text_cell(v)) == str(renderer.render("tungsten/tables/columns/text.html", v=v))


def test_cells_with_badges_icons_or_avatars_still_use_the_template():
    from tungsten.tables.columns import _is_plain_text

    icon_entry = {"text": "A", "full": None, "color": None, "icon": "check", "prefix": None, "suffix": None}
    for over in ({"badge": True}, {"copyable": True}, {"as_list": True}, {"avatar": {"url": None, "name": "A"}},
                 {"entries": [icon_entry]}):
        assert not _is_plain_text(_text_cell(**over))


def test_overridden_text_cell_template_is_still_used(tmp_path):
    from types import SimpleNamespace

    from tungsten.rendering import Renderer
    from tungsten.tables.columns import TextColumn

    renderer = Renderer()
    table = SimpleNamespace(renderer=renderer, ev=lambda: {}, ctx=None)
    assert "Hello" in TextColumn("name").render_cell(table, SimpleNamespace(name="Hello"))
    override = tmp_path / "tungsten" / "tables" / "columns"
    override.mkdir(parents=True)
    (override / "text.html").write_text("<em>{{ v.state }}</em>")
    renderer.add_dir(tmp_path)
    assert str(TextColumn("name").render_cell(table, SimpleNamespace(name="Hello"))) == "<em>Hello</em>"


def test_icons_are_cached_but_still_correct():
    from tungsten.support.icons import icon

    a = icon("check", "h-4 w-4")
    assert a is icon("check", "h-4 w-4")
    assert 'class="h-4 w-4"' in a and icon("check", "h-5 w-5") != a
    assert icon(None) == "" and icon("<svg>x</svg>") == "<svg>x</svg>"


def test_theme_css_follows_color_changes(panel):
    before = panel.theme_css()
    assert panel.theme_css() is before
    panel.colors["primary"] = "#ff0000"
    after = panel.theme_css()
    assert after != before and "255 0 0" in after


def test_counts_column_counts_the_page_in_one_query(admin, panel):
    import re

    from sqlalchemy import func, select

    from examples.shop.models import Customer, Order

    with count_queries(panel) as seen:
        html = admin.get("/admin/customers").text
    assert not [s for s in seen if "FROM orders WHERE" in s and "count" not in s.lower()]  # no per-row loads
    assert len([s for s in seen if "JOIN orders" in s]) == 1
    db = panel.sync_session_factory()
    try:
        expected = dict(db.execute(select(Customer.name, func.count(Order.id)).outerjoin(Order, Order.customer_id == Customer.id)
                                   .group_by(Customer.id)).all())
    finally:
        db.close()
    shown = [name for name in expected if name in html]
    assert shown
    for name in shown:  # each visible customer's row carries its own order count
        row = html.split(name, 1)[1].split("</tr>", 1)[0]
        assert re.search(rf">\s*{expected[name]}</span>", row), (name, expected[name])


def test_counts_column_works_for_many_to_many_and_outside_a_table():
    from types import SimpleNamespace

    from tungsten.tables.columns import TextColumn

    record = SimpleNamespace(tags=["a", "b", "c"])
    assert TextColumn("tags_count").counts("tags").get_state(record, {}) == 3


def test_counts_column_in_a_bound_table_with_many_to_many(panel):
    from types import SimpleNamespace

    from sqlalchemy import select

    from examples.shop.models import Product
    from tungsten.tables import Table
    from tungsten.tables.columns import TextColumn

    def run(db):
        products = list(db.scalars(select(Product).limit(5)))
        table = Table().columns([TextColumn("tags_count").counts("tags")])
        table.ctx = SimpleNamespace(db=db, user=None, tenant=None, request=None)
        table.model = Product
        table._page_records = products
        column = table._columns[0]
        return [(column.get_state(p, {"table": table}), len(p.tags)) for p in products]

    pairs = panel.with_session(run)
    assert pairs and all(counted == loaded for counted, loaded in pairs)
