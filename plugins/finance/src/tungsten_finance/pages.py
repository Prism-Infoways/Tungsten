"""Report pages: overview, profit and loss, balance sheet, trial balance, ledger statement, day book,
GST returns, stock summary and bank reconciliation. Each draws its tables with ``blocks.html``."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, ClassVar

from markupsafe import Markup
from sqlalchemy import select

from tungsten import Page
from tungsten.actions import Action
from tungsten.forms import Select

from .common import all_account_options, contact_options, currency, money_account_options, qty
from .gst import gstr1, gstr3b, state_name
from .ledger import (
    KINDS,
    MONEY_KINDS,
    VOUCHER_KINDS,
    balance_sheet,
    balances,
    day_book,
    profit_and_loss,
    statement,
    stock_summary,
    trial_balance,
)
from .models import ZERO, Expense, LedgerAccount, Payment
from .service import AGING_BUCKETS, PERIODS, money, payables, receivables, top_debtors
from .widgets import CashFlowChart, ExpenseCategoryChart, ReportStats, report_range


def _m(ctx: Any):
    cur = currency(ctx)
    return lambda value: money(value, cur)


def _dr_cr(value: Decimal, m: Any) -> str:
    return m(0) if not value else f"{m(abs(value))} {'Dr' if value > 0 else 'Cr'}"


def source_url(ctx: Any, source_type: str | None, source_id: int | None, kind: str | None = None) -> str | None:
    if source_type is None or source_id is None:
        return None
    if source_type == "document":
        from .models import Invoice

        doc = ctx.db.get(Invoice, source_id)
        if doc is None:
            return None
        slug = {"invoice": "invoices", "quote": "quotes", "credit_note": "credit-notes", "bill": "bills",
                "debit_note": "debit-notes"}[doc.kind]
        return ctx.url(slug, source_id)
    if source_type == "payment":
        payment = ctx.db.get(Payment, source_id)
        slug = "payments-made" if payment is not None and payment.direction == "out" else "payments"
        return ctx.url(slug, source_id, "edit")
    if source_type == "expense":
        return ctx.url("expenses", source_id, "edit")
    return None


def _ledger_link(ctx: Any, account: LedgerAccount, text: str | None = None, period: str | None = None) -> dict:
    params = {"account": account.id}
    if period:
        params["period"] = period
    return {"text": text or account.name, "url": ctx.url("ledger-statement", **params)}


class ReportPage(Page):
    """A report with a period picker."""

    navigation_group = "Finance reports"
    permission = "finance.reports"
    period_label: ClassVar[str] = "Period"
    default_period: ClassVar[str] = "this_year"
    as_of: ClassVar[bool] = False
    csv: ClassVar[list[tuple[str, str]]] = []

    @classmethod
    def filters_form(cls, form):
        options = PERIODS
        if cls.as_of:
            options = {"this_month": "Today", "last_month": "End of last month",
                       "last_year": "End of last financial year", "this_year": "Today (this year)"}
        return form.schema(cls.extra_filters() + [
            Select("period").label("As on" if cls.as_of else "Period").options(options)
            .default(cls.default_period).native()])

    @classmethod
    def extra_filters(cls) -> list:
        return []

    @classmethod
    def header_actions(cls, ctx):
        period = (ctx.filters or {}).get("period") or cls.default_period
        return [Action(f"csv_{name}").label(label).icon("download").color("gray")
                .url(ctx.url("finance-export", f"{name}.csv", period=period, **cls.csv_params(ctx)))
                for name, label in cls.csv]

    @classmethod
    def csv_params(cls, ctx) -> dict:
        return {}

    @classmethod
    def range(cls, ctx) -> tuple[dt.date | None, dt.date | None]:
        return report_range(ctx)

    @classmethod
    def blocks(cls, ctx) -> list[dict]:
        return []

    @classmethod
    def content(cls, ctx: Any) -> Any:
        return Markup(ctx.panel.renderer.render("tungsten_finance/blocks.html", blocks=cls.blocks(ctx), ctx=ctx,
                                                wide=getattr(cls, "wide", False)))


class FinanceReports(ReportPage):
    slug = "finance-reports"
    title = "Finance overview"
    navigation_label = "Overview"
    icon = "chart-pie"
    navigation_sort = 1
    default_period = "this_month"
    subheading = "Sales, money in and out, profit, who owes you and whom you owe."
    widgets: ClassVar[list] = [ReportStats, ExpenseCategoryChart, CashFlowChart]

    @classmethod
    def blocks(cls, ctx):
        db, m = ctx.db, _m(ctx)
        start, end = cls.range(ctx)

        def aging(buckets):
            rows = [[label, {"text": m(buckets[key]), "color": "danger" if key != "current" and buckets[key] else None}]
                    for key, label in AGING_BUCKETS]
            return rows, ["Total", m(sum(buckets.values(), ZERO))]

        owed_rows, owed_foot = aging(receivables(db))
        owe_rows, owe_foot = aging(payables(db))
        bal = balances(db)
        accounts = db.scalars(select(LedgerAccount).where(LedgerAccount.kind.in_(MONEY_KINDS))
                              .order_by(LedgerAccount.name)).all()
        tax = gstr3b(db, start, end)
        cols = [("", "start"), ("Amount", "end")]
        return [
            {"title": "Customers owe you", "icon": "hand-coins", "columns": cols, "rows": owed_rows, "foot": owed_foot},
            {"title": "You owe vendors", "icon": "receipt", "columns": cols, "rows": owe_rows, "foot": owe_foot},
            {"title": "Who owes the most", "icon": "users", "columns": [("Customer", "start"), ("Amount", "end")],
             "rows": [[n, m(a)] for n, a in top_debtors(db)], "empty": "Nobody owes you money right now."},
            {"title": "Bank and cash balances", "icon": "landmark", "columns": [("Account", "start"), ("Balance", "end")],
             "rows": [[_ledger_link(ctx, a), _dr_cr(bal.get(a.id, ZERO), m)] for a in accounts],
             "empty": "Add your bank accounts in Bank & cash."},
            {"title": "GST in this period", "icon": "percent", "columns": cols,
             "rows": [["Charged on sales", m(sum((tax["outward"][k] for k in ("igst", "cgst", "sgst")), ZERO))],
                      ["Input tax credit", m(sum((tax["itc"][k] for k in ("igst", "cgst", "sgst")), ZERO))]],
             "foot": ["To pay", m(tax["net"])], "link": {"label": "GST returns", "url": ctx.url("gst-returns")}},
        ]


class ProfitLossReport(ReportPage):
    slug = "profit-and-loss"
    title = "Profit and loss"
    icon = "trending-up"
    navigation_sort = 2
    subheading = "Sales less purchases is gross profit; less other expenses is net profit."
    csv: ClassVar[list] = [("profit-and-loss", "CSV")]

    @classmethod
    def blocks(cls, ctx):
        m = _m(ctx)
        start, end = cls.range(ctx)
        period = (ctx.filters or {}).get("period")
        p = profit_and_loss(ctx.db, start, end)
        s, t = p["sections"], p["totals"]

        def rows(kind):
            return [[_ledger_link(ctx, r["account"], period=period) | {"indent": 1}, m(r["amount"])] for r in s[kind]]

        cols = [("Account", "start"), ("Amount", "end")]
        trading = [[{"text": "Sales", "bold": True}, m(t["sales"])], *rows("sales"),
                   [{"text": "Less: Purchases", "bold": True}, m(t["purchase"])], *rows("purchase"),
                   [{"text": "Less: Direct expenses", "bold": True}, m(t["direct_expense"])], *rows("direct_expense")]
        pnl = [[{"text": "Gross profit", "bold": True}, m(p["gross_profit"])],
               [{"text": "Add: Other income", "bold": True}, m(t["other_income"])], *rows("other_income"),
               [{"text": "Less: Indirect expenses", "bold": True}, m(t["expense"])], *rows("expense")]
        net = p["net_profit"]
        return [
            {"title": "Trading account", "icon": "scale", "columns": cols, "rows": trading,
             "foot": ["Gross profit", m(p["gross_profit"])]},
            {"title": "Profit and loss", "icon": "trending-up", "columns": cols, "rows": pnl,
             "foot": ["Net profit" if net >= 0 else "Net loss",
                      {"text": m(net), "color": "success" if net >= 0 else "danger"}]},
        ]


class BalanceSheetReport(ReportPage):
    slug = "balance-sheet"
    title = "Balance sheet"
    icon = "scale"
    navigation_sort = 3
    as_of = True
    default_period = "this_month"
    subheading = "What the business owns and owes, on a date."
    csv: ClassVar[list] = [("balance-sheet", "CSV")]

    @classmethod
    def blocks(cls, ctx):
        m = _m(ctx)
        _, end = cls.range(ctx)
        b = balance_sheet(ctx.db, end)

        def side(groups):
            out = []
            for label, rows in groups.items():
                out.append([{"text": label, "bold": True}, m(sum((r["amount"] for r in rows), ZERO))])
                out += [[_ledger_link(ctx, r["account"]) | {"indent": 1}, m(r["amount"])] for r in rows]
            return out

        liab = side(b["liabilities"]) + side(b["equity"])
        liab.append([{"text": "Profit and loss account", "bold": True}, m(b["profit"])])
        if b["opening_difference"]:
            liab.append([{"text": "Difference in opening balances", "color": "danger"}, m(b["opening_difference"])])
        cols = [("", "start"), ("Amount", "end")]
        note = None if b["balanced"] else "The two sides don't match. Check opening balances in Chart of accounts."
        on = f"as on {end:%d %b %Y}" if end else ""
        return [
            {"title": f"Liabilities and capital {on}", "icon": "landmark", "columns": cols, "rows": liab,
             "foot": ["Total", m(b["total_liabilities"])], "note": note},
            {"title": f"Assets {on}", "icon": "wallet", "columns": cols, "rows": side(b["assets"]),
             "foot": ["Total", m(b["total_assets"])]},
        ]


class TrialBalanceReport(ReportPage):
    slug = "trial-balance"
    title = "Trial balance"
    icon = "list-checks"
    navigation_sort = 4
    as_of = True
    default_period = "this_month"
    subheading = "Every account's closing balance. Debit and credit totals must match."
    csv: ClassVar[list] = [("trial-balance", "CSV")]

    @classmethod
    def blocks(cls, ctx):
        m = _m(ctx)
        _, end = cls.range(ctx)
        tb = trial_balance(ctx.db, end)
        rows = []
        for r in tb["rows"]:
            name = _ledger_link(ctx, r["account"]) if r["account"] is not None else {"text": r["name"], "color": "danger"}
            rows.append([r["account"].code or "" if r["account"] else "", name, r["group"],
                         m(r["debit"]) if r["debit"] else "", m(r["credit"]) if r["credit"] else ""])
        return [{"title": "Trial balance" + (f" as on {end:%d %b %Y}" if end else ""), "icon": "list-checks",
                 "columns": [("Code", "start"), ("Account", "start"), ("Group", "start"), ("Debit", "end"),
                             ("Credit", "end")],
                 "rows": rows, "foot": ["", "Total", "", m(tb["debit"]), m(tb["credit"])],
                 "note": None if tb["balanced"] else "Debit and credit don't match.", "wide": True}]


class LedgerStatementReport(ReportPage):
    slug = "ledger-statement"
    title = "Ledger statement"
    icon = "book-open"
    navigation_sort = 5
    subheading = "Every entry of one account, or one customer or vendor, with a running balance."
    csv: ClassVar[list] = [("ledger", "CSV")]

    @classmethod
    def extra_filters(cls):
        return [Select("account").label("Account").options(all_account_options).searchable(),
                Select("contact").label("Customer / vendor").options(contact_options).searchable()]

    @classmethod
    def csv_params(cls, ctx):
        f = ctx.filters or {}
        return {k: f[k] for k in ("account", "contact") if f.get(k)}

    @classmethod
    def blocks(cls, ctx):
        m = _m(ctx)
        f = ctx.filters or {}
        account_id = int(f["account"]) if f.get("account") else None
        contact_id = int(f["contact"]) if f.get("contact") else None
        if not account_id and not contact_id:
            return [{"title": "Pick an account or a customer / vendor above", "icon": "book-open", "columns": [],
                     "rows": [], "empty": "Choose what to show from the filters at the top of the page."}]
        start, end = cls.range(ctx)
        st = statement(ctx.db, account_id=account_id, contact_id=contact_id, start=start, end=end)
        rows = [["", {"text": "Opening balance", "bold": True}, "", "", "", "", _dr_cr(st["opening"], m)]]
        for r in st["rows"]:
            url = source_url(ctx, r["source_type"], r["source_id"])
            rows.append([f"{r['date']:%d %b %Y}", r["particulars"], r["kind"],
                         {"text": r["number"] or "", "url": url} if url else (r["number"] or ""),
                         m(r["debit"]) if r["debit"] else "", m(r["credit"]) if r["credit"] else "",
                         _dr_cr(r["balance"], m)])
        title = []
        if account_id:
            acct = ctx.db.get(LedgerAccount, account_id)
            title.append(acct.name if acct else "")
        if contact_id:
            from .models import Contact

            contact = ctx.db.get(Contact, contact_id)
            title.append(contact.name if contact else "")
        return [{"title": " · ".join(title), "icon": "book-open", "wide": True,
                 "columns": [("Date", "start"), ("Particulars", "start"), ("Type", "start"), ("No.", "start"),
                             ("Debit", "end"), ("Credit", "end"), ("Balance", "end")],
                 "rows": rows, "foot": ["", "Closing balance", "", "", m(st["debit"]), m(st["credit"]),
                                        _dr_cr(st["closing"], m)]}]


class DayBookReport(ReportPage):
    slug = "day-book"
    title = "Day book"
    icon = "calendar-days"
    navigation_sort = 6
    default_period = "this_month"
    subheading = "Every voucher in the books, newest first."

    @classmethod
    def blocks(cls, ctx):
        m = _m(ctx)
        start, end = cls.range(ctx)
        rows = []
        for v in day_book(ctx.db, start, end):
            url = source_url(ctx, v.source_type, v.source_id) or (
                ctx.url("journals", v.id) if v.source_type is None else None)
            parts = [f"{ln.account.name} {'Dr' if ln.debit else 'Cr'}" for ln in v.lines]
            rows.append([f"{v.date:%d %b %Y}", {"text": v.number or "—", "url": url},
                         VOUCHER_KINDS.get(v.kind, v.kind), "; ".join(parts), m(v.total)])
        return [{"title": "Vouchers", "icon": "calendar-days", "wide": True,
                 "columns": [("Date", "start"), ("No.", "start"), ("Type", "start"), ("Accounts", "start"),
                             ("Amount", "end")], "rows": rows}]


class GstReport(ReportPage):
    slug = "gst-returns"
    title = "GST returns"
    icon = "percent"
    navigation_sort = 7
    default_period = "this_month"
    subheading = "GSTR-3B summary and the GSTR-1 tables (B2B, B2C, credit notes, HSN). Check with your CA before filing."
    csv: ClassVar[list] = [("gstr1-b2b", "B2B CSV"), ("gstr1-b2c", "B2C CSV"), ("gstr1-hsn", "HSN CSV")]
    wide = True

    @classmethod
    def blocks(cls, ctx):
        m = _m(ctx)
        start, end = cls.range(ctx)
        r3 = gstr3b(ctx.db, start, end)
        r1 = gstr1(ctx.db, start, end)
        heads = ("igst", "cgst", "sgst")
        three_b = [
            ["3.1 Outward supplies (sales less credit notes)", m(r3["outward"]["taxable"]),
             *[m(r3["outward"][h]) for h in heads]],
            ["4. Input tax credit (bills, debit notes, expenses)", m(r3["itc"]["taxable"]),
             *[m(r3["itc"][h]) for h in heads]],
        ]
        tax_cols = [("IGST", "end"), ("CGST", "end"), ("SGST", "end")]

        def doc_rows(rows):
            return [[r["number"], f"{r['date']:%d %b %Y}", r["gstin"] or "—", r["name"],
                     state_name(r["pos"]) or "—", m(r["taxable"]), m(r["igst"]), m(r["cgst"]), m(r["sgst"]),
                     m(r["total"])] for r in rows]

        doc_cols = [("No.", "start"), ("Date", "start"), ("GSTIN", "start"), ("Name", "start"),
                    ("Place of supply", "start"), ("Taxable", "end"), *tax_cols, ("Total", "end")]
        return [
            {"title": "GSTR-3B summary", "icon": "percent",
             "columns": [("", "start"), ("Taxable value", "end"), *tax_cols], "rows": three_b,
             "foot": ["Tax to pay (before cash ledger)", "", *[m(r3["payable"][h]) for h in heads]],
             "note": f"Net GST to pay: {m(r3['net'])}"},
            {"title": "GSTR-1 · B2B invoices (customers with GSTIN)", "icon": "building-2", "columns": doc_cols,
             "rows": doc_rows(r1["b2b"])},
            {"title": "GSTR-1 · B2C (customers without GSTIN)", "icon": "users",
             "columns": [("Place of supply", "start"), ("GST rate", "end"), ("Taxable", "end"), ("Tax", "end")],
             "rows": [[state_name(r["pos"]) or "—", f"{r['rate']}%", m(r["taxable"]), m(r["tax"])]
                      for r in r1["b2c"]]},
            {"title": "GSTR-1 · Credit notes", "icon": "undo-2", "columns": doc_cols,
             "rows": doc_rows(r1["credit_notes"])},
            {"title": "GSTR-1 · HSN summary", "icon": "list",
             "columns": [("HSN/SAC", "start"), ("Rate", "end"), ("Qty", "end"), ("Taxable", "end"), *tax_cols],
             "rows": [[r["hsn"], f"{r['rate']}%", f"{qty(r['quantity'])} {r['unit']}".strip(), m(r["taxable"]),
                       m(r["igst"]), m(r["cgst"]), m(r["sgst"])] for r in r1["hsn"]]},
        ]


class StockReport(ReportPage):
    slug = "stock-summary"
    title = "Stock summary"
    icon = "boxes"
    navigation_sort = 8
    as_of = True
    default_period = "this_month"
    subheading = "Opening stock, plus bought, less sold, and its value at cost."

    @classmethod
    def blocks(cls, ctx):
        m = _m(ctx)
        _, end = cls.range(ctx)
        rows = stock_summary(ctx.db, end)
        out = [[{"text": r["item"].name, "url": ctx.url("finance-items", r["item"].id, "edit")},
                r["item"].hsn or "", qty(r['opening']), qty(r['in']), qty(r['out']),
                {"text": f"{qty(r['closing'])} {r['item'].unit or ''}".strip(), "color": "danger" if r["low"] else None},
                m(r["value"])] for r in rows]
        return [{"title": "Stock in hand", "icon": "boxes", "wide": True,
                 "columns": [("Item", "start"), ("HSN", "start"), ("Opening", "end"), ("In", "end"), ("Out", "end"),
                             ("Closing", "end"), ("Value", "end")],
                 "rows": out, "foot": ["Total", "", "", "", "", "", m(sum((r["value"] for r in rows), ZERO))],
                 "empty": "Add goods in Items & stock to see stock here."}]


class BankReconciliation(ReportPage):
    slug = "bank-reconciliation"
    title = "Bank reconciliation"
    icon = "landmark"
    navigation_sort = 9
    as_of = True
    default_period = "this_month"
    subheading = "Match your books with the bank statement. Mark payments as cleared in the payments lists."

    @classmethod
    def extra_filters(cls):
        return [Select("bank").label("Bank account").options(money_account_options).native()]

    @classmethod
    def blocks(cls, ctx):
        m = _m(ctx)
        db = ctx.db
        f = ctx.filters or {}
        options = money_account_options(ctx)
        bank_id = int(f["bank"]) if f.get("bank") else (int(next(iter(options))) if options else None)
        if bank_id is None:
            return [{"title": "Add a bank account first", "columns": [], "rows": [],
                     "empty": "Add your bank in Bank & cash."}]
        _, end = cls.range(ctx)
        acct = db.get(LedgerAccount, bank_id)
        books = balances(db, end).get(bank_id, ZERO)
        pending = []
        query = select(Payment).where(Payment.account_id == bank_id, Payment.cleared_on.is_(None))
        expenses = select(Expense).where(Expense.account_id == bank_id, Expense.cleared_on.is_(None))
        if end:
            query, expenses = query.where(Payment.date <= end), expenses.where(Expense.date <= end)
        deposits = withdrawals = ZERO
        for p in db.scalars(query).unique().all():
            sign = 1 if p.direction == "in" else -1
            deposits += p.amount if sign > 0 else ZERO
            withdrawals += p.amount if sign < 0 else ZERO
            pending.append([f"{p.date:%d %b %Y}", {"text": p.number or "—", "url": ctx.url(
                "payments" if sign > 0 else "payments-made", p.id, "edit")},
                p.contact.name if p.contact else "", m(p.amount) if sign > 0 else "", m(p.amount) if sign < 0 else ""])
        for e in db.scalars(expenses).unique().all():
            withdrawals += e.amount
            pending.append([f"{e.date:%d %b %Y}", {"text": e.description, "url": ctx.url("expenses", e.id, "edit")},
                            e.contact.name if e.contact else "", "", m(e.amount)])
        bank = books - deposits + withdrawals
        return [
            {"title": f"{acct.name if acct else ''}", "icon": "landmark", "columns": [("", "start"), ("Amount", "end")],
             "rows": [["Balance as per books", _dr_cr(books, m)],
                      ["Less: money in not yet in the bank", m(deposits)],
                      ["Add: money out not yet out of the bank", m(withdrawals)]],
             "foot": ["Balance as per bank (should match the statement)", _dr_cr(bank, m)]},
            {"title": "Not cleared yet", "icon": "clock", "wide": True,
             "columns": [("Date", "start"), ("Entry", "start"), ("Party", "start"), ("In", "end"), ("Out", "end")],
             "rows": pending, "empty": "Everything is cleared."},
        ]


REPORT_PAGES = [FinanceReports, ProfitLossReport, BalanceSheetReport, TrialBalanceReport, LedgerStatementReport,
                DayBookReport, GstReport, StockReport, BankReconciliation]

__all__ = ["KINDS", "REPORT_PAGES", "BalanceSheetReport", "BankReconciliation", "DayBookReport", "FinanceReports",
           "GstReport", "LedgerStatementReport", "ProfitLossReport", "StockReport", "TrialBalanceReport"]
