"""Infolist CodeEntry/ViewEntry/entry actions and relation managers: pivot attach, associate,
polymorphic links, "has many through", separate relation pages and nested resources."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Table, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from tungsten import Panel, RelationManager, Resource
from tungsten.actions import (
    Action,
    AssociateAction,
    AttachAction,
    CreateAction,
    DeleteAction,
    DetachAction,
    DissociateAction,
    DissociateBulkAction,
    EditAction,
)
from tungsten.forms import Select, TextInput
from tungsten.infolists import CodeEntry, TextEntry, ViewEntry, highlight
from tungsten.relations import morph_many, morph_to_many
from tungsten.tables import TextColumn

from .conftest import PanelClient


class Base(DeclarativeBase):
    pass


team_members = Table("team_members", Base.metadata,
                     Column("team_id", ForeignKey("teams.id"), primary_key=True),
                     Column("member_id", ForeignKey("members.id"), primary_key=True),
                     Column("role", String(20), nullable=False, server_default="dev"))

taggables = Table("taggables", Base.metadata,
                  Column("tag_id", ForeignKey("tags.id"), primary_key=True),
                  Column("taggable_id", Integer, primary_key=True),
                  Column("taggable_type", String(20), primary_key=True))


class Member(Base):
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    members: Mapped[list[Member]] = relationship(secondary=team_members)
    projects: Mapped[list["Project"]] = relationship(back_populates="team")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team: Mapped[Team | None] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship()


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(String(100))
    commentable_id: Mapped[int | None] = mapped_column(nullable=True)
    commentable_type: Mapped[str | None] = mapped_column(String(20), nullable=True)


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    comments = morph_many("Comment", "commentable")
    tags = morph_to_many("Tag", "taggable", table="taggables")


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    comments = morph_many("Comment", "commentable")


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    lessons: Mapped[list["Lesson"]] = relationship(back_populates="course")


class Lesson(Base):
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    course: Mapped[Course] = relationship(back_populates="lessons")


# ---------------------------------------------------------------------- resources
class MembersRelationManager(RelationManager):
    relationship = "members"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name"), TextColumn("pivot.role").label("Role")]).header_actions([
            AttachAction().form([Select("role").options({"lead": "Lead", "dev": "Developer"}).required()]),
        ]).actions([DetachAction()])


class ProjectsRelationManager(RelationManager):
    relationship = "projects"
    separate_page = True

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name")]).header_actions([CreateAction(), AssociateAction()]).actions(
            [DissociateAction()]).bulk_actions([DissociateBulkAction()])


class TasksRelationManager(RelationManager):
    relationship = "projects.tasks"
    separate_page = True

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("title").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("title")]).header_actions([CreateAction()]).actions(
            [EditAction(), DeleteAction()])


def mail_action():
    return Action("mail").icon("mail").url(lambda record: f"mailto:{record.name.lower()}@example.com")


class TeamResource(Resource):
    model = Team
    relations = [MembersRelationManager, ProjectsRelationManager, TasksRelationManager]

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name")])

    @classmethod
    def infolist(cls, infolist):
        return infolist.schema([
            TextEntry("name").suffix_action(mail_action()).actions([
                Action("shout").label("Shout").requires_confirmation()
                .action(lambda record, db: setattr(record, "name", record.name.upper()) or db.commit()),
            ]),
            CodeEntry("settings").line_numbers(),
            ViewEntry("name", "team-card.html").view_data({"motto": "Ship it"}),
        ])


class CommentsRelationManager(RelationManager):
    relationship = "comments"
    record_title_attribute = "body"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("body").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("body")]).header_actions([CreateAction(), AssociateAction()]).actions(
            [DissociateAction()])


class TagsRelationManager(RelationManager):
    relationship = "tags"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name")]).header_actions([CreateAction(), AttachAction()]).actions(
            [DetachAction()])


class PostResource(Resource):
    model = Post
    relations = [CommentsRelationManager, TagsRelationManager]

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("title").required()])


class LessonResource(Resource):
    model = Lesson
    parent_relationship = "course"
    global_search_attributes = ["title"]

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("title").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("title")]).header_actions([CreateAction()]).actions([EditAction()])


class LessonsRelationManager(RelationManager):
    relationship = "lessons"
    related_resource = LessonResource


class CourseResource(Resource):
    model = Course
    relations = [LessonsRelationManager]

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name")])


LessonResource.parent_resource = CourseResource


@pytest.fixture()
def env(tmp_path):
    (tmp_path / "team-card.html").write_text('<p id="team-card">{{ state }} / {{ motto }} / {{ record.id }}</p>')
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(engine, expire_on_commit=False)
    with Session() as db:
        red = Team(name="Red", settings={"plan": "pro", "seats": 5, "beta": True})
        blue = Team(name="Blue")
        ann, bob, cid = Member(name="Ann"), Member(name="Bob"), Member(name="Cid")
        db.add_all([red, blue, ann, bob, cid])
        db.flush()
        red.members.append(ann)
        p1, p2, p3 = Project(name="Rocket", team=red), Project(name="Racer", team=red), Project(name="Bird", team=blue)
        db.add_all([p1, p2, p3])
        db.flush()
        db.add_all([Task(title="Fuel", project_id=p1.id), Task(title="Wheels", project_id=p2.id),
                    Task(title="Wings", project_id=p3.id)])
        post, video = Post(title="Hello"), Video(title="Clip")
        db.add_all([post, video, Tag(name="news"), Tag(name="tips")])
        db.flush()
        db.add_all([Comment(body="Nice post", commentable_id=post.id, commentable_type="posts"),
                    Comment(body="Nice clip", commentable_id=video.id, commentable_type="videos"),
                    Comment(body="Loose", commentable_id=None, commentable_type=None)])
        course = Course(name="Python")
        db.add_all([course, Course(name="Go")])
        db.flush()
        db.add_all([Lesson(title="Intro", course=course), Lesson(title="Loops", course=course)])
        db.commit()
    panel = Panel(engine=engine, secret_key="x", dashboard=None, template_dirs=[str(tmp_path)])
    panel.resources([TeamResource, PostResource, CourseResource, LessonResource])
    app = FastAPI()
    panel.mount(app)
    c = PanelClient(TestClient(app))
    c.get("/admin/teams")
    return c, Session


def act(c, host, scope, action, record="", **data):
    return c.post("/admin/_tw/action", {"_tw_host": host, "_tw_scope": scope, "_tw_name": action,
                                        "_tw_record": record, **data})


def trigger(r):
    return r.headers.get("HX-Trigger", "")


# ---------------------------------------------------------------------- infolists
def test_code_view_entries_and_entry_actions(env):
    c, Session = env
    html = c.get("/admin/teams/1").text
    # CodeEntry: dicts shown as coloured, pretty JSON with line numbers and a copy button
    assert "language-json" in html and "text-info-700" in html and "&#34;plan&#34;" in html
    assert 'title="Copy"' in html
    # ViewEntry renders the user's template with state, record and view_data
    assert '<p id="team-card">Red / Ship it / 1</p>' in html
    # entry actions: a url action after the value, a modal action under it
    assert 'href="mailto:red@example.com"' in html
    assert '"_tw_scope": "infolist"' in html and '"_tw_name": "shout"' in html
    r = c.get("/admin/_tw/action", params={"_tw_host": "resource:teams", "_tw_scope": "infolist",
                                           "_tw_name": "shout", "_tw_record": "1"}, htmx=True)
    assert r.status_code == 200 and "Shout" in r.text
    r = act(c, "resource:teams", "infolist", "shout", "1")
    assert r.status_code in (200, 204)
    with Session() as db:
        assert db.get(Team, 1).name == "RED"
    # an unknown entry action is not found
    assert "Page not found" in trigger(act(c, "resource:teams", "infolist", "nope", "1"))


def test_code_entry_placeholder_and_highlight():
    out = str(highlight('def f(x):  # add\n    return "a" + 1', "python"))
    assert 'text-purple-700' in out and "italic" in out and "text-success-700" in out and "text-warning-700" in out
    assert "&lt;b&gt;" in str(highlight("<b>", None))  # always escaped
    sql = str(highlight("SELECT * FROM t WHERE a = 'x'", "sql"))
    assert "text-purple-700" in sql and "text-success-700" in sql


def test_code_entry_empty_shows_placeholder(env):
    c, _ = env
    html = c.get("/admin/teams/2").text  # Blue has no settings
    assert "language-json" not in html and "—" in html


# ---------------------------------------------------------------------- relations
def test_attach_saves_pivot_fields_and_table_shows_them(env):
    c, Session = env
    host = "relation:teams:1:members"
    r = c.get("/admin/_tw/action", params={"_tw_host": host, "_tw_scope": "table", "_tw_name": "attach"}, htmx=True)
    assert 'name="role"' in r.text and ">Bob<" in r.text and ">Ann<" not in r.text
    r = act(c, host, "table", "attach", records=["2"], role="lead")
    assert "Attached" in trigger(r)
    with Session() as db:
        rows = db.execute(select(team_members)).mappings().all()
        assert {(row["member_id"], row["role"]) for row in rows} == {(1, "dev"), (2, "lead")}
    html = c.get("/admin/_tw/table", params={"host": host}, htmx=True).text
    assert "lead" in html and "dev" in html
    # the role is required
    r = act(c, host, "table", "attach", records=["3"])
    assert "Attached" not in trigger(r)
    r = act(c, host, "row", "detach", "2")
    assert "Detached" in trigger(r)
    with Session() as db:
        assert [m.id for m in db.get(Team, 1).members] == [1]
        assert db.get(Member, 2) is not None


def test_associate_and_dissociate_one_to_many(env):
    c, Session = env
    host = "relation:teams:1:projects"
    r = c.get("/admin/_tw/action", params={"_tw_host": host, "_tw_scope": "table", "_tw_name": "associate"},
              htmx=True)
    assert ">Bird<" in r.text and ">Rocket<" not in r.text
    r = act(c, host, "table", "associate", records=["3"])
    assert "Associated" in trigger(r)
    with Session() as db:
        assert db.get(Project, 3).team_id == 1
    r = act(c, host, "row", "dissociate", "1")
    assert "Dissociated" in trigger(r)
    with Session() as db:
        assert db.get(Project, 1).team_id is None and db.get(Project, 1) is not None
    r = c.post("/admin/_tw/action", {"_tw_host": host, "_tw_scope": "bulk", "_tw_name": "dissociate",
                                     "records": ["2", "3"]})
    assert "Dissociated" in trigger(r)
    with Session() as db:
        assert db.scalars(select(Project).where(Project.team_id == 1)).all() == []


def test_polymorphic_one_to_many_and_many_to_many(env):
    c, Session = env
    host = "relation:posts:1:comments"
    html = c.get("/admin/_tw/table", params={"host": host}, htmx=True).text
    assert "Nice post" in html and "Nice clip" not in html
    r = act(c, host, "table", "create", body="Fresh")
    assert "Created" in trigger(r)
    with Session() as db:
        fresh = db.scalars(select(Comment).where(Comment.body == "Fresh")).one()
        assert (fresh.commentable_id, fresh.commentable_type) == (1, "posts")
    # associate offers comments not on this post; linking fills both columns
    r = c.get("/admin/_tw/action", params={"_tw_host": host, "_tw_scope": "table", "_tw_name": "associate"},
              htmx=True)
    assert "Loose" in r.text and "Nice post" not in r.text
    r = act(c, host, "table", "associate", records=["3"])
    assert "Associated" in trigger(r)
    with Session() as db:
        loose = db.get(Comment, 3)
        assert (loose.commentable_id, loose.commentable_type) == (1, "posts")
    act(c, host, "row", "dissociate", "3")
    with Session() as db:
        loose = db.get(Comment, 3)
        assert (loose.commentable_id, loose.commentable_type) == (None, None)
    # many-to-many with a type column on the link table
    host = "relation:posts:1:tags"
    r = act(c, host, "table", "attach", records=["1", "2"])
    assert "Attached" in trigger(r)
    with Session() as db:
        rows = db.execute(select(taggables)).mappings().all()
        assert {(r["tag_id"], r["taggable_id"], r["taggable_type"]) for r in rows} == {(1, 1, "posts"), (2, 1, "posts")}
        db.execute(taggables.insert().values(tag_id=1, taggable_id=1, taggable_type="videos"))
        db.commit()
    html = c.get("/admin/_tw/table", params={"host": host}, htmx=True).text
    assert html.count("news") == 1  # the "videos" link row is not this post's
    act(c, host, "row", "detach", "1")
    with Session() as db:
        rows = db.execute(select(taggables)).mappings().all()
        assert {(r["tag_id"], r["taggable_type"]) for r in rows} == {(2, "posts"), (1, "videos")}
    r = act(c, host, "table", "create", name="howto")
    assert "Created" in trigger(r)
    with Session() as db:
        new = db.scalars(select(Tag).where(Tag.name == "howto")).one()
        assert db.execute(select(taggables).where(taggables.c.tag_id == new.id)).mappings().one()["taggable_type"] == "posts"


def test_has_many_through_is_listed_but_never_linked(env):
    c, Session = env
    host = "relation:teams:1:projects.tasks"
    html = c.get("/admin/_tw/table", params={"host": host}, htmx=True).text
    assert "Fuel" in html and "Wheels" in html and "Wings" not in html
    assert '"_tw_name": "create"' not in html  # can't create through a path
    assert "Not allowed" in trigger(act(c, host, "table", "create", title="Nope"))
    r = act(c, host, "row", "edit", "1", title="Fuel up")
    assert "Saved" in trigger(r)
    r = act(c, host, "row", "delete", "2")
    assert "Deleted" in trigger(r)
    with Session() as db:
        assert db.get(Task, 1).title == "Fuel up" and db.get(Task, 2) is None
    # tasks of another team are not reachable through this owner
    assert "Page not found" in trigger(act(c, host, "row", "edit", "3", title="x"))


def test_relation_on_its_own_page(env):
    c, _ = env
    html = c.get("/admin/teams/1/edit").text
    # separate pages are linked from the record, not shown under the form
    assert 'href="/admin/teams/1/projects"' in html and 'href="/admin/teams/1/projects-tasks"' in html
    assert "relation:teams:1:projects" not in html and "relation:teams:1:members" in html
    page = c.get("/admin/teams/1/projects")
    assert page.status_code == 200
    assert "Rocket" in page.text and "Bird" not in page.text and 'aria-current="page"' in page.text
    assert 'href="/admin/teams"' in page.text  # breadcrumbs
    assert "Fuel" in c.get("/admin/teams/1/projects-tasks").text
    assert c.get("/admin/teams/1/nothing").status_code == 404
    assert c.get("/admin/teams/99/projects").status_code == 404


def test_nested_resource_pages(env):
    c, Session = env
    # the nested resource is not in the menu and its own list goes to the parent
    html = c.get("/admin/courses").text
    assert 'href="/admin/lessons"' not in html
    assert c.get("/admin/lessons", follow_redirects=False).headers["location"] == "/admin/courses"
    # the parent lists its lessons with links to nested pages
    edit = c.get("/admin/courses/1/edit").text
    assert "/admin/courses/1/lessons/1/edit" in edit and 'href="/admin/courses/1/lessons/create"' in edit
    page = c.get("/admin/courses/1/lessons/create")
    assert page.status_code == 200 and 'name="title"' in page.text and 'href="/admin/courses/1/edit"' in page.text
    r = c.post("/admin/courses/1/lessons/create", {"title": "Classes"})
    assert r.status_code == 204
    with Session() as db:
        lesson = db.scalars(select(Lesson).where(Lesson.title == "Classes")).one()
        assert lesson.course_id == 1
    assert f"/admin/courses/1/lessons/{lesson.id}/edit" in r.headers.get("HX-Redirect", r.headers.get("HX-Location", ""))
    page = c.get(f"/admin/courses/1/lessons/{lesson.id}/edit")
    assert page.status_code == 200 and 'value="Classes"' in page.text
    r = c.post(f"/admin/courses/1/lessons/{lesson.id}/edit", {"title": "OOP"})
    assert "Saved" in trigger(r)
    with Session() as db:
        assert db.get(Lesson, lesson.id).title == "OOP"
    # a lesson of the course is only reachable under its own course
    assert c.get(f"/admin/courses/2/lessons/{lesson.id}/edit").status_code == 404
    # the old flat URL sends you to the nested one
    r = c.get("/admin/lessons/1/edit", follow_redirects=False)
    assert r.headers["location"] == "/admin/courses/1/lessons/1/edit"
    # deleting on the nested page goes back to the parent
    r = act(c, "relation:courses:1:lessons", "page", "delete", str(lesson.id))
    assert r.headers.get("HX-Redirect") == "/admin/courses/1/edit"
    with Session() as db:
        assert db.get(Lesson, lesson.id) is None
