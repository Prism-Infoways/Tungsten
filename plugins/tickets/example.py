"""Try the tickets plugin.

    pip install -e . -e plugins/tickets uvicorn
    uvicorn plugins.tickets.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
The customer page is http://127.0.0.1:8000/admin/support
"""

from __future__ import annotations

import datetime as dt

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_tickets import SavedReply, TicketCategory, TicketsPlugin, add_reply, create_ticket

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


engine = create_engine("sqlite:///tickets_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Tungsten Desk", colors={"primary": "indigo"}, spa=True)
panel.plugin(TicketsPlugin(api_token="demo-token"))
panel.create_tables(engine)


def seed() -> None:
    with Session() as db:
        if db.scalar(select(User)) is not None:
            return
        db.info["tungsten_panel"] = panel
        db.add_all([User(name="Asha Admin", email="admin@example.com", password=hash_password("password")),
                    User(name="Rohit Support", email="rohit@example.com", password=hash_password("password"))])
        db.add_all([TicketCategory(name="Billing", color="success", assign_to="2", sort=1),
                    TicketCategory(name="Technical", color="info", sort=2),
                    TicketCategory(name="Sales", color="purple", sort=3)])
        db.add_all([SavedReply(title="Password reset", body="Please use 'Forgot password' on the login page. "
                                                             "The link in the email works for one hour."),
                    SavedReply(title="Refund time", body="Refunds reach your bank in 5 to 7 working days.")])
        db.flush()
        rows = [("Charged twice for my plan", "high", 1, "Amit Sharma"),
                ("Can't log in after the update", "urgent", 2, "Priya Patel"),
                ("Need a quote for 20 users", "normal", 3, "Rahul Verma"),
                ("Export to Excel is slow", "low", 2, "Sneha Iyer"),
                ("Invoice has the wrong GST number", "normal", 1, "Vikram Singh")]
        for subject, priority, category, name in rows:
            ticket = create_ticket(db, subject=subject, description=f"Hi, {subject.lower()}. Please help.",
                                   requester_name=name, requester_email=f"{name.split()[0].lower()}@example.com",
                                   priority=priority, category_id=category, source="portal")
            if category == 1:
                add_reply(db, ticket, "Sorry about that! We are checking it with the bank.", user_id="2",
                          status="in_progress")
                add_reply(db, ticket, "Bank says the second charge is on hold.", user_id="2", internal=True)
            if priority == "urgent":  # show one overdue ticket
                ticket.due_at = dt.datetime.now() - dt.timedelta(hours=2)
        db.commit()


seed()
app = FastAPI()
panel.mount(app)


@app.get("/")
def root():
    return RedirectResponse("/admin/")
