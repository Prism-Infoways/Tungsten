from __future__ import annotations

import datetime as dt
from decimal import Decimal

from conftest import mails
from sqlalchemy import select
from tungsten_finance import (
    Contact,
    Expense,
    Invoice,
    Item,
    LedgerAccount,
    Payment,
    Voucher,
    account,
    account_balance,
    balance_sheet,
    contact_balance,
    create_bill,
    create_document,
    create_invoice,
    gstr1,
    gstr3b,
    profit_and_loss,
    receivables,
    record_payment,
    run_recurring,
    statement,
    stock_summary,
    trial_balance,
)
from tungsten_finance.gst import split_tax, state_code, valid_gstin
from tungsten_finance.service import money, month_end, next_number, period_range

ITEMS = [{"description": "Website design", "quantity": 1, "unit_price": 20000, "tax_rate": 18, "hsn": "998314"},
         {"description": "Hosting", "quantity": 12, "unit_price": "500", "tax_rate": 18, "hsn": "998315"}]


def action(admin, name, record, scope="page", host="invoices", **data):
    return admin.post("/admin/_tw/action", {"_tw_host": f"resource:{host}", "_tw_scope": scope, "_tw_name": name,
                                            "_tw_record": str(record), **data})


def make_invoice(panel, **kw):
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        invoice = create_invoice(db, customer="Amit Traders", email="Amit@Example.com", items=ITEMS, **kw)
        db.commit()
        return invoice.id, invoice.number, invoice.access_key


def books_balance(db):
    tb = trial_balance(db)
    sheet = balance_sheet(db)
    assert tb["balanced"], tb
    assert sheet["balanced"], (sheet["total_assets"], sheet["total_liabilities"])
    return tb, sheet


def test_pages_load(admin, panel):
    make_invoice(panel, status="sent")
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        create_bill(db, vendor="Paper Mart", items=[{"description": "Paper", "quantity": 10, "unit_price": 50,
                                                     "tax_rate": 12}])
        db.commit()
    urls = ["/admin/", "/admin/invoices/1", "/admin/bills/2"]
    for slug in ("invoices", "quotes", "credit-notes", "bills", "debit-notes", "payments", "payments-made",
                 "expenses", "finance-contacts", "finance-items", "chart-of-accounts", "bank-and-cash", "journals"):
        urls += [f"/admin/{slug}", f"/admin/{slug}/create"]
    for slug in ("finance-reports", "profit-and-loss", "balance-sheet", "trial-balance", "ledger-statement",
                 "day-book", "gst-returns", "stock-summary", "bank-reconciliation"):
        urls.append(f"/admin/{slug}?period=all")
    for url in urls:
        r = admin.get(url)
        assert r.status_code == 200, (url, r.text[:800])
    for widget in ("finance-stats", "cash-flow-chart", "report-stats", "expense-category-chart"):
        r = admin.get(f"/admin/_tw/widget/{widget}?_tw_page=finance-reports&period=this_year")
        assert r.status_code == 200, (widget, r.text[:500])


def test_invoice_totals_numbers_and_gst_split(panel):
    invoice_id, number, _ = make_invoice(panel)
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        invoice = db.get(Invoice, invoice_id)
        assert number == "INV-00001" and invoice.status == "draft"
        assert invoice.taxable == Decimal("26000.00") and invoice.tax_total == Decimal("4680.00")
        assert (invoice.cgst, invoice.sgst, invoice.igst) == (Decimal("2340.00"), Decimal("2340.00"), 0)
        assert invoice.total == Decimal("30680.00")
        assert invoice.due_date == invoice.issue_date + dt.timedelta(days=15)
        assert next_number(db) == "INV-00002"
        # another state: IGST, and a round off to the rupee
        other = create_invoice(db, customer="Kumar & Co", place_of_supply="Karnataka",
                               items=[{"description": "Logo", "quantity": 1, "unit_price": "99.70", "tax_rate": 18}])
        assert other.place_of_supply == "29" and other.igst == Decimal("17.95") and other.cgst == 0
        assert other.total == Decimal("118.00") and other.round_off == Decimal("0.35")


def test_external_id_skips_duplicates(panel):
    assert make_invoice(panel, external_id="order-7") == make_invoice(panel, external_id="order-7")
    with panel.db() as db:
        assert len(db.scalars(select(Contact)).all()) == 1


def test_create_in_panel_with_items(admin, panel):
    with panel.db() as db:
        db.add(Contact(name="Neha Stores", email="neha@example.com", kind="customer", state="27", payment_days=30))
        db.commit()
    admin.get("/admin/invoices/create")
    r = admin.post("/admin/invoices/create", {
        "contact_id": "1", "issue_date": "2026-10-01",
        "items.0.__row": "1", "items.0.description": "Logo", "items.0.quantity": "2",
        "items.0.unit_price": "1500", "items.0.discount": "10", "items.0.tax_rate": "18",
    })
    assert r.status_code == 204, r.text[:2000]
    with panel.db() as db:
        invoice = db.scalars(select(Invoice)).unique().one()
        assert invoice.number == "INV-00001" and invoice.kind == "invoice" and len(invoice.items) == 1
        assert invoice.discount == Decimal("300.00") and invoice.total == Decimal("3186.00")
        assert invoice.due_date == dt.date(2026, 10, 31)


def test_payments_post_to_ledger(admin, panel):
    invoice_id, _, _ = make_invoice(panel)
    with panel.db() as db:
        db.add(LedgerAccount(code="1100", name="HDFC", kind="bank", opening_balance=Decimal(1000)))
        db.commit()
        bank_id = db.scalars(select(LedgerAccount.id).where(LedgerAccount.name == "HDFC")).one()
    admin.get(f"/admin/invoices/{invoice_id}")
    r = action(admin, "payment", invoice_id, amount="10000", date="2026-10-05", method="upi",
               account_id=str(bank_id), reference="UTR1")
    assert r.status_code in (200, 204), r.text[:1000]
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        invoice = db.get(Invoice, invoice_id)
        assert invoice.status == "partial" and invoice.balance_due == Decimal("20680.00")
        assert account_balance(db, db.get(LedgerAccount, bank_id)) == Decimal("11000.00")
        assert contact_balance(db, invoice.contact) == Decimal("20680.00")
        assert account_balance(db, account(db, "output_cgst")) == Decimal("-2340.00")  # a credit balance
        record_payment(db, invoice, "20680")
        db.commit()
        assert invoice.status == "paid" and invoice.paid_at is not None
        books_balance(db)
        payment_id = db.scalars(select(Payment.id).where(Payment.reference == "UTR1")).one()
    # deleting a payment opens the invoice again and removes its voucher
    admin.get("/admin/payments")
    r = action(admin, "delete", payment_id, scope="row", host="payments")
    assert r.status_code in (200, 204), r.text[:1000]
    with panel.db() as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice.status == "partial" and invoice.amount_paid == Decimal("20680.00")
        assert db.scalars(select(Voucher).where(Voucher.source_type == "payment",
                                                Voucher.source_id == payment_id)).first() is None
        books_balance(db)


def test_payment_screen_updates_invoice(admin, panel):
    invoice_id, _, _ = make_invoice(panel, status="sent")
    admin.get("/admin/payments/create")
    r = admin.post("/admin/payments/create", {"invoice_id": str(invoice_id), "amount": "30680",
                                              "date": "2026-10-06", "method": "bank"})
    assert r.status_code == 204, r.text[:2000]
    with panel.db() as db:
        invoice = db.get(Invoice, invoice_id)
        payment = db.scalars(select(Payment)).one()
        assert invoice.status == "paid" and payment.contact_id == invoice.contact_id
        assert payment.number == "RCPT-00001" and payment.direction == "in"


def test_bills_expenses_profit_and_balance_sheet(panel):
    make_invoice(panel, status="sent")
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        bill = create_bill(db, vendor="Paper Mart", reference="PM/88", place_of_supply="27AAACP1234A1Z5",
                           items=[{"description": "Paper", "quantity": 100, "unit_price": 50, "tax_rate": 12}])
        assert bill.number == "BILL-00001" and bill.status == "sent" and bill.total == Decimal("5600.00")
        rent = db.scalars(select(LedgerAccount).where(LedgerAccount.name == "Rent")).one()
        expense = Expense(description="Office rent", amount=Decimal(11800), tax_amount=Decimal(1800),
                          category_id=rent.id, date=dt.date.today())
        db.add(expense)
        db.flush()
        from tungsten_finance.ledger import post_expense
        post_expense(db, expense)
        pay = record_payment(db, bill, "5600")
        db.commit()
        assert pay.direction == "out" and pay.number == "PAY-00001" and bill.status == "paid"
        pl = profit_and_loss(db)
        assert pl["totals"]["sales"] == Decimal("26000.00") and pl["totals"]["purchase"] == Decimal("5000.00")
        assert pl["gross_profit"] == Decimal("21000.00") and pl["net_profit"] == Decimal("11000.00")
        _, sheet = books_balance(db)
        assert sheet["profit"] == Decimal("11000.00")
        assert receivables(db)["current"] == Decimal("30680.00")
        r3b = gstr3b(db)
        assert r3b["outward"]["cgst"] == Decimal("2340.00") and r3b["itc"]["cgst"] == Decimal("1200.00")
        assert r3b["net"] == Decimal("4680.00") - Decimal("600.00") - Decimal("1800.00")


def test_credit_note_against_invoice(admin, panel):
    invoice_id, _, _ = make_invoice(panel, status="sent")
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        invoice = db.get(Invoice, invoice_id)
        note = create_document(db, "credit_note", contact=invoice.contact, against=invoice, status="sent",
                               items=[{"description": "Hosting back", "quantity": 2, "unit_price": 500,
                                       "tax_rate": 18, "hsn": "998315"}])
        db.commit()
        assert note.number == "CN-00001" and note.total == Decimal("1180.00")
        assert invoice.status == "partial" and invoice.balance_due == Decimal("29500.00")
        assert contact_balance(db, invoice.contact) == Decimal("29500.00")
        returns = gstr1(db)
        assert len(returns["credit_notes"]) == 1 and len(returns["b2b"]) == 0
        hosting = next(r for r in returns["hsn"] if r["hsn"] == "998315")
        assert hosting["quantity"] == Decimal(10) and hosting["taxable"] == Decimal("5000.00")
        books_balance(db)
    # the Credit note action opens a new note for this invoice
    admin.get(f"/admin/invoices/{invoice_id}")
    assert action(admin, "note", invoice_id).status_code in (200, 204)
    with panel.db() as db:
        assert db.scalars(select(Invoice).where(Invoice.kind == "credit_note")).unique().all()[-1].against_id \
            == invoice_id


def test_quote_becomes_invoice(admin, panel):
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        quote = create_document(db, "quote", name="Amit Traders", items=ITEMS)
        db.commit()
        quote_id = quote.id
        assert quote.number == "QT-00001"
        assert db.scalars(select(Voucher)).first() is None  # quotes never touch the books
    admin.get(f"/admin/quotes/{quote_id}")
    r = action(admin, "to_invoice", quote_id, host="quotes")
    assert r.status_code in (200, 204), r.text[:1000]
    with panel.db() as db:
        invoice = db.scalars(select(Invoice).where(Invoice.kind == "invoice")).unique().one()
        assert invoice.total == Decimal("30680.00") and db.get(Invoice, quote_id).status == "invoiced"


def test_journal_must_balance(admin, panel):
    with panel.db() as db:
        capital = db.scalars(select(LedgerAccount.id).where(LedgerAccount.system_key == "capital")).one()
        cash = db.scalars(select(LedgerAccount.id).where(LedgerAccount.system_key == "cash")).one()
    admin.get("/admin/journals/create")
    rows = {"kind": "journal", "date": "2026-10-01", "narration": "Owner put in money",
            "lines.0.__row": "1", "lines.0.account_id": str(cash), "lines.0.debit": "50000", "lines.0.credit": "",
            "lines.1.__row": "1", "lines.1.account_id": str(capital), "lines.1.debit": "", "lines.1.credit": "40000"}
    r = admin.post("/admin/journals/create", rows)
    assert r.status_code != 204 and "must be equal" in r.text
    r = admin.post("/admin/journals/create", {**rows, "lines.1.credit": "50000"})
    assert r.status_code == 204, r.text[:2000]
    with panel.db() as db:
        voucher = db.scalars(select(Voucher)).unique().one()
        assert voucher.number == "JV-00001" and voucher.total == Decimal("50000.00")
        assert account_balance(db, db.get(LedgerAccount, cash)) == Decimal("50000.00")
        books_balance(db)
        lines = statement(db, account_id=cash)["rows"]
        assert len(lines) == 1 and lines[0]["balance"] == Decimal("50000.00")


def test_recurring_and_stock(panel):
    with panel.db() as db:
        db.info["tungsten_panel"] = panel
        pen = Item(name="Pen", sku="PEN", hsn="9608", unit="pcs", sale_price=Decimal(20), purchase_price=Decimal(12),
                   tax_rate=Decimal(18), track_stock=True, opening_stock=Decimal(10), reorder_level=Decimal(50))
        db.add(pen)
        db.flush()
        create_bill(db, vendor="Pen House", items=[{"sku": "PEN", "quantity": 100}])
        invoice = create_invoice(db, customer="Amit Traders", status="sent", issue_date=dt.date(2026, 1, 31),
                                 items=[{"item_id": pen.id, "quantity": 70}])
        assert invoice.items[0].unit_price == Decimal(20) and invoice.items[0].hsn == "9608"
        row = next(r for r in stock_summary(db) if r["item"].sku == "PEN")
        assert row["closing"] == Decimal(40) and row["value"] == Decimal("480.00") and row["low"]
        invoice.repeat_months, invoice.next_repeat_on = 1, dt.date(2026, 2, 28)
        made = run_recurring(db, dt.date(2026, 4, 1))
        assert [m.issue_date for m in made] == [dt.date(2026, 2, 28), dt.date(2026, 3, 28)]
        assert invoice.next_repeat_on == dt.date(2026, 4, 28) and made[0].status == "draft"
        db.commit()


def test_send_emails_link_and_public_page(admin, panel):
    invoice_id, number, key = make_invoice(panel)
    assert admin.client.get(f"/admin/invoice/{number}/{key}").status_code == 404  # a draft is not public yet
    admin.get(f"/admin/invoices/{invoice_id}")
    r = action(admin, "send", invoice_id)
    assert r.status_code in (200, 204), r.text[:1000]
    to, subject, body = mails[-1]
    assert to == "amit@example.com" and number in subject
    assert f"https://books.example.com/admin/invoice/{number}/{key}" in body and "UPI: shop@okhdfc" in body
    page = admin.client.get(f"/admin/invoice/{number}/{key}")
    assert page.status_code == 200 and "Website design" in page.text and "12 MG Road" in page.text
    assert "₹30,680.00" in page.text and "CGST" in page.text and "998314" in page.text
    assert admin.client.get(f"/admin/invoice/{number}/wrong-key").status_code == 404
    with panel.db() as db:
        assert db.get(Invoice, invoice_id).status == "sent"


def test_cancel_and_duplicate(admin, panel):
    invoice_id, _, _ = make_invoice(panel, status="sent")
    admin.get(f"/admin/invoices/{invoice_id}")
    assert action(admin, "duplicate", invoice_id).status_code in (200, 204)
    assert action(admin, "cancel", invoice_id).status_code in (200, 204)
    with panel.db() as db:
        rows = db.scalars(select(Invoice).order_by(Invoice.id)).unique().all()
        assert [r.status for r in rows] == ["cancelled", "draft"]
        assert rows[1].number == "INV-00002" and rows[1].total == rows[0].total and rows[0].balance_due == 0
        assert db.scalars(select(Voucher)).first() is None  # cancelled and draft: nothing in the books


def test_reports_and_csv_export(admin, panel):
    make_invoice(panel, status="sent")
    page = admin.get("/admin/trial-balance?period=all").text
    assert "Sales" in page and "30,680.00" in page
    assert "GSTR-3B" in admin.get("/admin/gst-returns?period=all").text
    r = admin.client.get("/admin/finance-export/trial-balance.csv?period=all")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"], r.text[:500]
    assert "Sales" in r.text and "30680" in r.text
    r = admin.client.get("/admin/finance-export/gstr1-hsn.csv?period=all")
    assert r.status_code == 200 and "998314" in r.text


def test_expense_form_posts(admin, panel):
    with panel.db() as db:
        software = db.scalars(select(LedgerAccount.id).where(LedgerAccount.name == "Software")).one()
    admin.get("/admin/expenses/create")
    r = admin.post("/admin/expenses/create", {"description": "Figma", "amount": "1180", "tax_amount": "180",
                                              "tax_kind": "cgst_sgst", "date": "2026-10-02", "method": "card",
                                              "category_id": str(software)})
    assert r.status_code == 204, r.text[:2000]
    with panel.db() as db:
        expense = db.scalars(select(Expense)).one()
        assert expense.amount == Decimal("1180.00") and expense.category.name == "Software"
        assert account_balance(db, db.get(LedgerAccount, software)) == Decimal("1000.00")
        assert account_balance(db, account(db, "cash")) == Decimal("-1180.00")
        books_balance(db)


def test_helpers():
    assert money(1234.5) == "₹1,234.50" and money(-5, "USD") == "-$5.00"
    assert month_end(dt.date(2026, 2, 10)) == dt.date(2026, 2, 28)
    assert period_range("this_year", dt.date(2026, 2, 1)) == (dt.date(2025, 4, 1), dt.date(2026, 2, 1))
    assert period_range("last_year", dt.date(2026, 5, 1)) == (dt.date(2025, 4, 1), dt.date(2026, 3, 31))
    assert period_range("last_month", dt.date(2026, 1, 15)) == (dt.date(2025, 12, 1), dt.date(2025, 12, 31))
    assert state_code("27AAACP1234A1Z5") == "27" and state_code("Maharashtra") == "27" and state_code("7") == "07"
    assert split_tax(Decimal("100.01"), False) == (Decimal("50.00"), Decimal("50.01"), 0)
    assert valid_gstin("27AAACP1234A1Z5") and not valid_gstin("27AAACP1234")


def test_form_totals_update_live(admin, panel):
    admin.get("/admin/invoices/create")
    r = admin.client.post("/admin/_tw/form", data={
        "_tw_kind": "host", "_tw_host": "resource:invoices", "_tw_op": "create", "_tw_record": "",
        "_tw_form_id": "tw-record-form", "place_of_supply": "29", "items.0.__row": "1", "items.0.description": "Logo",
        "items.0.quantity": "2", "items.0.unit_price": "1000", "items.0.discount": "5", "items.0.tax_rate": "18"},
        headers={"HX-Request": "true", "HX-Trigger-Name": "items.0.unit_price", "X-CSRF-Token": admin.token})
    assert r.status_code == 200, r.text[:500]
    assert "₹1,900.00" in r.text and "₹342.00" in r.text and "₹2,242.00" in r.text and "IGST" in r.text
