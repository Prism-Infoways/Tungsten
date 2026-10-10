"""The double-entry books: chart of accounts, posting vouchers, balances and the accounting reports.

Every money event is posted as a ``Voucher`` with debit and credit lines that add up to the same
amount, like Tally and Busy do. Trial balance, profit and loss, balance sheet, ledger statements
and the day book all read those lines.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from .gst import split_tax
from .models import (
    ZERO,
    Contact,
    Expense,
    Invoice,
    Item,
    LedgerAccount,
    Payment,
    Voucher,
    VoucherLine,
)

#: kind: (group, section label shown in reports)
KINDS = {
    "bank": ("asset", "Bank accounts"),
    "cash": ("asset", "Cash in hand"),
    "receivable": ("asset", "Sundry debtors"),
    "tax_input": ("asset", "Input tax (GST)"),
    "current_asset": ("asset", "Current assets"),
    "fixed_asset": ("asset", "Fixed assets"),
    "payable": ("liability", "Sundry creditors"),
    "tax_output": ("liability", "Duties and taxes"),
    "loan": ("liability", "Loans"),
    "current_liability": ("liability", "Current liabilities"),
    "capital": ("equity", "Capital account"),
    "sales": ("income", "Sales"),
    "other_income": ("income", "Indirect income"),
    "purchase": ("expense", "Purchases"),
    "direct_expense": ("expense", "Direct expenses"),
    "expense": ("expense", "Indirect expenses"),
}
KIND_OPTIONS = {key: label for key, (_, label) in KINDS.items()}
GROUPS = {"asset": "Assets", "liability": "Liabilities", "equity": "Equity", "income": "Income",
          "expense": "Expenses"}
MONEY_KINDS = ("bank", "cash")

#: system_key: (code, name, kind)
SYSTEM_ACCOUNTS = {
    "cash": ("1000", "Cash", "cash"),
    "receivable": ("1200", "Accounts receivable", "receivable"),
    "input_cgst": ("1300", "Input CGST", "tax_input"),
    "input_sgst": ("1310", "Input SGST", "tax_input"),
    "input_igst": ("1320", "Input IGST", "tax_input"),
    "payable": ("2000", "Accounts payable", "payable"),
    "output_cgst": ("2100", "Output CGST", "tax_output"),
    "output_sgst": ("2110", "Output SGST", "tax_output"),
    "output_igst": ("2120", "Output IGST", "tax_output"),
    "capital": ("3000", "Capital", "capital"),
    "sales": ("4000", "Sales", "sales"),
    "other_income": ("4100", "Other income", "other_income"),
    "purchases": ("5000", "Purchases", "purchase"),
    "round_off": ("6900", "Round off", "expense"),
    "other_expenses": ("6990", "Other expenses", "expense"),
}
DEFAULT_EXPENSE_ACCOUNTS = [("6000", "Rent"), ("6010", "Salaries"), ("6020", "Software"), ("6030", "Marketing"),
                            ("6040", "Travel"), ("6050", "Office"), ("6060", "Utilities"), ("6070", "Bank charges"),
                            ("6080", "Taxes and fees")]
VOUCHER_KINDS = {"sales": "Sales", "purchase": "Purchase", "receipt": "Receipt", "payment": "Payment",
                 "journal": "Journal", "contra": "Contra", "credit_note": "Credit note", "debit_note": "Debit note",
                 "expense": "Expense"}


def group_of(kind: str | None) -> str:
    return KINDS.get(kind or "", ("asset", ""))[0]


# ---------------------------------------------------------------------- chart of accounts
def ensure_chart(db: Any, expense_accounts: bool = True) -> None:
    """Add the system accounts (and common expense accounts) that are missing."""
    have = {key for key in db.scalars(select(LedgerAccount.system_key).where(LedgerAccount.system_key.isnot(None)))}
    for key, (code, name, kind) in SYSTEM_ACCOUNTS.items():
        if key not in have:
            db.add(LedgerAccount(code=code, name=name, kind=kind, is_system=True, system_key=key))
    if expense_accounts and not db.scalar(select(func.count()).select_from(LedgerAccount).where(
            LedgerAccount.kind == "expense", LedgerAccount.is_system.is_(False))):
        for code, name in DEFAULT_EXPENSE_ACCOUNTS:
            db.add(LedgerAccount(code=code, name=name, kind="expense"))
    db.flush()


def account(db: Any, key: str) -> LedgerAccount:
    """A system account by its key (``sales``, ``output_cgst``...), made when missing."""
    found = db.scalars(select(LedgerAccount).where(LedgerAccount.system_key == key)).first()
    if found is None:
        code, name, kind = SYSTEM_ACCOUNTS[key]
        found = LedgerAccount(code=code, name=name, kind=kind, is_system=True, system_key=key)
        db.add(found)
        db.flush()
    return found


# ---------------------------------------------------------------------- posting
def unpost(db: Any, source_type: str, source_id: int | None) -> None:
    if source_id is None:
        return
    for voucher in db.scalars(select(Voucher).where(Voucher.source_type == source_type,
                                                    Voucher.source_id == source_id)).all():
        db.delete(voucher)
    db.flush()


def post(db: Any, *, kind: str, date: dt.date, lines: list[tuple], number: str | None = None,
         narration: str | None = None, source_type: str | None = None, source_id: int | None = None) -> Voucher | None:
    """Write a voucher. ``lines`` are ``(account, debit, credit, contact_id)`` tuples.

    A voucher made from a document replaces the document's earlier voucher. Lines with no amount are
    dropped. Debits and credits must be equal.
    """
    if source_type:
        unpost(db, source_type, source_id)
    clean = []
    for row in lines:
        acct, debit, credit = row[0], Decimal(row[1] or 0), Decimal(row[2] or 0)
        contact_id = row[3] if len(row) > 3 else None
        net = debit - credit  # a negative debit is a credit
        if not net:
            continue
        clean.append((acct, max(net, ZERO), max(-net, ZERO), contact_id))
    if not clean:
        return None
    debits = sum((d for _, d, _, _ in clean), ZERO)
    credits = sum((c for _, _, c, _ in clean), ZERO)
    if debits != credits:
        raise ValueError(f"Voucher does not balance: debit {debits} and credit {credits}")
    voucher = Voucher(kind=kind, number=number, date=date or dt.date.today(), narration=narration,
                      source_type=source_type, source_id=source_id)
    for i, (acct, debit, credit, contact_id) in enumerate(clean):
        voucher.lines.append(VoucherLine(account_id=acct.id, debit=debit, credit=credit, contact_id=contact_id,
                                         sort=i))
    db.add(voucher)
    db.flush()
    return voucher


def post_document(db: Any, doc: Invoice) -> Voucher | None:
    """Book an invoice, bill, credit note or debit note. Drafts, quotes and cancelled ones are taken out."""
    if not doc.is_posted:
        unpost(db, "document", doc.id)
        return None
    purchase = doc.is_purchase
    party = account(db, "payable" if purchase else "receivable")
    main = doc.ledger_account if purchase and doc.ledger_account is not None \
        else account(db, "purchases" if purchase else "sales")
    prefix = "input_" if purchase else "output_"
    taxes = [(account(db, prefix + name), Decimal(getattr(doc, name) or 0)) for name in ("cgst", "sgst", "igst")]
    round_off = Decimal(doc.round_off or 0)
    contact_id = doc.contact_id
    # written the way a sales invoice is booked: Dr customer, Cr sales and output tax
    rows = [(party, doc.total, ZERO, contact_id), (main, ZERO, doc.taxable)]
    rows += [(acct, ZERO, amount) for acct, amount in taxes]
    rows.append((account(db, "round_off"), ZERO, round_off))
    flip = purchase != doc.is_note  # bills and credit notes go the other way
    if flip:
        rows = [(r[0], r[2], r[1], *r[3:]) for r in rows]
    kind = {"invoice": "sales", "bill": "purchase"}.get(doc.kind, doc.kind)
    name = doc.contact.name if doc.contact else ""
    return post(db, kind=kind, date=doc.issue_date, number=doc.number, lines=rows, source_type="document",
                source_id=doc.id, narration=f"{VOUCHER_KINDS.get(kind, kind)} {doc.number} {name}".strip())


def money_account(db: Any, account_id: int | None) -> LedgerAccount:
    acct = db.get(LedgerAccount, account_id) if account_id else None
    return acct if acct is not None else account(db, "cash")


def post_payment(db: Any, payment: Payment) -> Voucher | None:
    """Receipt: Dr bank, Cr customer. Payment: Dr vendor, Cr bank."""
    bank = money_account(db, payment.account_id)
    amount = Decimal(payment.amount or 0)
    doc = payment.invoice if payment.invoice_id else None
    if doc is not None:  # a refund on a credit note still goes through the customer's account
        party = account(db, "payable" if doc.is_purchase else "receivable")
    else:
        party = account(db, "payable" if payment.direction == "out" else "receivable")
    if payment.direction == "out":
        rows = [(party, amount, ZERO, payment.contact_id), (bank, ZERO, amount)]
        kind = "payment"
    else:
        rows = [(bank, amount, ZERO), (party, ZERO, amount, payment.contact_id)]
        kind = "receipt"
    who = payment.contact.name if payment.contact else ""
    return post(db, kind=kind, date=payment.date, number=payment.number, lines=rows, source_type="payment",
                source_id=payment.id, narration=f"{VOUCHER_KINDS[kind]} {who} {payment.reference or ''}".strip())


def post_expense(db: Any, expense: Expense) -> Voucher | None:
    """Dr the expense account (and input GST), Cr the bank or cash it was paid from."""
    amount, tax = Decimal(expense.amount or 0), Decimal(expense.tax_amount or 0)
    category = db.get(LedgerAccount, expense.category_id) if expense.category_id else None
    category = category or account(db, "other_expenses")
    cgst, sgst, igst = split_tax(tax, expense.tax_kind == "igst")
    rows = [(category, amount - tax, ZERO, expense.contact_id), (account(db, "input_cgst"), cgst, ZERO),
            (account(db, "input_sgst"), sgst, ZERO), (account(db, "input_igst"), igst, ZERO),
            (money_account(db, expense.account_id), ZERO, amount)]
    return post(db, kind="expense", date=expense.date, number=f"EXP-{expense.id:05d}", lines=rows,
                source_type="expense", source_id=expense.id, narration=expense.description)


# ---------------------------------------------------------------------- balances
def _movements(db: Any, start: dt.date | None = None, end: dt.date | None = None,
               by_contact: bool = False) -> dict:
    cols = [VoucherLine.account_id] + ([VoucherLine.contact_id] if by_contact else [])
    query = (select(*cols, func.coalesce(func.sum(VoucherLine.debit), 0), func.coalesce(func.sum(VoucherLine.credit), 0))
             .join(Voucher, Voucher.id == VoucherLine.voucher_id).group_by(*cols))
    if start:
        query = query.where(Voucher.date >= start)
    if end:
        query = query.where(Voucher.date <= end)
    out = {}
    for row in db.execute(query).all():
        key = tuple(row[:-2]) if by_contact else row[0]
        out[key] = (Decimal(row[-2]), Decimal(row[-1]))
    return out


def _contact_openings(db: Any) -> dict[str, Decimal]:
    """Contacts' opening balances, added to the receivable (customers) or payable (vendors) account."""
    out = {"receivable": ZERO, "payable": ZERO}
    for contact in db.scalars(select(Contact).where(Contact.opening_balance != 0)).all():
        out["payable" if contact.kind == "vendor" else "receivable"] += contact.opening_signed
    return out


def balances(db: Any, end: dt.date | None = None, start: dt.date | None = None,
             with_opening: bool = True) -> dict[int, Decimal]:
    """Each account's balance (debit as plus). With ``start`` only the movement in the period."""
    moves = _movements(db, start, end)
    accounts = db.scalars(select(LedgerAccount)).all()
    contact_open = _contact_openings(db) if with_opening and not start else {}
    out = {}
    for acct in accounts:
        debit, credit = moves.get(acct.id, (ZERO, ZERO))
        value = debit - credit
        if with_opening and not start:
            value += acct.opening_signed + contact_open.get(acct.system_key or "", ZERO)
        out[acct.id] = value
    return out


def account_balance(db: Any, acct: LedgerAccount, end: dt.date | None = None) -> Decimal:
    return balances(db, end).get(acct.id, ZERO)


def opening_difference(db: Any) -> Decimal:
    """Opening balances that don't match (Tally's "Difference in opening balances"). Debit as plus."""
    total = sum((a.opening_signed for a in db.scalars(select(LedgerAccount)).all()), ZERO)
    return total + sum(_contact_openings(db).values(), ZERO)


def contact_balance(db: Any, contact: Contact, end: dt.date | None = None) -> Decimal:
    """What a contact owes you (plus) or you owe them (minus)."""
    query = (select(func.coalesce(func.sum(VoucherLine.debit), 0) - func.coalesce(func.sum(VoucherLine.credit), 0))
             .join(Voucher, Voucher.id == VoucherLine.voucher_id).where(VoucherLine.contact_id == contact.id))
    if end:
        query = query.where(Voucher.date <= end)
    return contact.opening_signed + Decimal(db.scalar(query) or 0)


# ---------------------------------------------------------------------- reports
def trial_balance(db: Any, end: dt.date | None = None) -> dict:
    rows = []
    bal = balances(db, end)
    for acct in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code, LedgerAccount.name)).all():
        value = bal.get(acct.id, ZERO)
        if value:
            rows.append({"account": acct, "group": GROUPS[group_of(acct.kind)],
                         "debit": value if value > 0 else ZERO, "credit": -value if value < 0 else ZERO})
    diff = opening_difference(db)
    if diff:
        rows.append({"account": None, "group": "", "name": "Difference in opening balances",
                     "debit": -diff if diff < 0 else ZERO, "credit": diff if diff > 0 else ZERO})
    debit = sum((r["debit"] for r in rows), ZERO)
    credit = sum((r["credit"] for r in rows), ZERO)
    return {"rows": rows, "debit": debit, "credit": credit, "balanced": debit == credit}


def profit_and_loss(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> dict:
    """Trading and profit and loss: sales less purchases and direct costs is gross profit; then
    other income less indirect expenses is net profit."""
    moves = balances(db, end, start, with_opening=False)
    sections: dict[str, list] = {kind: [] for kind in ("sales", "purchase", "direct_expense", "other_income", "expense")}
    for acct in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code, LedgerAccount.name)).all():
        if acct.kind not in sections:
            continue
        value = moves.get(acct.id, ZERO)
        amount = -value if group_of(acct.kind) == "income" else value
        if amount:
            sections[acct.kind].append({"account": acct, "amount": amount})
    totals = {kind: sum((r["amount"] for r in rows), ZERO) for kind, rows in sections.items()}
    gross = totals["sales"] - totals["purchase"] - totals["direct_expense"]
    net = gross + totals["other_income"] - totals["expense"]
    return {"sections": sections, "totals": totals, "gross_profit": gross, "net_profit": net,
            "income": totals["sales"] + totals["other_income"],
            "expenses": totals["purchase"] + totals["direct_expense"] + totals["expense"]}


def balance_sheet(db: Any, end: dt.date | None = None) -> dict:
    bal = balances(db, end)
    sides: dict[str, dict[str, list]] = {"asset": {}, "liability": {}, "equity": {}}
    for acct in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code, LedgerAccount.name)).all():
        group = group_of(acct.kind)
        if group not in sides:
            continue
        value = bal.get(acct.id, ZERO)
        amount = value if group == "asset" else -value
        if amount:
            sides[group].setdefault(KINDS[acct.kind][1], []).append({"account": acct, "amount": amount})
    profit = profit_and_loss(db, None, end)["net_profit"]
    diff = opening_difference(db)

    def total(group: str) -> Decimal:
        return sum((r["amount"] for rows in sides[group].values() for r in rows), ZERO)

    assets = total("asset")
    liabilities = total("liability") + total("equity") + profit + diff
    return {"assets": sides["asset"], "liabilities": sides["liability"], "equity": sides["equity"],
            "profit": profit, "opening_difference": diff, "total_assets": assets,
            "total_liabilities": liabilities, "balanced": assets == liabilities}


def statement(db: Any, *, account_id: int | None = None, contact_id: int | None = None,
              start: dt.date | None = None, end: dt.date | None = None) -> dict:
    """A ledger account's or a contact's lines with a running balance (debit as plus)."""
    query = select(VoucherLine).join(Voucher, Voucher.id == VoucherLine.voucher_id)
    opening = ZERO
    if account_id:
        acct = db.get(LedgerAccount, account_id)
        query = query.where(VoucherLine.account_id == account_id)
        if acct is not None:
            opening = acct.opening_signed + _contact_openings(db).get(acct.system_key or "", ZERO)
    if contact_id:
        contact = db.get(Contact, contact_id)
        query = query.where(VoucherLine.contact_id == contact_id)
        if contact is not None and not account_id:
            opening = contact.opening_signed
    if start:
        before = query.where(Voucher.date < start).with_only_columns(
            func.coalesce(func.sum(VoucherLine.debit), 0) - func.coalesce(func.sum(VoucherLine.credit), 0))
        opening += Decimal(db.scalar(before) or 0)
        query = query.where(Voucher.date >= start)
    if end:
        query = query.where(Voucher.date <= end)
    rows, running = [], opening
    for line in db.scalars(query.order_by(Voucher.date, Voucher.id, VoucherLine.sort)).unique().all():
        voucher = line.voucher
        running += Decimal(line.debit) - Decimal(line.credit)
        others = [ln.account.name for ln in voucher.lines if ln.id != line.id and ln.account_id != line.account_id]
        rows.append({"date": voucher.date, "number": voucher.number, "kind": VOUCHER_KINDS.get(voucher.kind, voucher.kind),
                     "particulars": ", ".join(dict.fromkeys(others)) or voucher.narration or "",
                     "narration": voucher.narration, "debit": line.debit, "credit": line.credit, "balance": running,
                     "source_type": voucher.source_type, "source_id": voucher.source_id})
    debit = sum((Decimal(r["debit"]) for r in rows), ZERO)
    credit = sum((Decimal(r["credit"]) for r in rows), ZERO)
    return {"opening": opening, "rows": rows, "debit": debit, "credit": credit, "closing": running}


def day_book(db: Any, start: dt.date | None = None, end: dt.date | None = None, limit: int = 500) -> list[Voucher]:
    query = select(Voucher)
    if start:
        query = query.where(Voucher.date >= start)
    if end:
        query = query.where(Voucher.date <= end)
    return list(db.scalars(query.order_by(Voucher.date.desc(), Voucher.id.desc()).limit(limit)).all())


def stock_summary(db: Any, end: dt.date | None = None) -> list[dict]:
    """Quantity in and out of each stock item from posted bills and invoices, and its value at cost."""
    from .models import InvoiceItem

    query = (select(InvoiceItem.item_id, Invoice.kind, func.sum(InvoiceItem.quantity))
             .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
             .where(InvoiceItem.item_id.isnot(None), Invoice.kind != "quote",
                    Invoice.status.notin_(("draft", "cancelled")))
             .group_by(InvoiceItem.item_id, Invoice.kind))
    if end:
        query = query.where(Invoice.issue_date <= end)
    moves: dict[int, dict[str, Decimal]] = {}
    for item_id, kind, qty in db.execute(query).all():
        moves.setdefault(item_id, {})[kind] = Decimal(qty or 0)
    rows = []
    for item in db.scalars(select(Item).where(Item.track_stock.is_(True), Item.kind == "goods")
                           .order_by(Item.name)).all():
        m = moves.get(item.id, {})
        qty_in = m.get("bill", ZERO) + m.get("credit_note", ZERO)
        qty_out = m.get("invoice", ZERO) + m.get("debit_note", ZERO)
        closing = Decimal(item.opening_stock or 0) + qty_in - qty_out
        low = item.reorder_level is not None and closing <= Decimal(item.reorder_level)
        rows.append({"item": item, "opening": Decimal(item.opening_stock or 0), "in": qty_in, "out": qty_out,
                     "closing": closing, "value": (closing * Decimal(item.purchase_price or 0)).quantize(Decimal("0.01")),
                     "low": low})
    return rows
