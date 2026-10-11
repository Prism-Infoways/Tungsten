"""Try the quick create plugin.

    pip install -e . -e plugins/quick-create uvicorn
    uvicorn example:app --app-dir plugins/quick-create --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password,
then click "+ New" in the top bar. With tungsten-tickets or tungsten-leads
installed, their forms show up in the menu too.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, Numeric, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_quick_create import QuickCreatePlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.forms import Select, TextInput
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


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(60), nullable=True)


class ProductResource(Resource):
    model = Product
    icon = "package"
    navigation_group = "Shop"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required(), TextInput("price").numeric().required()]).columns(2)

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable(), TextColumn("price")])


class CustomerResource(Resource):
    model = Customer
    icon = "users"
    navigation_group = "Shop"

    @classmethod
    def form(cls, form):
        return form.schema([TextInput("name").required(),
                            Select("city").options({"Delhi": "Delhi", "Mumbai": "Mumbai", "Pune": "Pune"})])

    @classmethod
    def table(cls, table):
        return table.columns([TextColumn("name").searchable(), TextColumn("city")])


engine = create_engine("sqlite:///quick_create_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Tungsten", navigation_groups=["Shop"])
panel.resources([ProductResource, CustomerResource])

try:  # other plugins join the menu by themselves
    from tungsten_tickets import TicketsPlugin

    panel.plugin(TicketsPlugin(portal=False))
except ImportError:
    pass
try:
    from tungsten_leads import LeadsPlugin

    panel.plugin(LeadsPlugin())
except ImportError:
    pass

quick = QuickCreatePlugin(shortcut="mod+shift+n")
panel.plugin(quick)
quick.add_link("docs", "Read the docs", "https://tungsten.prisminfoways.com/docs/quick-create", icon="book-open",
               group="Help")
panel.create_tables(engine)

with Session() as db:
    if db.scalar(select(User)) is None:
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.commit()

app = FastAPI()
panel.mount(app)


@app.get("/")
def root():
    return RedirectResponse("/admin/")
