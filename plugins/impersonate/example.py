"""Try the impersonate plugin.

    pip install -e . -e plugins/impersonate uvicorn
    uvicorn plugins.impersonate.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password,
then press "Log in as" on a user.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_impersonate import ImpersonatePlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.actions import EditAction
from tungsten.forms import TextInput, Toggle
from tungsten.tables import IconColumn, TextColumn


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserResource(Resource):
    model = User
    icon = "users"
    record_title_attribute = "name"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required(), TextInput("email").email().required(),
                            Toggle("is_active").label("Active")])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable(), TextColumn("email").searchable(),
                              IconColumn("is_active").label("Active").boolean()]).actions([EditAction()])


engine = create_engine("sqlite:///impersonate_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

with Session() as db:
    if db.scalars(select(User)).first() is None:
        for name, email in [("Asha Admin", "admin@example.com"), ("Ravi Agent", "ravi@example.com"),
                            ("Meena Customer", "meena@example.com")]:
            db.add(User(name=name, email=email, password=hash_password("password")))
        db.commit()

panel = Panel(path="/admin", brand_name="Impersonate demo", session_factory=Session, secret_key="change-me",
              auth=Auth(User, active_field="is_active"))
panel.resources([UserResource])
panel.plugin(ImpersonatePlugin(max_minutes=30))
panel.create_tables(engine)

app = FastAPI()
panel.mount(app)


@app.get("/")
def home():
    return RedirectResponse("/admin")
