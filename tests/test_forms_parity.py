"""Filament parity for forms: actions in forms, content blocks, Flex, Slider, masks,
timezones, tabs in the URL, Select create/edit forms, ModalTableSelect and the
rich editor (toolbar, attachments, mentions, blocks)."""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from decimal import Decimal

import pytest
from markupsafe import Markup
from sqlalchemy import select
from starlette.datastructures import FormData

from tungsten.actions import Action
from tungsten.forms import (
    Actions,
    Block,
    Callout,
    DatePicker,
    DateTimePicker,
    Flex,
    Form,
    Html,
    MentionProvider,
    ModalTableSelect,
    Repeater,
    RichEditor,
    Section,
    Slider,
    Split,
    Tab,
    Tabs,
    Text,
    Textarea,
    TextInput,
    ValidationError,
    ViewField,
    mentions_in,
    render_rich_content,
)
from tungsten.support.html import BLOCK_TYPE, MENTION_TYPE, sanitize

from .conftest import db_session


def make(schema, operation="create", record=None):
    form = Form().schema(schema)
    form.bind(None, operation=operation, record=record, refresh_url="/refresh")
    form.fill()
    return form


def again(form, pairs, action=None):
    """A new request: the same schema, loaded from ``pairs`` (and a UI action run)."""
    fresh = Form().schema(form.get_schema())
    fresh.bind(None, refresh_url="/refresh")
    fresh.load(FormData(pairs))
    if action:
        fresh.handle_ui_action(action)
    return fresh


# ---------------------------------------------------------------------- actions in forms
def slug_form():
    return [
        TextInput("title"),
        TextInput("slug")
        .suffix_action(Action("generate").icon("refresh-cw")
                       .action(lambda get, set: set("slug", get("title").lower().replace(" ", "-"))))
        .hint_action(Action("rename").form([Textarea("text").required()])
                     .fill_form(lambda get: {"text": get("title")})
                     .action(lambda data, set: set("title", data["text"]))),
    ]


def test_suffix_action_runs_at_once_and_sets_state():
    form = again(make(slug_form()), [("title", "Hello World"), ("slug", "")], "faction.call:slug:generate")
    assert form.get("slug") == "hello-world"
    html_ = form.render()
    assert "faction.call:slug:generate" in html_ and "faction.call:slug:rename" in html_


def test_action_modal_opens_validates_and_submits():
    form = again(make(slug_form()), [("title", "Old"), ("slug", "")], "faction.call:slug:rename")
    assert form.ui["_modal"] == "slug:rename"
    out = form.render()
    assert 'name="__modal.text"' in out and 'name="_tw_ui._modal" value="slug:rename"' in out
    assert form.modal.sub.get("__modal.text") == "Old"  # fill_form

    bad = again(form, [("title", "Old"), ("_tw_ui._modal", "slug:rename"), ("__modal.text", "")], "faction.submit::")
    assert bad.modal.sub.errors == {"__modal.text": ["The text field is required."]}
    assert "The text field is required." in bad.render()

    ok = again(form, [("title", "Old"), ("_tw_ui._modal", "slug:rename"), ("__modal.text", "New")], "faction.submit::")
    assert ok.get("title") == "New" and ok.modal is None and "_modal" not in ok.render()

    closed = again(form, [("title", "Old"), ("_tw_ui._modal", "slug:rename")], "faction.close::")
    assert closed.modal is None and closed.get("title") == "Old"


def test_form_actions_respect_visibility_and_read_only_forms():
    schema = [TextInput("a").suffix_action(Action("x").visible(False).action(lambda set: set("a", "nope")))]
    form = again(make(schema), [("a", "1")], "faction.call:a:x")
    assert form.get("a") == "1" and "faction.call:a:x" not in form.render()
    view = make([TextInput("a").suffix_action(Action("x").action(lambda set: set("a", "z")))], operation="view")
    assert "faction.call" not in view.render()
    # a field in a hidden section can't run its actions
    schema = [Section("S").visible(lambda get: get("show") == "1")
              .schema([TextInput("a").suffix_action(Action("x").action(lambda set: set("a", "hit")))]), TextInput("show")]
    assert again(make(schema), [("show", "0"), ("a", "")], "faction.call:a:x").get("a") == ""
    assert again(make(schema), [("show", "1"), ("a", "")], "faction.call:a:x").get("a") == "hit"
    # a link action still shows on a read-only form
    view = make([TextInput("a").hint_action(Action("docs").url("https://example.com"))], operation="view")
    assert 'href="https://example.com"' in view.render()


def test_actions_component_and_repeater_rows():
    schema = [
        Repeater("lines").schema([
            TextInput("qty"),
            Actions([Action("double").action(lambda get, set: set("qty", str(int(get("qty")) * 2)))]),
        ]).default_items(1),
    ]
    form = make(schema)
    out = form.render()
    assert "faction.call:lines.0._actions0:double" in out
    form = again(form, [("lines.0.qty", "4")], "faction.call:lines.0._actions0:double")
    assert form.get("lines.0.qty") == "8"
    assert submit(form, [("lines.0.qty", "3")]) == {"lines": [{"qty": "3"}]}  # Actions saves nothing


def submit(form, pairs):
    fresh = Form().schema(form.get_schema())
    fresh.bind(None, refresh_url="/refresh")
    fresh.load(FormData(pairs))
    return fresh.validate()


# ---------------------------------------------------------------------- content blocks and Flex
def test_text_html_callout_and_flex_render_and_save_nothing():
    form = make([
        Text("Prices include GST.").color("warning").weight("bold"),
        Html("<b>Bold</b><script>alert(1)</script>"),
        Html(Markup("<em>trusted</em>")),
        Callout("Stock is low").description("Only 3 left.").color("danger")
        .actions([Action("restock").action(lambda set: set("stock", "10"))]),
        Flex([Section("Main").schema([TextInput("name")]), Section("Side").schema([TextInput("stock")]).grow(False)]),
    ])
    out = form.render()
    assert "Prices include GST." in out and "font-bold" in out
    assert "<b>Bold</b>" in out and "<script>" not in out and "<em>trusted</em>" in out
    assert "Stock is low" in out and "Only 3 left." in out and "faction.call:_callout0:restock" in out
    assert "md:flex-row" in out and "min-w-0 shrink-0" in out
    assert submit(form, [("name", "x"), ("stock", "2")]) == {"name": "x", "stock": "2"}
    assert Split is Flex


def test_view_field_uses_its_own_template(tmp_path):
    from jinja2 import DictLoader

    from tungsten.rendering import default_renderer

    renderer = default_renderer()
    renderer.env.loader.loaders.insert(0, DictLoader({"my/stars.html": (
        '{% from "tungsten/forms/macros.html" import wrapper %}{% call wrapper(field, v) %}'
        '<input name="{{ v.path }}" value="{{ v.state }}" data-max="{{ v.max }}">{% endcall %}')}))
    try:
        form = make([ViewField("rating").view("my/stars.html", {"max": 5}).default(3).required()])
        out = form.render()
        assert 'name="rating" value="3" data-max="5"' in out
        assert submit(form, [("rating", "4")]) == {"rating": "4"}
    finally:
        renderer.env.loader.loaders.pop(0)


# ---------------------------------------------------------------------- slider, mask, timezone
def test_slider_casts_validates_and_renders():
    form = make([Slider("discount").range(0, 50).step(5).suffix("%").pips(25), Slider("price").range(10, 90).dual()])
    assert form.get("discount") == "0" and form.get("price") == ["10", "90"]
    out = form.render()
    assert 'type="range"' in out and 'step="5"' in out and out.count('name="price"') == 2
    data = submit(form, [("discount", "15"), ("price", "70"), ("price", "20")])
    assert data == {"discount": 15, "price": [20, 70]}
    with pytest.raises(ValidationError) as exc:
        submit(form, [("discount", "17"), ("price", "5"), ("price", "20")])
    assert "discount" in exc.value.errors and "at least 10" in exc.value.errors["price"][0]


def test_masks_render_and_strip():
    form = make([
        TextInput("phone").mask("99999-99999").strip_characters("-"),
        TextInput("amount").money_mask(prefix="₹", indian=True),
        TextInput("euro").money_mask(thousands=".", decimal=","),
    ])
    out = form.render()
    assert 'data-tw-mask="&#34;99999-99999&#34;"' in out and '&#34;indian&#34;: true' in out
    data = submit(form, [("phone", "98765-43210"), ("amount", "₹1,23,456.50"), ("euro", "1.234,5")])
    assert data == {"phone": "9876543210", "amount": Decimal("123456.50"), "euro": Decimal("1234.5")}


def test_datetime_timezone_round_trip():
    class Rec:
        starts_at = dt.datetime(2026, 1, 1, 6, 30)  # stored in UTC

    field = DateTimePicker("starts_at").timezone("Asia/Kolkata")
    form = make([field], operation="edit", record=Rec())
    assert form.get("starts_at") == "2026-01-01T12:00"
    assert "Asia/Kolkata" in form.render()
    assert submit(form, [("starts_at", "2026-01-01T12:00")]) == {"starts_at": dt.datetime(2026, 1, 1, 6, 30)}
    # a plain date picker ignores the timezone
    assert submit(make([DatePicker("d").timezone("Asia/Kolkata")]), [("d", "2026-01-01")]) == {"d": dt.date(2026, 1, 1)}


def test_tabs_open_tab_and_url_persistence():
    tabs = Tabs().persist_tab_in_query_string().persist_tab().active_tab(2).tabs([
        Tab("General").schema([TextInput("a")]), Tab("Media Files").schema([TextInput("b")]),
    ])
    out = make([tabs]).render()
    assert "tab: '1'" in out  # active_tab(2) is the second tab
    assert "searchParams.set(&#39;tab&#39;" in out or "searchParams.set('tab'" in out
    assert "media-files" in html.unescape(out) and "localStorage" in out


# ---------------------------------------------------------------------- rich editor
def test_rich_editor_toolbar_and_options():
    editor = (RichEditor("body").toolbar_buttons(["bold", "underline", "h2", "link", "attachFiles", "undo"])
              .mentions({1: "Asha", 2: "Ravi"})
              .blocks([Block("cta").label("Call to action").schema([TextInput("text")])]))
    out = make([editor]).render()
    assert 'data-trix-attribute="underline"' in out and 'data-trix-attribute="heading2"' in out
    assert 'data-trix-attribute="italic"' not in out
    assert "trix-button--icon-attach" not in out  # no attachments without ctx/file_attachments
    assert "data-tw-mentions" in out and "Asha" in html.unescape(out)
    with pytest.raises(ValueError):
        RichEditor("x").toolbar_buttons(["sparkles"])
    assert "data-trix-attribute" not in make([RichEditor("b").disable_all_toolbar_buttons()]).render()


def mention_html(ident="5", label="Dan"):
    data = {"contentType": MENTION_TYPE, "mentionId": ident, "mentionLabel": label, "mentionTrigger": "@",
            "content": "<img src=x onerror=alert(1)>"}
    return (f'<p>Hi <figure data-trix-attachment="{html.escape(json.dumps(data))}" '
            f'data-trix-content-type="{MENTION_TYPE}" class="attachment attachment--content" onclick="x">'
            f'<span class="tw-mention">@{label}</span></figure></p>')


def test_mentions_are_kept_safely_and_found():
    clean = RichEditor("b").clean(mention_html(label="Dan<b>"))
    assert "onerror" not in clean and "onclick" not in clean
    data = json.loads(html.unescape(re.search(r'data-trix-attachment="([^"]+)"', clean).group(1)))
    assert data["content"] == '<span class="tw-mention">@Dan&lt;b&gt;</span>'
    assert mentions_in(clean) == [{"trigger": "@", "id": "5", "label": "Dan<b>"}]
    # other fields keep stripping the attachment data
    assert "data-trix-attachment" not in sanitize(mention_html())
    out = render_rich_content(clean, mentions=[MentionProvider("@").url(lambda id: f"/users/{id}")])
    assert '<a href="/users/5" class="tw-mention" data-mention="5">@Dan&lt;b&gt;</a>' in out


def test_mention_search_on_the_server():
    editor = RichEditor("b").mentions(MentionProvider("#").search_using(lambda search: {"t1": f"Topic {search}"}))
    form = make([editor])
    assert editor.search_options(form, "#ab") == [("t1", "Topic ab")]
    assert editor.search_options(form, "@ab") == []


def test_blocks_insert_through_a_modal_and_render():
    cta = (Block("cta").label("Call to action").schema([TextInput("text").required(), TextInput("url")])
           .render_using(lambda config: Markup('<a class="btn" href="{}">{}</a>').format(config["url"], config["text"])))
    schema = [RichEditor("body").blocks([cta])]
    form = again(make(schema), [("body", "<p>Hi</p>"), ("_tw_ui.body.cursor", "2")], "faction.call:body:block_cta")
    assert form.ui["_modal"] == "body:block_cta" and 'name="__modal.text"' in form.render()
    done = again(form, [("body", "<p>Hi</p>"), ("_tw_ui.body.cursor", "2"), ("_tw_ui._modal", "body:block_cta"),
                        ("__modal.text", "Buy"), ("__modal.url", "/shop")], "faction.submit::")
    out = html.unescape(done.render())
    insert = json.loads(re.search(r"data-tw-insert=\"(\{.*?\})\"", out).group(1))
    assert insert["pos"] == 2 and insert["replace"] is False
    assert insert["attachment"]["blockConfig"] == {"text": "Buy", "url": "/shop"}

    stored = (f'<p>Hi</p><figure data-trix-attachment="{html.escape(json.dumps(insert["attachment"]))}" '
              f'data-trix-content-type="{BLOCK_TYPE}"><span class="tw-block">x</span></figure>')
    value = submit(make(schema), [("body", stored)])["body"]
    assert "blockConfig" in html.unescape(value)
    assert render_rich_content(value, editor=schema[0]) == '<p>Hi</p><a class="btn" href="/shop">Buy</a>'

    # editing an existing block opens its form filled with the block's settings
    edit = json.dumps({"id": "cta", "config": {"text": "Buy", "url": "/shop"}, "pos": 1})
    opened = again(form, [("body", value), ("_tw_ui.body.edit", edit)], "faction.call:body:block_cta")
    assert opened.modal.sub.get("__modal.text") == "Buy"


# ---------------------------------------------------------------------- in the panel
BASE = {"_tw_kind": "host", "_tw_host": "resource:products", "_tw_op": "create"}


def test_select_create_option_form_saves_and_selects(admin, panel):
    r = admin.post("/admin/_tw/form", {**BASE, "_tw_ui_action": "faction.call:brand_id:create_option"})
    assert r.status_code == 200 and 'name="__modal.name"' in r.text and "Create brand" in r.text
    r = admin.post("/admin/_tw/form", {**BASE, "_tw_ui._modal": "brand_id:create_option", "__modal.name": "Acme New",
                                       "__modal.website": "https://acme.test", "_tw_ui_action": "faction.submit::"})
    with db_session(panel) as db:
        from examples.shop.models import Brand

        brand = db.scalars(select(Brand).where(Brand.name == "Acme New")).one()
        assert brand.website == "https://acme.test"
    assert re.search(rf'<option value="{brand.id}" selected', r.text)
    assert "__modal" not in r.text
    # unique is checked against the brands table
    r = admin.post("/admin/_tw/form", {**BASE, "_tw_ui._modal": "brand_id:create_option", "__modal.name": "Acme New",
                                       "_tw_ui_action": "faction.submit::"})
    assert "has already been taken" in r.text and 'name="__modal.name"' in r.text


def test_select_edit_option_form_changes_the_selected_record(admin, panel):
    from examples.shop.models import Brand

    with db_session(panel) as db:
        brand = db.scalars(select(Brand)).first()
        brand_id, old = brand.id, brand.name
    data = {**BASE, "brand_id": str(brand_id)}
    r = admin.post("/admin/_tw/form", {**data, "_tw_ui_action": "faction.call:brand_id:edit_option"})
    assert f'value="{html.escape(old)}"' in r.text
    admin.post("/admin/_tw/form", {**data, "_tw_ui._modal": "brand_id:edit_option", "__modal.name": "Renamed Co",
                                   "_tw_ui_action": "faction.submit::"})
    with db_session(panel) as db:
        assert db.get(Brand, brand_id).name == "Renamed Co"
    # no edit button without a selected brand
    r = admin.post("/admin/_tw/form", {**BASE, "_tw_ui_action": "faction.call:brand_id:edit_option"})
    assert "__modal" not in r.text


def test_suffix_action_in_the_panel(admin):
    r = admin.post("/admin/_tw/form", {**BASE, "name": "Linen Shirt", "_tw_ui_action": "faction.call:sku:generate_sku"})
    assert re.search(r'name="sku" value="LIN-SHI-\d{4}"', r.text)


def test_rich_editor_attachment_upload(admin, panel):
    data = {**BASE, "_tw_field": "description"}
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    r = admin.client.post("/admin/_tw/form/attachment", data=data, files={"file": ("a.png", png, "image/png")},
                          headers={"X-CSRF-Token": admin.token, "HX-Request": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"].startswith("products/content/") and body["url"].endswith(body["path"])
    r = admin.client.post("/admin/_tw/form/attachment", data=data, files={"file": ("a.txt", b"hi", "text/plain")},
                          headers={"X-CSRF-Token": admin.token, "HX-Request": "true"})
    assert r.status_code == 422 and "not allowed" in r.json()["error"]
    r = admin.client.post("/admin/_tw/form/attachment", data={**BASE, "_tw_field": "name"},
                          files={"file": ("a.png", png, "image/png")},
                          headers={"X-CSRF-Token": admin.token, "HX-Request": "true"})
    assert r.status_code in (204, 404)  # not found (htmx requests get an empty reply)


def test_modal_table_select_in_the_panel(admin, panel, monkeypatch):
    from examples.shop.models import Brand
    from examples.shop.resources import ProductResource

    monkeypatch.setattr(ProductResource, "form", classmethod(lambda cls, form: form.schema([
        ModalTableSelect("brand_id").relationship("brand", "name").table_columns(["name", "website"]).per_page(2),
    ])))
    with db_session(panel) as db:
        brands = db.scalars(select(Brand).order_by(Brand.name)).all()
    r = admin.post("/admin/_tw/form", {**BASE, "_tw_ui_action": "faction.call:brand_id:select_records"})
    assert "<th class=\"px-3 py-2 text-start\">Website</th>" in r.text
    assert f'value="{brands[0].id}"' in r.text and f'value="{brands[2].id}"' not in r.text
    # page 2 and a search
    r = admin.post("/admin/_tw/form", {**BASE, "_tw_ui._modal": "brand_id:select_records",
                                       "_tw_ui_action": "picker.page:__modal.pick:2"})
    assert f'value="{brands[2].id}"' in r.text
    r = admin.post("/admin/_tw/form", {**BASE, "_tw_ui._modal": "brand_id:select_records",
                                       "_tw_ui.__modal.pick.q": brands[1].name})
    assert f'value="{brands[1].id}"' in r.text and f'value="{brands[0].id}"' not in r.text
    # pick one
    r = admin.post("/admin/_tw/form", {**BASE, "_tw_ui._modal": "brand_id:select_records",
                                       "__modal.pick": str(brands[1].id), "_tw_ui_action": "faction.submit::"})
    assert f'name="brand_id" value="{brands[1].id}"' in r.text and html.escape(brands[1].name) in r.text
    # a made-up key is refused when saving
    r = admin.post("/admin/products/create", {"brand_id": "99999"})
    assert "The selected brand is invalid." in r.text
