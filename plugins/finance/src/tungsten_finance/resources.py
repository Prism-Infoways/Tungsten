"""Admin screens of the finance plugin: invoices, payments, expenses, contacts, accounts, categories."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import func, select

from tungsten import Resource
from tungsten.actions import (
    Action,
    ActionGroup,
    BulkAction,
    DeleteAction,
    DeleteBulkAction,
    EditAction,
    ViewAction,
)
from tungsten.forms import (
    DatePicker,
    FileUpload,
    Group,
    Placeholder,
    Repeater,
    Section,
    Select,
    Textarea,
    TextInput,
    Toggle,
)
from tungsten.importexport import ExportAction, ExportBulkAction
from tungsten.infolists import TextEntry
from tungsten.support.colors import COLOR_NAMES
from tungsten.tables import DateFilter, ListTab, SelectFilter, TextColumn, ToggleColumn
from tungsten.tables.summarizers import Sum

from .models import ZERO, Contact, Expense, ExpenseCategory, Invoice, MoneyAccount, Payment
from .service import (
    ACCOUNT_KINDS,
    CONTACT_KINDS,
    CURRENCY_SYMBOLS,
    INVOICE_STATUSES,
    METHODS,
    OPEN_STATUSES,
    account_balance,
    money,
    prepare_new,
    recalculate,
    record_payment,
    refresh_paid,
    to_decimal,
)
from .views import render_document
from .widgets import FinanceStats


def _plugin(ctx: Any) -> Any:
    return ctx.panel.get_plugin("finance") if ctx is not None else None


def currency(ctx: Any) -> str:
    plugin = _plugin(ctx)
    return plugin.currency if plugin is not None else "INR"


def symbol(ctx: Any) -> str:
    cur = currency(ctx)
    return CURRENCY_SYMBOLS.get(cur, f"{cur} ").strip()


def status_options() -> dict[str, str]:
    return {key: label for key, (label, _) in INVOICE_STATUSES.items() if key != "overdue"}


def status_label(state: Any) -> str:
    return INVOICE_STATUSES.get(str(state), (str(state), "gray"))[0]


def status_color(state: Any) -> str:
    return INVOICE_STATUSES.get(str(state), ("", "gray"))[1]


def account_options(ctx: Any) -> dict[str, str]:
    rows = ctx.db.scalars(select(MoneyAccount).where(MoneyAccount.is_active.is_(True))
                          .order_by(MoneyAccount.name)).all()
    return {str(a.id): a.name for a in rows}


def _customers(query: Any) -> Any:
    return query.where(Contact.kind.in_(("customer", "both")))


def _vendors(query: Any) -> Any:
    return query.where(Contact.kind.in_(("vendor", "both")))


def _default_tax(ctx: Any) -> str:
    plugin = _plugin(ctx)
    rate = plugin.default_tax_rate if plugin is not None else 0
    return f"{rate:g}"


def _default_account(ctx: Any) -> str | None:
    options = account_options(ctx)
    return next(iter(options), None)


def form_totals(get: Any) -> dict[str, Decimal]:
    """Totals of the invoice form while it is being filled in."""
    subtotal = tax = ZERO
    for row in get("/items") or []:
        amount = to_decimal(row.get("quantity"), Decimal(1)) * to_decimal(row.get("unit_price"))
        subtotal += amount
        tax += amount * to_decimal(row.get("tax_rate")) / 100
    discount = to_decimal(get("/discount"))
    subtotal, tax = subtotal.quantize(Decimal("0.01")), tax.quantize(Decimal("0.01"))
    return {"subtotal": subtotal, "tax": tax, "total": max(subtotal + tax - discount, ZERO)}


def _view_url(ctx: Any, record: Any) -> str:
    return InvoiceResource.get_url(ctx, "view", record)


# ---------------------------------------------------------------------- invoice actions
def payment_action() -> Action:
    """Book money the customer paid against this invoice."""

    def run(record, data, db, ctx):
        record_payment(db, record, data["amount"], date=data.get("date") or None,
                       account_id=int(data["account_id"]) if data.get("account_id") else None,
                       method=data.get("method") or "bank", reference=data.get("reference") or None)
        db.commit()

    return (
        Action("payment").label("Record payment").icon("hand-coins").color("success")
        .visible(lambda record: record is not None and record.status not in ("paid", "cancelled"))
        .modal_heading(lambda record: f"Payment for {record.number}")
        .form(lambda ctx: [
            TextInput("amount").numeric().min_value(0.01).prefix(symbol(ctx)).required(),
            DatePicker("date").default(lambda: dt.date.today()).required(),
            Select("method").options(METHODS).default("bank").required().native(),
            *([Select("account_id").label("Paid into").options(account_options).native()
               .default(lambda ctx: _default_account(ctx))] if account_options(ctx) else []),
            TextInput("reference").max_length(100).placeholder("UTR / cheque number"),
        ])
        .fill_form(lambda record: {"amount": f"{record.balance_due:.2f}", "date": dt.date.today(),
                                   "method": "bank"})
        .modal_submit_action_label("Save payment")
        .action(run)
        .success_notification_title("Payment saved")
    )


def send_action() -> Action:
    """Email the invoice link to the customer and mark it as sent."""

    def run(record, db, ctx):
        plugin = _plugin(ctx)
        if plugin is not None:
            plugin.send_invoice(db, record, ctx)
        db.commit()

    return (
        Action("send").label("Send").icon("send").color("primary")
        .visible(lambda record: record is not None and record.status not in ("paid", "cancelled"))
        .requires_confirmation()
        .modal_heading(lambda record: f"Send {record.number}")
        .modal_description(lambda record: f"We email the invoice link to {record.contact.email}."
                           if record.contact and record.contact.email
                           else "This customer has no email. The invoice is only marked as sent.")
        .action(run)
        .success_notification_title("Invoice sent")
    )


def cancel_action() -> Action:
    def run(record, db):
        record.status = "cancelled"
        db.commit()

    return (
        Action("cancel").label("Cancel invoice").icon("ban").color("danger")
        .visible(lambda record: record is not None and record.status not in ("paid", "cancelled"))
        .requires_confirmation()
        .modal_description("The invoice stays in your records but nobody owes it any more.")
        .action(run)
        .success_notification_title("Invoice cancelled")
    )


def open_link_action() -> Action:
    def link(record, ctx):
        plugin = _plugin(ctx)
        return plugin.public_path_for(record) if plugin is not None else "#"

    return Action("open").label("Customer view").icon("printer").color("gray").url(link, open_in_new_tab=True)


def duplicate_action() -> Action:
    def run(record, db, ctx):
        from .models import InvoiceItem

        copy = Invoice(contact_id=record.contact_id, discount=record.discount, notes=record.notes,
                       terms=record.terms, status="draft", issue_date=dt.date.today())
        for item in record.items:
            copy.items.append(InvoiceItem(description=item.description, quantity=item.quantity,
                                          unit_price=item.unit_price, tax_rate=item.tax_rate, sort=item.sort))
        db.add(copy)
        prepare_new(db, copy)
        recalculate(copy)
        db.commit()
        ctx.__dict__["_finance_copy"] = copy

    return (
        Action("duplicate").label("Duplicate").icon("copy").color("gray")
        .action(run)
        .success_notification_title("Copy made as a draft")
        .success_redirect_url(lambda ctx: InvoiceResource.get_url(ctx, "edit", ctx.__dict__["_finance_copy"]))
    )


class InvoiceResource(Resource):
    model = Invoice
    slug = "invoices"
    icon = "file-text"
    navigation_group = "Finance"
    navigation_sort = 1
    description = "Bill your customers, share a link they can print, and track what they still owe."
    global_search_attributes: ClassVar[list[str]] = ["number", "contact.name"]
    record_title_attribute = "number"
    widgets: ClassVar[list] = [FinanceStats]

    @classmethod
    def navigation_badge(cls, db):
        return db.scalar(select(func.count()).select_from(Invoice).where(
            Invoice.status.in_(OPEN_STATUSES), Invoice.due_date < dt.date.today())) or None

    navigation_badge_color = "danger"

    @classmethod
    def form(cls, form):
        def show(key):
            return lambda get, ctx: money(form_totals(get)[key], currency(ctx))

        return form.columns(3).schema([
            Section("Invoice").icon("file-text").column_span(2).columns(2).schema([
                Select("contact_id").label("Customer").relationship("contact", "name", modify_query=_customers)
                .searchable().preload().required().column_span("full"),
                DatePicker("issue_date").label("Invoice date").default(lambda: dt.date.today()).required(),
                DatePicker("due_date").label("Due date")
                .helper_text("Empty: set from your payment terms."),
                TextInput("number").max_length(30).unique().visible(lambda operation: operation != "create"),
                Select("status").options(status_options()).visible(lambda operation: operation != "create"),
            ]),
            Section("Total").icon("calculator").column_span(1).columns(1).schema([
                Placeholder("subtotal_view").label("Subtotal").content(show("subtotal")),
                Placeholder("tax_view").label("Tax").content(show("tax")),
                TextInput("discount").numeric().min_value(0).default("0").prefix(lambda ctx: symbol(ctx))
                .live(debounce=500),
                Placeholder("total_view").label("Total").content(show("total")),
            ]),
            Section("Items").icon("list").column_span("full").schema([
                Repeater("items").relationship("items", order_column="sort").table().hidden_label()
                .schema([
                    TextInput("description").required().max_length(255).placeholder("Website design"),
                    TextInput("quantity").label("Qty").numeric().min_value(0).default("1").required()
                    .live(debounce=500),
                    TextInput("unit_price").label("Price").numeric().required().live(debounce=500),
                    TextInput("tax_rate").label("Tax %").numeric().min_value(0).default(_default_tax)
                    .live(debounce=500),
                ])
                .min_items(1).add_action_label("Add line").column_span("full"),
            ]),
            Section("Notes").icon("sticky-note").column_span("full").columns(2).collapsible().schema([
                Textarea("notes").label("Note to the customer").rows(3),
                Textarea("terms").label("Terms").rows(3)
                .helper_text("Empty: your default terms."),
            ]),
        ])

    @classmethod
    def infolist(cls, infolist):
        return infolist.columns(3).schema([
            Section("Invoice").icon("file-text").column_span(2).columns(1).schema([
                Placeholder("document").hidden_label()
                .content(lambda record, ctx: render_document(ctx, record)),
            ]),
            Group([
                Section("Status").icon("flag").columns(1).schema([
                    TextEntry("status").badge().inline_label()
                    .state(lambda record: record.display_status)
                    .format_state_using(status_label).color(status_color),
                    TextEntry("total").inline_label()
                    .format_state_using(lambda state, ctx: money(state, currency(ctx))),
                    TextEntry("amount_paid").label("Paid").inline_label()
                    .format_state_using(lambda state, ctx: money(state, currency(ctx))),
                    TextEntry("balance_due").label("Still owed").inline_label().weight("bold")
                    .state(lambda record: record.balance_due)
                    .format_state_using(lambda state, ctx: money(state, currency(ctx)))
                    .color(lambda record: "danger" if record.is_overdue else None),
                    TextEntry("due_date").label("Due").date().placeholder("—").inline_label(),
                    TextEntry("sent_at").label("Sent").since().placeholder("Not yet").inline_label(),
                ]),
                Section("Customer").icon("user").columns(1).schema([
                    TextEntry("contact.name").label("Name").placeholder("—").inline_label(),
                    TextEntry("contact.email").label("Email").copyable().placeholder("—").inline_label(),
                    TextEntry("contact.phone").label("Phone").copyable().placeholder("—").inline_label(),
                ]),
            ]).columns(1).column_span(1),
        ])

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        actions = super().header_actions(ctx, page, record)
        if page == "view":
            return [payment_action().button(), send_action().button(), open_link_action().button(),
                    ActionGroup([EditAction(), duplicate_action(), cancel_action(), DeleteAction()]).button()]
        return actions

    @classmethod
    def after_create(cls, record, db, ctx):
        prepare_new(db, record)
        recalculate(record)
        db.flush()

    @classmethod
    def after_save(cls, record, db, ctx):
        recalculate(record)
        refresh_paid(db, record)

    @classmethod
    def table(cls, table):
        def is_open(model):
            return model.status.in_(OPEN_STATUSES)

        def bulk_cancel(records, db):
            for r in records:
                if r.status != "paid":
                    r.status = "cancelled"
            db.commit()

        def bulk_sent(records, db):
            for r in records:
                if r.status == "draft":
                    r.status = "sent"
                    r.sent_at = dt.datetime.now().replace(microsecond=0)
            db.commit()

        def fmt(state, ctx):
            return money(state, currency(ctx))

        return (
            table.columns([
                TextColumn("number").label("No.").searchable().sortable().copyable().weight("medium"),
                TextColumn("contact.name").label("Customer").searchable().sortable()
                .description(lambda record: record.contact.email if record.contact else None),
                TextColumn("issue_date").label("Date").date().sortable(),
                TextColumn("due_date").label("Due").date().sortable().toggleable()
                .color(lambda record: "danger" if record.is_overdue else None),
                TextColumn("status").badge().sortable().state(lambda record: record.display_status)
                .format_state_using(status_label).color(status_color),
                TextColumn("total").sortable().format_state_using(fmt)
                .summarize(Sum().format_state_using(lambda state: f"{float(state or 0):,.2f}")),
                TextColumn("balance_due").label("Owed").format_state_using(fmt)
                .state(lambda record: record.balance_due),
            ])
            .filters([
                SelectFilter("status").options(status_options()).multiple(),
                SelectFilter("contact_id").label("Customer").relationship("contact", "name"),
                DateFilter("issue_date").label("Invoice date"),
            ])
            .tabs([
                ListTab("all").label("All"),
                ListTab("unpaid").label("Unpaid").badge(color="warning")
                .query(lambda query, model: query.where(is_open(model))),
                ListTab("overdue").label("Overdue").badge(color="danger").query(
                    lambda query, model: query.where(is_open(model), model.due_date < dt.date.today())),
                ListTab("draft").label("Drafts").query(lambda query, model: query.where(model.status == "draft")),
                ListTab("paid").label("Paid").query(lambda query, model: query.where(model.status == "paid")),
            ])
            .actions([
                payment_action().icon_button(),
                ActionGroup([ViewAction(), EditAction(), open_link_action(), DeleteAction()]),
            ])
            .bulk_actions([
                BulkAction("sent").label("Mark as sent").icon("send").action(bulk_sent)
                .success_notification_title("Invoices marked as sent"),
                BulkAction("cancel").label("Cancel").icon("ban").color("danger").requires_confirmation()
                .action(bulk_cancel).success_notification_title("Invoices cancelled"),
                ExportBulkAction(),
                DeleteBulkAction(),
            ])
            .header_actions([ExportAction()])
            .record_url(lambda record, ctx: _view_url(ctx, record))
            .default_sort("issue_date", "desc")
        )


# ---------------------------------------------------------------------- payments
class PaymentResource(Resource):
    model = Payment
    slug = "payments"
    icon = "hand-coins"
    navigation_group = "Finance"
    navigation_sort = 2
    label = "Payment"
    description = "Money you received. A payment against an invoice marks it part paid or paid."

    @classmethod
    def form(cls, form):
        def invoice_options(ctx, record):
            rows = list(ctx.db.scalars(select(Invoice).where(Invoice.status.in_(("draft", *OPEN_STATUSES)))
                                       .order_by(Invoice.issue_date.desc()).limit(300)).unique().all())
            if record is not None and record.invoice is not None and record.invoice not in rows:
                rows.append(record.invoice)
            return {str(i.id): f"{i.number} · {i.contact.name if i.contact else '—'} · "
                               f"{money(i.balance_due, currency(ctx))} owed" for i in rows}

        return form.columns(2).schema([
            Select("invoice_id").label("Invoice").options(invoice_options).searchable().live()
            .helper_text("Empty for money that is not for an invoice.").column_span("full"),
            Select("contact_id").label("From").relationship("contact", "name", modify_query=_customers)
            .searchable().preload().visible(lambda get: not get("invoice_id")),
            TextInput("amount").numeric().min_value(0.01).prefix(lambda ctx: symbol(ctx)).required(),
            DatePicker("date").default(lambda: dt.date.today()).required(),
            Select("method").options(METHODS).default("bank").required(),
            Select("account_id").label("Paid into").options(account_options).default(_default_account),
            TextInput("reference").max_length(100).placeholder("UTR / cheque number"),
            Textarea("notes").rows(2).column_span("full"),
        ])

    @classmethod
    def before_save(cls, record, ctx):
        record.__dict__["_fin_old_invoice"] = record.invoice_id

    @classmethod
    def after_create(cls, record, db, ctx):
        cls._fill_contact(record, db)
        cls._sync(db, record.invoice_id, None)

    @classmethod
    def after_save(cls, record, db, ctx):
        cls._fill_contact(record, db)
        cls._sync(db, record.invoice_id, record.__dict__.pop("_fin_old_invoice", None))

    @classmethod
    def after_delete(cls, record, db):
        cls._sync(db, None, record.invoice_id)

    @staticmethod
    def _fill_contact(record, db):
        if record.invoice_id:
            invoice = db.get(Invoice, record.invoice_id)
            if invoice is not None and invoice.contact_id:
                record.contact_id = invoice.contact_id

    @staticmethod
    def _sync(db, invoice_id, old_invoice_id):
        """Update the paid amount of the payment's invoice (and of the one it moved away from)."""
        db.flush()
        for i in {invoice_id, old_invoice_id} - {None}:
            invoice = db.get(Invoice, i)
            if invoice is None:
                continue
            if invoice.status == "draft" and i == invoice_id:
                invoice.status = "sent"
            refresh_paid(db, invoice)

    @classmethod
    def table(cls, table):
        def fmt(state, ctx):
            return money(state, currency(ctx))

        return (
            table.columns([
                TextColumn("date").date().sortable(),
                TextColumn("contact.name").label("From").searchable().placeholder("—"),
                TextColumn("invoice.number").label("Invoice").placeholder("—")
                .url(lambda record, ctx: InvoiceResource.get_url(ctx, "view", record.invoice)
                     if record.invoice else None),
                TextColumn("method").badge().color("gray").format_state_using(lambda state: METHODS.get(state, state)),
                TextColumn("account.name").label("Into").placeholder("—").toggleable(),
                TextColumn("reference").placeholder("—").searchable().toggleable(),
                TextColumn("amount").sortable().format_state_using(fmt).weight("medium"),
            ])
            .filters([
                SelectFilter("method").options(METHODS),
                SelectFilter("account_id").label("Account").relationship("account", "name"),
                DateFilter("date"),
            ])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([ExportBulkAction(), DeleteBulkAction()])
            .header_actions([ExportAction()])
            .default_sort("date", "desc")
        )


# ---------------------------------------------------------------------- expenses
class ExpenseResource(Resource):
    model = Expense
    slug = "expenses"
    icon = "receipt"
    navigation_group = "Finance"
    navigation_sort = 3
    description = "Money you spent, with the bill or receipt, so the reports show your real profit."

    @classmethod
    def form(cls, form):
        return form.columns(3).schema([
            Section("Expense").icon("receipt").column_span(2).columns(2).schema([
                TextInput("description").required().max_length(255).placeholder("Office rent for May")
                .column_span("full"),
                TextInput("amount").label("Amount paid").numeric().min_value(0.01)
                .prefix(lambda ctx: symbol(ctx)).required().helper_text("Tax included."),
                TextInput("tax_amount").label("Tax in it").numeric().min_value(0).default("0")
                .prefix(lambda ctx: symbol(ctx)).helper_text("GST you can claim back."),
                DatePicker("date").default(lambda: dt.date.today()).required(),
                Select("category_id").label("Category").relationship("category", "name").preload(),
                Textarea("notes").rows(2).column_span("full"),
            ]),
            Section("Paid").icon("wallet").column_span(1).columns(1).schema([
                Select("contact_id").label("Paid to").relationship("contact", "name", modify_query=_vendors)
                .searchable().preload(),
                Select("account_id").label("Paid from").options(account_options).default(_default_account),
                Select("method").options(METHODS).default("bank").required(),
                TextInput("reference").max_length(100).placeholder("Bill number"),
                FileUpload("receipt").label("Bill or receipt").directory("finance/receipts").max_size(10240),
            ]),
        ])

    @classmethod
    def table(cls, table):
        def fmt(state, ctx):
            return money(state, currency(ctx))

        return (
            table.columns([
                TextColumn("date").date().sortable(),
                TextColumn("description").weight("medium").searchable().limit(60)
                .description(lambda record: record.contact.name if record.contact else None),
                TextColumn("category.name").label("Category").badge()
                .color(lambda record: record.category.color if record.category else "gray").placeholder("—"),
                TextColumn("account.name").label("From").placeholder("—").toggleable(),
                TextColumn("tax_amount").label("Tax").format_state_using(fmt).toggleable(hidden_by_default=True),
                TextColumn("amount").sortable().format_state_using(fmt).weight("medium"),
            ])
            .filters([
                SelectFilter("category_id").label("Category").relationship("category", "name").multiple(),
                SelectFilter("contact_id").label("Paid to").relationship("contact", "name"),
                SelectFilter("account_id").label("Account").relationship("account", "name"),
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
    navigation_group = "Finance"
    navigation_sort = 4
    label = "Customer or vendor"
    plural_label = "Customers & vendors"
    navigation_label = "Customers & vendors"
    description = "People and companies you bill or pay."
    global_search_attributes: ClassVar[list[str]] = ["name", "company", "email"]
    record_title_attribute = "name"

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("name").required().max_length(150),
            Select("kind").label("Type").options(CONTACT_KINDS).default("customer").required(),
            TextInput("company").max_length(150),
            TextInput("tax_id").label("GSTIN / tax number").max_length(40),
            TextInput("email").email().max_length(255).prefix_icon("mail"),
            TextInput("phone").tel().max_length(40).prefix_icon("phone"),
            Textarea("address").rows(3).column_span("full"),
            Textarea("notes").rows(2).column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        def owed(record, ctx):
            total = sum((i.balance_due for i in ctx.db.scalars(select(Invoice).where(
                Invoice.contact_id == record.id, Invoice.status.in_(OPEN_STATUSES))).unique().all()), ZERO)
            return money(total, currency(ctx)) if total else None

        return (
            table.columns([
                TextColumn("name").weight("medium").searchable().sortable()
                .description(lambda record: record.company),
                TextColumn("kind").label("Type").badge().color("gray")
                .format_state_using(lambda state: CONTACT_KINDS.get(state, state)),
                TextColumn("email").searchable().copyable().placeholder("—"),
                TextColumn("phone").placeholder("—").toggleable(),
                TextColumn("tax_id").label("GSTIN").placeholder("—").toggleable(hidden_by_default=True),
                TextColumn("owed").label("Owes you").state(owed).placeholder("—"),
            ])
            .filters([SelectFilter("kind").label("Type").options(CONTACT_KINDS)])
            .actions([EditAction(), DeleteAction()])
            .bulk_actions([ExportBulkAction(), DeleteBulkAction()])
            .header_actions([ExportAction()])
            .default_sort("name", "asc")
        )


# ---------------------------------------------------------------------- settings screens
class MoneyAccountResource(Resource):
    model = MoneyAccount
    slug = "money-accounts"
    icon = "landmark"
    navigation_group = "Finance"
    navigation_sort = 40
    label = "Bank or cash account"
    plural_label = "Bank & cash"
    navigation_label = "Bank & cash"
    description = "Where your money sits. The balance is the opening balance plus payments in, minus expenses."
    simple = True

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("name").required().max_length(100).placeholder("HDFC current account"),
            Select("kind").label("Type").options(ACCOUNT_KINDS).default("bank").required(),
            TextInput("number").label("Account number / UPI id").max_length(60),
            TextInput("opening_balance").numeric().default("0").prefix(lambda ctx: symbol(ctx)),
            Toggle("is_active").label("In use").default(True),
            Textarea("notes").rows(2).column_span("full"),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").weight("medium").searchable().description(lambda record: record.number),
                TextColumn("kind").label("Type").badge().color("gray")
                .format_state_using(lambda state: ACCOUNT_KINDS.get(state, state)),
                TextColumn("balance").state(lambda record, ctx: money(account_balance(ctx.db, record),
                                                                      currency(ctx))).weight("medium"),
                ToggleColumn("is_active").label("In use"),
            ])
            .actions([EditAction(), DeleteAction()])
            .default_sort("name", "asc")
        )


class ExpenseCategoryResource(Resource):
    model = ExpenseCategory
    slug = "expense-categories"
    icon = "tags"
    navigation_group = "Finance"
    navigation_sort = 50
    label = "Expense category"
    description = "Kinds of expenses, like Rent or Salaries. The reports group spending by these."
    simple = True

    @classmethod
    def form(cls, form):
        return form.columns(2).schema([
            TextInput("name").required().max_length(100).placeholder("Rent"),
            Select("color").options({c: c.title() for c in COLOR_NAMES if c != "primary"} | {"primary": "Brand"})
            .default("gray").required(),
            TextInput("sort").label("Order").integer().default(0),
        ])

    @classmethod
    def table(cls, table):
        return (
            table.columns([
                TextColumn("name").badge().color(lambda record: record.color or "gray"),
                TextColumn("sort").label("Order").sortable(),
            ])
            .actions([EditAction(), DeleteAction()])
            .reorderable("sort")
            .default_sort("sort", "asc")
        )


__all__ = [
    "ContactResource", "ExpenseCategoryResource", "ExpenseResource", "InvoiceResource", "MoneyAccountResource",
    "PaymentResource", "payment_action", "send_action",
]
