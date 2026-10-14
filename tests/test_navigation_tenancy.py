"""Tenant in the URL, tenant sign-up and settings pages, billing hooks, per-tenant roles,
clusters, record sub-navigation and the top navigation bar."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Column, ForeignKey, String, Table, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from tungsten import Auth, Panel, Resource, Tenancy, hash_password
from tungsten.forms import TextInput
from tungsten.tables import TextColumn
from tungsten.tenancy import BillingProvider

from .conftest import PanelClient


class Base(DeclarativeBase):
    pass


membership = Table("nt_membership", Base.metadata,
                   Column("team_id", ForeignKey("nt_teams.id"), primary_key=True),
                   Column("member_id", ForeignKey("nt_members.id"), primary_key=True))


class Team(Base):
    __tablename__ = "nt_teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    projects: Mapped[list["Project"]] = relationship(viewonly=True)


class Member(Base):
    __tablename__ = "nt_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(100), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    teams: Mapped[list[Team]] = relationship(secondary=membership)


class Project(Base):
    __tablename__ = "nt_projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    team_id: Mapped[int] = mapped_column(ForeignKey("nt_teams.id"))


class ProjectResource(Resource):
    model = Project

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable()])


class PlanBilling(BillingProvider):
    def is_subscribed(self, ctx, tenant):
        return tenant.plan == "pro"

    def billing_url(self, ctx, tenant):
        return f"https://billing.example.com/{tenant.slug}"


def make_app(**tenancy_kw):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        red, blue, green = Team(name="Red", slug="red"), Team(name="Blue", slug="blue"), Team(name="Green", slug="green")
        db.add_all([red, blue, green])
        db.flush()
        db.add(Member(name="Ann", email="ann@x.com", password=hash_password("password"), teams=[red, blue]))
        db.add(Member(name="Bob", email="bob@x.com", password=hash_password("password"), teams=[]))
        db.add_all([Project(name="Red rocket", team_id=red.id), Project(name="Blue bird", team_id=blue.id),
                    Project(name="Green leaf", team_id=green.id)])
        db.commit()
    tenancy = Tenancy(Team, ownership="team_id", tenants=lambda user: user.teams, url=True, slug_attribute="slug",
                      **tenancy_kw)
    panel = Panel(session_factory=Session, secret_key="t", auth=Auth(Member), tenancy=tenancy)
    panel.resources([ProjectResource])
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    return app, Session, panel


def test_tenant_in_url_scopes_records_and_links():
    app, Session, _ = make_app()
    c = PanelClient(TestClient(app))
    c.login("ann@x.com")
    r = c.get("/admin/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/red/"
    html = c.get("/admin/red/projects").text
    assert "Red rocket" in html and "Blue bird" not in html
    assert 'href="/admin/red/projects/create"' in html and 'href="/admin/blue/"' in html
    html = c.get("/admin/blue/projects").text
    assert "Blue bird" in html and "Red rocket" not in html
    # create inside a tenant sets it on the record
    r = c.post("/admin/blue/projects/create", {"name": "Blue boat"})
    assert r.status_code == 204 and r.headers["HX-Redirect"].startswith("/admin/blue/projects/")
    with Session() as db:
        assert db.scalars(select(Project).where(Project.name == "Blue boat")).one().team_id == 2
    # a tenant the user is not in, and records of another tenant, are not found
    assert c.get("/admin/green/projects").status_code == 404
    assert c.get("/admin/red/projects/2/edit").status_code == 404
    assert c.get("/admin/blue/projects/2/edit").status_code == 200
    # table reloads inside the tenant
    assert "Blue bird" in c.get("/admin/blue/_tw/table?host=resource:projects", htmx=True).text
    # old links without the tenant go to the last used one
    r = c.get("/admin/projects/create?x=1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/blue/projects/create?x=1"
    # login and assets have no tenant part
    assert c.get("/admin/login", follow_redirects=False).status_code in (200, 303)


def test_tenant_registration_and_profile():
    app, Session, panel = make_app(
        registration=[TextInput("name").required(), TextInput("slug").required().unique()],
        on_register=lambda tenant, user: user.teams.append(tenant),
        profile=[TextInput("name").required(), TextInput("slug").required()],
    )
    c = PanelClient(TestClient(app))
    c.login("bob@x.com")
    # a user without a team is sent to the sign-up page
    r = c.get("/admin/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/tenant/new"
    html = c.get("/admin/tenant/new").text
    assert "Register team" in html and 'name="slug"' in html
    r = c.post("/admin/tenant/new", {"name": "Bob's band", "slug": ""})
    assert r.status_code == 200 and "required" in r.text.lower()
    r = c.post("/admin/tenant/new", {"name": "Bob's band", "slug": "band"})
    assert r.status_code == 204 and r.headers["HX-Redirect"] == "/admin/band/"
    with Session() as db:
        bob = db.scalars(select(Member).where(Member.email == "bob@x.com")).one()
        assert [t.slug for t in bob.teams] == ["band"]
    html = c.get("/admin/band/").text
    assert 'href="/admin/band/tenant/profile"' in html and "Team settings" in html
    assert 'href="/admin/tenant/new"' in html
    html = c.get("/admin/band/tenant/profile").text
    assert 'value="Bob&#39;s band"' in html or "Bob's band" in html
    r = c.post("/admin/band/tenant/profile", {"name": "The Band", "slug": "the-band"})
    assert r.status_code == 204 and r.headers["HX-Redirect"] == "/admin/the-band/tenant/profile"
    with Session() as db:
        assert db.scalars(select(Team).where(Team.slug == "the-band")).one().name == "The Band"


def test_tenant_profile_permission():
    app, _, _ = make_app(profile=[TextInput("name")], can_edit_profile=lambda tenant: tenant.slug == "red")
    c = PanelClient(TestClient(app))
    c.login("ann@x.com")
    assert c.get("/admin/red/tenant/profile").status_code == 200
    assert c.get("/admin/blue/tenant/profile").status_code == 403
    assert "Team settings" not in c.get("/admin/blue/").text


def test_billing_hooks_require_subscription():
    app, Session, _ = make_app(billing=PlanBilling(), require_subscription=True)
    with Session() as db:
        db.get(Team, 1).plan = "pro"
        db.commit()
    c = PanelClient(TestClient(app))
    c.login("ann@x.com")
    assert c.get("/admin/red/projects").status_code == 200
    assert 'href="/admin/red/tenant/billing"' in c.get("/admin/red/").text
    r = c.get("/admin/blue/projects", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/blue/tenant/billing"
    r = c.get("/admin/blue/tenant/billing", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "https://billing.example.com/blue"


def test_session_tenancy_still_works_without_url():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        red = Team(name="Red", slug="red")
        db.add(red)
        db.flush()
        db.add(Member(name="Ann", email="ann@x.com", password=hash_password("password"), teams=[red]))
        db.add(Project(name="Red rocket", team_id=red.id))
        db.commit()
    panel = Panel(session_factory=Session, secret_key="t", auth=Auth(Member),
                  tenancy=Tenancy(Team, ownership="team_id", tenants=lambda user: user.teams))
    panel.resources([ProjectResource])
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    c = PanelClient(TestClient(app))
    c.login("ann@x.com")
    html = c.get("/admin/projects").text
    assert "Red rocket" in html and 'href="/admin/projects/create"' in html


# ---------------------------------------------------------------- per-tenant roles
def test_roles_per_tenant():
    from tungsten.auth.rbac import RolesField
    from tungsten.models import Role

    class MemberResource(Resource):
        model = Member
        slug = "nt-members"
        tenant_scoped = False

        @classmethod
        def form(cls, form):
            return form.schema([TextInput("name"), RolesField("roles").per_tenant()])

    app, Session, panel = make_app()
    panel.rbac()
    panel.resources([MemberResource])
    with Session() as db:
        db.add_all([Role(name="Admin", permissions=["*"]),
                    Role(name="Viewer", permissions=["projects.view_any", "projects.view", "nt-members.view_any",
                                                     "nt-members.view", "nt-members.update"])])
        db.commit()
        ann = db.scalars(select(Member).where(Member.email == "ann@x.com")).one()
        red, blue = db.get(Team, 1), db.get(Team, 2)
        panel.auth.assign_role(db, ann, "Admin", tenant=red)
        panel.auth.assign_role(db, ann, "Viewer", tenant=blue)
    c = PanelClient(TestClient(app))
    c.login("ann@x.com")
    # Admin in Red: may create; Viewer in Blue: may only look
    assert c.get("/admin/red/projects/create").status_code == 200
    assert c.get("/admin/blue/projects").status_code == 200
    assert c.get("/admin/blue/projects/create").status_code == 403
    # the roles field shows and saves the roles of the current tenant only
    html = c.get("/admin/blue/nt-members/1/edit").text
    assert 'name="roles"' in html
    with Session() as db:
        viewer = db.scalars(select(Role).where(Role.name == "Viewer")).one()
        admin = db.scalars(select(Role).where(Role.name == "Admin")).one()
    r = c.post("/admin/red/nt-members/1/edit", {"name": "Ann", "roles": [str(viewer.id)]})
    assert r.status_code == 200
    from tungsten.models import TenantRoleAssignment

    with Session() as db:
        rows = {(a.tenant_id, a.role_id) for a in db.scalars(select(TenantRoleAssignment))}
    assert rows == {("1", viewer.id), ("2", viewer.id)}
    assert admin.id not in {r for _, r in rows}
    assert c.get("/admin/red/projects/create").status_code == 403


# ---------------------------------------------------------------- navigation
from tungsten import NavigationItem, Page  # noqa: E402
from tungsten.navigation import Cluster  # noqa: E402


class Settings(Cluster):
    icon = "settings"
    navigation_group = "Admin"
    description = "Panel settings"


class TagResource(Resource):
    model = Team
    slug = "tags"
    cluster = Settings
    navigation_sort = 2
    tenant_scoped = False

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name")])


class General(Page):
    cluster = Settings
    navigation_sort = 1


class ProjectWithMenu(ProjectResource):
    slug = "plans"
    record_sub_navigation = ("view", "edit")
    sub_navigation_position = "top"

    @classmethod
    def get_record_sub_navigation(cls, ctx, record):
        return super().get_record_sub_navigation(ctx, record) + [
            NavigationItem("Docs", f"/docs/{record.id}", icon="book")]


def make_nav_app(**panel_kw):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        red = Team(name="Red", slug="red")
        db.add(red)
        db.flush()
        db.add(Member(name="Ann", email="ann@x.com", password=hash_password("password"), teams=[red]))
        db.add(Project(name="Red rocket", team_id=red.id))
        db.commit()
    panel = Panel(session_factory=Session, secret_key="t", auth=Auth(Member), **panel_kw)
    panel.resources([ProjectResource, ProjectWithMenu, TagResource]).pages([General])
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    c = PanelClient(TestClient(app))
    c.login("ann@x.com")
    return c


def test_cluster_menu_and_sub_navigation():
    c = make_nav_app()
    html = c.get("/admin/projects").text
    # one "Settings" item in the menu, not its members
    assert 'href="/admin/settings"' in html and 'href="/admin/tags"' not in html
    assert 'href="/admin/general"' not in html and "data-tw-sub-navigation" not in html
    r = c.get("/admin/settings", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/general"
    html = c.get("/admin/tags").text
    assert 'data-tw-sub-navigation="start"' in html and "Panel settings" in html
    assert 'href="/admin/general"' in html and 'href="/admin/tags"' in html
    nav = html[html.index("data-tw-sub-navigation"):]
    assert nav.index("/admin/general") < nav.index("/admin/tags")  # sorted by navigation_sort
    assert 'aria-current="page"' in html[html.index('Admin'):]  # the cluster item is active
    assert "data-tw-sub-navigation" in c.get("/admin/general").text
    assert c.get("/admin/nope", follow_redirects=False).status_code == 404


def test_record_sub_navigation():
    c = make_nav_app()
    html = c.get("/admin/plans/1").text
    assert 'data-tw-sub-navigation="top"' in html
    assert 'href="/admin/plans/1/edit"' in html and 'href="/docs/1"' in html
    assert "data-tw-sub-navigation" not in c.get("/admin/plans").text
    assert "data-tw-sub-navigation" not in c.get("/admin/projects/1").text


def test_top_navigation():
    c = make_nav_app(top_navigation=True)
    html = c.get("/admin/projects").text
    assert "data-tw-top-navigation" in html and "lg:hidden" in html
    top = html[html.index("data-tw-top-navigation"):html.index("</nav>", html.index("data-tw-top-navigation"))]
    assert 'href="/admin/projects"' in top and 'href="/admin/settings"' in top and "Admin" in top
    assert "lg:ps-64" not in html
    assert "data-tw-top-navigation" not in make_nav_app().get("/admin/projects").text


def test_record_sub_navigation_lists_relation_pages():
    from tungsten import RelationManager

    class ProjectsManager(RelationManager):
        relationship = "projects"
        separate_page = True

        @classmethod
        def table(cls, table):
            return table.columns([TextColumn("name")])

    class TeamResource(Resource):
        model = Team
        slug = "teams"
        tenant_scoped = False
        relations = [ProjectsManager]
        record_sub_navigation = ("view", "edit", "projects")

        @classmethod
        def form(cls, form):
            return form.schema([TextInput("name")])

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        red = Team(name="Red", slug="red")
        db.add(red)
        db.flush()
        db.add(Member(name="Ann", email="ann@x.com", password=hash_password("password"), teams=[red]))
        db.add(Project(name="Red rocket", team_id=red.id))
        db.commit()
    panel = Panel(session_factory=Session, secret_key="t", auth=Auth(Member))
    panel.resources([TeamResource])
    panel.create_tables(engine)
    app = FastAPI()
    panel.mount(app)
    c = PanelClient(TestClient(app))
    c.login("ann@x.com")
    html = c.get("/admin/teams/1/projects").text
    nav = html[html.index('data-tw-sub-navigation="start"'):]
    nav = nav[:nav.index("</nav>")]
    assert 'href="/admin/teams/1"' in nav and 'href="/admin/teams/1/edit"' in nav
    assert nav.count('aria-current="page"') == 1
    assert 'href="/admin/teams/1/projects" class' in nav and "Red rocket" in html
    active = nav[nav.index('aria-current="page"') - 300:nav.index('aria-current="page"')]
    assert "/admin/teams/1/projects" in active
    edit = c.get("/admin/teams/1/edit").text
    nav = edit[edit.index("data-tw-sub-navigation"):]
    active = nav[:nav.index('aria-current="page"')]
    assert active.rindex('href="/admin/teams/1/edit"') > active.rindex('href="/admin/teams/1"')
