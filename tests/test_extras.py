"""Multi-tenancy, plugins, render hooks, no-auth panels and the CLI."""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from markupsafe import Markup
from sqlalchemy import ForeignKey, String, Table, Column, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from tungsten import Auth, NavigationItem, Page, Panel, Plugin, Resource, Tenancy, hash_password
from tungsten.forms import TextInput
from tungsten.tables import TextColumn

from .conftest import PanelClient, run_cli


class Base(DeclarativeBase):
    pass


membership = Table("membership", Base.metadata,
                   Column("team_id", ForeignKey("teams.id"), primary_key=True),
                   Column("member_id", ForeignKey("members.id"), primary_key=True))


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    teams: Mapped[list[Team]] = relationship(secondary=membership)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))


class ProjectResource(Resource):
    model = Project
    global_search_attributes = ["name"]

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable()])


class HelloPlugin(Plugin):
    id = "hello"

    def register(self, panel):
        panel.navigation_items([NavigationItem("Help", "/help", icon="life-buoy")])

    def boot(self, panel):
        panel.render_hook("content.start", lambda: Markup('<div id="hello-hook">Hello hook</div>'))


class About(Page):
    @classmethod
    def content(cls, ctx):
        return Markup("<p>About page body</p>")


def make_tenant_app():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        red, blue = Team(name="Red"), Team(name="Blue")
        db.add_all([red, blue])
        db.flush()
        db.add(Member(name="Ann", email="ann@x.com", password=hash_password("password"), teams=[red, blue]))
        db.add_all([Project(name="Red rocket", team_id=red.id), Project(name="Blue bird", team_id=blue.id)])
        db.commit()
    panel = Panel(session_factory=Session, secret_key="t", auth=Auth(Member),
                  tenancy=Tenancy(Team, ownership="team_id", tenants=lambda user: user.teams))
    panel.resources([ProjectResource]).pages([About]).plugin(HelloPlugin())
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    return app, Session


def test_tenancy_scopes_and_assigns_records():
    app, Session = make_tenant_app()
    c = PanelClient(TestClient(app))
    assert c.login("ann@x.com").status_code == 303
    html = c.get("/admin/projects").text
    assert "Red rocket" in html and "Blue bird" not in html
    assert 'name="tenant"' in html  # tenant switcher
    r = c.post("/admin/projects/create", {"name": "Red racer"})
    assert r.status_code == 204
    with Session() as db:
        assert db.scalars(select(Project).where(Project.name == "Red racer")).one().team_id == 1
    # records of another tenant are not reachable
    assert c.get("/admin/projects/2/edit").status_code == 404
    assert "Blue bird" not in c.get("/admin/_tw/search?q=bird", htmx=True).text
    r = c.client.post("/admin/_tw/tenant", data={"tenant": "2", "_token": c.token}, follow_redirects=False)
    assert r.status_code == 303
    html = c.get("/admin/projects").text
    assert "Blue bird" in html and "Red rocket" not in html


def test_plugin_hooks_and_custom_page():
    app, _ = make_tenant_app()
    c = PanelClient(TestClient(app))
    c.login("ann@x.com")
    html = c.get("/admin/about").text
    assert "About page body" in html and 'id="hello-hook"' in html and ">Help<" in html


def test_panel_without_auth():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    panel = Panel(engine=engine, path="/backoffice", secret_key="x", dashboard=None)
    panel.resources([ProjectResource])
    app = FastAPI()
    panel.mount(app)
    c = PanelClient(TestClient(app))
    r = c.get("/backoffice/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/backoffice/projects"
    assert c.get("/backoffice/projects").status_code == 200
    assert c.get("/backoffice/login", follow_redirects=False).status_code == 303


def test_brand_colors_from_hex():
    from tungsten.support.colors import css_variables, palette_from_hex

    pal = palette_from_hex("#ff0000")
    assert pal[500] == (255, 0, 0) and pal[50][1] > 200 and pal[950][0] < 100
    css = css_variables({"primary": "#123456", "gray": "slate"})
    assert "--tw-c-primary-500:18 52 86;" in css and "--tw-c-gray-500:100 116 139;" in css


def test_cli_generators(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = run_cli("make:resource", "Project", "--model", "tests.test_extras:Project", "--generate")
    assert code == 0, capsys.readouterr()
    text = (tmp_path / "admin/resources/project_resource.py").read_text()
    assert "class ProjectResource(Resource):" in text and 'TextInput("name").required().max_length(50)' in text
    assert run_cli("make:resource", "Project") == 1  # exists
    for args in (["make:page", "Settings", "--form"], ["make:widget", "Sales", "--type", "chart"],
                 ["make:relation-manager", "Team", "projects"], ["make:plugin", "Blog"], ["init"]):
        code = run_cli(*args)
        assert code == 0, (args, capsys.readouterr())
    compile((tmp_path / "admin/pages/settings.py").read_text(), "settings.py", "exec")
    compile((tmp_path / "admin/widgets/sales.py").read_text(), "sales.py", "exec")
    assert re.search(r"class ProjectsRelationManager", (tmp_path / "admin/resources/team_projects_relation_manager.py").read_text())
