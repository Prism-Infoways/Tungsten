from __future__ import annotations

import datetime as dt
from decimal import Decimal

from conftest import mails
from sqlalchemy import select
from tungsten_finance import (
    Contact,
    Expense,
    ExpenseCategory,
    Invoice,
    MoneyAccount,
    Payment,
    account_balance,
    create_invoice,
    receivables,
    record_payment,
    tax_summary,
)
from tungsten_finance.service import money, month_end, next_number, period_range


def action(admin, name, record, scope="page", **data):
    return admin.post("/admin/_tw/action", {"_tw_host": "resource:invoices", "_tw_scope": scope, "_tw_name": name,
                                            "_tw_record": str(record), **data})


def make_invoice(panel, **kw):
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        invoice = create_invoice(db, customer="Amit Traders", email="Amit@Example.com", **{
            "items": [{"description": "Website design", "quantity": 1, "unit_price": 20000, "tax_rate": 18},
                      {"description": "Hosting", "quantity": 12, "unit_price": "500", "tax_rate": 18}], **kw})
        db.commit()
        return invoice.id, invoice.number, invoice.access_key


def test_pages_load(admin, panel):
    make_invoice(panel)
    for url in ("/admin/invoices", "/admin/invoices/create", "/admin/payments", "/admin/payments/create",
                "/admin/expenses", "/admin/expenses/create", "/admin/finance-contacts", "/admin/money-accounts",
                "/admin/expense-categories", "/admin/finance-reports", "/admin/invoices/1", "/admin/"):
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[:800])
    assert "Finance" in admin.get("/admin/invoices").text
    for widget in ("finance-stats", "cash-flow-chart", "report-stats", "expense-category-chart"):
        r = admin.get(f"/admin/_tw/widget/{widget}?_tw_page=finance-reports&period=this_year")
        assert r.status_code == 200, (widget, r.text[:500])


def test_create_invoice_totals_and_numbers(panel):
    invoice_id, number, _ = make_invoice(panel, discount=600)
    with panel.db() as db:
        invoice = db.get(Invoice, invoice_id)
        assert number == "INV-00001"
        assert invoice.subtotal == Decimal("26000.00") and invoice.tax_total == Decimal("4680.00")
        assert invoice.total == Decimal("30080.00") and invoice.status == "draft"
        assert invoice.due_date == invoice.issue_date + dt.timedelta(days=15)
        assert invoice.contact.email == "amit@example.com"
        assert next_number(db) == "INV-00002"
    make_invoice(panel)
    with panel.db() as db:  # the same customer is found again by email
        assert len(db.scalars(select(Contact)).all()) == 1


def test_external_id_skips_duplicates(panel):
    first = make_invoice(panel, external_id="order-7")
    second = make_invoice(panel, external_id="order-7")
    assert first == second


def test_create_in_panel_with_items(admin, panel):
    with panel.db() as db:
        db.add(Contact(name="Neha Stores", email="neha@example.com", kind="customer"))
        db.commit()
    admin.get("/admin/invoices/create")
    r = admin.post("/admin/invoices/create", {
        "contact_id": "1", "issue_date": "2026-10-01", "discount": "0",
        "items.0.__row": "1", "items.0.description": "Logo", "items.0.quantity": "2",
        "items.0.unit_price": "1500", "items.0.tax_rate": "18",
    })
    assert r.status_code == 204, r.text[:2000]
    with panel.db() as db:
        invoice = db.scalars(select(Invoice)).unique().one()
        assert invoice.number == "INV-00001" and len(invoice.items) == 1
        assert invoice.total == Decimal("3540.00") and invoice.due_date == dt.date(2026, 10, 16)


def test_payments_mark_partial_then_paid(admin, panel):
    invoice_id, _, _ = make_invoice(panel)
    with panel.db() as db:
        db.add(MoneyAccount(name="HDFC", opening_balance=Decimal(1000)))
        db.commit()
    admin.get(f"/admin/invoices/{invoice_id}")
    r = action(admin, "payment", invoice_id, amount="10000", date="2026-10-05", method="upi", account_id="1",
               reference="UTR1")
    assert r.status_code in (200, 204), r.text[:1000]
    with panel.db() as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice.status == "partial" and invoice.amount_paid == Decimal("10000.00")
        assert invoice.balance_due == Decimal("20680.00")
        assert account_balance(db, db.get(MoneyAccount, 1)) == Decimal("11000.00")
        db.info["tungsten_panel"] = panel
        record_payment(db, invoice, "20680")
        db.commit()
        assert invoice.status == "paid" and invoice.paid_at is not None
        payment = db.scalars(select(Payment).where(Payment.reference == "UTR1")).one()
        payment_id = payment.id
    # deleting a payment opens the invoice again
    admin.get("/admin/payments")
    r = admin.post("/admin/_tw/action", {"_tw_host": "resource:payments", "_tw_scope": "row",
                                         "_tw_name": "delete", "_tw_record": str(payment_id)})
    assert r.status_code in (200, 204), r.text[:1000]
    with panel.db() as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice.status == "partial" and invoice.amount_paid == Decimal("20680.00")


def test_payment_screen_updates_invoice(admin, panel):
    invoice_id, _, _ = make_invoice(panel)
    admin.get("/admin/payments/create")
    r = admin.post("/admin/payments/create", {"invoice_id": str(invoice_id), "amount": "30680",
                                              "date": "2026-10-06", "method": "bank"})
    assert r.status_code == 204, r.text[:2000]
    with panel.db() as db:
        invoice = db.get(Invoice, invoice_id)
        payment = db.scalars(select(Payment)).one()
        assert invoice.status == "paid" and payment.contact_id == invoice.contact_id


def test_send_emails_link_and_public_page(admin, panel):
    invoice_id, number, key = make_invoice(panel)
    # a draft is not public yet
    assert admin.client.get(f"/admin/invoice/{number}/{key}").status_code == 404
    admin.get(f"/admin/invoices/{invoice_id}")
    r = action(admin, "send", invoice_id)
    assert r.status_code in (200, 204), r.text[:1000]
    to, subject, body = mails[-1]
    assert to == "amit@example.com" and number in subject
    assert f"https://books.example.com/admin/invoice/{number}/{key}" in body and "UPI: shop@okhdfc" in body
    page = admin.client.get(f"/admin/invoice/{number}/{key}")
    assert page.status_code == 200 and "Website design" in page.text and "12 MG Road" in page.text
    assert "₹30,680.00" in page.text and "How to pay" in page.text
    assert admin.client.get(f"/admin/invoice/{number}/wrong-key").status_code == 404
    with panel.db() as db:
        assert db.get(Invoice, invoice_id).status == "sent"


def test_cancel_and_duplicate(admin, panel):
    invoice_id, _, _ = make_invoice(panel)
    admin.get(f"/admin/invoices/{invoice_id}")
    assert action(admin, "duplicate", invoice_id).status_code in (200, 204)
    assert action(admin, "cancel", invoice_id).status_code in (200, 204)
    with panel.db() as db:
        rows = db.scalars(select(Invoice).order_by(Invoice.id)).unique().all()
        assert [r.status for r in rows] == ["cancelled", "draft"]
        assert rows[1].number == "INV-00002" and rows[1].total == rows[0].total and rows[0].balance_due == 0


def test_expenses_reports_and_aging(admin, panel):
    make_invoice(panel, issue_date=dt.date.today() - dt.timedelta(days=60), status="sent")
    make_invoice(panel, status="sent")
    with panel.db() as db:
        assert len(db.scalars(select(ExpenseCategory)).all()) >= 5  # default categories
        rent = db.scalars(select(ExpenseCategory).where(ExpenseCategory.name == "Rent")).one()
        db.add(Expense(description="Office rent", amount=Decimal(11800), tax_amount=Decimal(1800),
                       category_id=rent.id, date=dt.date.today()))
        db.commit()
        aging = receivables(db)
        assert aging["current"] == Decimal("30680.00") and aging["31_60"] == Decimal("30680.00")
        tax = tax_summary(db)
        assert tax["collected"] == Decimal("9360.00") and tax["net"] == Decimal("7560.00")
    page = admin.get("/admin/finance-reports?period=all").text
    assert "Who owes the most" in page and "Amit Traders" in page and "₹61,360.00" in page
    tab = admin.get("/admin/invoices?tab=overdue").text
    assert "INV-00001" in tab


def test_expense_form(admin, panel):
    admin.get("/admin/expenses/create")
    r = admin.post("/admin/expenses/create", {"description": "Figma", "amount": "1180", "tax_amount": "180",
                                              "date": "2026-10-02", "method": "card", "category_id": "3"})
    assert r.status_code == 204, r.text[:2000]
    with panel.db() as db:
        expense = db.scalars(select(Expense)).one()
        assert expense.amount == Decimal("1180.00") and expense.category.name == "Software"


def test_helpers():
    assert money(1234.5) == "₹1,234.50" and money(-5, "USD") == "-$5.00"
    assert month_end(dt.date(2026, 2, 10)) == dt.date(2026, 2, 28)
    assert period_range("this_year", dt.date(2026, 2, 1)) == (dt.date(2025, 4, 1), dt.date(2026, 2, 1))
    assert period_range("last_year", dt.date(2026, 5, 1)) == (dt.date(2025, 4, 1), dt.date(2026, 3, 31))
    assert period_range("last_month", dt.date(2026, 1, 15)) == (dt.date(2025, 12, 1), dt.date(2025, 12, 31))


def test_form_totals_update_live(admin, panel):
    admin.get("/admin/invoices/create")
    r = admin.client.post("/admin/_tw/form", data={
        "_tw_kind": "host", "_tw_host": "resource:invoices", "_tw_op": "create", "_tw_record": "",
        "_tw_form_id": "tw-record-form", "discount": "100", "items.0.__row": "1", "items.0.description": "Logo",
        "items.0.quantity": "2", "items.0.unit_price": "1000", "items.0.tax_rate": "18"},
        headers={"HX-Request": "true", "HX-Trigger-Name": "items.0.unit_price", "X-CSRF-Token": admin.token})
    assert r.status_code == 200, r.text[:500]
    assert "₹2,000.00" in r.text and "₹360.00" in r.text and "₹2,260.00" in r.text
