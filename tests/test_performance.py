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
