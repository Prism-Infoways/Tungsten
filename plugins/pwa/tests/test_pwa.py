from __future__ import annotations

import json
import re

import pytest
from conftest import login
from tungsten_pwa import PWAPlugin

from tungsten import Plugin


def sw_config(client, path="/admin") -> dict:
    text = client.get(f"{path}/_tw/pwa/sw.js").text
    return json.loads(re.match(r"self\.TW_PWA = (.*?);\n", text).group(1))


# ---------------------------------------------------------------------- manifest
def test_manifest_uses_the_panel_brand_and_colors(make):
    _, client = make(colors={"primary": "indigo"}, brand_tagline="Orders on the go")
    r = client.get("/admin/_tw/pwa/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    assert r.headers["cache-control"] == "no-cache"
    m = r.json()
    assert m["name"] == m["short_name"] == "Acme Admin"
    assert m["description"] == "Orders on the go"
    assert m["start_url"] == m["scope"] == m["id"] == "/admin/"
    assert m["display"] == "standalone"
    assert m["theme_color"] == "#6366f1"  # indigo 500
    assert {i["sizes"] for i in m["icons"]} == {"192x192", "512x512"}
    assert any(i["purpose"] == "maskable" for i in m["icons"])
    assert "shortcuts" not in m


def test_icons_are_served(make):
    _, client = make()
    for icon in client.get("/admin/_tw/pwa/manifest.webmanifest").json()["icons"]:
        r = client.get(icon["src"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_manifest_options(make):
    plugin = PWAPlugin(name="Acme", short_name="A", description="Hi", theme_color="#123456", background_color="#000",
                       display="fullscreen", start_path="orders",
                       icons=[{"src": "/static/i.png", "sizes": "512x512", "type": "image/png"}], categories=())
    _, client = make(plugin)
    m = client.get("/admin/_tw/pwa/manifest.webmanifest").json()
    assert (m["name"], m["short_name"], m["description"], m["theme_color"]) == ("Acme", "A", "Hi", "#123456")
    assert m["start_url"] == "/admin/orders" and m["display"] == "fullscreen"
    assert m["icons"] == [{"src": "/static/i.png", "sizes": "512x512", "type": "image/png"}]
    assert "categories" not in m


def test_bad_options_fail_early():
    with pytest.raises(ValueError):
        PWAPlugin(display="window")
    with pytest.raises(ValueError):
        PWAPlugin(icons=[{"sizes": "512x512"}])
    with pytest.raises(ValueError):
        PWAPlugin(theme_color="  ")


def test_odd_primary_color_falls_back_to_orange(make):
    panel, client = make()
    panel.colors["primary"] = {"x": "not a color"}
    assert client.get("/admin/_tw/pwa/manifest.webmanifest").json()["theme_color"] == "#f97316"


# ---------------------------------------------------------------------- shortcuts
class OrdersPlugin(Plugin):
    id = "orders"

    def pwa_shortcuts(self, panel):
        return [("New order", "orders/create"), {"name": "Today", "url": "orders?tab=today", "description": "Due"}]


class BrokenPlugin(Plugin):
    id = "broken"

    def pwa_shortcuts(self, panel):
        raise RuntimeError("boom")


def test_shortcuts_from_options_other_plugins_and_add_shortcut(make):
    pwa = PWAPlugin(shortcuts=[("Customers", "customers"), ("Customers again", "customers"), "bad", ("", "x")])
    panel, client = make(pwa)
    panel.plugin(OrdersPlugin())
    panel.plugin(BrokenPlugin())  # a failing plugin is skipped, not fatal
    panel.get_plugin("pwa").add_shortcut("Reports", "/reports/sales", icon="/static/r.png")
    shortcuts = client.get("/admin/_tw/pwa/manifest.webmanifest").json()["shortcuts"]
    assert [(s["name"], s["url"]) for s in shortcuts] == [
        ("Customers", "/admin/customers"), ("Reports", "/reports/sales"),
        ("New order", "/admin/orders/create"), ("Today", "/admin/orders?tab=today"),
    ]
    assert shortcuts[3]["description"] == "Due"
    assert shortcuts[1]["icons"] == [{"src": "/static/r.png", "sizes": "any"}]
    assert shortcuts[0]["icons"][0]["src"].endswith("/icon-192.png")


# ---------------------------------------------------------------------- service worker
def test_service_worker_headers_and_config(make):
    _, client = make()
    r = client.get("/admin/_tw/pwa/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["service-worker-allowed"] == "/admin/"
    assert r.headers["cache-control"] == "no-cache"
    config = sw_config(client)
    assert config["cachePrefix"] == "tungsten-pwa-admin-"
    assert config["offline"] == "/admin/_tw/pwa/offline"
    assert config["uninstall"] is False
    assert any(u.startswith("/admin/assets/tungsten.css?v=") for u in config["precache"])
    # only static files are saved for later, never pages
    assert all("/assets/" in u or "/plugins/" in u for u in config["precache"])


def test_new_settings_give_a_new_worker_version(make):
    _, a = make(PWAPlugin())
    _, b = make(PWAPlugin(offline_text="Back soon"))
    _, c = make(PWAPlugin())
    assert sw_config(a)["version"] != sw_config(b)["version"]
    assert sw_config(a)["version"] == sw_config(c)["version"]


def test_settings_cannot_break_out_of_the_script(make):
    _, client = make(PWAPlugin(precache=["/x</script><script>alert(1)</script>"]))
    text = client.get("/admin/_tw/pwa/sw.js").text
    assert "</script>" not in text.split("\n", 1)[0]


def test_each_panel_has_its_own_caches(make):
    _, admin = make(path="/admin", id="admin")
    _, portal = make(path="/portal", id="portal")
    assert sw_config(admin)["cachePrefix"] != sw_config(portal, "/portal")["cachePrefix"]


def test_panel_at_the_site_root(make):
    _, client = make(path="/")
    assert client.get("/_tw/pwa/sw.js").headers["service-worker-allowed"] == "/"
    m = client.get("/_tw/pwa/manifest.webmanifest").json()
    assert m["scope"] == m["start_url"] == "/"
    assert 'data-sw="/_tw/pwa/sw.js" data-scope="/"' in client.get("/login").text


# ---------------------------------------------------------------------- offline page
def test_offline_page_is_public_and_has_no_user_data(make):
    _, client = make()
    login(client)
    r = client.get("/admin/_tw/pwa/offline")
    assert r.status_code == 200
    assert r.headers["x-robots-tag"] == "noindex"
    assert "You are offline" in r.text and "Try again" in r.text and "Acme Admin" in r.text
    assert "Asha" not in r.text and "_token" not in r.text and "X-CSRF-Token" not in r.text


def test_routes_work_without_login(make):
    _, client = make()
    for url in ("/admin/_tw/pwa/manifest.webmanifest", "/admin/_tw/pwa/sw.js", "/admin/_tw/pwa/offline"):
        assert client.get(url, follow_redirects=False).status_code == 200


# ---------------------------------------------------------------------- page tags
def test_tags_on_login_and_panel_pages(make):
    _, client = make()
    page = client.get("/admin/login").text
    assert '<link rel="manifest" href="/admin/_tw/pwa/manifest.webmanifest">' in page
    assert '<meta name="theme-color" content="#f97316">' in page
    assert 'rel="apple-touch-icon"' in page
    assert re.search(r'src="/admin/plugins/pwa/pwa\.js\?v=\w+"', page)
    login(client)
    page = client.get("/admin/").text
    assert "data-tw-pwa-install" in page and 'id="tw-pwa-offline"' in page


def test_login_and_csrf_still_work(make):
    _, client = make()
    login(client)
    assert client.get("/admin/", follow_redirects=False).status_code == 200


def test_button_and_bar_can_be_turned_off(make):
    _, client = make(PWAPlugin(install_button=False, offline_banner=False))
    login(client)
    page = client.get("/admin/").text
    assert "data-tw-pwa-install" not in page and "tw-pwa-offline" not in page
    assert 'rel="manifest"' in page


def test_uninstall_removes_the_app(make):
    _, client = make(PWAPlugin(uninstall=True))
    assert 'rel="manifest"' not in client.get("/admin/login").text
    assert client.get("/admin/_tw/pwa/manifest.webmanifest").status_code == 404
    config = sw_config(client)
    assert config["uninstall"] is True and config["precache"] == []
