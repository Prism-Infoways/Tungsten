"""Tests for async engines, the query builder, email verification and translations."""

from __future__ import annotations

from sqlalchemy import select

from examples.shop.models import Product

from .conftest import db_session
from .test_panel import table


def qb(**rules):
    """Turn {"0.0.c": "price", ...} into query builder params."""
    return {f"filters.query.g.{k}": v for k, v in rules.items()}


def names(panel, query):
    with db_session(panel) as db:
        return sorted(p.name for p in db.scalars(query))


def test_query_builder_rules(admin, panel):
    r = table(admin, "resource:products", _f="1", per_page="100", **qb(**{
        "0.0.c": "price", "0.0.op": "gt", "0.0.v": "3000",
        "0.1.c": "name", "0.1.op": "contains", "0.1.v": "a",
    }))
    assert r.status_code == 200
    expected = names(panel, select(Product).where(Product.price > 3000, Product.name.ilike("%a%"),
                                                  Product.deleted_at.is_(None)))
    assert expected and all(n in r.text for n in expected)
    assert f'of <span class="font-medium">{len(expected)}</span> results' in r.text
    assert "Price is greater than 3000" in r.text and "Name contains “a”" in r.text
    assert "filters.query.g.0.1.v=a" in r.headers["HX-Replace-Url"]


def test_query_builder_or_groups_and_relationships(admin, panel):
    r = table(admin, "resource:products", _f="1", per_page="100", **qb(**{
        "0.0.c": "stock", "0.0.op": "lt", "0.0.v": "10",
        "1.0.c": "is_featured", "1.0.op": "true",
        "2.0.c": "tags", "2.0.op": "count_gte", "2.0.v": "2",
    }))
    with db_session(panel) as db:
        expected = sorted(p.name for p in db.scalars(select(Product).where(Product.deleted_at.is_(None)))
                          if p.stock < 10 or p.is_featured or len(p.tags) >= 2)
    assert f'of <span class="font-medium">{len(expected)}</span> results' in r.text
    assert "or Featured is true" in r.text


def test_query_builder_incomplete_rules_are_ignored(admin, panel):
    r = table(admin, "resource:products", _f="1", **qb(**{"0.0.c": "price", "0.0.op": "between", "0.0.v": "100"}))
    with db_session(panel) as db:
        total = len(db.scalars(select(Product).where(Product.deleted_at.is_(None))).all())
    assert f'of <span class="font-medium">{total}</span> results' in r.text
    assert 'title="Not applied yet"' in r.text


def test_query_builder_buttons(admin):
    r = table(admin, "resource:products", _f="1", _qb="add:query:new:price")
    assert 'name="filters.query.g.0.0.c" value="price"' in r.text
    assert "filters.query.g.0.0.op=eq" in r.headers["HX-Replace-Url"]
    r = table(admin, "resource:products", _f="1", _qb="add:query:0:tags", **qb(**{"0.0.c": "price", "0.0.op": "eq"}))
    assert 'name="filters.query.g.0.1.c" value="tags"' in r.text
    r = table(admin, "resource:products", _f="1", _qb="remove:query:0:0", **qb(**{"0.0.c": "price", "0.0.op": "eq"}))
    assert "filters.query.g.0" not in r.text


# ---------------------------------------------------------------------- email verification


def unverify(panel, email="admin@example.com"):
    from examples.shop.models import User

    with db_session(panel) as db:
        user = db.scalars(select(User).where(User.email == email)).one()
        user.email_verified_at = None
        db.commit()


def link_from(mail):
    import re

    return re.search(r"(/admin/email-verification/verify/\S+)", mail["body"]).group(1)


def test_unverified_user_must_verify(admin, panel):
    unverify(panel)
    r = admin.get("/admin/products", follow_redirects=False)
    assert r.headers["location"] == "/admin/email-verification/prompt"
    r = admin.get("/admin/email-verification/prompt")
    assert "Verify your email" in r.text and "admin@example.com" in r.text

    panel.test_mails.clear()
    r = admin.post("/admin/email-verification/prompt", htmx=False)
    assert "Verification link sent" in r.text
    assert len(panel.test_mails) == 1 and panel.test_mails[0]["to"] == "admin@example.com"
    r = admin.post("/admin/email-verification/prompt", htmx=False)
    assert "Please wait a moment" in r.text and len(panel.test_mails) == 1  # once a minute

    r = admin.get(link_from(panel.test_mails[0]), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/"
    assert "Email verified" in admin.get("/admin/").text
    assert admin.get("/admin/products").status_code == 200


def test_bad_or_stale_verification_links(admin, panel):
    unverify(panel)
    r = admin.get("/admin/email-verification/verify/not-a-token")
    assert "This link has expired" in r.text
    admin.post("/admin/email-verification/prompt", htmx=False)
    link = link_from(panel.test_mails[-1])
    # changing the email makes the old link useless
    from examples.shop.models import User

    with db_session(panel) as db:
        db.scalars(select(User).where(User.email == "admin@example.com")).one().email = "new@example.com"
        db.commit()
    assert "This link has expired" in admin.get(link).text


def test_registration_sends_verification_link(client, panel):
    client.get("/admin/register")
    client.client.post("/admin/register", data={"_token": client.token, "name": "Reg", "email": "reg2@x.com",
                                                "password": "password123", "password_confirmation": "password123"})
    mail = panel.test_mails[-1]
    assert mail["to"] == "reg2@x.com" and "Verify your Tungsten email address" == mail["subject"]
    # works without being signed in
    r = client.get(link_from(mail), follow_redirects=False)
    assert r.headers["location"] == "/admin/login"
    from examples.shop.models import User

    with db_session(panel) as db:
        assert db.scalars(select(User).where(User.email == "reg2@x.com")).one().email_verified_at is not None


def test_changing_email_in_profile_needs_verification(admin, panel):
    r = admin.post("/admin/profile", {"name": "Kuldeep Gothwal", "email": "kd@example.com"})
    assert r.headers.get("HX-Redirect") == "/admin/email-verification/prompt"
    assert panel.test_mails[-1]["to"] == "kd@example.com"
    assert admin.get("/admin/products", follow_redirects=False).headers["location"].endswith("/prompt")


# ---------------------------------------------------------------------- translations


def test_translator_basics(tmp_path):
    from tungsten.i18n import Translator, extract_strings

    (tmp_path / "hi.json").write_text('{"Products": "उत्पाद", "Hello :name": "नमस्ते :name", "Saved": "ठीक है"}')
    t = Translator("en", [tmp_path])
    assert t.translate("Products", "hi") == "उत्पाद"
    assert t.translate("Hello :name", "hi", name="Asha") == "नमस्ते Asha"
    assert t.translate("Saved", "hi") == "ठीक है"  # app files override Tungsten's own wording
    assert t.translate("Unknown words", "hi") == "Unknown words"
    assert t.translate("Products", "en") == "Products"
    assert t.negotiate("fr-CH, hi;q=0.9, en;q=0.8", ["en", "hi"]) == "hi"
    assert t.negotiate("pt-BR", ["en", "pt"]) == "pt"
    assert "Contains" in extract_strings(["src/tungsten/tables/query_builder.py"])


def test_builtin_hindi_is_complete_and_keeps_placeholders():
    import json
    import re

    from tungsten.i18n import BUILTIN_DIR, extract_strings

    hi = json.loads((BUILTIN_DIR / "hi.json").read_text(encoding="utf-8"))
    missing = [s for s in extract_strings([BUILTIN_DIR.parent]) if not hi.get(s)]
    assert missing == []
    for key, value in hi.items():
        assert set(re.findall(r":[a-z]+", key)) == set(re.findall(r":[a-z]+", value)), key


def test_language_switch(admin, client):
    html = admin.get("/admin/").text
    assert 'data-tw-languages' in html and "हिन्दी" in html and '<html lang="en"' in html
    r = admin.post("/admin/_tw/locale", {"locale": "hi"})
    assert r.headers.get("HX-Refresh") == "true"
    html = admin.get("/admin/products").text
    assert '<html lang="hi"' in html
    assert "उत्पाद" in html  # demo label from examples/shop/lang/hi.json
    assert "फ़िल्टर" in html and "कॉलम" in html  # Tungsten's own text
    assert "window.twLang" in html
    r = admin.post("/admin/products/create", {"name": ""})
    assert "भरना ज़रूरी है" in r.text  # validation messages too
    r = admin.post("/admin/_tw/locale", {"locale": "xx"})  # unknown languages are ignored
    assert '<html lang="hi"' in admin.get("/admin/").text


def test_browser_language_and_login_switcher(client):
    r = client.get("/admin/login", headers={"Accept-Language": "hi-IN,hi;q=0.9"})
    assert "फिर से स्वागत है" in r.text and 'data-tw-languages' in r.text
    r = client.get("/admin/login", headers={"Accept-Language": "de"})
    assert "Welcome back" in r.text


def test_notifications_are_translated(admin):
    admin.post("/admin/_tw/locale", {"locale": "hi"})
    r = admin.post("/admin/_tw/column", {"host": "resource:brands", "record": "1", "column": "name", "value": "X"})
    import json

    assert json.loads(r.headers["HX-Trigger"])["tw-notify"][0]["title"] == "सेव हो गया"


def test_lang_extract_cli(tmp_path):
    import json

    from typer.testing import CliRunner

    from tungsten.cli import app

    result = CliRunner().invoke(app, ["lang:extract", "hi", "--path", "examples/shop", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "hi.json").read_text(encoding="utf-8"))
    assert "Low stock only" in data and data["Low stock only"] == ""
    assert "Filters" not in data  # Tungsten already ships this one


# ---------------------------------------------------------------------- async engine


def test_async_engine_mode(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from examples.shop import pages as shop_pages
    from examples.shop.factory import create_app
    from examples.shop.seed import seed

    from .conftest import PanelClient

    url = f"sqlite:///{tmp_path / 'shop.db'}"
    seed(url)
    monkeypatch.setattr(shop_pages, "SETTINGS_FILE", tmp_path / "settings.json")
    app, panel = create_app(url.replace("sqlite://", "sqlite+aiosqlite://"), storage_dir=str(tmp_path / "s"))
    assert panel.is_async
    c = PanelClient(TestClient(app))
    assert c.login().status_code == 303
    newest = panel.with_session(lambda db: db.scalars(select(Product).order_by(Product.id.desc())).first().name)
    assert newest in c.get("/admin/products").text
    r = c.post("/admin/_tw/action", {"_tw_host": "resource:brands", "_tw_scope": "page", "_tw_name": "create",
                                     "name": "Async Brand", "website": ""})
    assert r.headers.get("HX-Refresh") == "true", r.text
    from examples.shop.models import Brand

    assert panel.with_session(lambda db: db.scalars(select(Brand).where(Brand.name == "Async Brand")).one()).name \
        == "Async Brand"


def test_async_closures_are_awaited():
    from tungsten.support.evaluate import call

    async def double(value):
        return value * 2

    assert call(double, value=4) == 8
