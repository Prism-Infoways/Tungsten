"""Functions other code (and other plugins) use to bill customers, record bills and book money.

    from tungsten_finance import create_invoice, record_payment

    invoice = create_invoice(db, customer="Amit Traders", email="amit@example.com",
                             items=[{"description": "Website design", "quantity": 1, "unit_price": 25000,
                                     "tax_rate": 18}])
    record_payment(db, invoice, 10000, method="upi", reference="UTR 1234")
    db.commit()
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from .gst import is_inter_state, split_tax, state_code
from .ledger import ensure_chart, post_document, post_payment
from .models import CENT, ZERO, Contact, Expense, Invoice, InvoiceItem, Item, Payment

DOC_KINDS = {
    "invoice": {"label": "Invoice", "plural": "Invoices", "prefix": "INV-", "party": "customer"},
    "quote": {"label": "Quote", "plural": "Quotes", "prefix": "QT-", "party": "customer"},
    "credit_note": {"label": "Credit note", "plural": "Credit notes", "prefix": "CN-", "party": "customer"},
    "bill": {"label": "Bill", "plural": "Bills", "prefix": "BILL-", "party": "vendor"},
    "debit_note": {"label": "Debit note", "plural": "Debit notes", "prefix": "DN-", "party": "vendor"},
}
INVOICE_STATUSES = {
    "draft": ("Draft", "gray"),
    "sent": ("Sent", "info"),
    "partial": ("Part paid", "warning"),
    "paid": ("Paid", "success"),
    "overdue": ("Overdue", "danger"),
    "cancelled": ("Cancelled", "gray"),
}
BILL_STATUSES = {**INVOICE_STATUSES, "sent": ("Open", "info")}
NOTE_STATUSES = {"draft": ("Draft", "gray"), "sent": ("Open", "info"), "partial": ("Part used", "warning"),
                 "paid": ("Used", "success"), "cancelled": ("Cancelled", "gray")}
QUOTE_STATUSES = {"draft": ("Draft", "gray"), "sent": ("Sent", "info"), "accepted": ("Accepted", "success"),
                  "declined": ("Declined", "danger"), "invoiced": ("Invoiced", "primary")}
#: invoices and bills that still wait for money
OPEN_STATUSES = ("sent", "partial")
METHODS = {"bank": "Bank transfer", "upi": "UPI", "cash": "Cash", "card": "Card", "cheque": "Cheque",
           "other": "Other"}
CONTACT_KINDS = {"customer": "Customer", "vendor": "Vendor", "both": "Customer and vendor"}
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "AED": "AED ", "JPY": "¥", "AUD": "A$",
                    "CAD": "C$", "SGD": "S$"}


def statuses_for(kind: str) -> dict[str, tuple[str, str]]:
    if kind == "quote":
        return QUOTE_STATUSES
    if kind in ("credit_note", "debit_note"):
        return NOTE_STATUSES
    return BILL_STATUSES if kind == "bill" else INVOICE_STATUSES


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


# ---------------------------------------------------------------------- numbers
def prefix_for(kind: str, plugin: Any = None) -> str:
    if plugin is not None:
        return plugin.prefixes.get(kind, DOC_KINDS[kind]["prefix"])
    return DOC_KINDS[kind]["prefix"]


def next_number(db: Any, prefix: str = "INV-", column: Any = None) -> str:
    """The next free number, like INV-00013. Counts up from the highest number with this prefix."""
    column = column if column is not None else Invoice.number
    highest = 0
    for number in db.scalars(select(column).where(column.like(f"{prefix}%"))).all():
        tail = number[len(prefix):]
        if tail.isdigit():
            highest = max(highest, int(tail))
    return f"{prefix}{highest + 1:05d}"


# ---------------------------------------------------------------------- documents
def home_state(plugin: Any) -> str | None:
    return state_code(plugin.state) if plugin is not None else None


def recalculate(invoice: Invoice, plugin: Any = None) -> None:
    """Work out taxable value, CGST/SGST/IGST, round off and total from the items."""
    subtotal = sum((item.gross for item in invoice.items), ZERO)
    discount = sum((item.discount_amount for item in invoice.items), ZERO)
    taxable = subtotal - discount
    tax = sum((item.tax for item in invoice.items), ZERO)
    supply = state_code(invoice.place_of_supply) or (invoice.contact.state if invoice.contact else None)
    cgst, sgst, igst = split_tax(tax, is_inter_state(home_state(plugin), supply))
    invoice.subtotal, invoice.discount, invoice.taxable = subtotal, discount, taxable
    invoice.cgst, invoice.sgst, invoice.igst, invoice.tax_total = cgst, sgst, igst, tax
    exact = taxable + tax
    rounded = exact.quantize(Decimal(1), rounding=ROUND_HALF_UP) if (plugin is None or plugin.round_off) else exact
    invoice.round_off = rounded - exact
    invoice.total = rounded


def refresh_paid(db: Any, invoice: Invoice) -> None:
    """Sum the document's payments (and credit or debit notes against it) and move its status along."""
    db.flush()
    paid = to_decimal(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                                .where(Payment.invoice_id == invoice.id)))
    if not invoice.is_note:
        paid += to_decimal(db.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.against_id == invoice.id, Invoice.kind.in_(("credit_note", "debit_note")),
            Invoice.status.notin_(("draft", "cancelled")))))
    elif invoice.against_id and invoice.status not in ("draft", "cancelled"):
        paid = to_decimal(invoice.total)  # a note against a document is used up by it
    invoice.amount_paid = paid.quantize(CENT)
    if invoice.status in ("cancelled", "draft") or invoice.kind == "quote":
        return
    total = to_decimal(invoice.total)
    if invoice.amount_paid > 0 and invoice.amount_paid >= total:
        invoice.status = "paid"
        invoice.paid_at = invoice.paid_at or dt.datetime.now().replace(microsecond=0)
    elif invoice.amount_paid > 0:
        invoice.status, invoice.paid_at = "partial", None
    elif invoice.status in ("partial", "paid"):
        invoice.status, invoice.paid_at = "sent", None


def settle(db: Any, invoice: Invoice) -> None:
    """After any change to a document: totals, paid amount, status, the ledger, and the document it is against."""
    plugin = finance_plugin(db)
    recalculate(invoice, plugin)
    refresh_paid(db, invoice)
    post_document(db, invoice)
    if invoice.against_id:
        target = db.get(Invoice, invoice.against_id)
        if target is not None:
            refresh_paid(db, target)


def prepare_new(db: Any, invoice: Invoice) -> None:
    """Fill what a new document needs: number, due date, place of supply, terms. Call before flush."""
    plugin = finance_plugin(db)
    kind = invoice.kind or "invoice"
    invoice.kind = kind
    if not invoice.number:
        invoice.number = next_number(db, prefix_for(kind, plugin))
    if not invoice.issue_date:
        invoice.issue_date = dt.date.today()
    if invoice.contact is None and invoice.contact_id:
        invoice.contact = db.get(Contact, invoice.contact_id)
    if not invoice.due_date and kind in ("invoice", "bill", "quote"):
        days = invoice.contact.payment_days if invoice.contact and invoice.contact.payment_days else None
        days = days if days is not None else (plugin.due_days if plugin is not None else 15)
        invoice.due_date = invoice.issue_date + dt.timedelta(days=days)
    if not invoice.place_of_supply:
        invoice.place_of_supply = (invoice.contact.state if invoice.contact else None) or home_state(plugin)
    if plugin is not None and not invoice.terms and plugin.terms and kind in ("invoice", "quote"):
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


def _item_row(db: Any, row: dict, i: int, purchase: bool) -> InvoiceItem:
    item = None
    if row.get("item_id"):
        item = db.get(Item, int(row["item_id"]))
    elif row.get("sku"):
        item = db.scalars(select(Item).where(Item.sku == str(row["sku"]))).first()
    price_default = (item.purchase_price if purchase else item.sale_price) if item else ZERO
    return InvoiceItem(
        item_id=item.id if item else None,
        description=str(row.get("description") or (item.name if item else "Item"))[:255],
        hsn=row.get("hsn") or (item.hsn if item else None),
        unit=row.get("unit") or (item.unit if item else None),
        quantity=to_decimal(row.get("quantity"), Decimal(1)),
        unit_price=to_decimal(row.get("unit_price"), price_default),
        discount=to_decimal(row.get("discount")),
        tax_rate=to_decimal(row.get("tax_rate"), item.tax_rate if item else ZERO), sort=i)


def create_document(db: Any, kind: str, *, items: list[dict], contact: Contact | None = None,
                    name: str | None = None, email: str | None = None, issue_date: dt.date | None = None,
                    due_date: dt.date | None = None, notes: str | None = None, status: str = "draft",
                    reference: str | None = None, place_of_supply: str | None = None,
                    against: Invoice | None = None, external_id: str | None = None) -> Invoice:
    """Make an invoice, quote, credit note, bill or debit note.

    ``items`` are dicts with description, quantity, unit_price, tax_rate, and optional discount (%),
    hsn, unit, and item_id or sku of an ``Item``. Pass a ``contact``, or a ``name`` (and ``email``) to
    find or add one. The same ``external_id`` never makes a second document.
    """
    if external_id:
        existing = find_invoice(db, external_id=external_id)
        if existing is not None:
            return existing
    ensure_chart(db)
    if contact is None and name:
        contact = find_or_create_contact(db, name, email, kind=DOC_KINDS[kind]["party"])
    doc = Invoice(kind=kind, contact=contact, contact_id=contact.id if contact else None,
                  issue_date=issue_date or dt.date.today(), due_date=due_date, notes=notes, status=status,
                  reference=reference, place_of_supply=state_code(place_of_supply), external_id=external_id,
                  against_id=against.id if against is not None else None)
    purchase = kind in ("bill", "debit_note")
    for i, row in enumerate(items):
        doc.items.append(_item_row(db, row, i, purchase))
    db.add(doc)
    prepare_new(db, doc)
    if status == "sent":
        doc.sent_at = dt.datetime.now().replace(microsecond=0)
    db.flush()
    settle(db, doc)
    return doc


def create_invoice(db: Any, *, items: list[dict], customer: str | None = None, **kw: Any) -> Invoice:
    """``create_document(db, "invoice", ...)``; ``customer`` is the customer's name."""
    return create_document(db, "invoice", items=items, name=customer, **kw)


def create_bill(db: Any, *, items: list[dict], vendor: str | None = None, **kw: Any) -> Invoice:
    """A vendor's bill; ``vendor`` is the vendor's name and ``reference`` their bill number."""
    kw.setdefault("status", "sent")
    return create_document(db, "bill", items=items, name=vendor, **kw)


def copy_document(db: Any, source: Invoice, kind: str | None = None, **changes: Any) -> Invoice:
    """A new draft with the same customer and lines (Duplicate, quote to invoice, credit note for an invoice)."""
    doc = Invoice(kind=kind or source.kind, contact_id=source.contact_id, contact=source.contact,
                  notes=source.notes, place_of_supply=source.place_of_supply, status="draft",
                  issue_date=dt.date.today(), ledger_account_id=source.ledger_account_id,
                  terms=source.terms if (kind or source.kind) in ("invoice", "quote") else None)
    for key, value in changes.items():
        setattr(doc, key, value)
    for item in source.items:
        doc.items.append(InvoiceItem(item_id=item.item_id, description=item.description, hsn=item.hsn,
                                     quantity=item.quantity, unit=item.unit, unit_price=item.unit_price,
                                     discount=item.discount, tax_rate=item.tax_rate, sort=item.sort))
    db.add(doc)
    prepare_new(db, doc)
    db.flush()
    settle(db, doc)
    return doc


def quote_to_invoice(db: Any, quote: Invoice) -> Invoice:
    invoice = copy_document(db, quote, "invoice")
    quote.status = "invoiced"
    return invoice


def run_recurring(db: Any, today: dt.date | None = None) -> list[Invoice]:
    """Make the repeat invoices that are due (call once a day, e.g. from cron). Returns the new drafts."""
    today = today or dt.date.today()
    made = []
    due = db.scalars(select(Invoice).where(Invoice.repeat_months.isnot(None), Invoice.next_repeat_on.isnot(None),
                                           Invoice.next_repeat_on <= today)).unique().all()
    for source in due:
        while source.next_repeat_on and source.next_repeat_on <= today:
            copy = copy_document(db, source, issue_date=source.next_repeat_on)
            if source.due_date and source.issue_date:
                copy.due_date = copy.issue_date + (source.due_date - source.issue_date)
            made.append(copy)
            source.next_repeat_on = add_months(source.next_repeat_on, source.repeat_months or 1)
    db.flush()
    return made


def add_months(day: dt.date, months: int) -> dt.date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    last = month_end(dt.date(year, month, 1)).day
    return dt.date(year, month, min(day.day, last))


# ---------------------------------------------------------------------- payments
def record_payment(db: Any, invoice: Invoice | None, amount: Any, *, date: dt.date | None = None,
                   account_id: int | None = None, method: str = "bank", reference: str | None = None,
                   notes: str | None = None, contact: Contact | None = None, direction: str | None = None) -> Payment:
    """Book money received for an invoice, or paid for a bill, and update its status.

    Without a document pass ``contact`` and ``direction`` ("in" or "out").
    """
    plugin = finance_plugin(db)
    if direction is None:
        direction = "out" if invoice is not None and invoice.kind in ("bill", "credit_note") else "in"
    if account_id is None and plugin is not None:
        account_id = plugin.default_account_id(db)
    payment = Payment(direction=direction, amount=to_decimal(amount).quantize(CENT), date=date or dt.date.today(),
                      invoice_id=invoice.id if invoice is not None else None,
                      contact_id=(invoice.contact_id if invoice is not None else None) or (contact.id if contact else None),
                      account_id=account_id, method=method, reference=reference, notes=notes)
    payment.number = next_number(db, "PAY-" if direction == "out" else "RCPT-", Payment.number)
    db.add(payment)
    db.flush()
    if payment.contact_id and payment.contact is None:
        payment.contact = db.get(Contact, payment.contact_id)
    post_payment(db, payment)
    if invoice is not None:
        if invoice.status == "draft":
            invoice.status = "sent"
        refresh_paid(db, invoice)
        post_document(db, invoice)
    return payment


# ---------------------------------------------------------------------- cash figures and dates
def money_in(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> Decimal:
    """Payments received."""
    query = select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.direction == "in")
    if start:
        query = query.where(Payment.date >= start)
    if end:
        query = query.where(Payment.date <= end)
    return to_decimal(db.scalar(query))


def money_out(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> Decimal:
    """Expenses plus payments made to vendors."""
    query = select(func.coalesce(func.sum(Expense.amount), 0))
    paid = select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.direction == "out")
    if start:
        query, paid = query.where(Expense.date >= start), paid.where(Payment.date >= start)
    if end:
        query, paid = query.where(Expense.date <= end), paid.where(Payment.date <= end)
    return to_decimal(db.scalar(query)) + to_decimal(db.scalar(paid))


def invoiced(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(Invoice.total), 0)).where(
        Invoice.kind == "invoice", Invoice.status.notin_(("draft", "cancelled")))
    if start:
        query = query.where(Invoice.issue_date >= start)
    if end:
        query = query.where(Invoice.issue_date <= end)
    return to_decimal(db.scalar(query))


def expenses_by_category(db: Any, start: dt.date | None = None,
                         end: dt.date | None = None) -> list[tuple[str, Decimal]]:
    """``[(expense account, amount), ...]`` from the ledger (expenses and bills), biggest first."""
    from .ledger import profit_and_loss

    pnl = profit_and_loss(db, start, end)
    rows = [(r["account"].name, r["amount"]) for kind in ("purchase", "direct_expense", "expense")
            for r in pnl["sections"][kind] if r["amount"] > 0]
    return sorted(rows, key=lambda row: row[1], reverse=True)


AGING_BUCKETS = [("current", "Not due yet"), ("1_30", "1-30 days late"), ("31_60", "31-60 days late"),
                 ("61_90", "61-90 days late"), ("90_plus", "Over 90 days late")]


def receivables(db: Any, today: dt.date | None = None, kind: str = "invoice") -> dict[str, Decimal]:
    """Money still owed on invoices (or on bills, ``kind="bill"``), split by how late it is."""
    today = today or dt.date.today()
    buckets = {key: ZERO for key, _ in AGING_BUCKETS}
    for doc in db.scalars(select(Invoice).where(Invoice.kind == kind, Invoice.status.in_(OPEN_STATUSES))).unique().all():
        late = (today - doc.due_date).days if doc.due_date else 0
        key = ("current" if late <= 0 else "1_30" if late <= 30 else "31_60" if late <= 60
               else "61_90" if late <= 90 else "90_plus")
        buckets[key] += doc.balance_due
    return buckets


def payables(db: Any, today: dt.date | None = None) -> dict[str, Decimal]:
    return receivables(db, today, kind="bill")


def top_debtors(db: Any, limit: int = 5, kind: str = "invoice") -> list[tuple[str, Decimal]]:
    """Customers who owe the most (or vendors you owe the most, ``kind="bill"``)."""
    owed: dict[str, Decimal] = {}
    for doc in db.scalars(select(Invoice).where(Invoice.kind == kind, Invoice.status.in_(OPEN_STATUSES))).unique().all():
        name = doc.contact.name if doc.contact else "—"
        owed[name] = owed.get(name, ZERO) + doc.balance_due
    return sorted(owed.items(), key=lambda row: row[1], reverse=True)[:limit]


def month_start(day: dt.date, back: int = 0) -> dt.date:
    year, month = day.year, day.month - back
    while month < 1:
        month += 12
        year -= 1
    return dt.date(year, month, 1)


def month_end(day: dt.date) -> dt.date:
    following = dt.date(day.year + (day.month == 12), day.month % 12 + 1, 1)
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
