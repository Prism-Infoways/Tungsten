"""Try the leads plugin.

    pip install -e . -e plugins/leads uvicorn
    uvicorn plugins.leads.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
"""

from __future__ import annotations

import datetime as dt

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten import Auth, Panel, hash_password

from tungsten_leads import LeadField, LeadsPlugin, add_activity, create_lead


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


engine = create_engine("sqlite:///leads_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Tungsten CRM", colors={"primary": "orange"}, spa=True)
panel.plugin(LeadsPlugin(capture_token="demo-token"))
panel.create_tables(engine)


def seed() -> None:
    with Session() as db:
        if db.scalar(select(User)) is not None:
            return
        db.add_all([User(name="Asha Admin", email="admin@example.com", password=hash_password("password")),
                    User(name="Rohit Sales", email="rohit@example.com", password=hash_password("password"))])
        db.add_all([
            LeadField(label="Budget", key="budget", type="number", sort=1),
            LeadField(label="City", key="city", type="text", sort=2),
            LeadField(label="Interested in", key="interest", type="select", options=["Website", "App", "SEO"], sort=3),
            LeadField(label="Best time to call", key="call_time", type="multiselect",
                      options=["Morning", "Afternoon", "Evening"], sort=4),
        ])
        db.flush()
        people = [("Amit Sharma", "new", "meta"), ("Priya Patel", "contacted", "website"),
                  ("Rahul Verma", "qualified", "whatsapp"), ("Sneha Iyer", "proposal", "referral"),
                  ("Vikram Singh", "won", "meta"), ("Neha Gupta", "lost", "manual")]
        for i, (name, status, source) in enumerate(people):
            lead = create_lead(db, name=name, email=f"{name.split()[0].lower()}@example.com",
                               phone=f"+91 98765 4321{i}", source=source, status=status, assigned_to="1",
                               custom_fields={"budget": 50000 * (i + 1), "city": ["Pune", "Mumbai", "Delhi"][i % 3],
                                              "interest": ["Website", "App", "SEO"][i % 3]})
            lead.follow_up_at = dt.datetime.now() + dt.timedelta(days=i - 2)
            add_activity(db, lead, "Called, asked for a quote", type="call", user_id="1")
        db.commit()


seed()
app = FastAPI()
panel.mount(app)


@app.get("/")
def root():
    return RedirectResponse("/admin/")
