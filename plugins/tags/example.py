"""Try the tags plugin, next to Leads, Tickets and HR.

    pip install -e . -e plugins/tags -e plugins/leads -e plugins/tickets -e plugins/hr uvicorn
    uvicorn plugins.tags.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
"""

from __future__ import annotations

import datetime as dt

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_hr import Employee, HRPlugin
from tungsten_leads import Lead, LeadsPlugin
from tungsten_tags import Tag, TagsPlugin
from tungsten_tickets import TicketsPlugin, create_ticket

from tungsten import Auth, Panel, hash_password


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


engine = create_engine("sqlite:///tags_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Tungsten CRM", spa=True)
panel.plugin(LeadsPlugin())
panel.plugin(TicketsPlugin(email_requester=False))
panel.plugin(HRPlugin())
panel.plugin(TagsPlugin())
panel.create_tables(engine)
panel.boot()  # the tags plugin finds Leads, Tickets and HR here


def seed() -> None:
    with Session() as db:
        if db.scalar(select(User)) is not None:
            return
        db.info["tungsten_panel"] = panel
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        db.add_all([Tag(name="VIP", key="vip", color="danger", description="Our biggest customers"),
                    Tag(name="Follow up", key="follow up", color="warning"),
                    Tag(name="Webinar", key="webinar", color="info"),
                    Tag(name="Delhi", key="delhi", color="purple")])
        db.commit()
        db.add_all([Lead(name="Amit Sharma", company="Sharma Traders", tags=["VIP", "Delhi"]),
                    Lead(name="Priya Patel", company="Patel Foods", tags=["Webinar", "Follow up"]),
                    Lead(name="Rahul Verma", tags=["Webinar"]), Lead(name="Sneha Iyer")])
        ticket = create_ticket(db, subject="Charged twice for my plan", requester_name="Amit Sharma",
                               requester_email="amit@example.com")
        ticket.tags = ["VIP"]
        db.add(Employee(code="EMP-0001", first_name="Ravi", last_name="Kumar", joined_on=dt.date(2025, 4, 1)))
        db.commit()
        panel.get_plugin("tags").set_tags(db, db.scalars(select(Employee)).one(), ["Delhi"])
        db.commit()


seed()
app = FastAPI()
panel.mount(app)


@app.get("/")
def root():
    return RedirectResponse("/admin/")
