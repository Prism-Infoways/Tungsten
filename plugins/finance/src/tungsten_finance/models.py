"""Tables of the finance plugin. Money is stored as ``Numeric(14, 2)``."""

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


class MoneyAccount(FinanceBase):
    """Where money sits: a bank account, cash box, card or wallet (UPI, PayPal...)."""

    __tablename__ = "tungsten_fin_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), default="bank")
    #: account number, last 4 digits, UPI id...
    number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    def __str__(self) -> str:
        return self.name


class Contact(FinanceBase):
    """A customer you bill, a vendor you pay, or both."""

    __tablename__ = "tungsten_fin_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="customer", index=True)
    company: Mapped[str | None] = mapped_column(String(150), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: GSTIN, VAT number...
    tax_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    def __str__(self) -> str:
        return self.name


class Invoice(FinanceBase):
    __tablename__ = "tungsten_fin_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: the number people see, like INV-00012
    number: Mapped[str | None] = mapped_column(String(30), nullable=True, unique=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    #: draft, sent, partial, paid or cancelled. "Overdue" is worked out from due_date.
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    issue_date: Mapped[dt.date] = mapped_column(Date, default=_today, index=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    discount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: secret part of the customer's link to the invoice
    access_key: Mapped[str] = mapped_column(String(40), default=new_access_key)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    #: id in the system it came from (a shop order...), to skip duplicates
    external_id: Mapped[str | None] = mapped_column(String(150), nullable=True, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    contact: Mapped[Contact | None] = relationship(lazy="joined")
    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceItem.sort")
    payments: Mapped[list[Payment]] = relationship(back_populates="invoice", order_by="Payment.date")

    @property
    def balance_due(self) -> Decimal:
        if self.status == "cancelled":
            return ZERO
        return max(Decimal(self.total or 0) - Decimal(self.amount_paid or 0), ZERO)

    @property
    def is_overdue(self) -> bool:
        return bool(self.status in ("sent", "partial") and self.due_date and self.due_date < dt.date.today())

    @property
    def display_status(self) -> str:
        return "overdue" if self.is_overdue else self.status

    def __str__(self) -> str:
        return self.number or f"#{self.id}"


class InvoiceItem(FinanceBase):
    __tablename__ = "tungsten_fin_invoice_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("tungsten_fin_invoices.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=Decimal(1))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    #: percent, like 18 for 18% GST
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=ZERO)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    invoice: Mapped[Invoice] = relationship(back_populates="items")

    @property
    def amount(self) -> Decimal:
        return (Decimal(self.quantity or 0) * Decimal(self.unit_price or 0)).quantize(CENT)

    @property
    def tax(self) -> Decimal:
        return (self.amount * Decimal(self.tax_rate or 0) / 100).quantize(CENT)

    def __str__(self) -> str:
        return self.description


class Payment(FinanceBase):
    """Money that came in, usually against an invoice."""

    __tablename__ = "tungsten_fin_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, default=_today, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    #: cash, bank, upi, card, cheque or other
    method: Mapped[str] = mapped_column(String(20), default="bank")
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    invoice: Mapped[Invoice | None] = relationship(back_populates="payments")
    contact: Mapped[Contact | None] = relationship(lazy="joined")
    account: Mapped[MoneyAccount | None] = relationship(lazy="joined")

    def __str__(self) -> str:
        return f"{self.amount} on {self.date:%d %b %Y}" if self.date else str(self.amount)


class ExpenseCategory(FinanceBase):
    __tablename__ = "tungsten_fin_expense_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(20), default="gray")
    sort: Mapped[int] = mapped_column(Integer, default=0)

    def __str__(self) -> str:
        return self.name


class Expense(FinanceBase):
    """Money that went out: rent, salaries, software, travel..."""

    __tablename__ = "tungsten_fin_expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, default=_today, index=True)
    description: Mapped[str] = mapped_column(String(255))
    #: the full amount paid, tax included
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    #: the tax inside ``amount`` (input GST you can claim back)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=ZERO)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_expense_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("tungsten_fin_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(20), default="bank")
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    receipt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    category: Mapped[ExpenseCategory | None] = relationship(lazy="joined")
    contact: Mapped[Contact | None] = relationship(lazy="joined")
    account: Mapped[MoneyAccount | None] = relationship(lazy="joined")

    def __str__(self) -> str:
        return self.description
