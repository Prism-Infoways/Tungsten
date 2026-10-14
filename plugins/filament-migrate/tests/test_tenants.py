"""Relations and global scopes that live in a model's traits (issues #68 and #69)."""

from __future__ import annotations

import ast
import sys

import pytest
from conftest import PanelClient, convert, laravel_hash
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture()
def tenants3(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LARAVEL_PATH", raising=False)
    conv = convert(tmp_path, "tenants3")
    yield conv
    sys.path.remove(str(tmp_path))


def test_files_are_valid_python(tenants3):
    for rel, content in tenants3.result.files.items():
        if rel.endswith(".py"):
            ast.parse(content, filename=rel)


def test_relation_from_a_trait_is_converted(tenants3):
    models = tenants3.import_("models")
    assert "company" in models.Location.__mapper__.relationships
    # the pair with Company.locations is kept
    assert models.Company.__mapper__.relationships["locations"].back_populates == "company"
    # a relation named like a boot method prefix is still a relation
    assert "booking" in models.Note.__mapper__.relationships


def test_missing_relation_is_left_out_and_reported(tenants3):
    src = tenants3.file("resources/note_resource.py")
    assert "TextColumn('owner.name')" not in src and ".relationship('owner'" not in src
    assert "TextColumn('booking.name')" in src
    report = tenants3.file("MIGRATION_REPORT.md")
    assert "uses relation `owner`, which Note does not have" in report


def test_global_scopes_are_reported(tenants3):
    report = tenants3.file("MIGRATION_REPORT.md")
    security = report.split("## Security: check these first", 1)[1].split("\n## ", 1)[0]
    assert "app/Models/Concerns/BelongsToCompany.php line 13: global scope CompanyScope on Location" in security
    assert "app/Models/Site.php line 9: global scope CompanyScope on Site" in security
    assert "global scope 'active' (closure) on Note" in security
    assert "Tenancy(Company, ownership='company_id', tenants=lambda user: [user.company])" in security
    app = tenants3.file("app.py")
    assert "TODO(filament): SECURITY" in app
    assert "#   Location: CompanyScope -> tenancy=Tenancy(Company, ownership='company_id'" in app
    scopes = [t for t in tenants3.result.todos if t.reason.startswith("SECURITY:")]
    assert len(scopes) == 3


def test_list_pages_render(tenants3):
    models = tenants3.import_("models")
    engine = create_engine(f"sqlite:///{tenants3.root / 'database' / 'database.sqlite'}")
    models.Base.metadata.create_all(engine)
    with Session(engine) as db:
        acme, other = models.Company(name="Acme"), models.Company(name="Other")
        db.add_all([acme, other])
        db.flush()
        db.add(models.User(name="Ann", email="ann@acme.test", password=laravel_hash("secret123"), company_id=acme.id))
        db.add_all([models.Location(name="Pune", company_id=acme.id), models.Site(name="Plant", company_id=acme.id),
                    models.Note(body="Hello")])
        db.commit()
    engine.dispose()
    client = PanelClient(TestClient(tenants3.import_("app").app))
    assert client.login("ann@acme.test", "secret123").status_code == 303
    for url, text in [("/admin/locations", "Pune"), ("/admin/sites", "Plant"), ("/admin/notes", "Hello")]:
        r = client.get(url)
        assert r.status_code == 200, (url, r.text[:500])
        assert text in r.text
    assert "Acme" in client.get("/admin/locations").text
