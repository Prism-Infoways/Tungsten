"""GST for India: state codes, CGST+SGST or IGST, and the GSTR-1 and GSTR-3B summaries."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from .models import CENT, ZERO, Expense, Invoice

STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
    "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh",
    "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "96": "Outside India",
}
STATE_OPTIONS = {code: f"{code} · {name}" for code, name in sorted(STATES.items())}


def state_code(value: Any) -> str | None:
    """``"27"``, ``27``, ``"Maharashtra"`` or a GSTIN all give ``"27"``."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text[:2].isdigit():
        return text[:2].zfill(2) if len(text) <= 2 else text[:2]
    if text.isdigit():
        return text.zfill(2)
    lowered = text.lower()
    for code, name in STATES.items():
        if name.lower() == lowered:
            return code
    return None


def state_name(code: str | None) -> str:
    return STATES.get(code or "", code or "")


def is_inter_state(home: str | None, supply: str | None) -> bool:
    """IGST when the place of supply is another state. Unknown states count as the same state."""
    return bool(home and supply and home != supply)


def split_tax(tax: Decimal, inter_state: bool) -> tuple[Decimal, Decimal, Decimal]:
    """``(cgst, sgst, igst)`` for a tax amount."""
    if inter_state:
        return ZERO, ZERO, tax
    half = (tax / 2).quantize(CENT)
    return half, tax - half, ZERO


def valid_gstin(value: str | None) -> bool:
    """Shape check of a GSTIN (15 characters, state code, PAN, check letter)."""
    if not value:
        return True
    text = value.strip().upper()
    return len(text) == 15 and text[:2].isdigit() and text[2:7].isalpha() and text[7:11].isdigit() \
        and text[11].isalpha() and text[13] == "Z"


# ---------------------------------------------------------------------- returns
def _posted(db: Any, kinds: tuple[str, ...], start: dt.date | None, end: dt.date | None) -> list[Invoice]:
    query = select(Invoice).where(Invoice.kind.in_(kinds), Invoice.status.notin_(("draft", "cancelled")))
    if start:
        query = query.where(Invoice.issue_date >= start)
    if end:
        query = query.where(Invoice.issue_date <= end)
    return list(db.scalars(query.order_by(Invoice.issue_date, Invoice.id)).unique().all())


def _rate(value: Any) -> str:
    """A tax rate as a key: 18, 18.0 and 18.000 are all "18"."""
    return f"{Decimal(value or 0).normalize():f}"


def _sign(doc: Invoice) -> int:
    return -1 if doc.is_note else 1


def gstr1(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> dict:
    """The GSTR-1 tables most small businesses fill: B2B invoices, B2C totals, credit notes and HSN summary."""
    b2b, notes, b2c, hsn = [], [], {}, {}
    for doc in _posted(db, ("invoice", "credit_note"), start, end):
        gstin = doc.contact.tax_id if doc.contact and doc.contact.tax_id else None
        row = {"number": doc.number, "date": doc.issue_date, "gstin": gstin,
               "name": doc.contact.name if doc.contact else "", "pos": doc.place_of_supply,
               "taxable": doc.taxable, "igst": doc.igst, "cgst": doc.cgst, "sgst": doc.sgst, "total": doc.total}
        if doc.kind == "credit_note":
            notes.append(row)
        elif gstin:
            b2b.append(row)
        else:
            for item in doc.items:
                key = (doc.place_of_supply or "", _rate(item.tax_rate))
                entry = b2c.setdefault(key, {"pos": key[0], "rate": key[1], "taxable": ZERO, "tax": ZERO})
                entry["taxable"] += item.amount
                entry["tax"] += item.tax
        inter = doc.igst > 0
        for item in doc.items:
            key = (item.hsn or "—", _rate(item.tax_rate))
            entry = hsn.setdefault(key, {"hsn": key[0], "rate": key[1], "unit": item.unit or "", "quantity": ZERO,
                                         "taxable": ZERO, "igst": ZERO, "cgst": ZERO, "sgst": ZERO})
            sign = _sign(doc)
            cgst, sgst, igst = split_tax(item.tax, inter)
            entry["quantity"] += sign * Decimal(item.quantity or 0)
            entry["taxable"] += sign * item.amount
            entry["igst"] += sign * igst
            entry["cgst"] += sign * cgst
            entry["sgst"] += sign * sgst
    return {"b2b": b2b, "b2c": sorted(b2c.values(), key=lambda r: (r["pos"], r["rate"])),
            "credit_notes": notes, "hsn": sorted(hsn.values(), key=lambda r: (r["hsn"], r["rate"]))}


def gstr3b(db: Any, start: dt.date | None = None, end: dt.date | None = None) -> dict:
    """GSTR-3B: tax on sales (3.1), input tax credit from bills and expenses (4), and what is left to pay."""

    def total(docs: list[Invoice]) -> dict[str, Decimal]:
        out = {"taxable": ZERO, "igst": ZERO, "cgst": ZERO, "sgst": ZERO}
        for doc in docs:
            for key in out:
                out[key] += _sign(doc) * Decimal(getattr(doc, key) or 0)
        return out

    outward = total(_posted(db, ("invoice", "credit_note"), start, end))
    inward = total(_posted(db, ("bill", "debit_note"), start, end))
    query = select(Expense).where(Expense.tax_amount > 0)
    if start:
        query = query.where(Expense.date >= start)
    if end:
        query = query.where(Expense.date <= end)
    for expense in db.scalars(query).unique().all():
        cgst, sgst, igst = split_tax(Decimal(expense.tax_amount), expense.tax_kind == "igst")
        inward["cgst"] += cgst
        inward["sgst"] += sgst
        inward["igst"] += igst
        inward["taxable"] += Decimal(expense.amount) - Decimal(expense.tax_amount)
    payable = {key: outward[key] - inward[key] for key in ("igst", "cgst", "sgst")}
    return {"outward": outward, "itc": inward, "payable": payable,
            "net": sum(payable.values(), ZERO)}
