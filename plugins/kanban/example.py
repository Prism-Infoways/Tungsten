"""A task board demo. Run: uvicorn example:app --reload, then open http://127.0.0.1:8000/admin (admin@example.com / password)."""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_kanban import Board, KanbanPlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.forms import Select, Textarea, TextInput
from tungsten.tables import TextColumn

STATUSES = {"todo": ("To do", "gray"), "doing": ("Doing", "primary"), "review": ("Review", "warning"),
            "done": ("Done", "success")}


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="todo")
    sort: Mapped[int] = mapped_column(Integer, default=0)


class TaskResource(Resource):
    model = Task
    icon = "check-square"

    @classmethod
    def form(cls, form):
        options = {k: v[0] for k, v in STATUSES.items()}
        return form.schema([TextInput("title").required(), Select("status").options(options).default("todo"),
                            Textarea("notes")])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("title").searchable(), TextColumn("status").badge()])


engine = create_engine("sqlite:///kanban-demo.db")
Base.metadata.create_all(engine)
factory = sessionmaker(engine, expire_on_commit=False)
with factory() as db:
    if not db.query(User).first():
        db.add(User(name="Admin", email="admin@example.com", password=hash_password("password")))
        for i, (title, status) in enumerate([("Write the brief", "done"), ("Design the page", "doing"),
                                             ("Build the form", "todo"), ("Check on mobile", "review")]):
            db.add(Task(title=title, status=status, sort=i))
        db.commit()

panel = Panel(path="/admin", session_factory=factory, secret_key="change-me", auth=Auth(User))
panel.resources([TaskResource])
panel.plugin(KanbanPlugin(boards=[
    Board(TaskResource, column="status", columns=STATUSES, description="notes", order_column="sort",
          search=["title", "notes"], wip_limits={"doing": 3}),
]))
panel.create_tables(engine)
app = FastAPI()
panel.mount(app)
