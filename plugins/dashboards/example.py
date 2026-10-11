"""Try the dashboards plugin, with widgets from the HR, Finance and Tickets plugins when they are installed.

    pip install -e . -e plugins/dashboards uvicorn
    pip install -e plugins/hr -e plugins/finance -e plugins/tickets   # optional: more widgets to pick
    uvicorn plugins.dashboards.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
Go to Dashboards, click "New dashboard", then drag widgets around.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_dashboards import DashboardsPlugin

from tungsten import Auth, ChartWidget, Panel, Resource, Stat, StatsOverviewWidget, hash_password


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


class TeamStats(StatsOverviewWidget):
    @classmethod
    def stats(cls, db):
        users = db.scalar(select(func.count()).select_from(User)) or 0
        return [Stat("Team members", users).icon("users"), Stat("Open tasks", 14).icon("list-checks").color("warning")]


class VisitsChart(ChartWidget):
    heading = "Visits this week"
    icon = "chart-line"

    @classmethod
    def data(cls, ctx, filter=None):
        return {"labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                "datasets": [{"label": "Visits", "data": [120, 180, 150, 210, 260, 140, 90]}]}


engine = create_engine("sqlite:///dashboards_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Tungsten", spa=True)
panel.resources([UserResource])
panel.widgets([TeamStats, VisitsChart])

# other plugins bring their own widgets; they show up in the "Add widgets" list by themselves
for module, name in (("tungsten_hr", "HRPlugin"), ("tungsten_finance", "FinancePlugin"),
                     ("tungsten_tickets", "TicketsPlugin")):
    try:
        panel.plugin(getattr(__import__(module), name)())
    except ImportError:
        pass

dashboards = DashboardsPlugin()
dashboards.add_template("Team", [TeamStats, VisitsChart])
panel.plugin(dashboards)
panel.create_tables(engine)

with Session() as db:
    if db.scalar(select(User)) is None:
        db.add(User(name="Admin", email="admin@example.com", password=hash_password("password")))
        db.commit()

app = FastAPI()
panel.mount(app)


@app.get("/")
def home():
    return RedirectResponse("/admin")
