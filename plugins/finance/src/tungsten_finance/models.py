"""Tables of the finance plugin. Money is stored as ``Numeric(14, 2)``.

Every invoice, bill, payment, expense and journal is posted to a double-entry ledger
(``Voucher`` + ``VoucherLine``), like Tally and Busy. The reports read that ledger.
"""

from __future__ import annotations

import datetime as dt
import secrets
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _now() -> dt.datetime:
    return dt.datetime.now()


def _today() -> dt.date:
    return dt.date.today()


def new_access_key() -> str:
    return secrets.token_urlsafe(18)


class FinanceBase(DeclarativeBase):
    pass


class LedgerAccount(FinanceBase):
    """One account in the chart of accounts ("ledger" in Tally): Sales, HDFC Bank, Rent, Output CGST...

    ``kind`` decides where it shows in the reports, see ``ledger.KINDS``. Bank and cash accounts
    are ledger accounts too (``kind`` bank or cash).
    """

    __tablename__ = "tungsten_fin_ledger_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30), index=True)
    #: account number, IFSC, UPI id... for bank accounts
    number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    #: dr or cr
    opening_side: Mapped[str] = mapped_column(String(2), default="dr")
    #: made by the plugin (Sales, Output CGST...); can't be deleted
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    #: short key the plugin finds system accounts by ("sales", "output_cgst"...)
    system_key: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)
    color: Mapped[str] = mapped_column(String(20), default="gray")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    @property
    def opening_signed(self) -> Decimal:
        """Opening balance with debit as plus and credit as minus."""
        amount = Decimal(self.opening_balance or 0)
        return -amount if self.opening_side == "cr" else amount

    def __str__(self) -> str:
        return self.name


class Contact(FinanceBase):
    """A customer you bill, a vendor you buy from, or both ("party" in Tally and Busy)."""

    __tablename__ = "tungsten_fin_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="customer", index=True)
    company: Mapped[str | None] = mapped_column(String(150), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: GSTIN, VAT number...
    tax_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: GST state code ("27" for Maharashtra); decides CGST+SGST or IGST
    state: Mapped[str | None] = mapped_column(String(4), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: days to pay; empty: the plugin's due_days
    payment_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    #: dr: they owed you on the opening date, cr: you owed them
    opening_side: Mapped[str] = mapped_column(String(2), default="dr")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    @property
    def opening_signed(self) -> Decimal:
        amount = Decimal(self.opening_balance or 0)
        return -amount if self.opening_side == "cr" else amount

    def __str__(self) -> str:
        return self.name


class Item(FinanceBase):
    """A product or service you sell or buy ("stock item" in Tally)."""

    __tablename__ = "tungsten_fin_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    sku: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    #: goods or service
    kind: Mapped[str] = mapped_column(String(10), default="goods")
    hsn: Mapped[str | None] = mapped_column(String(12), nullable=True)
    unit: Mapped[str] = mapped_column(String(12), default="Nos")
    sale_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=ZERO)
    track_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    opening_stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=ZERO)
    #: warn when stock falls to this
    reorder_level: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    def __str__(self) -> str:
        return self.name


class Invoice(FinanceBase):
    """A sales or purchase document. ``kind`` is one of:

    - ``invoice``: you bill a customer (sales)
    - ``quote``: an estimate; never posted, can turn into an invoice
    - ``credit_note``: you give a customer money back or reduce what they owe (sales return)
    - ``bill``: a vendor bills you (purchase)
    - ``debit_note``: you send goods back to a vendor (purchase return)
    """

    __tablename__ = "tungsten_fin_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="invoice", index=True)
    #: our number, like INV-00012 or BILL-00003
    number: Mapped[str | None] = mapped_column(String(30), nullable=True, unique=True, index=True)
    #: the vendor's bill number, the customer's PO number...
    reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    #: draft, sent, partial, paid or cancelled (quotes: draft, sent, accepted, declined, invoiced).
    #: "Overdue" is worked out from due_date.
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    issue_date: Mapped[dt.date] = mapped_column(Date, default=_today, index=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    #: GST state code of the place of supply
    place_of_supply: Mapped[str | None] = mapped_column(String(4), nullable=True)
    #: the purchase or expense account a bill is booked to (empty: Purchases)
    ledger_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_ledger_accounts.id", ondelete="SET NULL"), nullable=True)
    #: the invoice a credit note is for (or the bill a debit note is for)
    against_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    taxable: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    cgst: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    sgst: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    igst: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    round_off: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    #: payments plus credit notes against it
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: secret part of the customer's link to the invoice
    access_key: Mapped[str] = mapped_column(String(40), default=new_access_key)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    #: repeat: make a copy every ``repeat_months`` months, next one on ``next_repeat_on``
    repeat_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_repeat_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    #: id in the system it came from (a shop order...), to skip duplicates
    external_id: Mapped[str | None] = mapped_column(String(150), nullable=True, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    contact: Mapped[Contact | None] = relationship(lazy="joined")
    ledger_account: Mapped[LedgerAccount | None] = relationship()
    against: Mapped[Invoice | None] = relationship(remote_side=[id])
    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceItem.sort")
    payments: Mapped[list[Payment]] = relationship(back_populates="invoice", order_by="Payment.date")

    @property
    def is_purchase(self) -> bool:
        return self.kind in ("bill", "debit_note")

    @property
    def is_note(self) -> bool:
        return self.kind in ("credit_note", "debit_note")

    @property
    def is_posted(self) -> bool:
        """Booked in the ledger: not a quote, draft or cancelled."""
        return self.kind != "quote" and self.status not in ("draft", "cancelled")

    @property
    def balance_due(self) -> Decimal:
        if self.status == "cancelled" or self.kind == "quote":
            return ZERO
        return max(Decimal(self.total or 0) - Decimal(self.amount_paid or 0), ZERO)

    @property
    def is_overdue(self) -> bool:
        return bool(self.kind in ("invoice", "bill") and self.status in ("sent", "partial")
                    and self.due_date and self.due_date < dt.date.today())

    @property
    def display_status(self) -> str:
        return "overdue" if self.is_overdue else self.status

    def __str__(self) -> str:
        return self.number or f"#{self.id}"


class InvoiceItem(FinanceBase):
    __tablename__ = "tungsten_fin_invoice_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("tungsten_fin_invoices.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_items.id", ondelete="SET NULL"), nullable=True, index=True)
    description: Mapped[str] = mapped_column(String(255))
    hsn: Mapped[str | None] = mapped_column(String(12), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal(1))
    unit: Mapped[str | None] = mapped_column(String(12), nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    #: percent off this line
    discount: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=ZERO)
    #: percent, like 18 for 18% GST
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=ZERO)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    invoice: Mapped[Invoice] = relationship(back_populates="items")
    item: Mapped[Item | None] = relationship()

    @property
    def gross(self) -> Decimal:
        return (Decimal(self.quantity or 0) * Decimal(self.unit_price or 0)).quantize(CENT)

    @property
    def discount_amount(self) -> Decimal:
        return (self.gross * Decimal(self.discount or 0) / 100).quantize(CENT)

    @property
    def amount(self) -> Decimal:
        """Taxable value of the line, after its discount."""
        return self.gross - self.discount_amount

    @property
    def tax(self) -> Decimal:
        return (self.amount * Decimal(self.tax_rate or 0) / 100).quantize(CENT)

    def __str__(self) -> str:
        return self.description


class Payment(FinanceBase):
    """Money that came in (``direction`` in, from a customer) or went out (out, to a vendor)."""

    __tablename__ = "tungsten_fin_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    direction: Mapped[str] = mapped_column(String(3), default="in", index=True)
    number: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    date: Mapped[dt.date] = mapped_column(Date, default=_today, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    #: the bank or cash ledger account
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_ledger_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    #: cash, bank, upi, card, cheque or other
    method: Mapped[str] = mapped_column(String(20), default="bank")
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: the day it showed in the bank statement (bank reconciliation)
    cleared_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    invoice: Mapped[Invoice | None] = relationship(back_populates="payments")
    contact: Mapped[Contact | None] = relationship(lazy="joined")
    account: Mapped[LedgerAccount | None] = relationship(lazy="joined")

    def __str__(self) -> str:
        return self.number or (f"{self.amount} on {self.date:%d %b %Y}" if self.date else str(self.amount))


class Expense(FinanceBase):
    """Money that went out straight away: rent, salaries, software, travel..."""

    __tablename__ = "tungsten_fin_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, default=_today, index=True)
    description: Mapped[str] = mapped_column(String(255))
    #: the full amount paid, tax included
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    #: the GST inside ``amount`` (input tax you can claim back)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    #: cgst_sgst (same state) or igst
    tax_kind: Mapped[str] = mapped_column(String(10), default="cgst_sgst")
    #: the expense ledger account (the category: Rent, Salaries...)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_ledger_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    #: the bank or cash ledger account it was paid from
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_ledger_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(20), default="bank")
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    receipt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cleared_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    category: Mapped[LedgerAccount | None] = relationship(foreign_keys=[category_id], lazy="joined")
    contact: Mapped[Contact | None] = relationship(lazy="joined")
    account: Mapped[LedgerAccount | None] = relationship(foreign_keys=[account_id], lazy="joined")

    def __str__(self) -> str:
        return self.description


class Voucher(FinanceBase):
    """One entry in the books. ``kind``: sales, purchase, receipt, payment, journal, contra,
    credit_note, debit_note or expense. Vouchers made from documents point back with
    ``source_type`` and ``source_id`` and are rebuilt when the document changes."""

    __tablename__ = "tungsten_fin_vouchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="journal", index=True)
    number: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    date: Mapped[dt.date] = mapped_column(Date, default=_today, index=True)
    narration: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    lines: Mapped[list[VoucherLine]] = relationship(
        back_populates="voucher", cascade="all, delete-orphan", order_by="VoucherLine.sort")

    @property
    def total(self) -> Decimal:
        return sum((Decimal(line.debit or 0) for line in self.lines), ZERO)

    def __str__(self) -> str:
        return self.number or f"#{self.id}"


class VoucherLine(FinanceBase):
    __tablename__ = "tungsten_fin_voucher_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    voucher_id: Mapped[int] = mapped_column(ForeignKey("tungsten_fin_vouchers.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("tungsten_fin_ledger_accounts.id", ondelete="RESTRICT"), index=True)
    #: the customer or vendor, on receivable and payable lines
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    voucher: Mapped[Voucher] = relationship(back_populates="lines")
    account: Mapped[LedgerAccount] = relationship(lazy="joined")
    contact: Mapped[Contact | None] = relationship(lazy="joined")
