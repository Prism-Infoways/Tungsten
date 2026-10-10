"""Admin screens: payments, expenses, contacts, items, chart of accounts, bank and cash, journals.

Invoices, quotes, notes and bills are in ``documents.py``.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import func, select

from tungsten import Resource
from tungsten.actions import ActionGroup, BulkAction, DeleteAction, DeleteBulkAction, EditAction, ViewAction
from tungsten.forms import (
    DatePicker,
    FileUpload,
    Placeholder,
    Repeater,
    Section,
    Select,
    Textarea,
    TextInput,
    Toggle,
)
from tungsten.importexport import ExportAction, ExportBulkAction
from tungsten.tables import DateFilter, ListTab, SelectFilter, TextColumn, ToggleColumn
from tungsten.tables.summarizers import Sum

from .common import (
    all_account_options,
    cached,
    contact_options,
    customers,
    default_money_account,
    dr_cr,
    expense_account_options,
    money_account_options,
    qty,
    show_money,
    symbol,
    vendors,
)
from .gst import STATE_OPTIONS, state_code, state_name, valid_gstin
from .ledger import (
    KIND_OPTIONS,
    KINDS,
    MONEY_KINDS,
    VOUCHER_KINDS,
    balances,
    contact_balance,
    post_expense,
    post_payment,
    stock_summary,
    unpost,
)
from .models import ZERO, Contact, Expense, Invoice, Item, LedgerAccount, Payment, Voucher, VoucherLine
from .service import CONTACT_KINDS, METHODS, OPEN_STATUSES, money, next_number, post_document, refresh_paid, to_decimal

SIDES = {"dr": "Dr (they owe / you have)", "cr": "Cr (you owe)"}


# ---------------------------------------------------------------------- payments
class PaymentResource(Resource):
    """Shared screen; subclasses set ``direction``."""

    model = Payment
    direction: ClassVar[str] = "in"
    navigation_group = "Sales"

    @classmethod
    def query(cls, ctx):
        return select(Payment).where(Payment.direction == cls.direction)

    @classmethod
    def form(cls, form):
        incoming = cls.direction == "in"
        kinds = ("invoice", "debit_note") if incoming else ("bill", "credit_note")

        def doc_options(ctx, get, record):
            query = select(Invoice).where(Invoice.kind.in_(kinds), Invoice.status.in_(OPEN_STATUSES))
            if get("contact_id"):
                query = query.where(Invoice.contact_id == int(get("contact_id")))
            rows = list(ctx.db.scalars(query.order_by(Invoice.issue_date.desc()).limit(300)).unique().all())
            if record is not None and record.invoice is not None and record.invoice not in rows:
                rows.append(record.invoice)
            return {str(d.id): f"{d.number} · {d.contact.name if d.contact else '—'} · "
                               f"{money(d.balance_due)} open" for d in rows}

        return form.columns(2).schema([
            Select("contact_id").label("From" if incoming else "To")
            .relationship("contact", "name", modify_query=customers if incoming else vendors)
            .searchable().preload().live(),
            Select("invoice_id").label("For invoice" if incoming else "For bill").options(doc_options).searchable()
            .helper_text("Empty: an advance, or money not for one document."),
            TextInput("amount").numeric().min_value(0.01).prefix(lambda ctx: symbol(ctx)).required(),
            DatePicker("date").default(lambda: dt.date.today()).required(),
            Select("method").options(METHODS).default("bank").required(),
            Select("account_id").label("Paid into" if incoming else "Paid from").options(money_account_options)
            .default(default_money_account),
            TextInput("reference").max_length(100).placeholder("UTR / cheque number"),
            DatePicker("cleared_on").label("Cleared in bank on").helper_text("For bank reconciliation."),
            Textarea("notes").rows(2).column_span("full"),
        ])

    @classmethod
    def before_create(cls, record):
        record.direction = cls.direction

    @classmethod
    def before_save(cls, record, ctx):
        record.__dict__["_fin_old_invoice"] = record.invoice_id

    @classmethod
    def after_create(cls, record, db, ctx):
        record.number = next_number(db, "RCPT-" if cls.direction == "in" else "PAY-", Payment.number)
        cls._sync(record, db, None)

    @classmethod
    def after_save(cls, record, db, ctx):
        cls._sync(record, db, record.__dict__.pop("_fin_old_invoice", None))

    @classmethod
    def after_delete(cls, record, db):
        unpost(db, "payment", record.id)
        if record.invoice_id:
            invoice = db.get(Invoice, record.invoice_id)
            if invoice is not None:
                refresh_paid(db, invoice)
                post_document(db, invoice)

    @staticmethod
    def _sync(record, db, old_invoice_id):
        db.flush()
        if record.invoice_id:
            invoice = db.get(Invoice, record.invoice_id)
            if invoice is not None and invoice.contact_id:
                record.contact_id = invoice.contact_id
        db.flush()
        db.refresh(record)
        post_payment(db, record)
        for i in {record.invoice_id, old_invoice_id} - {None}:
            invoice = db.get(Invoice, i)
            if invoice is None:
                continue
            if invoice.status == "draft" and i == record.invoice_id:
                invoice.status = "sent"
            refresh_paid(db, invoice)
            post_document(db, invoice)

    @classmethod
    def table(cls, table):
        def cleared(records, data, db):
            for r in records:
                r.cleared_on = data.get("date") or dt.date.today()
            db.commit()

        return (
            table.columns([
                TextColumn("number").label("No.").searchable().sortable().weight("medium"),
                TextColumn("date").date().sortable(),
                TextColumn("contact.name").label("From" if cls.direction == "in" else "To").searchable()
                .placeholder("—"),
                TextColumn("invoice.number").label("For").placeholder("—"),
                TextColumn("method").badge().color("gray").format_state_using(lambda state: METHODS.get(state, state)),
                TextColumn("account.name").label("Account").placeholder("—").toggleable(),
                TextColumn("reference").placeholder("—").searchable().toggleable(),
                TextColumn("cleared_on").label("Cleared").date().placeholder("—").toggleable(),
                TextColumn("amount").sortable().format_state_using(show_money).weight("medium")
                .summarize(Sum().format_state_using(lambda state: f"{float(state or 0):,.2f}")),
            ])
            .filters([
                SelectFilter("method").options(METHODS),
                SelectFilter("account_id").label("Account").relationship("account", "name"),
                DateFilter("date"),
            ])
            .tabs([
                ListTab("all").label("All"),
                ListTab("uncleared").label("Not cleared in bank").query(
                    lambda query, model: query.where(model.cleared_on.is_(None))),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([
                BulkAction("cleared").label("Mark cleared in bank").icon("check")
                .form(lambda form: form.schema([DatePicker("date").label("Cleared on")
                                                .default(lambda: dt.date.today()).required()]))
                .action(cleared).success_notification_title("Marked as cleared"),
                ExportBulkAction(), DeleteBulkAction(),
            ])
            .header_actions([ExportAction()])
            .default_sort("date", "desc")
        )


class PaymentReceivedResource(PaymentResource):
    direction = "in"
    slug = "payments"
    icon = "hand-coins"
    navigation_sort = 3
    label = "Payment received"
    plural_label = "Payments received"
    description = "Money customers paid you. A payment for an invoice marks it part paid or paid."


class PaymentMadeResource(PaymentResource):
    direction = "out"
    slug = "payments-made"
    icon = "banknote"
    navigation_group = "Purchases"
    navigation_sort = 7
    label = "Payment made"
    plural_label = "Payments made"
    description = "Money you paid vendors for their bills, or refunds to customers."


# ---------------------------------------------------------------------- expenses
class ExpenseResource(Resource):
    model = Expense
    slug = "expenses"
    icon = "receipt"
    navigation_group = "Purchases"
    navigation_sort = 9
    description = "Money you spent straight away, with the bill or receipt. Booked to an expense account."

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Section("Expense").icon("receipt").column_span(2).columns(2).schema([
                TextInput("description").required().max_length(255).placeholder("Office rent for May")
                .column_span("full"),
                TextInput("amount").label("Amount paid").numeric().min_value(0.01)
                .prefix(lambda ctx: symbol(ctx)).required().helper_text("GST included."),
                TextInput("tax_amount").label("GST in it").numeric().min_value(0).default("0")
                .prefix(lambda ctx: symbol(ctx)).helper_text("Input tax you can claim back."),
                DatePicker("date").default(lambda: dt.date.today()).required(),
                Select("tax_kind").label("GST type").options({"cgst_sgst": "CGST + SGST (same state)",
                                                             "igst": "IGST (other state)"}).default("cgst_sgst"),
                Select("category_id").label("Expense account").options(expense_account_options).required(),
                Textarea("notes").rows(2).column_span("full"),
            ]),
            Section("Paid").icon("wallet").column_span(1).columns(1).schema([
                Select("contact_id").label("Paid to").relationship("contact", "name", modify_query=vendors)
                .searchable().preload(),
                Select("account_id").label("Paid from").options(money_account_options).default(default_money_account),
                Select("method").options(METHODS).default("bank").required(),
                TextInput("reference").max_length(100).placeholder("Bill number"),
                DatePicker("cleared_on").label("Cleared in bank on"),
                FileUpload("receipt").label("Bill or receipt").directory("finance/receipts").max_size(10240),
            ]),
        ])

    @classmethod
    def after_create(cls, record, db, ctx):
        db.flush()
        post_expense(db, record)

    @classmethod
    def after_save(cls, record, db, ctx):
        db.flush()
        post_expense(db, record)

    @classmethod
    def after_delete(cls, record, db):
        unpost(db, "expense", record.id)

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("date").date().sortable(),
                TextColumn("description").weight("medium").searchable().limit(60)
                .description(lambda record: record.contact.name if record.contact else None),
                TextColumn("category.name").label("Account").badge().color("gray").placeholder("—"),
                TextColumn("account.name").label("From").placeholder("—").toggleable(),
                TextColumn("tax_amount").label("GST").format_state_using(show_money).toggleable(hidden_by_default=True),
                TextColumn("amount").sortable().format_state_using(show_money).weight("medium")
                .summarize(Sum().format_state_using(lambda state: f"{float(state or 0):,.2f}")),
            ])
            .filters([
                SelectFilter("category_id").label("Account").options(expense_account_options).multiple(),
                SelectFilter("contact_id").label("Paid to").relationship("contact", "name"),
                SelectFilter("account_id").label("From").options(money_account_options),
                DateFilter("date"),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([ExportBulkAction(), DeleteBulkAction()])
            .header_actions([ExportAction()])
            .default_sort("date", "desc")
        )


# ---------------------------------------------------------------------- contacts
class ContactResource(Resource):
    model = Contact
    slug = "finance-contacts"
    icon = "users"
    navigation_group = "Sales"
    navigation_sort = 5
    label = "Customer or vendor"
    plural_label = "Customers & vendors"
    navigation_label = "Customers & vendors"
    description = "People and companies you bill or buy from, with GSTIN, state and what they owe."
    global_search_attributes: ClassVar[list[str]] = ["name", "company", "email", "tax_id"]
    record_title_attribute = "name"

    @classmethod
    def form(cls, form):
        def gstin_state(state, set, get):
            if state and not get("state"):
                set("state", state_code(state) or "")

        return form.columns(2).schema([
            TextInput("name").required().max_length(150),
            Select("kind").label("Type").options(CONTACT_KINDS).default("customer").required(),
            TextInput("company").max_length(150),
            TextInput("tax_id").label("GSTIN").max_length(15).live(on_blur=True).after_state_updated(gstin_state)
            .rule(lambda value: valid_gstin(value) or "This GSTIN doesn't look right (15 characters)."),
            Select("state").label("State").options(STATE_OPTIONS).searchable()
            .helper_text("Decides CGST + SGST or IGST."),
            TextInput("payment_days").label("Payment terms (days)").integer().min_value(0)
            .helper_text("Empty: your default."),
            TextInput("email").email().max_length(255).prefix_icon("mail"),
            TextInput("phone").tel().max_length(40).prefix_icon("phone"),
            Textarea("address").rows(3).column_span("full"),
            TextInput("opening_balance").label("Opening balance").numeric().default("0")
            .prefix(lambda ctx: symbol(ctx)),
            Select("opening_side").label("Opening side").options(SIDES).default("dr"),
            Textarea("notes").rows(2).column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        def balance(record, ctx):
            return dr_cr(contact_balance(ctx.db, record), ctx)

        def statement_url(record, ctx):
            return ctx.url("ledger-statement", contact=record.id, period="this_year")

        from tungsten.actions import Action

        return (
            table.columns([
                TextColumn("name").weight("medium").searchable().sortable()
                .description(lambda record: record.company),
                TextColumn("kind").label("Type").badge().color("gray")
                .format_state_using(lambda state: CONTACT_KINDS.get(state, state)),
                TextColumn("tax_id").label("GSTIN").searchable().placeholder("—").toggleable(),
                TextColumn("state").label("State").placeholder("—").toggleable(hidden_by_default=True)
                .format_state_using(lambda state: state_name(state)),
                TextColumn("email").searchable().copyable().placeholder("—").toggleable(),
                TextColumn("phone").placeholder("—").toggleable(hidden_by_default=True),
                TextColumn("balance").label("Balance").state(balance),
            ])
            .filters([SelectFilter("kind").label("Type").options(CONTACT_KINDS)])
            .actions([
                Action("statement").label("Statement").icon("book-open").color("gray").url(statement_url),
                ActionGroup([EditAction(), DeleteAction()]),
            ])
            .bulk_actions([ExportBulkAction(), DeleteBulkAction()])
            .header_actions([ExportAction()])
            .default_sort("name", "asc")
        )


# ---------------------------------------------------------------------- items
class ItemResource(Resource):
    model = Item
    slug = "finance-items"
    icon = "boxes"
    navigation_group = "Accounting"
    navigation_sort = 20
    label = "Item"
    navigation_label = "Items & stock"
    description = "Products and services with HSN/SAC, prices, GST rate and stock in hand."
    global_search_attributes: ClassVar[list[str]] = ["name", "sku", "hsn"]
    record_title_attribute = "name"

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("name").required().max_length(150).column_span("full"),
            Select("kind").label("Type").options({"goods": "Goods", "service": "Service"}).default("goods").required()
            .live(),
            TextInput("sku").label("SKU / code").max_length(60),
            TextInput("hsn").label("HSN / SAC").max_length(12),
            TextInput("unit").max_length(12).default("Nos").placeholder("Nos, Kg, Hrs"),
            TextInput("sale_price").numeric().min_value(0).default("0").prefix(lambda ctx: symbol(ctx)),
            TextInput("purchase_price").label("Cost price").numeric().min_value(0).default("0")
            .prefix(lambda ctx: symbol(ctx)),
            TextInput("tax_rate").label("GST %").numeric().min_value(0).default("18"),
            Toggle("track_stock").label("Track stock").default(True).visible(lambda get: get("kind") == "goods"),
            TextInput("opening_stock").numeric().default("0").visible(lambda get: get("kind") == "goods"),
            TextInput("reorder_level").label("Warn when stock is at").numeric()
            .visible(lambda get: get("kind") == "goods"),
            Textarea("description").rows(2).column_span("full"),
            Toggle("is_active").label("In use").default(True),
        ])

    @classmethod
    def table(cls, table):
        def stock(record, ctx):
            rows = cached(ctx, "stock", lambda: {r["item"].id: r for r in stock_summary(ctx.db)})
            row = rows.get(record.id)
            return f"{qty(row['closing'])} {record.unit or ''}".strip() if row else None

        def stock_color(record, ctx):
            rows = cached(ctx, "stock", lambda: {r["item"].id: r for r in stock_summary(ctx.db)})
            row = rows.get(record.id)
            return "danger" if row and row["low"] else None

        return (
            table.columns([
                TextColumn("name").weight("medium").searchable().sortable().description(lambda record: record.sku),
                TextColumn("kind").label("Type").badge().color("gray").toggleable(),
                TextColumn("hsn").label("HSN/SAC").searchable().placeholder("—"),
                TextColumn("sale_price").label("Price").format_state_using(show_money).sortable(),
                TextColumn("tax_rate").label("GST").format_state_using(lambda state: f"{float(state or 0):g}%"),
                TextColumn("stock").label("In stock").state(stock).placeholder("—").color(stock_color),
                ToggleColumn("is_active").label("In use").toggleable(),
            ])
            .filters([SelectFilter("kind").label("Type").options({"goods": "Goods", "service": "Service"})])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([ExportBulkAction(), DeleteBulkAction()])
            .header_actions([ExportAction()])
            .default_sort("name", "asc")
        )


# ---------------------------------------------------------------------- chart of accounts
def _in_use(db: Any, account: LedgerAccount) -> bool:
    return bool(db.scalar(select(func.count()).select_from(VoucherLine).where(VoucherLine.account_id == account.id)))


class LedgerAccountResource(Resource):
    model = LedgerAccount
    slug = "chart-of-accounts"
    icon = "list-tree"
    navigation_group = "Accounting"
    navigation_sort = 10
    label = "Account"
    plural_label = "Chart of accounts"
    navigation_label = "Chart of accounts"
    description = "Every account (ledger) in your books, with its group and balance. Like Tally's ledgers."
    global_search_attributes: ClassVar[list[str]] = ["name", "code"]
    record_title_attribute = "name"
    kinds: ClassVar[tuple[str, ...] | None] = None

    @classmethod
    def query(cls, ctx):
        query = select(LedgerAccount)
        return query.where(LedgerAccount.kind.in_(cls.kinds)) if cls.kinds else query

    @classmethod
    def form(cls, form):
        options = {k: v for k, v in KIND_OPTIONS.items() if not cls.kinds or k in cls.kinds}
        return form.columns(2).schema([
            TextInput("name").required().max_length(120),
            TextInput("code").max_length(20).placeholder("6100"),
            Select("kind").label("Group").options(options).default(cls.kinds[0] if cls.kinds else "expense")
            .required().disabled(lambda record: record is not None and record.is_system),
            TextInput("number").label("Account number / IFSC / UPI").max_length(60),
            TextInput("opening_balance").numeric().default("0").prefix(lambda ctx: symbol(ctx)),
            Select("opening_side").label("Opening side").options({"dr": "Dr", "cr": "Cr"}).default("dr"),
            Toggle("is_active").label("In use").default(True),
            Textarea("notes").rows(2).column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        def balance(record, ctx):
            return dr_cr(cached(ctx, "balances", lambda: balances(ctx.db)).get(record.id, ZERO), ctx)

        def statement_url(record, ctx):
            return ctx.url("ledger-statement", account=record.id, period="this_year")

        from tungsten.actions import Action

        tabs = [ListTab("all").label("All")]
        if not cls.kinds:
            from .ledger import GROUPS

            for group, label in GROUPS.items():
                kinds = [k for k, (g, _) in KINDS.items() if g == group]
                tabs.append(ListTab(group).label(label).query(
                    lambda query, model, kinds=kinds: query.where(model.kind.in_(kinds))))
        return (
            table.columns([
                TextColumn("code").sortable().searchable().placeholder("—"),
                TextColumn("name").weight("medium").searchable().sortable().description(lambda record: record.number),
                TextColumn("kind").label("Group").badge().color("gray")
                .format_state_using(lambda state: KIND_OPTIONS.get(state, state)),
                TextColumn("balance").label("Balance").state(balance).weight("medium"),
                ToggleColumn("is_active").label("In use").toggleable(),
            ])
            .tabs(tabs if len(tabs) > 1 else [])
            .filters([] if cls.kinds else [SelectFilter("kind").label("Group").options(KIND_OPTIONS)])
            .actions([
                Action("statement").label("Ledger").icon("book-open").color("gray").url(statement_url),
                ActionGroup([EditAction(), DeleteAction().visible(
                    lambda record, ctx: record is not None and not record.is_system and not _in_use(ctx.db, record))]),
            ])
            .bulk_actions([ExportBulkAction()])
            .header_actions([ExportAction()])
            .default_sort("code", "asc")
        )


class MoneyAccountResource(LedgerAccountResource):
    slug = "bank-and-cash"
    icon = "landmark"
    navigation_sort = 11
    label = "Bank or cash account"
    plural_label = "Bank & cash"
    navigation_label = "Bank & cash"
    description = "Where your money sits, with live balances from payments, bills and expenses."
    kinds = MONEY_KINDS


# ---------------------------------------------------------------------- journals
class JournalResource(Resource):
    """Manual entries: opening adjustments, depreciation, cash deposits (contra), salaries due..."""

    model = Voucher
    slug = "journals"
    icon = "notebook-pen"
    navigation_group = "Accounting"
    navigation_sort = 12
    label = "Journal voucher"
    navigation_label = "Journal vouchers"
    description = "Manual entries for anything that isn't an invoice, bill, payment or expense. Debit must equal credit."
    record_title_attribute = "number"

    @classmethod
    def query(cls, ctx):
        return select(Voucher).where(Voucher.source_type.is_(None))

    @classmethod
    def form(cls, form):
        def totals(get):
            rows = get("/lines") or []
            debit = sum((to_decimal(r.get("debit")) for r in rows), ZERO)
            credit = sum((to_decimal(r.get("credit")) for r in rows), ZERO)
            return debit, credit

        def balanced(value, get):
            debit, credit = totals(get)
            if not debit:
                return "Enter at least one debit and one credit."
            return True if debit == credit else f"Debit ({debit:,.2f}) and credit ({credit:,.2f}) must be equal."

        return form.columns(3).schema([
            Section("Voucher").icon("notebook-pen").column_span(2).columns(2).schema([
                Select("kind").label("Type").options({"journal": "Journal", "contra": "Contra (bank and cash)"})
                .default("journal").required(),
                DatePicker("date").default(lambda: dt.date.today()).required(),
                Textarea("narration").rows(2).column_span("full"),
            ]),
            Section("Total").icon("scale").column_span(1).columns(1).schema([
                Placeholder("debit_view").label("Debit").content(lambda get: f"{totals(get)[0]:,.2f}"),
                Placeholder("credit_view").label("Credit").content(lambda get: f"{totals(get)[1]:,.2f}"),
            ]),
            Section("Lines").icon("list").column_span("full").schema([
                Repeater("lines").relationship("lines", order_column="sort").table().hidden_label()
                .schema([
                    Select("account_id").label("Account").options(all_account_options).searchable().required(),
                    Select("contact_id").label("Customer / vendor").options(contact_options).searchable(),
                    TextInput("debit").numeric().min_value(0).live(debounce=500),
                    TextInput("credit").numeric().min_value(0).live(debounce=500),
                ])
                .min_items(2).default_items(2).add_action_label("Add line").column_span("full")
                .rule(balanced),
            ]),
        ])

    @classmethod
    def after_create(cls, record, db, ctx):
        prefix = "CV-" if record.kind == "contra" else "JV-"
        record.number = next_number(db, prefix, Voucher.number)
        cls._clean(record)

    @classmethod
    def after_save(cls, record, db, ctx):
        cls._clean(record)

    @staticmethod
    def _clean(record):
        for line in record.lines:
            line.debit = Decimal(line.debit or 0)
            line.credit = Decimal(line.credit or 0)

    @classmethod
    def infolist(cls, infolist):
        from .views import render_voucher

        return infolist.schema([
            Section("Voucher").icon("notebook-pen").schema([
                Placeholder("voucher").hidden_label().content(lambda record, ctx: render_voucher(ctx, record)),
            ]),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("number").label("No.").searchable().sortable().weight("medium"),
                TextColumn("date").date().sortable(),
                TextColumn("kind").label("Type").badge().color("gray")
                .format_state_using(lambda state: VOUCHER_KINDS.get(state, state)),
                TextColumn("narration").limit(70).searchable().placeholder("—"),
                TextColumn("total").label("Amount").state(lambda record: record.total).format_state_using(show_money),
            ])
            .filters([DateFilter("date")])
            .actions([ActionGroup([ViewAction(), EditAction(), DeleteAction()])])
            .bulk_actions([ExportBulkAction(), DeleteBulkAction()])
            .record_url(lambda record, ctx: cls.get_url(ctx, "view", record))
            .default_sort("date", "desc")
        )


RESOURCES = [PaymentReceivedResource, PaymentMadeResource, ExpenseResource, ContactResource, ItemResource,
             LedgerAccountResource, MoneyAccountResource, JournalResource]

__all__ = ["RESOURCES", "SIDES", "ContactResource", "ExpenseResource", "ItemResource", "JournalResource",
           "LedgerAccountResource", "MoneyAccountResource", "PaymentMadeResource", "PaymentReceivedResource"]
