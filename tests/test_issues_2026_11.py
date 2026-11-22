"""Issues #131-#145 (November 2026)."""

from __future__ import annotations

import re

from tungsten.i18n import lower_label


# ---------------------------------------------------------------------- #144 "Edit MCP prompt"
def test_lower_label_keeps_short_forms():
    assert lower_label("MCP prompt") == "MCP prompt"
    assert lower_label("Blog Post") == "blog post"
    assert lower_label("API key for URL") == "API key for URL"
    assert lower_label("Order") == "order"


# ---------------------------------------------------------------------- #134 SPA links inside a box
def test_link_buttons_and_cancel_say_where_they_go(admin):
    html = admin.get("/admin/posts/1/edit").text
    cancels = re.findall(r'<a href="[^"]*"[^>]*>Cancel</a>', html)
    assert cancels and all('hx-target="body"' in a for a in cancels)


def test_boost_guard_in_script():
    from pathlib import Path

    import tungsten

    js = (Path(tungsten.__file__).parent / "static" / "tungsten" / "tungsten.js").read_text()
    assert 'd.target = document.body' in js and "twTrapFocus" in js and "data-max-size" in js


# ---------------------------------------------------------------------- #142 #143 layout bits
def test_layout_bits(admin):
    html = admin.get("/admin/").text
    assert 'class="flex min-h-screen flex-col' in html          # footer at the bottom
    assert "max-sm:fixed" in html                                # bell panel stays on a phone screen
    assert "xl:block" in html                                     # user name only where it fits


def test_breadcrumb_last_crumb_is_cut(admin):
    html = admin.get("/admin/posts/1/edit").text
    nav = re.search(r'<nav class="mb-2 flex min-w-0[^"]*" aria-label="Breadcrumb">(.*?)</nav>', html, re.S).group(1)
    assert "shrink-0 whitespace-nowrap" in nav and "min-w-0 truncate" in nav


def test_dashboard_item_lit_at_home(admin):
    html = admin.get("/admin/").text
    assert re.search(r'class="tw-nav-item flex-1 tw-nav-item-active"', html)


# ---------------------------------------------------------------------- #136 #141 upload field
def test_upload_field_renders_limit_and_one_hint():
    from tungsten.forms.fields import FileUpload, file_size_label

    assert file_size_label(500) == "1 KB" and file_size_label(5 * 1024 * 1024) == "5 MB"
    field = FileUpload("doc").max_size(1024)
    assert field.too_big_message() == '"{name}" is {size}. The biggest file you can upload here is 1 MB.'
