"""Try the backups plugin.

    pip install -e . -e plugins/backups -e plugins/security-audit uvicorn
    uvicorn plugins.backups.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
Backups is under Settings. The Security audit gets a "Recent backup" check.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_backups import BackupsPlugin

from tungsten import Auth, LocalStorage, Panel, Resource, hash_password
from tungsten.forms import FileUpload, TextInput
from tungsten.tables import TextColumn


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    file: Mapped[str | None] = mapped_column(String(300), nullable=True)


class DocumentResource(Resource):
    model = Document

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("title").required(), FileUpload("file").directory("documents")])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("title").searchable(), TextColumn("file")])


engine = create_engine("sqlite:///backups_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Tungsten Shop", storage=LocalStorage("storage/tungsten"), activity_log=True, spa=True)
panel.resources([DocumentResource])
try:  # the audit's "Recent backup" check shows how the plugins work together
    from tungsten_security_audit import SecurityAuditPlugin

    panel.plugin(SecurityAuditPlugin())
except ImportError:
    pass
panel.plugin(BackupsPlugin(folder="storage/backups", keep=10))
panel.create_tables(engine)

with Session() as db:
    if db.scalar(select(User)) is None:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.add_all([Document(title=f"Invoice {n}") for n in range(1, 6)])
        db.commit()

app = FastAPI()


@app.get("/")
def home():
    return RedirectResponse("/admin")


panel.mount(app)
