"""Try the PWA plugin.

    pip install -e . -e plugins/pwa uvicorn
    uvicorn plugins.pwa.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
In Chrome or Edge, press the Install app button in the top bar (or the install
icon in the address bar). Service workers need https, or http://127.0.0.1 /
http://localhost while you try it out.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_pwa import PWAPlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.actions import DeleteAction, EditAction
from tungsten.forms import TextInput
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


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(30), default="")


class CustomerResource(Resource):
    model = Customer
    icon = "users"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required(), TextInput("phone").tel()])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable(), TextColumn("phone")]).actions(
            [EditAction(), DeleteAction()])


engine = create_engine("sqlite:///pwa_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Acme Admin", brand_tagline="Orders and customers on the go", spa=True)
panel.resources([CustomerResource])
panel.plugin(PWAPlugin(shortcuts=[("New customer", "customers/create"), ("Customers", "customers")]))
panel.create_tables(engine)

with Session() as db:
    if db.scalar(select(User)) is None:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.add_all([Customer(name="Ravi Kumar", phone="98100 00001"), Customer(name="Meena Shah", phone="98100 00002")])
        db.commit()

app = FastAPI()


@app.get("/")
def home():
    return RedirectResponse("/admin")


panel.mount(app)
