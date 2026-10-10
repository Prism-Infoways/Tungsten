"""Finance and accounts plugin for Tungsten.

    from tungsten_finance import FinancePlugin

    panel.plugin(FinancePlugin(business_address="12 MG Road, Pune", business_tax_id="27ABCDE1234F1Z5",
                               payment_details="UPI: shop@okhdfc"))
    panel.create_tables(engine)   # also creates the finance tables

Adds a "Finance" menu: invoices with line items and GST, a printable link for the customer,
payments that mark invoices part paid or paid, expenses with receipts, customers and vendors,
bank and cash accounts with balances, and a Reports page (profit and loss, money owed, tax).
"""

from __future__ import annotations

import datetime as dt
import hmac
import logging
from pathlib import Path
from typing import Any

from fastapi import Request

from tungsten import Plugin
from tungsten.routes import Routes
from tungsten.support.evaluate import call

from .models import (
    Contact,
    Expense,
    ExpenseCategory,
    FinanceBase,
    Invoice,
    InvoiceItem,
    MoneyAccount,
    Payment,
)
from .pages import FinanceReports
from .resources import (
    ContactResource,
    ExpenseCategoryResource,
    ExpenseResource,
    InvoiceResource,
    MoneyAccountResource,
    PaymentResource,
)
from .service import (
    account_balance,
    create_invoice,
    ensure_default_categories,
    expenses_by_category,
    find_invoice,
    find_or_create_contact,
    money,
    money_in,
    money_out,
    next_number,
    recalculate,
    receivables,
    record_payment,
    refresh_paid,
    tax_summary,
)
from .views import document_data
from .widgets import CashFlowChart, ExpenseCategoryChart, FinanceStats, ReportStats

__version__ = "0.1.0"

log = logging.getLogger("tungsten.finance")

RESOURCES = [InvoiceResource, PaymentResource, ExpenseResource, ContactResource, MoneyAccountResource,
             ExpenseCategoryResource]


class FinancePlugin(Plugin):
    """``FinancePlugin(currency="INR", number_prefix="INV-", due_days=15, default_tax_rate=18, ...)``.

    - ``currency`` is an ISO code (INR, USD, EUR...). Amounts show with its symbol.
    - ``number_prefix`` and ``due_days`` shape new invoices; ``terms`` is printed at the bottom of each.
    - ``default_tax_rate`` fills the Tax % of new invoice lines (18 for 18% GST, 0 for none).
    - ``business_*`` and ``logo_url`` are printed at the top of invoices. The name defaults to the panel's.
    - ``payment_details`` (bank account, UPI id...) shows under unpaid invoices as "How to pay".
    - ``public_links`` adds ``<panel>/invoice/<number>/<key>``: a page the customer can open and print
      without logging in.
    - ``year_start_month`` is the first month of the financial year in reports (4: April, as in India).
    - ``default_categories`` adds common expense categories (Rent, Salaries...) when there are none.
    - ``mailer`` sends invoice emails; by default the panel's ``Auth(mailer=...)``.
    """

    id = "finance"
    metadata = FinanceBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, currency: str = "INR", number_prefix: str = "INV-", due_days: int = 15,
                 default_tax_rate: float = 18, terms: str | None = None, business_name: str | None = None,
                 business_address: str | None = None, business_tax_id: str | None = None,
                 business_email: str | None = None, business_phone: str | None = None,
                 logo_url: str | None = None, payment_details: str | None = None, public_links: bool = True,
                 public_path: str = "invoice", year_start_month: int = 4, mailer: Any = None,
                 dashboard_widgets: bool = True, reports: bool = True, default_categories: bool = True, navigation_group: str = "Finance") -> None:
        self.currency = currency.upper()
        self.number_prefix = number_prefix
        self.due_days = due_days
        self.default_tax_rate = default_tax_rate
        self.terms = terms
        self.business_name = business_name
        self.business_address = business_address
        self.business_tax_id = business_tax_id
        self.business_email = business_email
        self.business_phone = business_phone
        self.logo_url = logo_url
        self.payment_details = payment_details
        self.public_links = public_links
        self.public_path = public_path.strip("/")
        self.year_start_month = year_start_month
        self.mailer = mailer
        self.dashboard_widgets = dashboard_widgets
        self.reports = reports
        self.default_categories = default_categories
        self.navigation_group = navigation_group
        self.panel: Any = None
        self.sent_listeners: dict[str, Any] = {}

    # ------------------------------------------------------------------ hooks for other code
    def on_invoice_sent(self, key: str, fn: Any) -> None:
        """Run ``fn(db, invoice, link)`` after an invoice is sent (a WhatsApp plugin can send it there too)."""
        self.sent_listeners[key] = fn

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        for resource in RESOURCES:
            resource.navigation_group = self.navigation_group
        panel.resources(RESOURCES)
        if self.reports:
            FinanceReports.navigation_group = self.navigation_group
            panel.pages([FinanceReports])
        panel.navigation_group(self.navigation_group, icon="wallet")
        if self.dashboard_widgets:
            panel.widgets([FinanceStats, CashFlowChart])
        if self.public_links:
            panel.routes(self._routes)

    def boot(self, panel: Any) -> None:
        if not self.default_categories or panel.session_factory is None or panel.is_async:
            return
        try:
            panel.with_session(self._seed)
        except Exception:  # noqa: BLE001  tables not made yet: create_tables() runs later
            log.debug("Finance tables not ready; default expense categories not added")

    @staticmethod
    def _seed(db: Any) -> None:
        ensure_default_categories(db)
        db.commit()

    def permissions(self) -> list[tuple[str, str]]:
        return [("finance.reports", "See finance reports")]

    def business(self, panel: Any = None) -> dict[str, Any]:
        """What is printed at the top of invoices."""
        panel = panel or self.panel
        return {"name": self.business_name or (panel.brand_name if panel is not None else ""),
                "address": self.business_address, "tax_id": self.business_tax_id,
                "email": self.business_email, "phone": self.business_phone, "logo_url": self.logo_url}

    # ------------------------------------------------------------------ links
    def public_path_for(self, invoice: Invoice) -> str:
        return self.panel.url(self.public_path, invoice.number, invoice.access_key)

    def customer_link(self, invoice: Invoice, ctx: Any = None) -> str | None:
        """The customer's private link to the invoice (None without public links or a known address)."""
        if not self.public_links:
            return None
        path = self.public_path_for(invoice)
        if self.panel.app_url:
            return f"{self.panel.app_url}{path}"
        if ctx is not None and getattr(ctx, "request", None) is not None:
            return self.panel.absolute_url(ctx, path)
        return None

    # ------------------------------------------------------------------ sending
    def send_invoice(self, db: Any, invoice: Invoice, ctx: Any = None) -> bool:
        """Mark the invoice sent and email its link to the customer. True when an email went out."""
        if invoice.status == "draft":
            invoice.status = "sent"
        invoice.sent_at = dt.datetime.now().replace(microsecond=0)
        link = self.customer_link(invoice, ctx)
        for key, fn in list(self.sent_listeners.items()):
            try:
                fn(db, invoice, link)
            except Exception:  # one broken listener must not stop the others
                log.exception("Invoice sent listener %s failed for %s", key, invoice.number)
        contact = invoice.contact
        if contact is None or not contact.email:
            return False
        business = self.business()
        subject = f"Invoice {invoice.number} from {business['name']}"
        lines = [f"Hello {contact.name},", "",
                 f"Here is invoice {invoice.number} for {money(invoice.total, self.currency)}."]
        if invoice.due_date:
            lines.append(f"Please pay by {invoice.due_date:%d %b %Y}.")
        if link:
            lines += ["", "See and print it here:", link]
        if self.payment_details:
            lines += ["", "How to pay:", self.payment_details]
        lines += ["", "Thank you,", business["name"]]
        mailer = self.mailer or self.panel.auth.mailer
        if mailer is None:
            return False
        try:
            call(mailer, to=contact.email, subject=subject, body="\n".join(lines), url=link, invoice=invoice,
                 kind="invoice_sent")
        except Exception:  # a broken mail server must not lose the invoice
            log.exception("Could not email invoice %s to %s", invoice.number, contact.email)
            return False
        return True

    # ------------------------------------------------------------------ routes
    def _routes(self, app: Any, panel: Any) -> None:
        routes = Routes(panel)
        plugin = self

        def show(ctx: Any, fd: Any, number: str, key: str):
            invoice = find_invoice(ctx.db, number)
            if invoice is None or invoice.status == "draft" \
                    or not hmac.compare_digest(invoice.access_key.encode(), key.encode()):
                return routes.error(ctx, 404, "Invoice not found", "Check the link you were sent.")
            from markupsafe import Markup

            document = Markup(panel.renderer.render("tungsten_finance/document.html",
                                                    **document_data(panel, plugin, invoice)))
            return ctx.render("tungsten_finance/public.html", title=f"Invoice {invoice.number}", document=document)

        @app.get(f"/{self.public_path}/{{number}}/{{key}}")
        async def public_invoice(request: Request, number: str, key: str):
            return await routes.run(request, show, public=True, number=number, key=key)


__all__ = [
    "CashFlowChart", "Contact", "ContactResource", "Expense", "ExpenseCategory", "ExpenseCategoryChart",
    "ExpenseCategoryResource", "ExpenseResource", "FinanceBase", "FinancePlugin", "FinanceReports",
    "FinanceStats", "Invoice", "InvoiceItem", "InvoiceResource", "MoneyAccount", "MoneyAccountResource",
    "Payment", "PaymentResource", "ReportStats", "account_balance", "create_invoice", "expenses_by_category",
    "find_invoice", "find_or_create_contact", "money", "money_in", "money_out", "next_number", "recalculate",
    "receivables", "record_payment", "refresh_paid", "tax_summary",
]
