"""Admin screens for sales and purchase documents: invoices, quotes, credit notes, bills and debit notes.

They share one table (``Invoice.kind``) and one screen class; each kind turns its own buttons on.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
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
    Group,
    Placeholder,
    Repeater,
    Section,
    Select,
    Textarea,
    TextInput,
)
from tungsten.importexport import ExportAction, ExportBulkAction
from tungsten.infolists import TextEntry
from tungsten.tables import DateFilter, ListTab, SelectFilter, TextColumn
from tungsten.tables.summarizers import Sum

from .common import (
    currency,
    customers,
    default_money_account,
    expense_account_options,
    money_account_options,
    plugin_of,
    qty,
    show_money,
    symbol,
    vendors,
)
from .gst import STATE_OPTIONS, is_inter_state, split_tax, state_code, state_name
from .ledger import unpost
from .models import ZERO, Contact, Invoice, Item
from .service import (
    DOC_KINDS,
    METHODS,
    OPEN_STATUSES,
    copy_document,
    home_state,
    money,
    prepare_new,
    quote_to_invoice,
    record_payment,
    refresh_paid,
    settle,
    statuses_for,
    to_decimal,
)
from .views import render_document
from .widgets import FinanceStats

REPEAT_OPTIONS = {"1": "Every month", "3": "Every 3 months", "6": "Every 6 months", "12": "Every year"}


def form_totals(get: Any, ctx: Any) -> dict[str, Decimal]:
    """Totals of a document form while it is being filled in, with the GST split."""
    subtotal = discount = tax = ZERO
    for row in get("/items") or []:
        gross = to_decimal(row.get("quantity"), Decimal(1)) * to_decimal(row.get("unit_price"))
        off = gross * to_decimal(row.get("discount")) / 100
        subtotal += gross
        discount += off
        tax += ((gross - off) * to_decimal(row.get("tax_rate")) / 100).quantize(Decimal("0.01"))
    subtotal, discount = subtotal.quantize(Decimal("0.01")), discount.quantize(Decimal("0.01"))
    taxable = subtotal - discount
    plugin = plugin_of(ctx)
    supply = state_code(get("/place_of_supply"))
    if not supply and get("/contact_id"):
        contact = ctx.db.get(Contact, int(get("/contact_id")))
        supply = contact.state if contact is not None else None
    cgst, sgst, igst = split_tax(tax, is_inter_state(home_state(plugin), supply))
    exact = taxable + tax
    total = exact.quantize(Decimal(1), rounding=ROUND_HALF_UP) if (plugin is None or plugin.round_off) else exact
    return {"subtotal": subtotal, "discount": discount, "taxable": taxable, "cgst": cgst, "sgst": sgst,
            "igst": igst, "round_off": total - exact, "total": total}


def _status_label(kind: str):
    return lambda state: statuses_for(kind).get(str(state), (str(state), "gray"))[0] \
        if str(state) != "overdue" else "Overdue"


def _status_color(kind: str):
    return lambda state: "danger" if str(state) == "overdue" else statuses_for(kind).get(str(state), ("", "gray"))[1]


def _resource_for(kind: str) -> type:
    return {"invoice": InvoiceResource, "quote": QuoteResource, "credit_note": CreditNoteResource,
            "bill": BillResource, "debit_note": DebitNoteResource}[kind]


def _open_docs(ctx: Any, kinds: tuple[str, ...], contact_id: Any = None, current: Any = None) -> dict[str, str]:
    query = select(Invoice).where(Invoice.kind.in_(kinds), Invoice.status.in_(("draft", *OPEN_STATUSES)))
    if contact_id:
        query = query.where(Invoice.contact_id == int(contact_id))
    rows = list(ctx.db.scalars(query.order_by(Invoice.issue_date.desc()).limit(300)).unique().all())
    if current is not None and current not in rows:
        rows.append(current)
    return {str(d.id): f"{d.number} · {d.contact.name if d.contact else '—'} · "
                       f"{money(d.balance_due, currency(ctx))} open" for d in rows}


# ---------------------------------------------------------------------- actions
def payment_action() -> Action:
    """Money in for an invoice or debit note, money out for a bill or credit note."""

    def run(record, data, db, ctx):
        record_payment(db, record, data["amount"], date=data.get("date") or None,
                       account_id=int(data["account_id"]) if data.get("account_id") else None,
                       method=data.get("method") or "bank", reference=data.get("reference") or None)
        db.commit()

    def label(record):
        if record is not None and record.kind == "bill":
            return "Pay bill"
        if record is not None and record.is_note:
            return "Record refund"
        return "Record payment"

    return (
        Action("payment").label(label).icon("hand-coins").color("success")
        .visible(lambda record: record is not None and record.kind != "quote"
                 and record.status not in ("paid", "cancelled") and not (record.is_note and record.against_id))
        .modal_heading(lambda record: f"{label(record)}: {record.number}")
        .form(lambda ctx: [
            TextInput("amount").numeric().min_value(0.01).prefix(symbol(ctx)).required(),
            DatePicker("date").default(lambda: dt.date.today()).required(),
            Select("method").options(METHODS).default("bank").required().native(),
            Select("account_id").label("Bank or cash").options(money_account_options).native()
            .default(default_money_account),
            TextInput("reference").max_length(100).placeholder("UTR / cheque number"),
        ])
        .fill_form(lambda record, ctx: {"amount": f"{record.balance_due:.2f}", "date": dt.date.today(),
                                        "method": "bank", "account_id": default_money_account(ctx)})
        .modal_submit_action_label("Save")
        .action(run)
        .success_notification_title("Saved")
    )


def confirm_action() -> Action:
    """A draft becomes final and is booked in the ledger (no email)."""

    def run(record, db):
        record.status = "sent"
        settle(db, record)
        db.commit()

    return (
        Action("confirm").label(lambda record: "Mark as sent" if record is not None and record.kind in
                                ("invoice", "quote") else "Confirm")
        .icon("check").color("gray")
        .visible(lambda record: record is not None and record.status == "draft")
        .action(run).success_notification_title("Done")
    )


def send_action() -> Action:
    """Email the invoice or quote link to the customer and mark it as sent."""

    def run(record, db, ctx):
        plugin = plugin_of(ctx)
        if plugin is not None:
            plugin.send_invoice(db, record, ctx)
        settle(db, record)
        db.commit()

    return (
        Action("send").label("Send").icon("send").color("primary")
        .visible(lambda record: record is not None and record.kind in ("invoice", "quote", "credit_note")
                 and record.status in ("draft", "sent", "partial"))
        .requires_confirmation()
        .modal_heading(lambda record: f"Send {record.number}")
        .modal_description(lambda record: f"We email the link to {record.contact.email}."
                           if record.contact and record.contact.email
                           else "This customer has no email. It is only marked as sent.")
        .action(run)
        .success_notification_title("Sent")
    )


def cancel_action() -> Action:
    def run(record, db):
        record.status = "cancelled"
        settle(db, record)
        db.commit()

    return (
        Action("cancel").label("Cancel").icon("ban").color("danger")
        .visible(lambda record: record is not None and record.status not in ("paid", "cancelled", "invoiced"))
        .requires_confirmation()
        .modal_description("It stays in your records but is taken out of the books and nobody owes it any more.")
        .action(run)
        .success_notification_title("Cancelled")
    )


def open_link_action() -> Action:
    def link(record, ctx):
        plugin = plugin_of(ctx)
        return plugin.public_path_for(record) if plugin is not None else "#"

    return (Action("open").label("Customer view").icon("printer").color("gray").url(link, open_in_new_tab=True)
            .visible(lambda record: record is not None and not record.is_purchase))


def _go_to(kind: str, page: str = "edit"):
    return lambda ctx: _resource_for(kind).get_url(ctx, page, ctx.__dict__["_finance_new"])


def duplicate_action() -> Action:
    def run(record, db, ctx):
        ctx.__dict__["_finance_new"] = copy_document(db, record)
        db.commit()

    return (Action("duplicate").label("Duplicate").icon("copy").color("gray").action(run)
            .success_notification_title("Copy made as a draft")
            .success_redirect_url(lambda record, ctx: _resource_for(record.kind).get_url(
                ctx, "edit", ctx.__dict__["_finance_new"])))


def note_action() -> Action:
    """A credit note for an invoice, or a debit note for a bill, with the same lines."""

    def run(record, db, ctx):
        kind = "debit_note" if record.kind == "bill" else "credit_note"
        ctx.__dict__["_finance_new"] = copy_document(db, record, kind, against_id=record.id)
        db.commit()

    return (
        Action("note").label(lambda record: "Debit note" if record is not None and record.kind == "bill"
                             else "Credit note").icon("undo-2").color("gray")
        .visible(lambda record: record is not None and record.kind in ("invoice", "bill")
                 and record.status not in ("draft", "cancelled"))
        .action(run).success_notification_title("Draft note made. Change the lines and confirm it.")
        .success_redirect_url(lambda record, ctx: _resource_for(
            "debit_note" if record.kind == "bill" else "credit_note").get_url(ctx, "edit", ctx.__dict__["_finance_new"]))
    )


def quote_actions() -> list[Action]:
    def convert(record, db, ctx):
        ctx.__dict__["_finance_new"] = quote_to_invoice(db, record)
        db.commit()

    def set_status(status):
        def run(record, db):
            record.status = status
            db.commit()
        return run

    def open_quote(record):
        return record is not None and record.kind == "quote" and record.status not in ("invoiced",)

    return [
        Action("to_invoice").label("Make invoice").icon("file-check").color("success")
        .visible(open_quote).action(convert)
        .success_notification_title("Invoice made as a draft").success_redirect_url(_go_to("invoice")),
        Action("accepted").label("Accepted").icon("thumbs-up").color("gray")
        .visible(lambda record: open_quote(record) and record.status != "accepted")
        .action(set_status("accepted")).success_notification_title("Marked as accepted"),
        Action("declined").label("Declined").icon("thumbs-down").color("gray")
        .visible(lambda record: open_quote(record) and record.status != "declined")
        .action(set_status("declined")).success_notification_title("Marked as declined"),
    ]


# ---------------------------------------------------------------------- the screen
class DocumentResource(Resource):
    """Shared screen; subclasses set ``kind``."""

    model = Invoice
    kind: ClassVar[str] = "invoice"
    navigation_group = "Sales"
    global_search_attributes: ClassVar[list[str]] = ["number", "contact.name", "reference"]
    record_title_attribute = "number"

    @classmethod
    def query(cls, ctx):
        return select(Invoice).where(Invoice.kind == cls.kind)

    @classmethod
    def is_purchase(cls) -> bool:
        return cls.kind in ("bill", "debit_note")

    @classmethod
    def party_label(cls) -> str:
        return "Vendor" if cls.is_purchase() else "Customer"

    @classmethod
    def form(cls, form):
        kind = cls.kind
        purchase = cls.is_purchase()

        def show(key):
            return lambda get, ctx: money(form_totals(get, ctx)[key], currency(ctx))

        def tax_visible(key):
            return lambda get, ctx: bool(form_totals(get, ctx)[key])

        def fill_item(state, set, db):
            if not state:
                return
            item = db.get(Item, int(state))
            if item is None:
                return
            set("description", item.name)
            set("hsn", item.hsn or "")
            set("unit_price", f"{(item.purchase_price if purchase else item.sale_price) or 0:.2f}")
            set("tax_rate", qty(item.tax_rate))

        def item_options(ctx):
            rows = ctx.db.scalars(select(Item).where(Item.is_active.is_(True)).order_by(Item.name)).all()
            return {str(i.id): i.name for i in rows}

        def default_tax(ctx):
            plugin = plugin_of(ctx)
            return f"{plugin.default_tax_rate if plugin is not None else 0:g}"

        def against_options(ctx, get, record):
            target = ("bill",) if kind == "debit_note" else ("invoice",)
            current = record.against if record is not None else None
            return _open_docs(ctx, target, get("contact_id"), current)

        details = [
            Select("contact_id").label(cls.party_label())
            .relationship("contact", "name", modify_query=vendors if purchase else customers)
            .searchable().preload().required().live().column_span("full"),
            DatePicker("issue_date").label(f"{DOC_KINDS[kind]['label']} date").default(lambda: dt.date.today())
            .required(),
        ]
        if kind in ("invoice", "bill", "quote"):
            details.append(DatePicker("due_date").label("Valid until" if kind == "quote" else "Due date")
                           .helper_text("Empty: from the payment terms."))
        if kind in ("credit_note", "debit_note"):
            details.append(Select("against_id").label("For bill" if kind == "debit_note" else "For invoice")
                           .options(against_options).searchable()
                           .helper_text("Empty: kept as credit to use or refund later."))
        details += [
            TextInput("reference").label({"bill": "Vendor's bill number", "invoice": "PO number"}.get(kind, "Reference"))
            .max_length(60).required(kind == "bill"),
            Select("place_of_supply").label("Vendor's state" if purchase else "Place of supply").options(STATE_OPTIONS)
            .searchable().live().helper_text("Empty: the contact's state. Another state means IGST."),
        ]
        if kind == "bill":
            details.append(Select("ledger_account_id").label("Book to").options(expense_account_options)
                           .helper_text("Empty: Purchases."))
        details += [
            TextInput("number").max_length(30).unique().visible(lambda operation: operation != "create"),
            Select("status").options(lambda: {k: v[0] for k, v in statuses_for(kind).items() if k != "overdue"})
            .visible(lambda operation: operation != "create"),
        ]
        if kind == "invoice":
            details += [
                Select("repeat_months").label("Repeat").options(REPEAT_OPTIONS).live()
                .helper_text("A copy is made as a draft on the next date."),
                DatePicker("next_repeat_on").label("Next copy on").visible(lambda get: bool(get("repeat_months"))),
            ]

        return form.columns(3).schema([
            Section(DOC_KINDS[kind]["label"]).icon("file-text").column_span(2).columns(2).schema(details),
            Section("Total").icon("calculator").column_span(1).columns(1).schema([
                Placeholder("subtotal_view").label("Subtotal").content(show("subtotal")),
                Placeholder("discount_view").label("Discount").content(show("discount"))
                .visible(tax_visible("discount")),
                Placeholder("taxable_view").label("Taxable value").content(show("taxable")),
                Placeholder("cgst_view").label("CGST").content(show("cgst")).visible(tax_visible("cgst")),
                Placeholder("sgst_view").label("SGST").content(show("sgst")).visible(tax_visible("sgst")),
                Placeholder("igst_view").label("IGST").content(show("igst")).visible(tax_visible("igst")),
                Placeholder("round_view").label("Round off").content(show("round_off"))
                .visible(tax_visible("round_off")),
                Placeholder("total_view").label("Total").content(show("total")),
            ]),
            Section("Items").icon("list").column_span("full").schema([
                Repeater("items").relationship("items", order_column="sort").table().hidden_label()
                .schema([
                    Select("item_id").label("Item").options(item_options).searchable().live()
                    .after_state_updated(fill_item),
                    TextInput("description").required().max_length(255).placeholder("Website design"),
                    TextInput("hsn").label("HSN/SAC").max_length(12),
                    TextInput("quantity").label("Qty").numeric().min_value(0).default("1").required()
                    .live(debounce=500),
                    TextInput("unit_price").label("Price").numeric().required().live(debounce=500),
                    TextInput("discount").label("Disc %").numeric().min_value(0).max_value(100).default("0")
                    .live(debounce=500),
                    TextInput("tax_rate").label("GST %").numeric().min_value(0).default(default_tax)
                    .live(debounce=500),
                ])
                .min_items(1).add_action_label("Add line").column_span("full"),
            ]),
            Section("Notes").icon("sticky-note").column_span("full").columns(2).collapsible().schema([
                Textarea("notes").label("Note to the vendor" if purchase else "Note to the customer").rows(3),
                Textarea("terms").label("Terms").rows(3).helper_text("Empty: your default terms."),
            ]),
        ])

    @classmethod
    def infolist(cls, infolist):
        kind = cls.kind

        def payments(record, ctx):
            rows = [f"{p.date:%d %b %Y} · {METHODS.get(p.method, p.method)} · {money(p.amount, currency(ctx))}"
                    for p in record.payments]
            return "\n".join(rows) or None

        return infolist.columns(3).schema([
            Section(DOC_KINDS[kind]["label"]).icon("file-text").column_span(2).columns(1).schema([
                Placeholder("document").hidden_label()
                .content(lambda record, ctx: render_document(ctx, record)),
            ]),
            Group([
                Section("Status").icon("flag").columns(1).schema([
                    TextEntry("status").badge().inline_label()
                    .state(lambda record: record.display_status)
                    .format_state_using(_status_label(kind)).color(_status_color(kind)),
                    TextEntry("total").inline_label().format_state_using(show_money),
                    TextEntry("amount_paid").label("Used" if kind in ("credit_note", "debit_note") else "Paid")
                    .inline_label().format_state_using(show_money).visible(kind != "quote"),
                    TextEntry("balance_due").label("Open").inline_label().weight("bold")
                    .state(lambda record: record.balance_due).format_state_using(show_money)
                    .color(lambda record: "danger" if record.is_overdue else None).visible(kind != "quote"),
                    TextEntry("due_date").label("Due").date().placeholder("—").inline_label(),
                    TextEntry("against.number").label("For").placeholder("—").inline_label()
                    .visible(kind in ("credit_note", "debit_note")),
                    TextEntry("payments").label("Payments").placeholder("None yet").state(payments)
                    .visible(kind != "quote"),
                ]),
                Section(cls.party_label()).icon("user").columns(1).schema([
                    TextEntry("contact.name").label("Name").placeholder("—").inline_label(),
                    TextEntry("contact.tax_id").label("GSTIN").copyable().placeholder("—").inline_label(),
                    TextEntry("place_of_supply").label("State").placeholder("—").inline_label()
                    .format_state_using(lambda state: state_name(state)),
                    TextEntry("contact.email").label("Email").copyable().placeholder("—").inline_label(),
                ]),
            ]).columns(1).column_span(1),
        ])

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        actions = super().header_actions(ctx, page, record)
        if page != "view":
            return actions
        main = [payment_action().button(), confirm_action().button()]
        if cls.kind in ("invoice", "quote", "credit_note"):
            main += [send_action().button(), open_link_action().button()]
        if cls.kind == "quote":
            main = [a.button() for a in quote_actions()] + main[1:]
        more = [EditAction(), duplicate_action(), note_action(), cancel_action(), DeleteAction()]
        return main + [ActionGroup(more).button()]

    @classmethod
    def before_create(cls, record):
        record.kind = cls.kind
        if cls.kind == "bill":
            record.status = "sent"  # bills are booked when entered

    @classmethod
    def after_create(cls, record, db, ctx):
        prepare_new(db, record)
        db.flush()
        settle(db, record)

    @classmethod
    def before_save(cls, record, ctx):
        record.__dict__["_fin_old_against"] = record.against_id

    @classmethod
    def after_save(cls, record, db, ctx):
        if not record.place_of_supply and record.contact_id:
            contact = db.get(Contact, record.contact_id)
            record.place_of_supply = contact.state if contact is not None else None
        settle(db, record)
        old = record.__dict__.pop("_fin_old_against", None)
        if old and old != record.against_id:
            target = db.get(Invoice, old)
            if target is not None:
                refresh_paid(db, target)

    @classmethod
    def after_delete(cls, record, db):
        unpost(db, "document", record.id)
        if record.against_id:
            target = db.get(Invoice, record.against_id)
            if target is not None:
                refresh_paid(db, target)

    @classmethod
    def navigation_badge(cls, db):
        if cls.kind not in ("invoice", "bill"):
            return None
        return db.scalar(select(func.count()).select_from(Invoice).where(
            Invoice.kind == cls.kind, Invoice.status.in_(OPEN_STATUSES), Invoice.due_date < dt.date.today())) or None

    navigation_badge_color = "danger"

    @classmethod
    def table(cls, table):
        kind = cls.kind

        def is_open(model):
            return model.status.in_(OPEN_STATUSES)

        def bulk_confirm(records, db):
            for r in records:
                if r.status == "draft":
                    r.status = "sent"
                    settle(db, r)
            db.commit()

        def bulk_cancel(records, db):
            for r in records:
                if r.status not in ("paid", "cancelled"):
                    r.status = "cancelled"
                    settle(db, r)
            db.commit()

        tabs = [ListTab("all").label("All")]
        if kind in ("invoice", "bill"):
            tabs += [
                ListTab("unpaid").label("Unpaid").badge(color="warning")
                .query(lambda query, model: query.where(is_open(model))),
                ListTab("overdue").label("Overdue").badge(color="danger").query(
                    lambda query, model: query.where(is_open(model), model.due_date < dt.date.today())),
                ListTab("paid").label("Paid").query(lambda query, model: query.where(model.status == "paid")),
            ]
        if kind == "quote":
            tabs += [ListTab(s).label(label).query(lambda query, model, s=s: query.where(model.status == s))
                     for s, (label, _) in statuses_for("quote").items() if s != "draft"]
        tabs.append(ListTab("draft").label("Drafts").query(lambda query, model: query.where(model.status == "draft")))
        if kind == "invoice":
            tabs.append(ListTab("repeat").label("Repeating").query(
                lambda query, model: query.where(model.repeat_months.isnot(None))))

        return (
            table.columns([
                TextColumn("number").label("No.").searchable().sortable().copyable().weight("medium")
                .description(lambda record: record.reference),
                TextColumn("contact.name").label(cls.party_label()).searchable().sortable()
                .description(lambda record: record.contact.tax_id if record.contact else None),
                TextColumn("issue_date").label("Date").date().sortable(),
                TextColumn("due_date").label("Due").date().sortable().toggleable()
                .color(lambda record: "danger" if record.is_overdue else None),
                TextColumn("status").badge().sortable().state(lambda record: record.display_status)
                .format_state_using(_status_label(kind)).color(_status_color(kind)),
                TextColumn("taxable").label("Taxable").format_state_using(show_money).toggleable(hidden_by_default=True),
                TextColumn("tax_total").label("GST").format_state_using(show_money).toggleable(hidden_by_default=True),
                TextColumn("total").sortable().format_state_using(show_money)
                .summarize(Sum().format_state_using(lambda state: f"{float(state or 0):,.2f}")),
                TextColumn("balance_due").label("Open").format_state_using(show_money)
                .state(lambda record: record.balance_due).visible(kind != "quote"),
            ])
            .filters([
                SelectFilter("status").options({k: v[0] for k, v in statuses_for(kind).items() if k != "overdue"})
                .multiple(),
                SelectFilter("contact_id").label(cls.party_label()).relationship("contact", "name"),
                DateFilter("issue_date").label("Date"),
            ])
            .tabs(tabs)
            .actions([
                payment_action().icon_button(),
                ActionGroup([ViewAction(), EditAction(), DeleteAction()]),
            ])
            .bulk_actions([
                BulkAction("confirm").label("Confirm drafts").icon("check").action(bulk_confirm)
                .success_notification_title("Confirmed"),
                BulkAction("cancel").label("Cancel").icon("ban").color("danger").requires_confirmation()
                .action(bulk_cancel).success_notification_title("Cancelled"),
                ExportBulkAction(),
                DeleteBulkAction(),
            ])
            .header_actions([ExportAction()])
            .record_url(lambda record, ctx: cls.get_url(ctx, "view", record))
            .default_sort("issue_date", "desc")
        )


class InvoiceResource(DocumentResource):
    kind = "invoice"
    slug = "invoices"
    icon = "file-text"
    navigation_sort = 1
    description = "Bill your customers with GST, share a link they can print, and track what they still owe."
    widgets: ClassVar[list] = [FinanceStats]

    @classmethod
    def header_actions(cls, ctx, page, record=None):
        actions = super().header_actions(ctx, page, record)
        if page in ("index", "list"):
            def run(db, ctx):
                from .service import run_recurring

                made = run_recurring(db)
                db.commit()
                ctx.__dict__["_finance_made"] = len(made)

            actions = [*actions, Action("repeat").label("Make repeat invoices").icon("repeat").color("gray")
                       .action(run).success_notification_title("Repeat invoices made as drafts")]
        return actions


class QuoteResource(DocumentResource):
    kind = "quote"
    slug = "quotes"
    icon = "file-pen"
    navigation_sort = 2
    label = "Quote"
    description = "Estimates for customers. Turn an accepted quote into an invoice in one click."


class CreditNoteResource(DocumentResource):
    kind = "credit_note"
    slug = "credit-notes"
    icon = "undo-2"
    navigation_sort = 4
    label = "Credit note"
    description = "Sales returns and discounts after the invoice. They lower what the customer owes."


class BillResource(DocumentResource):
    kind = "bill"
    slug = "bills"
    icon = "receipt-text"
    navigation_sort = 6
    navigation_group = "Purchases"
    label = "Bill"
    description = "Bills from your vendors: what you bought, the GST you can claim, and what you still owe."


class DebitNoteResource(DocumentResource):
    kind = "debit_note"
    slug = "debit-notes"
    icon = "redo-2"
    navigation_sort = 8
    navigation_group = "Purchases"
    label = "Debit note"
    description = "Purchase returns to your vendors. They lower what you owe."


DOCUMENT_RESOURCES = [InvoiceResource, QuoteResource, CreditNoteResource, BillResource, DebitNoteResource]
