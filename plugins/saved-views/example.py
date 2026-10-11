"""Try the saved views plugin.

    pip install -e . -e plugins/saved-views uvicorn
    uvicorn plugins.saved-views.example:app --reload     (from plugins/saved-views: uvicorn example:app)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
On the Orders list, pick a filter or a search, then click "Save view".
"""

from __future__ import annotations

import datetime as dt
import random

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, Date, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_saved_views import SavedViewsPlugin

from tungsten import Auth, Panel, Resource, hash_password
from tungsten.forms import DatePicker, Select, TextInput
from tungsten.tables import DateFilter, ListTab, SelectFilter, TextColumn

STATUSES = {"new": "New", "pending": "Pending", "shipped": "Shipped", "cancelled": "Cancelled"}


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="new")
    owner_id: Mapped[str] = mapped_column(String(20), default="")
    total: Mapped[int] = mapped_column(Integer, default=0)
    placed_on: Mapped[dt.date] = mapped_column(Date, default=dt.date.today)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)


def user_options(db):
    return {str(u.id): u.name for u in db.scalars(select(User)).all()}


class OrderResource(Resource):
    model = Order
    icon = "shopping-cart"
    soft_delete_column = None

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("customer").required(),
            Select("status").options(STATUSES).required(),
            Select("owner_id").label("Owner").options(user_options),
            TextInput("total").integer(),
            DatePicker("placed_on"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("customer").searchable().sortable(),
                TextColumn("status").badge().sortable(),
                TextColumn("owner_id").label("Owner").state(lambda record, db: user_options(db).get(record.owner_id))
                .toggleable(),
                TextColumn("total").sortable().toggleable(),
                TextColumn("placed_on").date().sortable().toggleable(),
            ])
            .filters([
                SelectFilter("status").options(STATUSES),
                SelectFilter("owner_id").label("Owner").options(user_options),
                DateFilter("placed_on"),
            ])
            .tabs([ListTab("all").label("All").badge(),
                   ListTab("unpaid").label("Unpaid").query(lambda query, model: query.where(model.is_paid.is_(False)))])
        )


engine = create_engine("sqlite:///saved_views_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

views = SavedViewsPlugin()
# a ready view for everyone; {me} is the signed-in user
views.preset("orders", "My orders", "filters.owner_id.value={me}", icon="user-round", color="primary")

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Tungsten Shop", spa=True)
panel.resources([OrderResource])
panel.plugin(views)
panel.create_tables(engine)


def seed() -> None:
    with Session() as db:
        if db.scalar(select(User)) is not None:
            return
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.add(User(name="Ravi Sales", email="ravi@example.com", password=hash_password("password")))
        rnd = random.Random(7)
        names = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Sara", "Vihaan", "Zoya", "Ishaan", "Anaya"]
        for i in range(40):
            db.add(Order(customer=f"{rnd.choice(names)} {i + 1}", status=rnd.choice(list(STATUSES)),
                         owner_id=rnd.choice(["1", "2"]), total=rnd.randint(300, 9000), is_paid=rnd.random() < 0.5,
                         placed_on=dt.date.today() - dt.timedelta(days=rnd.randint(0, 60))))
        db.commit()


seed()
app = FastAPI()
panel.mount(app)


@app.get("/")
def home():
    return RedirectResponse("/admin")
