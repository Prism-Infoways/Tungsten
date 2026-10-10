"""Functions other code (and other plugins) use to bill customers and book money.

    from tungsten_finance import create_invoice, record_payment

    invoice = create_invoice(db, customer="Amit Traders", email="amit@example.com",
                             items=[{"description": "Website design", "quantity": 1, "unit_price": 25000,
                                     "tax_rate": 18}])
    record_payment(db, invoice, 10000, method="upi", reference="UTR 1234")
    db.commit()
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from .models import CENT, ZERO, Contact, Expense, ExpenseCategory, Invoice, InvoiceItem, MoneyAccount, Payment

INVOICE_STATUSES = {
    "draft": ("Draft", "gray"),
    "sent": ("Sent", "info"),
    "partial": ("Part paid", "warning"),
    "paid": ("Paid", "success"),
    "overdue": ("Overdue", "danger"),
    "cancelled": ("Cancelled", "gray"),
}
#: invoices that still wait for money
OPEN_STATUSES = ("sent", "partial")
METHODS = {"bank": "Bank transfer", "upi": "UPI", "cash": "Cash", "card": "Card", "cheque": "Cheque",
           "other": "Other"}
ACCOUNT_KINDS = {"bank": "Bank", "cash": "Cash", "card": "Card", "wallet": "Wallet / UPI", "other": "Other"}
CONTACT_KINDS = {"customer": "Customer", "vendor": "Vendor", "both": "Customer and vendor"}
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "AED": "AED ", "JPY": "¥", "AUD": "A$",
                    "CAD": "C$", "SGD": "S$"}
DEFAULT_EXPENSE_CATEGORIES = ["Rent", "Salaries", "Software", "Marketing", "Travel", "Office", "Utilities",
                              "Taxes and fees", "Other"]


def finance_plugin(db: Any) -> Any:
    """The ``FinancePlugin`` of the panel this session belongs to (None in plain scripts)."""
    from tungsten import Panel

    panel = Panel.of(db)
    return panel.get_plugin("finance") if panel is not None else None


def to_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return default


def money(value: Any, currency: str = "INR") -> str:
    """``₹1,250.00``; negative amounts get a minus sign in front."""
    amount = to_decimal(value)
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    return f"{'-' if amount < 0 else ''}{symbol}{abs(amount):,.2f}"


# ---------------------------------------------------------------------- invoices
def next_number(db: Any, prefix: str = "INV-") -> str:
    """The next free number, like INV-00013. Counts up from the highest number with this prefix."""
    numbers = db.scalars(select(Invoice.number).where(Invoice.number.like(f"{prefix}%"))).all()
    highest = 0
    for number in numbers:
        tail = number[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:05d}"


def recalculate(invoice: Invoice) -> None:
    """Work out subtotal, tax and total from the items. Discount comes off the total."""
    subtotal = sum((item.amount for item in invoice.items), ZERO)
    tax = sum((item.tax for item in invoice.items), ZERO)
    invoice.subtotal = subtotal
    invoice.tax_total = tax
    invoice.discount = to_decimal(invoice.discount).quantize(CENT)
    invoice.total = max(subtotal + tax - invoice.discount, ZERO)


def refresh_paid(db: Any, invoice: Invoice) -> None:
    """Sum the invoice's payments and move its status to partial / paid (or back)."""
    db.flush()
    paid = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.invoice_id == invoice.id))
    invoice.amount_paid = to_decimal(paid).quantize(CENT)
    if invoice.status == "cancelled":
        return
    total = to_decimal(invoice.total)
    if invoice.amount_paid > 0 and invoice.amount_paid >= total:
        invoice.status = "paid"
        invoice.paid_at = invoice.paid_at or dt.datetime.now().replace(microsecond=0)
    elif invoice.amount_paid > 0:
        invoice.status, invoice.paid_at = "partial", None
    elif invoice.status in ("partial", "paid"):
        invoice.status, invoice.paid_at = "sent", None


def prepare_new(db: Any, invoice: Invoice) -> None:
    """Fill what a new invoice needs: its number and due date. Call before flush."""
    plugin = finance_plugin(db)
    if not invoice.number:
        invoice.number = next_number(db, plugin.number_prefix if plugin is not None else "INV-")
    if not invoice.issue_date:
        invoice.issue_date = dt.date.today()
    if not invoice.due_date:
        days = plugin.due_days if plugin is not None else 15
        invoice.due_date = invoice.issue_date + dt.timedelta(days=days)
    if plugin is not None and not invoice.terms and plugin.terms:
        invoice.terms = plugin.terms
    if not invoice.status:
        invoice.status = "draft"


def find_invoice(db: Any, number: str | None = None, *, external_id: str | None = None) -> Invoice | None:
    if external_id:
        return db.scalars(select(Invoice).where(Invoice.external_id == str(external_id))).first()
    if number:
        return db.scalars(select(Invoice).where(Invoice.number == number.strip().upper())).first()
    return None


def find_or_create_contact(db: Any, name: str, email: str | None = None, kind: str = "customer",
                           **fields: Any) -> Contact:
    """The contact with this email (or name), made when it is new."""
    query = select(Contact)
    if email:
        query = query.where(func.lower(Contact.email) == email.strip().lower())
    else:
        query = query.where(Contact.name == name)
    contact = db.scalars(query).first()
    if contact is None:
        contact = Contact(name=name, email=email.strip().lower() if email else None, kind=kind, **fields)
        db.add(contact)
        db.flush()
    elif contact.kind != kind and contact.kind != "both":
        contact.kind = "both"
    return contact


def create_invoice(db: Any, *, items: list[dict], contact: Contact | None = None, customer: str | None = None,
                   email: str | None = None, issue_date: dt.date | None = None, due_date: dt.date | None = None,
                   discount: Any = 0, notes: str | None = None, status: str = "draft",
                   external_id: str | None = None) -> Invoice:
    """Make an invoice. ``items`` are dicts with description, quantity, unit_price and tax_rate.

    Pass a ``contact``, or a ``customer`` name (and ``email``) to find or add one.
    With ``external_id`` the same outside id never makes a second invoice.
    """
    if external_id:
        existing = find_invoice(db, external_id=external_id)
        if existing is not None:
            return existing
    if contact is None and customer:
        contact = find_or_create_contact(db, customer, email)
    invoice = Invoice(contact=contact, issue_date=issue_date or dt.date.today(), due_date=due_date,
                      discount=to_decimal(discount), notes=notes, status=status, external_id=external_id)
    for i, row in enumerate(items):
        invoice.items.append(InvoiceItem(
            description=str(row.get("description") or "Item")[:255],
            quantity=to_decimal(row.get("quantity"), Decimal(1)), unit_price=to_decimal(row.get("unit_price")),
            tax_rate=to_decimal(row.get("tax_rate")), sort=i))
    db.add(invoice)
    prepare_new(db, invoice)
    recalculate(invoice)
    if status == "sent":
        invoice.sent_at = dt.datetime.now().replace(microsecond=0)
    db.flush()
    return invoice


def record_payment(db: Any, invoice: Invoice | None, amount: Any, *, date: dt.date | None = None,
                   account_id: int | None = None, method: str = "bank", reference: str | None = None,
                   notes: str | None = None, contact: Contact | None = None) -> Payment:
    """Book money that came in, and update the invoice's paid amount and status."""
    payment = Payment(amount=to_decimal(amount).quantize(CENT), date=date or dt.date.today(),
                      invoice_id=invoice.id if invoice is not None else None,
                      contact_id=(invoice.contact_id if invoice is not None else None) or (contact.id if contact else None),
                      account_id=account_id, method=method, reference=reference, notes=notes)
    db.add(payment)
    if invoice is not None:
        if invoice.status == "draft":
            invoice.status = "sent"
        refresh_paid(db, invoice)
    else:
        db.flush()
    return payment


def ensure_default_categories(db: Any) -> None:
    if db.scalar(select(func.count()).select_from(ExpenseCategory)):
        return
    for i, name in enumerate(DEFAULT_EXPENSE_CATEGORIES):
        db.add(ExpenseCategory(name=name, sort=i))


# ---------------------------------------------------------------------- reports
def account_balance(db: Any, account: MoneyAccount) -> Decimal:
    """Opening balance, plus payments into the account, minus expenses paid from it."""
    money_in = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.account_id == account.id))
    money_out = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.account_id == account.id))
    return (to_decimal(account.opening_balance) + to_decimal(money_in) - to_decimal(money_out)).quantize(CENT)


def money_in(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(Payment.amount), 0))
    if start:
        query = query.where(Payment.date >= start)
    if end:
        query = query.where(Payment.date <= end)
    return to_decimal(db.scalar(query))


def money_out(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(Expense.amount), 0))
    if start:
        query = query.where(Expense.date >= start)
    if end:
        query = query.where(Expense.date <= end)
    return to_decimal(db.scalar(query))


def expenses_by_category(db: Any, start: dt.date | None = None,
                         end: dt.date | None = None) -> list[tuple[str, Decimal]]:
    """``[(category name, amount), ...]``, biggest first."""
    query = (select(ExpenseCategory.name, func.sum(Expense.amount))
             .select_from(Expense).outerjoin(ExpenseCategory, Expense.category_id == ExpenseCategory.id)
             .group_by(ExpenseCategory.name))
    if start:
        query = query.where(Expense.date >= start)
    if end:
        query = query.where(Expense.date <= end)
    rows = [(name or "No category", to_decimal(total)) for name, total in db.execute(query).all()]
    return sorted(rows, key=lambda row: row[1], reverse=True)


def invoiced(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(Invoice.total), 0)).where(Invoice.status.notin_(("draft", "cancelled")))
    if start:
        query = query.where(Invoice.issue_date >= start)
    if end:
        query = query.where(Invoice.issue_date <= end)
    return to_decimal(db.scalar(query))


def tax_summary(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> dict[str, Decimal]:
    """Tax you charged on invoices, tax you paid on expenses, and what is left to pay."""
    out_query = select(func.coalesce(func.sum(Invoice.tax_total), 0)).where(
        Invoice.status.notin_(("draft", "cancelled")))
    in_query = select(func.coalesce(func.sum(Expense.tax_amount), 0))
    if start:
        out_query, in_query = out_query.where(Invoice.issue_date >= start), in_query.where(Expense.date >= start)
    if end:
        out_query, in_query = out_query.where(Invoice.issue_date <= end), in_query.where(Expense.date <= end)
    collected, paid = to_decimal(db.scalar(out_query)), to_decimal(db.scalar(in_query))
    return {"collected": collected, "paid": paid, "net": collected - paid}


AGING_BUCKETS = [("current", "Not due yet"), ("1_30", "1-30 days late"), ("31_60", "31-60 days late"),
                 ("61_90", "61-90 days late"), ("90_plus", "Over 90 days late")]


def receivables(db: Any, today: dt.date | None = None) -> dict[str, Decimal]:
    """Money customers still owe, split by how late it is (an "aging" report)."""
    today = today or dt.date.today()
    buckets = {key: ZERO for key, _ in AGING_BUCKETS}
    for invoice in db.scalars(select(Invoice).where(Invoice.status.in_(OPEN_STATUSES))).unique().all():
        late = (today - invoice.due_date).days if invoice.due_date else 0
        key = ("current" if late <= 0 else "1_30" if late <= 30 else "31_60" if late <= 60
               else "61_90" if late <= 90 else "90_plus")
        buckets[key] += invoice.balance_due
    return buckets


def top_debtors(db: Any, limit: int = 5) -> list[tuple[str, Decimal]]:
    """Customers who owe the most."""
    owed: dict[str, Decimal] = {}
    for invoice in db.scalars(select(Invoice).where(Invoice.status.in_(OPEN_STATUSES))).unique().all():
        name = invoice.contact.name if invoice.contact else "No customer"
        owed[name] = owed.get(name, ZERO) + invoice.balance_due
    return sorted(owed.items(), key=lambda row: row[1], reverse=True)[:limit]


def month_start(day: dt.date, back: int = 0) -> dt.date:
    year, month = day.year, day.month - back
    while month < 1:
        month += 12
        year -= 1
    return dt.date(year, month, 1)


def month_end(day: dt.date) -> dt.date:
    following = month_start(dt.date(day.year + (day.month == 12), day.month % 12 + 1, 1))
    return following - dt.timedelta(days=1)


def monthly(db: Any, months: int = 6, today: dt.date | None = None) -> list[dict]:
    """Money in and out for each of the last ``months`` months, oldest first."""
    today = today or dt.date.today()
    rows = []
    for back in range(months - 1, -1, -1):
        start = month_start(today, back)
        end = month_end(start)
        rows.append({"label": start.strftime("%b %Y"), "in": money_in(db, start, end),
                     "out": money_out(db, start, end)})
    return rows


PERIODS = {
    "this_month": "This month", "last_month": "Last month", "this_quarter": "This quarter",
    "this_year": "This financial year", "last_year": "Last financial year", "all": "All time",
}


def period_range(period: str | None, today: dt.date | None = None,
                 year_start_month: int = 4) -> tuple[dt.date | None, dt.date | None]:
    """Start and end dates of a period. The financial year starts in April by default (India)."""
    today = today or dt.date.today()
    if period == "last_month":
        start = month_start(today, 1)
        return start, month_end(start)
    if period == "this_quarter":
        start = month_start(today, (today.month - 1) % 3)
        return start, today
    if period in ("this_year", "last_year"):
        year = today.year if today.month >= year_start_month else today.year - 1
        if period == "last_year":
            year -= 1
        start = dt.date(year, year_start_month, 1)
        end = month_end(month_start(dt.date(year + 1, year_start_month, 1), 1))
        return start, (min(end, today) if period == "this_year" else end)
    if period == "all":
        return None, None
    return month_start(today), today
