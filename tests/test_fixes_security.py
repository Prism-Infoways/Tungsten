"""Fixes for tenancy, policies, auth links, logout, exports, imports, file serving and the CLI."""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Table, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from examples.shop.models import Product
from examples.shop.resources import ProductResource
from tungsten import Auth, Panel, Resource, Tenancy, hash_password
from tungsten.forms import Select, TextInput
from tungsten.importexport import ExportAction, ExportBulkAction, ExportColumn, ImportAction, ImportColumn, Importer
from tungsten.importexport import run_import, write_xlsx
from tungsten.tables import TextColumn

from .conftest import PanelClient, db_session
from .test_panel import action


class Base(DeclarativeBase):
    pass


crew = Table("fx_crew", Base.metadata,
             Column("team_id", ForeignKey("fx_teams.id"), primary_key=True),
             Column("member_id", ForeignKey("fx_members.id"), primary_key=True))


class Team(Base):
    __tablename__ = "fx_teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class Member(Base):
    __tablename__ = "fx_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    email_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    joined_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teams: Mapped[list[Team]] = relationship(secondary=crew)


class Category(Base):
    __tablename__ = "fx_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    team_id: Mapped[int] = mapped_column(ForeignKey("fx_teams.id"))


class Project(Base):
    __tablename__ = "fx_projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("fx_teams.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("fx_categories.id"), nullable=True)
    category: Mapped[Category | None] = relationship()


class Notice(Base):
    """Has a ``team_id`` but is shared by all teams (``tenant_scoped = False``)."""

    __tablename__ = "fx_notices"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("fx_teams.id"), nullable=True)


class Doc(Base):
    """Owned through a relationship with another name (``tenant_ownership = "owner_team"``)."""

    __tablename__ = "fx_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    owner_team_id: Mapped[int | None] = mapped_column(ForeignKey("fx_teams.id"), nullable=True)
    owner_team: Mapped[Team | None] = relationship()


class ProjectImporter(Importer):
    model = Project
    unique_by = "code"
    columns = [ImportColumn("name").required().example("Moon base"), ImportColumn("code").example("MB-1"),
               ImportColumn("category").relationship("category", "name").example("Ops")]


class ProjectResource(Resource):
    model = Project
    global_search_attributes = ["name"]

    @classmethod
    def form(cls, form):
        return form.schema([
            TextInput("name").required(),
            TextInput("code").unique(),
            Select("category_id").relationship("category", "name").searchable(),
        ])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable()]).header_actions([ImportAction(ProjectImporter)])


class NoticeResource(Resource):
    model = Notice
    tenant_scoped = False

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("title").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("title")])


class DocResource(Resource):
    model = Doc
    tenant_ownership = "owner_team"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("title").required()])

    @classmethod
    def table(cls, table):
        return (table.columns([TextColumn("title")])
                .header_actions([ExportAction(columns=[ExportColumn("title", "Heading", lambda state: state.upper()),
                                                       ExportColumn("owner_team.name", "Team")])])
                .bulk_actions([ExportBulkAction()]))


def make_app(session_key: str = "tw_tenant"):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        red, blue = Team(name="Red"), Team(name="Blue")
        db.add_all([red, blue])
        db.flush()
        db.add(Member(name="Ann", email="ann@x.com", password=hash_password("password"), teams=[red, blue]))
        db.add(Member(name="Nobody", email="nobody@x.com", password=hash_password("password"), teams=[]))
        ops_red, ops_blue = Category(name="Ops red", team_id=red.id), Category(name="Ops blue", team_id=blue.id)
        db.add_all([ops_red, ops_blue])
        db.flush()
        db.add_all([Project(name="Red rocket", code="R-1", team_id=red.id, category_id=ops_red.id),
                    Project(name="Blue bird", code="SAME", team_id=blue.id, category_id=ops_blue.id),
                    Notice(title="Shared notice", team_id=blue.id),
                    Doc(title="Red doc", owner_team_id=red.id), Doc(title="Blue doc", owner_team_id=blue.id)])
        db.commit()
    panel = Panel(session_factory=Session, secret_key="t", auth=Auth(Member),
                  tenancy=Tenancy(Team, ownership="team_id", tenants=lambda user: user.teams, session_key=session_key))
    panel.resources([ProjectResource, NoticeResource, DocResource])
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    return app, Session, panel


def signed_in(app, email="ann@x.com"):
    c = PanelClient(TestClient(app))
    assert c.login(email).status_code == 303
    c.get("/admin/")
    return c


# ---------------------------------------------------------------------- 1. users without a tenant


def test_user_without_tenant_sees_no_tenant_records():
    app, Session, _ = make_app()
    c = signed_in(app, "nobody@x.com")
    html = c.get("/admin/projects").text
    assert "Red rocket" not in html and "Blue bird" not in html
    assert c.get("/admin/projects/1").status_code == 404
    assert c.get("/admin/projects/1/edit").status_code == 404
    assert c.get("/admin/projects/create").status_code == 403
    r = c.post("/admin/projects/create", {"name": "Sneaky"})
    assert "Not allowed" in r.headers.get("HX-Trigger", "")
    assert "Red rocket" not in c.get("/admin/_tw/search?q=rocket", htmx=True).text
    with Session() as db:
        assert db.scalars(select(Project).where(Project.name == "Sneaky")).first() is None
    # a model opted out of tenancy stays visible
    assert "Shared notice" in c.get("/admin/notices").text


def test_tenancy_assign_refuses_without_tenant():
    _, Session, panel = make_app()
    ctx = SimpleNamespace(panel=panel, tenant=None)
    with pytest.raises(PermissionError):
        panel.tenancy.assign(ctx, Project, Project(name="x"))


# ---------------------------------------------------------------------- 2. importer, options and unique per tenant


def test_import_unique_by_and_relationship_stay_in_tenant():
    _, Session, panel = make_app()
    with Session() as db:
        red = db.get(Team, 1)
        ctx = SimpleNamespace(panel=panel, tenant=red, db=db, user=None)
        created, updated, failures = run_import(ctx, ProjectImporter, [
            {"name": "Mine now", "code": "SAME"},             # Blue's code: must create a Red record
            {"name": "Bad category", "category": "Ops blue"},  # Blue's category is not found
            {"name": "Good category", "category": "Ops red"},
        ])
        assert (created, updated) == (2, 0)
        assert failures and "not found" in failures[0][1]
    with Session() as db:
        blue_bird = db.get(Project, 2)
        assert blue_bird.name == "Blue bird" and blue_bird.team_id == 2
        assert db.scalars(select(Project).where(Project.name == "Mine now")).one().team_id == 1


def test_select_options_and_unique_are_scoped_to_tenant():
    app, Session, _ = make_app()
    c = signed_in(app)
    html = c.get("/admin/projects/create").text
    assert "Ops red" in html and "Ops blue" not in html
    # another tenant's category id is refused
    r = c.post("/admin/projects/create", {"name": "Hijack", "category_id": "2"})
    assert "The selected category is invalid." in r.text
    # "SAME" is only used by Blue, so it is free for Red
    r = c.post("/admin/projects/create", {"name": "Twin", "code": "SAME", "category_id": "1"})
    assert r.status_code == 204, r.text
    r = c.post("/admin/projects/create", {"name": "Copy", "code": "R-1"})
    assert "has already been taken" in r.text


# ---------------------------------------------------------------------- 3. tenant_scoped / tenant_ownership


def test_resource_tenant_settings_are_used():
    app, Session, _ = make_app()
    c = signed_in(app)
    assert "Shared notice" in c.get("/admin/notices").text  # tenant_scoped = False
    html = c.get("/admin/docs").text
    assert "Red doc" in html and "Blue doc" not in html  # tenant_ownership = "owner_team"
    assert c.get("/admin/docs/2").status_code == 404
    assert c.post("/admin/docs/create", {"title": "New doc"}).status_code == 204
    assert c.post("/admin/notices/create", {"title": "New notice"}).status_code == 204
    with Session() as db:
        assert db.scalars(select(Doc).where(Doc.title == "New doc")).one().owner_team_id == 1
        assert db.scalars(select(Notice).where(Notice.title == "New notice")).one().team_id is None


# ---------------------------------------------------------------------- 4. emailed links use app_url


def _reset_mail(client, panel, host=None):
    client.get("/admin/forgot-password")
    headers = {"host": host} if host else {}
    client.client.post("/admin/forgot-password", data={"_token": client.token, "email": "admin@example.com"},
                       headers=headers)
    return panel.test_mails[-1]["body"]


def test_reset_link_uses_app_url_not_host_header(client, panel):
    panel.app_url = "https://admin.example.org"
    body = _reset_mail(client, panel, host="evil.example")
    assert "https://admin.example.org/admin/reset-password/" in body and "evil.example" not in body


def test_reset_link_falls_back_to_request_host(client, panel):
    assert panel.app_url is None
    assert "http://testserver/admin/reset-password/" in _reset_mail(client, panel)


def test_verification_link_uses_app_url(panel):
    from examples.shop.models import User
    from tungsten.auth.verification import verification_url

    panel.app_url = "https://admin.example.org"
    with db_session(panel) as db:
        user = db.scalars(select(User)).first()
        url = verification_url(SimpleNamespace(panel=panel, request=None), user)
    assert url.startswith("https://admin.example.org/admin/email-verification/verify/")


def test_panel_app_url_option():
    assert Panel(app_url="https://a.example/").app_url == "https://a.example"


# ---------------------------------------------------------------------- 5. logout forgets a custom tenant key


def test_logout_clears_custom_tenant_session_key():
    app, _, _ = make_app(session_key="team")
    c = signed_in(app)
    c.client.post("/admin/_tw/tenant", data={"tenant": "2", "_token": c.token})
    assert "Blue bird" in c.get("/admin/projects").text
    c.client.post("/admin/logout", data={"_token": c.token})
    c = PanelClient(c.client)
    assert c.login("ann@x.com").status_code == 303
    html = c.get("/admin/projects").text
    assert "Red rocket" in html and "Blue bird" not in html


# ---------------------------------------------------------------------- 6. export needs an export action


def test_export_needs_an_export_action():
    app, _, _ = make_app()
    c = signed_in(app)
    assert c.get("/admin/_tw/export?host=resource:projects&format=csv").status_code == 403
    assert c.get("/admin/_tw/export?host=resource:projects&format=csv&keys=1").status_code == 403
    assert c.get("/admin/_tw/export?host=resource:docs&format=csv").status_code == 200
    assert c.get("/admin/_tw/export?host=resource:docs&format=csv&keys=1").status_code == 200


def test_export_refused_when_action_hidden(admin, monkeypatch):
    original = ProductResource.table

    def table(cls, t):
        t = original.__func__(cls, t)
        return t.header_actions([ExportAction().visible(False)]).bulk_actions([])

    monkeypatch.setattr(ProductResource, "table", classmethod(table))
    assert admin.get("/admin/_tw/export?host=resource:products&format=csv").status_code == 403
    assert admin.get("/admin/_tw/export?host=resource:products&format=csv&keys=1").status_code == 403


# ---------------------------------------------------------------------- 7. stored files need a signed-in user


def test_storage_needs_login(app_and_panel, admin, panel):
    import io

    stored = panel.storage.save(io.BytesIO(b"secret"), "note.txt", "docs")
    anon = TestClient(app_and_panel[0])
    r = anon.get(f"/admin/storage/{stored}", follow_redirects=False)
    assert r.status_code == 303 and "/admin/login" in r.headers["location"]
    assert admin.get(f"/admin/storage/{stored}").content == b"secret"
    # explicitly public storage serves files to anyone, but never the imports folder
    panel.storage.public = True
    assert anon.get(f"/admin/storage/{stored}").content == b"secret"
    private = panel.storage.save(io.BytesIO(b"rows"), "failed-rows.csv", "imports")
    assert anon.get(f"/admin/storage/{private}", follow_redirects=False).status_code == 303
    assert not panel.storage.is_public(f"docs/../{private}")


def test_failed_rows_report_needs_login(app_and_panel, admin):
    csv_bytes = b"name,sku,price\nBad Row,,abc\n"
    r = admin.client.post("/admin/_tw/form", data={"_tw_kind": "action", "_tw_host": "resource:products",
                                                   "_tw_scope": "table", "_tw_name": "import"},
                          files={"file.__upload": ("products.csv", csv_bytes, "text/csv")},
                          headers={"HX-Request": "true", "X-CSRF-Token": admin.token})
    stored = re.search(r'name="file" value="([^"]+)"', r.text).group(1)
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:products", "_tw_scope": "table", "_tw_name": "import",
                                         "file": stored})
    url = json.loads(r.headers["HX-Trigger"])["tw-notify"][0]["actions"][0]["url"]
    anon = TestClient(app_and_panel[0])
    assert anon.get(url, follow_redirects=False).status_code == 303
    assert b"Error" in admin.get(url).content


# ---------------------------------------------------------------------- 8. policies use closure injection


class _Policy:
    async def view_any(self, user):
        return user.email == "admin@example.com"

    def update(self, user):  # no record parameter
        return False

    async def view(self, user, record, ctx):
        return record.id != 2


def test_policy_methods_by_name_and_async(admin, monkeypatch):
    monkeypatch.setattr(ProductResource, "policy", _Policy())
    assert admin.get("/admin/products").status_code == 200
    assert admin.get("/admin/products/1/edit").status_code == 403
    assert admin.get("/admin/products/1").status_code == 200
    assert admin.get("/admin/products/2").status_code == 403


def test_async_policy_false_is_respected(admin, monkeypatch):
    class Deny:
        async def view_any(self, user):
            return False

    monkeypatch.setattr(ProductResource, "policy", Deny())
    assert admin.get("/admin/products").status_code == 403


def test_positional_policy_still_works(admin, monkeypatch):
    class Old:
        def update(self, u, r=None):
            return r is None or r.id != 1

    monkeypatch.setattr(ProductResource, "policy", Old())
    assert admin.get("/admin/products/1/edit").status_code == 403
    assert admin.get("/admin/products/2/edit").status_code == 200


# ---------------------------------------------------------------------- 9. make:user


cli_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
cli_panel = Panel(engine=cli_engine, secret_key="c", auth=Auth(Member, email_verification=True))


def test_make_user_marks_verified_and_parses_values(capsys):
    from .conftest import run_cli

    Base.metadata.create_all(cli_engine)
    base = ["make:user", "--panel", "tests.test_fixes_security:cli_panel", "--name", "Asha", "--password", "secret123"]
    code = run_cli(*base, "--email", "asha@x.com", "--set", "joined_on=2024-01-02", "--set", "score=7")
    assert code == 0, capsys.readouterr()
    code = run_cli(*base, "--email", "raj@x.com", "--unverified", "--set", "email_verified_at=null")
    assert code == 0, capsys.readouterr()
    code = run_cli(*base, "--email", "dev@x.com", "--unverified", "--set", "email_verified_at=2024-05-06T07:08")
    assert code == 0, capsys.readouterr()
    with sessionmaker(cli_engine)() as db:
        asha = db.scalars(select(Member).where(Member.email == "asha@x.com")).one()
        assert isinstance(asha.email_verified_at, dt.datetime)
        assert asha.joined_on == dt.date(2024, 1, 2) and asha.score == 7
        assert db.scalars(select(Member).where(Member.email == "raj@x.com")).one().email_verified_at is None
        dev = db.scalars(select(Member).where(Member.email == "dev@x.com")).one()
        assert dev.email_verified_at == dt.datetime(2024, 5, 6, 7, 8)


def test_make_user_role_help_matches_code():
    from tungsten.cli import build_parser

    command = build_parser().commands["make:user"]
    help_text = next(a.help for a in command._actions if a.dest == "role")
    assert "contains 'admin'" in help_text and "created with * if missing" not in help_text


# ---------------------------------------------------------------------- 10. excel install hint


def test_excel_error_names_the_real_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    with pytest.raises(RuntimeError, match=r"tungsten-admin\[excel\]"):
        write_xlsx([["a"]])


# ---------------------------------------------------------------------- 11. example CSV and ExportColumn


def test_import_modal_offers_example_csv(app_and_panel, admin):
    r = action(admin, "get", host="resource:products", scope="table", name="import")
    m = re.search(r'href="([^"]*import-example[^"]*)"', r.text)
    assert m and "Download example CSV" in r.text
    url = m.group(1).replace("&amp;", "&")
    r = admin.get(url)
    assert r.headers["content-disposition"] == 'attachment; filename="products-example.csv"'
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Name,SKU") and lines[1].startswith("Premium T-Shirt,TSH-001")
    anon = TestClient(app_and_panel[0])
    assert anon.get(url, follow_redirects=False).status_code == 303


def test_example_csv_needs_import_permission():
    app, _, _ = make_app()
    c = signed_in(app, "nobody@x.com")  # no tenant: may not create, so may not import
    assert c.get("/admin/_tw/import-example?host=resource:projects&action=import").status_code == 403
    c = signed_in(app)
    r = c.get("/admin/_tw/import-example?host=resource:projects&action=import")
    assert r.status_code == 200 and "Moon base,MB-1,Ops" in r.content.decode("utf-8-sig")


def test_export_action_uses_export_columns():
    app, _, _ = make_app()
    c = signed_in(app)
    r = action(c, "get", host="resource:docs", scope="table", name="export")
    assert 'value="title"' in r.text and "Heading" in r.text
    r = action(c, host="resource:docs", scope="table", name="export", format="csv", columns=["title", "owner_team.name"],
               state="")
    url = r.headers["HX-Redirect"]
    assert "action=export" in url
    lines = c.get(url).content.decode("utf-8-sig").splitlines()
    assert lines == ["Heading,Team", "RED DOC,Red"]


def test_product_table_export_unchanged(admin, panel):
    r = admin.get("/admin/_tw/export?host=resource:products&format=csv&keys=1")
    with db_session(panel) as db:
        assert db.get(Product, 1).name in r.content.decode("utf-8-sig")
