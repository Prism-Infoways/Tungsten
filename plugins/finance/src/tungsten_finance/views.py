"""The invoice as a printable document, used in the panel and on the customer's page."""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from .models import Invoice
from .service import INVOICE_STATUSES, money


def _rate(value: Any) -> str:
    return f"{float(value or 0):g}%"


def document_data(panel: Any, plugin: Any, invoice: Invoice) -> dict:
    cur = plugin.currency if plugin is not None else "INR"
    label, color = INVOICE_STATUSES.get(invoice.display_status, (invoice.status, "gray"))
    return {
        "invoice": invoice,
        "business": plugin.business(panel) if plugin is not None else {"name": panel.brand_name},
        "customer": invoice.contact,
        "items": [{"description": item.description, "quantity": f"{float(item.quantity or 0):g}",
                   "price": money(item.unit_price, cur), "tax": _rate(item.tax_rate),
                   "amount": money(item.amount, cur)} for item in invoice.items],
        "subtotal": money(invoice.subtotal, cur),
        "tax_total": money(invoice.tax_total, cur),
        "discount": money(invoice.discount, cur) if invoice.discount else None,
        "total": money(invoice.total, cur),
        "paid": money(invoice.amount_paid, cur) if invoice.amount_paid else None,
        "balance": money(invoice.balance_due, cur),
        "status_label": label,
        "status_color": color,
        "payment_details": plugin.payment_details if plugin is not None else None,
    }


def render_document(ctx: Any, invoice: Invoice | None) -> Markup:
    if invoice is None:
        return Markup("")
    plugin = ctx.panel.get_plugin("finance")
    return Markup(ctx.panel.renderer.render("tungsten_finance/document.html",
                                            **document_data(ctx.panel, plugin, invoice)))
