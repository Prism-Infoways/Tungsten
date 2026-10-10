"""Try the finance plugin.

    pip install -e . -e plugins/finance uvicorn
    uvicorn plugins.finance.example:app --reload     (from the repo root)

Open http://127.0.0.1:8000/admin and sign in with admin@example.com / password.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import Boolean, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from tungsten_finance import (
    Contact,
    Expense,
    ExpenseCategory,
    FinancePlugin,
    MoneyAccount,
    create_invoice,
    record_payment,
)
from tungsten_finance.service import ensure_default_categories

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


engine = create_engine("sqlite:///finance_demo.db")
Base.metadata.create_all(engine)
Session = sessionmaker(engine, expire_on_commit=False)

panel = Panel(path="/admin", session_factory=Session, secret_key="dev-only", auth=Auth(User),
              brand_name="Prism Studio", colors={"primary": "emerald"}, spa=True)
panel.plugin(FinancePlugin(business_address="12 MG Road\nPune 411001", business_tax_id="27ABCDE1234F1Z5",
                           business_email="accounts@example.com", terms="Payment within 15 days of the invoice.",
                           payment_details="Bank: HDFC 50200012345678, IFSC HDFC0000123\nUPI: studio@okhdfc"))
panel.create_tables(engine)


def seed() -> None:
    with Session() as db:
        if db.scalar(select(User)) is not None:
            return
        db.info["tungsten_panel"] = panel
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        ensure_default_categories(db)
        bank = MoneyAccount(name="HDFC current", kind="bank", number="…5678", opening_balance=Decimal(150000))
        cash = MoneyAccount(name="Cash box", kind="cash", opening_balance=Decimal(5000))
        db.add_all([bank, cash, Contact(name="WeWork Pune", kind="vendor", email="billing@example.com")])
        db.flush()
        today = dt.date.today()
        customers = [("Amit Traders", "amit@example.com"), ("Neha Stores", "neha@example.com"),
                     ("Rahul Exports", "rahul@example.com"), ("Sneha Foods", "sneha@example.com")]
        for i, (name, email) in enumerate(customers * 2):
            invoice = create_invoice(
                db, customer=name, email=email, issue_date=today - dt.timedelta(days=12 * i), status="sent",
                items=[{"description": "Website design", "quantity": 1, "unit_price": 18000 + 2000 * i,
                        "tax_rate": 18},
                       {"description": "Hosting (months)", "quantity": 6, "unit_price": 800, "tax_rate": 18}])
            if i % 3 == 1:
                record_payment(db, invoice, invoice.total, date=invoice.issue_date + dt.timedelta(days=5),
                               account_id=bank.id, method="upi")
            elif i % 3 == 2:
                record_payment(db, invoice, 10000, date=invoice.issue_date + dt.timedelta(days=3),
                               account_id=bank.id)
        categories = {c.name: c.id for c in db.scalars(select(ExpenseCategory))}
        for months_back in range(4):
            day = today - dt.timedelta(days=30 * months_back)
            db.add_all([
                Expense(description="Office rent", amount=Decimal(17700), tax_amount=Decimal(2700), date=day,
                        category_id=categories["Rent"], account_id=bank.id),
                Expense(description="Salaries", amount=Decimal(22000), date=day, category_id=categories["Salaries"],
                        account_id=bank.id),
                Expense(description="Figma and Google Workspace", amount=Decimal(4720), tax_amount=Decimal(720),
                        date=day, category_id=categories["Software"], account_id=bank.id, method="card"),
                Expense(description="Tea and snacks", amount=Decimal(1800), date=day, category_id=categories["Office"],
                        account_id=cash.id, method="cash"),
            ])
        db.commit()


seed()
app = FastAPI()
panel.mount(app)


@app.get("/")
def root():
    return RedirectResponse("/admin/")
