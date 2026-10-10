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
    FinancePlugin,
    Item,
    LedgerAccount,
    create_bill,
    create_document,
    create_invoice,
    ensure_chart,
    record_payment,
)
from tungsten_finance.ledger import post_expense

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
panel.plugin(FinancePlugin(state="27", business_address="12 MG Road\nPune 411001", business_tax_id="27ABCDE1234F1Z5",
                           business_email="accounts@example.com", terms="Payment within 15 days of the invoice.",
                           payment_details="Bank: HDFC 50200012345678, IFSC HDFC0000123\nUPI: studio@okhdfc"))
panel.create_tables(engine)


def seed() -> None:
    with Session() as db:
        if db.scalar(select(User)) is not None:
            return
        db.info["tungsten_panel"] = panel
        db.add(User(name="Asha Admin", email="admin@example.com", password=hash_password("password")))
        ensure_chart(db)
        bank = LedgerAccount(code="1100", name="HDFC current", kind="bank", number="…5678",
                             opening_balance=Decimal(150000))
        db.add_all([bank,
                    Contact(name="WeWork Pune", kind="vendor", email="billing@example.com", state="27"),
                    Item(name="Website design", kind="service", hsn="998314", unit="job", sale_price=Decimal(20000),
                         tax_rate=Decimal(18)),
                    Item(name="Hosting (months)", kind="service", hsn="998315", unit="month", sale_price=Decimal(800),
                         tax_rate=Decimal(18)),
                    Item(name="Printed brochure", sku="BRO-A4", hsn="4911", unit="pcs", sale_price=Decimal(40),
                         purchase_price=Decimal(22), tax_rate=Decimal(12), track_stock=True,
                         opening_stock=Decimal(200), reorder_level=Decimal(100))])
        cash = db.scalars(select(LedgerAccount).where(LedgerAccount.system_key == "cash")).one()
        cash.opening_balance = Decimal(5000)
        capital = db.scalars(select(LedgerAccount).where(LedgerAccount.system_key == "capital")).one()
        capital.opening_balance, capital.opening_side = Decimal(155000), "cr"
        db.flush()
        today = dt.date.today()
        customers = [("Amit Traders", "amit@example.com", "27"), ("Neha Stores", "neha@example.com", "27"),
                     ("Rahul Exports", "rahul@example.com", "29"), ("Sneha Foods", "sneha@example.com", "07")]
        for name, email, state in customers:
            db.add(Contact(name=name, email=email, kind="customer", state=state))
        db.flush()
        for i, (name, email, _) in enumerate(customers * 2):
            invoice = create_invoice(
                db, customer=name, email=email, issue_date=today - dt.timedelta(days=12 * i), status="sent",
                items=[{"description": "Website design", "quantity": 1, "unit_price": 18000 + 2000 * i,
                        "tax_rate": 18, "hsn": "998314"},
                       {"description": "Hosting (months)", "quantity": 6, "unit_price": 800, "tax_rate": 18,
                        "hsn": "998315"},
                       {"sku": "BRO-A4", "quantity": 25}])
            if i % 3 == 1:
                record_payment(db, invoice, invoice.total, date=invoice.issue_date + dt.timedelta(days=5),
                               account_id=bank.id, method="upi")
            elif i % 3 == 2:
                record_payment(db, invoice, 10000, date=invoice.issue_date + dt.timedelta(days=3),
                               account_id=bank.id)
        create_document(db, "quote", name="Rahul Exports", items=[{"description": "Mobile app", "quantity": 1,
                                                                   "unit_price": 150000, "tax_rate": 18}])
        bill = create_bill(db, vendor="Print Hub", reference="PH/221", issue_date=today - dt.timedelta(days=20),
                           items=[{"sku": "BRO-A4", "quantity": 300}])
        record_payment(db, bill, bill.total, date=today - dt.timedelta(days=10), account_id=bank.id)
        accounts = {a.name: a.id for a in db.scalars(select(LedgerAccount))}
        for months_back in range(4):
            day = today - dt.timedelta(days=30 * months_back)
            expenses = [
                Expense(description="Office rent", amount=Decimal(17700), tax_amount=Decimal(2700), date=day,
                        category_id=accounts["Rent"], account_id=bank.id),
                Expense(description="Salaries", amount=Decimal(22000), date=day, category_id=accounts["Salaries"],
                        account_id=bank.id),
                Expense(description="Figma and Google Workspace", amount=Decimal(4720), tax_amount=Decimal(720),
                        date=day, category_id=accounts["Software"], account_id=bank.id, method="card"),
                Expense(description="Tea and snacks", amount=Decimal(1800), date=day,
                        category_id=accounts["Office"], account_id=cash.id, method="cash"),
            ]
            db.add_all(expenses)
            db.flush()
            for expense in expenses:
                post_expense(db, expense)
        db.commit()


seed()
app = FastAPI()
panel.mount(app)


@app.get("/")
def root():
    return RedirectResponse("/admin/")
