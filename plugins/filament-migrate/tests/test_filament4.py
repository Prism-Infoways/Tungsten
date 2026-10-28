"""Filament 4 keeps forms and tables in their own classes; the converter follows them."""

from __future__ import annotations

import ast
import sys

import pytest
from conftest import PanelClient, convert, laravel_hash
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture()
def blog4(tmp_path, monkeypatch):
    monkeypatch.delenv("LARAVEL_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conv = convert(tmp_path, "blog4")
    yield conv
    sys.path.remove(str(tmp_path))


def test_resource_follows_schema_and_table_classes(blog4):
    src = blog4.file("resources/post_resource.py")
    ast.parse(src)
    assert "icon = 'newspaper'" in src  # Heroicon::OutlinedNewspaper
    assert "navigation_group = 'Content'" in src
    assert "TextInput('title').required().min_length(3).max_length(120)" in src
    assert "TextInput('slug').required().regex(r'^[A-Za-z0-9_-]+$')" in src
    assert ".min_value(1).max_value(5)" in src
    assert "DateTimePicker('published_at').visible(lambda get: (get('state') == 'published'))" in src
    assert "def infolist(cls, infolist):" in src
    assert "TextEntry('published_at').datetime()" in src
    assert "lambda state: {'draft': 'gray', 'published': 'success'}.get(state, None)" in src
    assert "TextColumn('published_at').datetime('%b %-d, %Y %H:%M').sortable()" in src
    # a list in searchable() names the columns to search (issue #94)
    assert "TextColumn('title').searchable(columns=['title', 'slug']).limit(40)" in src
    # recordActions -> actions; toolbarActions split into bulk and header actions
    assert ".actions([\n                ViewAction(),\n                EditAction(),\n            ])" in src
    assert ".bulk_actions([\n                BulkActionGroup([" in src
    assert ".header_actions([\n                CreateAction(),\n            ])" in src
    assert "TODO" not in src


def test_mysql_url_is_masked_in_the_report(blog4):
    report = blog4.file("MIGRATION_REPORT.md")
    assert "mysql+pymysql://blog_user:***@db.internal:3307/blog" in report
    assert "p@ss" not in report and "pip install pymysql" in report
    from tungsten_filament import laravel_database_url

    assert laravel_database_url(blog4.root) == "mysql+pymysql://blog_user:p%40ss%20word@db.internal:3307/blog"


def test_ulid_keys_and_custom_foreign_key(blog4):
    models = blog4.import_("models")
    engine = create_engine("sqlite://")
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = models.User(name="Ann", email="ann@x.test", password="x")
        post = models.Post(title="Hi", slug="hi", body="<p>Hi</p>", author=user)
        db.add(post)
        db.commit()
        assert len(post.id) == 26 and post.id == post.id.lower()
        assert user.posts == [post]


def test_blog_admin_runs(blog4, tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'blog.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    models = blog4.import_("models")
    engine = create_engine(db_url)
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = models.User(name="Ann", email="ann@x.test", password=laravel_hash("secret"), is_admin=True)
        db.add(models.Post(title="Hello world", slug="hello", body="<p>Hi</p>", author=user, state="published"))
        db.commit()
        post_id = db.query(models.Post).one().id
    engine.dispose()
    client = PanelClient(TestClient(blog4.import_("app").app))
    assert client.login("ann@x.test", "secret").status_code == 303
    for url in ["/admin/posts", "/admin/posts/create", f"/admin/posts/{post_id}", f"/admin/posts/{post_id}/edit"]:
        r = client.get(url)
        assert r.status_code == 200, (url, r.text[:300])
    assert "Hello world" in client.get("/admin/posts").text
