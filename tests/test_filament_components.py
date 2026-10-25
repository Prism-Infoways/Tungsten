"""The last Filament components: Markdown and code editors, MorphToSelect, FusedGroup, the Icon,
Image and UnorderedList blocks, and the Split, Stack, Panel and Grid table layouts."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from examples.shop.models import Category, Post, Product
from tungsten.forms import (
    CodeEditor,
    Form,
    FusedGroup,
    ValidationError,
    Icon,
    Image,
    MarkdownEditor,
    MorphToSelect,
    MorphType,
    Text,
    TextInput,
    UnorderedList,
)
from tungsten.support.markdown import markdown_text, markdown_to_html
from tungsten.tables import Grid, Panel, Split, Stack, Table, TextColumn

from .conftest import db_session
from .test_forms_parity import again, make
from .test_panel import table


# ---------------------------------------------------------------------- markdown
def test_markdown_covers_the_everyday_subset():
    html = str(markdown_to_html(
        "# Title\n\nSome **bold**, *italic*, ~~old~~ and `code` with [a link](https://x.y/) and https://a.b/c.\n\n"
        "- one\n- two\n  - nested\n- three\n\n1. first\n2. second\n\n- [x] done\n- [ ] open\n\n> quoted\n\n"
        "```python\nprint('hi')\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\n<script>alert(1)</script>"))
    assert "<h1>Title</h1>" in html
    assert "<strong>bold</strong>" in html and "<em>italic</em>" in html and "<del>old</del>" in html
    assert "<code>code</code>" in html and '<a href="https://x.y/">a link</a>' in html
    assert '<a href="https://a.b/c">https://a.b/c</a>' in html
    assert "<li>two\n<ul>\n<li>nested</li>\n</ul></li>" in html  # nested list inside its item
    assert "<ol>\n<li>first</li>" in html
    assert "&#9745; done" in html or "☑ done" in html
    assert "<blockquote><p>quoted</p></blockquote>" in html
    assert "<pre><code>print(&#x27;hi&#x27;)</code></pre>" in html or "<pre><code>print(&#39;hi&#39;)</code></pre>" in html
    assert "<table><thead><tr><th>a</th><th>b</th></tr></thead>" in html and "<td>2</td>" in html
    assert "<hr>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert markdown_to_html(None) == "" and markdown_to_html("") == ""
    assert markdown_text("# Hi **there**") == "Hi there"


def test_markdown_editor_renders_toolbar_preview_and_saves_html():
    form = make([MarkdownEditor("body").toolbar_buttons(["bold", "link"]).html_column("body_html")],
                operation="edit", record=type("R", (), {"body": "Hello **you**", "body_html": None})())
    html = str(form.render())
    assert "data-tw-markdown-editor" in html and 'name="body"' in html
    assert html.count('@click="run(') == 2 and "run('bold')" in html and "run('image')" not in html
    assert "<strong>you</strong>" in html  # the preview is drawn on the server too

    class Rec:
        body = None
        body_html = None

    rec = Rec()
    f = Form().schema([MarkdownEditor("body").html_column("body_html")])
    f.bind(None, operation="edit", record=rec, refresh_url="/r")
    f.fill()
    f.get_schema()[0].fill_record(f, rec, {"body": "# Hi"})
    assert rec.body == "# Hi" and rec.body_html == "<h1>Hi</h1>"
    hidden = make([MarkdownEditor("body").toolbar_buttons([]).preview(False)])
    text = str(hidden.render())
    assert "run(" not in text and "Preview" not in text


def test_code_editor_json_mode():
    form = make([CodeEditor("settings").json()], operation="edit", record=type("R", (), {"settings": {"a": 1}})())
    html = str(form.render())
    assert "data-tw-code-editor" in html and ">json<" in html.lower() or "json" in html
    assert '{\n  &#34;a&#34;: 1\n}' in html  # pretty printed into the textarea
    bad = again(form, [("settings", "{not json")])
    with pytest.raises(ValidationError):
        bad.validate()
    assert any("valid JSON" in e for e in bad.errors.get("settings", []))
    good = again(form, [("settings", '{"b": [1, 2]}')])
    assert good.validate()["settings"] == {"b": [1, 2]}
    python = make([CodeEditor("script").language("python")])
    assert "indent: 4" in str(python.render())  # Tab is 4 spaces for Python


# ---------------------------------------------------------------------- blocks and FusedGroup
def test_icon_image_and_list_blocks():
    form = make([
        Icon("sparkles").color("warning").size("lg").tooltip("New"),
        Image("/media/map.png", "Office map").size("lg").circular().link("/big.png"),
        UnorderedList([Text("Fast").icon("zap"), "Simple"]).size("md"),
        UnorderedList(lambda: ["one", "two"]).ordered(),
    ])
    html = str(form.render())
    assert 'title="New"' in html and "h-6 w-6" in html and "text-warning" in html
    assert 'src="/media/map.png"' in html and 'alt="Office map"' in html and "rounded-full" in html and 'href="/big.png"' in html
    assert "list-disc" in html and "Fast" in html and "Simple" in html and "text-base" in html
    assert "list-decimal" in html and "<li><p" in html
    assert form.validate() == {}  # none of them hold a value


def test_fused_group_joins_fields_and_hides_their_labels():
    form = make([FusedGroup("Address").schema([
        TextInput("street").placeholder("Street"), TextInput("city").placeholder("City").required(),
    ]).columns(2).helper_text("Shown on invoices")])
    html = str(form.render())
    assert "data-tw-fused" in html and "--tw-fused-cols: 2" in html
    assert ">Address<" in html and "Shown on invoices" in html
    assert 'for="' not in html.split("data-tw-fused")[1]  # the children's own labels are hidden
    assert 'placeholder="Street"' in html
    failed = again(form, [("street", "x"), ("city", "")])
    with pytest.raises(ValidationError):
        failed.validate()
    assert "tw-fused-error" in str(failed.render())


# ---------------------------------------------------------------------- MorphToSelect
def test_morph_to_select_builds_two_selects():
    morph = MorphToSelect("featured").types([MorphType(Product).title("name"), MorphType(Category, key="cat").title("name")])
    type_select, record_select = morph.child_components()
    assert type_select.name == "featured_type" and record_select.name == "featured_id"
    assert type_select._options == {"Product": "Product", "cat": "Category"}
    assert morph.type_for("cat").model is Category and morph.type_for("nope") is None
    renamed = MorphToSelect("target").type_column("kind").id_column("ref").searchable()
    assert [c.name for c in renamed.child_components()] == ["kind", "ref"]
    assert renamed.child_components()[1]._searchable


def test_morph_to_select_follows_the_type_and_saves(admin, panel):
    r = admin.get("/admin/posts/create")
    assert 'name="featured_type"' in r.text and 'name="featured_id"' in r.text
    assert ">Product<" in r.text and ">Category<" in r.text
    # choosing a type reloads the form with that model's records
    r = admin.post("/admin/_tw/form", {"_tw_kind": "host", "_tw_host": "resource:posts", "_tw_op": "create",
                                       "featured_type": "Category", "_tw_live": "featured_type"}, htmx=True)
    assert r.status_code == 200
    with db_session(panel) as db:
        category = db.scalars(select(Category)).first()
    assert f'<option value="{category.id}"' in r.text and category.name in r.text
    assert ">Category<" in r.text.split('for="')[-1][:200] or "Category" in r.text
    r = admin.post("/admin/posts/create", {"title": "Morph", "slug": "morph", "status": "draft",
                                           "featured_type": "Category", "featured_id": str(category.id)})
    assert r.status_code == 204, r.text
    with db_session(panel) as db:
        post = db.scalars(select(Post).where(Post.slug == "morph")).one()
        assert post.featured_type == "Category" and post.featured_id == category.id


# ---------------------------------------------------------------------- table layouts
def test_layout_columns_flatten_for_search_and_render_as_cards(admin):
    t = Table().columns([
        Split([Stack([TextColumn("name").searchable(), TextColumn("email")]), TextColumn("status").grow(False)]),
        Panel([Grid([TextColumn("a"), TextColumn("b")]).columns({"md": 2, "xl": 4})]).collapsible(),
    ])
    assert t.has_layout()
    assert [c.name for c in t._columns] == ["name", "email", "status", "a", "b"]
    assert t.is_searchable()
    grid = Grid([TextColumn("x")]).columns(3)
    assert grid.grid_classes() == "grid-cols-1 md:grid-cols-3"
    assert Grid([TextColumn("x")]).columns({"md": 2, "xl": 4}).grid_classes() == "grid-cols-1 md:grid-cols-2 xl:grid-cols-4"

    r = table(admin, "resource:posts")
    assert 'data-tw-layout="split"' in r.text and 'data-tw-layout="stack"' in r.text and 'data-tw-layout="panel"' in r.text
    assert "data-tw-layout-cell" in r.text
    assert "Summer sale is coming" in r.text and "Kuldeep" in r.text
    assert not re.search(r"<th[^>]*>\s*<span class=\"whitespace-nowrap\">Title</span>", r.text)  # no column headers
    assert "max-lg:hidden" in r.text  # visible_from("lg")
    assert "blocks" in r.text
    # the inner columns still search
    r = table(admin, "resource:posts", search="summer")
    assert "Summer sale" in r.text and "Welcome to our store" not in r.text
