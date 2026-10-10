"""Documents and vouchers as HTML: the printable invoice (panel and customer page) and a voucher's lines."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from .gst import state_name
from .models import Invoice, Voucher
from .service import DOC_KINDS, money, statuses_for

TITLES = {"invoice": "TAX INVOICE", "quote": "QUOTATION", "credit_note": "CREDIT NOTE", "bill": "PURCHASE BILL",
          "debit_note": "DEBIT NOTE"}


def _num(value: Any) -> str:
    return f"{float(value or 0):g}"


def document_data(panel: Any, plugin: Any, invoice: Invoice) -> dict:
    cur = plugin.currency if plugin is not None else "INR"
    statuses = statuses_for(invoice.kind)
    label, color = ("Overdue", "danger") if invoice.is_overdue else statuses.get(invoice.status, (invoice.status, "gray"))
    business = plugin.business(panel) if plugin is not None else {"name": panel.brand_name}
    party_from, party_to = (invoice.contact, None) if invoice.is_purchase else (None, invoice.contact)
    return {
        "invoice": invoice,
        "title": TITLES.get(invoice.kind, "INVOICE") if (invoice.tax_total or invoice.kind != "invoice") else "INVOICE",
        "kind_label": DOC_KINDS.get(invoice.kind, {}).get("label", "Invoice"),
        "business": business,
        "customer": party_to or invoice.contact,
        "vendor": party_from,
        "place_of_supply": f"{invoice.place_of_supply} · {state_name(invoice.place_of_supply)}"
        if invoice.place_of_supply else None,
        "show_hsn": any(item.hsn for item in invoice.items),
        "show_discount": any(item.discount for item in invoice.items),
        "items": [{"description": item.description, "hsn": item.hsn or "", "quantity": _num(item.quantity),
                   "unit": item.unit or "", "price": money(item.unit_price, cur),
                   "discount": f"{_num(item.discount)}%" if item.discount else "", "tax": f"{_num(item.tax_rate)}%",
                   "amount": money(item.amount, cur)} for item in invoice.items],
        "subtotal": money(invoice.subtotal, cur),
        "discount": money(invoice.discount, cur) if invoice.discount else None,
        "taxable": money(invoice.taxable, cur),
        "taxes": [(name, money(getattr(invoice, key), cur)) for key, name in
                  (("cgst", "CGST"), ("sgst", "SGST"), ("igst", "IGST")) if getattr(invoice, key)],
        "round_off": money(invoice.round_off, cur) if invoice.round_off else None,
        "total": money(invoice.total, cur),
        "paid": money(invoice.amount_paid, cur) if invoice.amount_paid and invoice.kind != "quote" else None,
        "balance": money(invoice.balance_due, cur),
        "status_label": label,
        "status_color": color,
        "against": invoice.against.number if invoice.against_id and invoice.against else None,
        "payment_details": plugin.payment_details if plugin is not None and invoice.kind in ("invoice", "quote")
        else None,
    }


def render_document(ctx: Any, invoice: Invoice | None) -> Markup:
    if invoice is None:
        return Markup("")
    plugin = ctx.panel.get_plugin("finance")
    return Markup(ctx.panel.renderer.render("tungsten_finance/document.html",
                                            **document_data(ctx.panel, plugin, invoice)))


def render_voucher(ctx: Any, voucher: Voucher | None) -> Markup:
    if voucher is None:
        return Markup("")
    plugin = ctx.panel.get_plugin("finance")
    cur = plugin.currency if plugin is not None else "INR"
    rows = [[line.account.name if line.account else "", line.contact.name if line.contact else "",
             money(line.debit, cur) if line.debit else "", money(line.credit, cur) if line.credit else ""]
            for line in voucher.lines]
    block = {"title": f"{voucher.number or ''} · {voucher.date:%d %b %Y}", "icon": "notebook-pen",
             "columns": [("Account", "start"), ("Customer / vendor", "start"), ("Debit", "end"), ("Credit", "end")],
             "rows": rows, "foot": ["Total", "", money(voucher.total, cur), money(voucher.total, cur)],
             "note": voucher.narration, "plain": True}
    return Markup(ctx.panel.renderer.render("tungsten_finance/blocks.html", blocks=[block], ctx=ctx))
