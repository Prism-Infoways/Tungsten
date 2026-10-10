"""Finance and accounting plugin for Tungsten, in the spirit of Tally, Busy and Zoho Books.

    from tungsten_finance import FinancePlugin

    panel.plugin(FinancePlugin(state="27", business_tax_id="27ABCDE1234F1Z5",
                               payment_details="UPI: shop@okhdfc"))
    panel.create_tables(engine)   # also creates the finance tables

Sales (invoices, quotes, credit notes, payments received), purchases (bills, debit notes, payments
made, expenses), items with stock, a double-entry ledger with chart of accounts and journal vouchers,
GST with CGST/SGST/IGST, and reports: profit and loss, balance sheet, trial balance, ledger statements,
day book, GSTR-1 and GSTR-3B, stock summary and bank reconciliation.
"""

from __future__ import annotations

import csv
import datetime as dt
import hmac
import io
import logging
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import select

from tungsten import Plugin
from tungsten.routes import Routes
from tungsten.support.evaluate import call

from .documents import (
    DOCUMENT_RESOURCES,
    BillResource,
    CreditNoteResource,
    DebitNoteResource,
    InvoiceResource,
    QuoteResource,
)
from .gst import STATES, gstr1, gstr3b, state_code
from .ledger import (
    account,
    account_balance,
    balance_sheet,
    balances,
    contact_balance,
    day_book,
    ensure_chart,
    post,
    post_document,
    profit_and_loss,
    statement,
    stock_summary,
    trial_balance,
)
from .models import (
    Contact,
    Expense,
    FinanceBase,
    Invoice,
    InvoiceItem,
    Item,
    LedgerAccount,
    Payment,
    Voucher,
    VoucherLine,
)
from .pages import REPORT_PAGES, FinanceReports
from .resources import (
    RESOURCES,
    ContactResource,
    ExpenseResource,
    ItemResource,
    JournalResource,
    LedgerAccountResource,
    MoneyAccountResource,
    PaymentMadeResource,
    PaymentReceivedResource,
)
from .service import (
    copy_document,
    create_bill,
    create_document,
    create_invoice,
    expenses_by_category,
    find_invoice,
    find_or_create_contact,
    money,
    money_in,
    money_out,
    next_number,
    payables,
    quote_to_invoice,
    recalculate,
    receivables,
    record_payment,
    refresh_paid,
    run_recurring,
    settle,
)
from .views import document_data
from .widgets import CashFlowChart, ExpenseCategoryChart, FinanceStats, ReportStats, report_range

__version__ = "0.2.0"

log = logging.getLogger("tungsten.finance")

SALES = [InvoiceResource, QuoteResource, CreditNoteResource, PaymentReceivedResource, ContactResource]
PURCHASES = [BillResource, DebitNoteResource, PaymentMadeResource, ExpenseResource]
ACCOUNTING = [LedgerAccountResource, MoneyAccountResource, JournalResource, ItemResource]


class FinancePlugin(Plugin):
    """``FinancePlugin(state="27", currency="INR", due_days=15, default_tax_rate=18, ...)``.

    - ``state`` is your GST state (code like ``"27"`` or a name like ``"Maharashtra"``). Sales to
      another state get IGST, the rest CGST + SGST.
    - ``currency`` is an ISO code (INR, USD, EUR...). Amounts show with its symbol.
    - ``prefixes`` change document numbers, e.g. ``{"invoice": "INV/25-26/"}``; ``number_prefix`` is
      the invoice one.
    - ``due_days`` sets due dates; ``terms`` is printed at the bottom of invoices and quotes.
    - ``default_tax_rate`` fills the GST % of new lines (18, or 0 for none).
    - ``round_off`` rounds totals to the rupee, booked to the Round off account.
    - ``business_*`` and ``logo_url`` are printed at the top of documents. The name defaults to the panel's.
    - ``payment_details`` (bank account, UPI id...) shows under unpaid invoices as "How to pay".
    - ``public_links`` adds ``<panel>/invoice/<number>/<key>``: a page the customer opens and prints
      without logging in.
    - ``year_start_month`` is the first month of the financial year in reports (4: April, as in India).
    - ``mailer`` sends invoice emails; by default the panel's ``Auth(mailer=...)``.
    - ``navigation_groups`` renames the menu groups: ``{"sales": ..., "purchases": ..., "accounting": ...,
      "reports": ...}``.
    """

    id = "finance"
    metadata = FinanceBase.metadata
    templates = Path(__file__).with_name("templates")

    def __init__(self, state: str | None = None, currency: str = "INR", number_prefix: str | None = None,
                 prefixes: dict[str, str] | None = None, due_days: int = 15, default_tax_rate: float = 18,
                 round_off: bool = True, terms: str | None = None, business_name: str | None = None,
                 business_address: str | None = None, business_tax_id: str | None = None,
                 business_email: str | None = None, business_phone: str | None = None,
                 logo_url: str | None = None, payment_details: str | None = None, public_links: bool = True,
                 public_path: str = "invoice", year_start_month: int = 4, mailer: Any = None,
                 dashboard_widgets: bool = True, reports: bool = True, default_accounts: bool = True,
                 navigation_groups: dict[str, str] | None = None) -> None:
        self.state = state_code(state) or (state_code(business_tax_id) if business_tax_id else None)
        self.currency = currency.upper()
        self.prefixes = dict(prefixes or {})
        if number_prefix:
            self.prefixes.setdefault("invoice", number_prefix)
        self.due_days = due_days
        self.default_tax_rate = default_tax_rate
        self.round_off = round_off
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
        self.default_accounts = default_accounts
        self.navigation_groups = {"sales": "Sales", "purchases": "Purchases", "accounting": "Accounting",
                                  "reports": "Finance reports", **(navigation_groups or {})}
        self.panel: Any = None
        self.sent_listeners: dict[str, Any] = {}

    # ------------------------------------------------------------------ hooks for other code
    def on_invoice_sent(self, key: str, fn: Any) -> None:
        """Run ``fn(db, invoice, link)`` after an invoice is sent (a WhatsApp plugin can send it there too)."""
        self.sent_listeners[key] = fn

    # ------------------------------------------------------------------ setup
    def register(self, panel: Any) -> None:
        self.panel = panel
        groups = self.navigation_groups
        for group, resources in (("sales", SALES), ("purchases", PURCHASES), ("accounting", ACCOUNTING)):
            for resource in resources:
                resource.navigation_group = groups[group]
        panel.resources([*SALES, *PURCHASES, *ACCOUNTING])
        panel.navigation_group(groups["sales"], icon="wallet")
        panel.navigation_group(groups["purchases"], icon="shopping-bag")
        panel.navigation_group(groups["accounting"], icon="book-open")
        if self.reports:
            for page in REPORT_PAGES:
                page.navigation_group = groups["reports"]
            panel.pages(REPORT_PAGES)
            panel.navigation_group(groups["reports"], icon="chart-pie", collapsed=True)
        if self.dashboard_widgets:
            panel.widgets([FinanceStats, CashFlowChart])
        panel.routes(self._routes)

    def boot(self, panel: Any) -> None:
        if panel.session_factory is None or panel.is_async:
            return
        try:
            panel.with_session(self._seed)
        except Exception:  # noqa: BLE001  tables not made yet: create_tables() runs later
            log.debug("Finance tables not ready; chart of accounts not added yet")

    def _seed(self, db: Any) -> None:
        ensure_chart(db, expense_accounts=self.default_accounts)
        db.commit()

    def permissions(self) -> list[tuple[str, str]]:
        return [("finance.reports", "See finance reports")]

    def business(self, panel: Any = None) -> dict[str, Any]:
        """What is printed at the top of documents."""
        panel = panel or self.panel
        return {"name": self.business_name or (panel.brand_name if panel is not None else ""),
                "address": self.business_address, "tax_id": self.business_tax_id,
                "email": self.business_email, "phone": self.business_phone, "logo_url": self.logo_url,
                "state": STATES.get(self.state or "", None)}

    def default_account_id(self, db: Any) -> int | None:
        """The first bank account, else Cash: where payments go when none is picked."""
        bank = db.scalars(select(LedgerAccount.id).where(LedgerAccount.kind == "bank",
                                                         LedgerAccount.is_active.is_(True))
                          .order_by(LedgerAccount.id)).first()
        return bank or account(db, "cash").id

    # ------------------------------------------------------------------ links
    def public_path_for(self, invoice: Invoice) -> str:
        return self.panel.url(self.public_path, invoice.number, invoice.access_key)

    def customer_link(self, invoice: Invoice, ctx: Any = None) -> str | None:
        """The customer's private link to the document (None without public links or a known address)."""
        if not self.public_links or invoice.is_purchase:
            return None
        path = self.public_path_for(invoice)
        if self.panel.app_url:
            return f"{self.panel.app_url}{path}"
        if ctx is not None and getattr(ctx, "request", None) is not None:
            return self.panel.absolute_url(ctx, path)
        return None

    # ------------------------------------------------------------------ sending
    def send_invoice(self, db: Any, invoice: Invoice, ctx: Any = None) -> bool:
        """Mark the invoice (or quote) sent and email its link to the customer. True when an email went out."""
        if invoice.status == "draft":
            invoice.status = "sent"
        invoice.sent_at = dt.datetime.now().replace(microsecond=0)
        settle(db, invoice)
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
        what = {"quote": "quote", "credit_note": "credit note"}.get(invoice.kind, "invoice")
        subject = f"{what.title()} {invoice.number} from {business['name']}"
        lines = [f"Hello {contact.name},", "", f"Here is {what} {invoice.number} for {money(invoice.total, self.currency)}."]
        if invoice.due_date and invoice.kind == "invoice":
            lines.append(f"Please pay by {invoice.due_date:%d %b %Y}.")
        if link:
            lines += ["", "See and print it here:", link]
        if self.payment_details and invoice.kind == "invoice":
            lines += ["", "How to pay:", self.payment_details]
        lines += ["", "Thank you,", business["name"]]
        mailer = self.mailer or self.panel.auth.mailer
        if mailer is None:
            return False
        try:
            call(mailer, to=contact.email, subject=subject, body="\n".join(lines), url=link, invoice=invoice,
                 kind=f"{invoice.kind}_sent")
        except Exception:  # a broken mail server must not lose the invoice
            log.exception("Could not email %s to %s", invoice.number, contact.email)
            return False
        return True

    # ------------------------------------------------------------------ routes
    def _routes(self, app: Any, panel: Any) -> None:
        routes = Routes(panel)
        plugin = self

        def show(ctx: Any, fd: Any, number: str, key: str):
            invoice = find_invoice(ctx.db, number)
            if invoice is None or invoice.status == "draft" or invoice.is_purchase \
                    or not hmac.compare_digest(invoice.access_key.encode(), key.encode()):
                return routes.error(ctx, 404, "Not found", "Check the link you were sent.")
            from markupsafe import Markup

            document = Markup(panel.renderer.render("tungsten_finance/document.html",
                                                    **document_data(panel, plugin, invoice)))
            return ctx.render("tungsten_finance/public.html", title=invoice.number, document=document)

        def export(ctx: Any, fd: Any, name: str):
            if not ctx.can("finance.reports"):
                return routes.error(ctx, 403, "Not allowed", "You can't see finance reports.")
            ctx.__dict__["_filters"] = dict(ctx.request.query_params)
            start, end = report_range(ctx)
            rows = export_rows(ctx.db, name.removesuffix(".csv"), start, end, ctx.request.query_params)
            if rows is None:
                return routes.error(ctx, 404, "Not found", "No such report.")
            out = io.StringIO()
            csv.writer(out).writerows(rows)
            from starlette.responses import Response

            return Response(out.getvalue(), media_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="{name}"'})

        if self.public_links:
            @app.get(f"/{self.public_path}/{{number}}/{{key}}")
            async def public_invoice(request: Request, number: str, key: str):
                return await routes.run(request, show, public=True, number=number, key=key)

        @app.get("/finance-export/{name}")
        async def finance_export(request: Request, name: str):
            return await routes.run(request, export, name=name)


def export_rows(db: Any, name: str, start: Any, end: Any, params: Any = None) -> list[list] | None:
    """Rows (header first) of a report as CSV: trial-balance, profit-and-loss, balance-sheet, ledger,
    gstr1-b2b, gstr1-b2c, gstr1-hsn."""
    params = params or {}
    if name == "trial-balance":
        tb = trial_balance(db, end)
        return [["Code", "Account", "Group", "Debit", "Credit"]] + [
            [r["account"].code if r["account"] else "", r["account"].name if r["account"] else r["name"], r["group"],
             r["debit"], r["credit"]] for r in tb["rows"]] + [["", "Total", "", tb["debit"], tb["credit"]]]
    if name == "profit-and-loss":
        p = profit_and_loss(db, start, end)
        rows = [["Section", "Account", "Amount"]]
        for kind, items in p["sections"].items():
            rows += [[kind, r["account"].name, r["amount"]] for r in items]
        return rows + [["", "Gross profit", p["gross_profit"]], ["", "Net profit", p["net_profit"]]]
    if name == "balance-sheet":
        b = balance_sheet(db, end)
        rows = [["Side", "Group", "Account", "Amount"]]
        for side in ("liabilities", "equity", "assets"):
            for group, items in b[side].items():
                rows += [[side, group, r["account"].name, r["amount"]] for r in items]
        return rows + [["liabilities", "", "Profit and loss account", b["profit"]]]
    if name == "ledger":
        account_id = int(params["account"]) if params.get("account") else None
        contact_id = int(params["contact"]) if params.get("contact") else None
        st = statement(db, account_id=account_id, contact_id=contact_id, start=start, end=end)
        return [["Date", "Number", "Type", "Particulars", "Debit", "Credit", "Balance"],
                ["", "", "", "Opening balance", "", "", st["opening"]]] + [
            [r["date"], r["number"], r["kind"], r["particulars"], r["debit"], r["credit"], r["balance"]]
            for r in st["rows"]]
    if name in ("gstr1-b2b", "gstr1-cdnr"):
        data = gstr1(db, start, end)["b2b" if name == "gstr1-b2b" else "credit_notes"]
        return [["GSTIN", "Name", "Number", "Date", "Place of supply", "Taxable", "IGST", "CGST", "SGST", "Total"]] + [
            [r["gstin"] or "", r["name"], r["number"], r["date"], r["pos"] or "", r["taxable"], r["igst"], r["cgst"],
             r["sgst"], r["total"]] for r in data]
    if name == "gstr1-b2c":
        return [["Place of supply", "Rate", "Taxable", "Tax"]] + [
            [r["pos"], r["rate"], r["taxable"], r["tax"]] for r in gstr1(db, start, end)["b2c"]]
    if name == "gstr1-hsn":
        return [["HSN", "Rate", "Unit", "Quantity", "Taxable", "IGST", "CGST", "SGST"]] + [
            [r["hsn"], r["rate"], r["unit"], r["quantity"], r["taxable"], r["igst"], r["cgst"], r["sgst"]]
            for r in gstr1(db, start, end)["hsn"]]
    return None


__all__ = [
    "DOCUMENT_RESOURCES",
    "RESOURCES",
    "BillResource",
    "CashFlowChart",
    "Contact",
    "ContactResource",
    "CreditNoteResource",
    "DebitNoteResource",
    "Expense",
    "ExpenseCategoryChart",
    "ExpenseResource",
    "FinanceBase",
    "FinancePlugin",
    "FinanceReports",
    "FinanceStats",
    "Invoice",
    "InvoiceItem",
    "InvoiceResource",
    "Item",
    "ItemResource",
    "JournalResource",
    "LedgerAccount",
    "LedgerAccountResource",
    "MoneyAccountResource",
    "Payment",
    "PaymentMadeResource",
    "PaymentReceivedResource",
    "QuoteResource",
    "ReportStats",
    "Voucher",
    "VoucherLine",
    "account",
    "account_balance",
    "balance_sheet",
    "balances",
    "contact_balance",
    "copy_document",
    "create_bill",
    "create_document",
    "create_invoice",
    "day_book",
    "ensure_chart",
    "expenses_by_category",
    "export_rows",
    "find_invoice",
    "find_or_create_contact",
    "gstr1",
    "gstr3b",
    "money",
    "money_in",
    "money_out",
    "next_number",
    "payables",
    "post",
    "post_document",
    "profit_and_loss",
    "quote_to_invoice",
    "recalculate",
    "receivables",
    "record_payment",
    "refresh_paid",
    "run_recurring",
    "settle",
    "statement",
    "stock_summary",
    "trial_balance",
]
