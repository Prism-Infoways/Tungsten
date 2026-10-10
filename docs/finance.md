---
title: Finance and accounts
description: Add invoices with GST, payments, expenses, bank and cash balances and profit reports to your panel, with a printable invoice link for customers.
---

The `tungsten-finance` plugin adds simple bookkeeping to your panel. Bill customers, record what they pay, log your expenses, and see your profit and who owes you money.

## Install

```bash
pip install tungsten-finance
```

```python
from tungsten_finance import FinancePlugin

panel = Panel(..., app_url="https://admin.example.com", auth=Auth(User, mailer=send_mail))
panel.plugin(FinancePlugin(
    business_address="12 MG Road, Pune 411001",
    business_tax_id="27ABCDE1234F1Z5",
    payment_details="Bank: HDFC 50200012345678, IFSC HDFC0000123\nUPI: shop@okhdfc",
))
panel.create_tables(engine)
```

This adds a **Finance** menu with **Invoices**, **Payments**, **Expenses**, **Customers & vendors**, **Reports**, **Bank & cash** and **Expense categories**, plus dashboard numbers and a money in / money out chart. It needs `tungsten-admin` 0.1.5 or newer.

`mailer` is your own `send_mail(to, subject, body)` function. `app_url` makes the invoice links in emails full links.

## Invoices

Each invoice has a number like `INV-00012`, a customer, an invoice date, a due date and line items. Every line has a description, quantity, price and **tax %** (18 by default, for 18% GST). Subtotal, tax, discount and total update while you type.

- **Statuses**: Draft, Sent, Part paid, Paid, Cancelled. An invoice shows as **Overdue** when it is sent or part paid and the due date has passed.
- **Due date**: leave it empty and it is set from `due_days` (15 by default).
- **Tabs**: All, Unpaid, Overdue, Drafts, Paid. Filters by status, customer and date. Export to CSV or Excel.

On an invoice page:

- **Record payment**: the amount is filled with what is still owed. The invoice becomes part paid or paid by itself.
- **Send**: emails the customer a link to the invoice and marks it sent.
- **Customer view**: opens the page the customer sees, with a **Print or save as PDF** button.
- **Duplicate** makes a draft copy, for monthly bills. **Cancel invoice** keeps it in your records but nobody owes it.

The customer page is `<panel>/invoice/<number>/<key>`. The key is secret, so only people with the link can open it. Drafts are never shown.

## Payments and expenses

**Payments** are money in. Pick an invoice, or leave it empty for money that is not for an invoice. Each payment has a method (bank transfer, UPI, cash, card, cheque) and the account it went into. Editing or deleting a payment updates its invoice.

**Expenses** are money out: a description, the amount paid (tax included), the tax inside it, a category, the vendor, the account it was paid from and the bill or receipt file.

## Customers, vendors and accounts

**Customers & vendors** keeps names, company, GSTIN, email, phone and address, and shows how much each customer owes you.

**Bank & cash** lists where your money sits. The balance is the opening balance, plus payments into the account, minus expenses paid from it.

**Expense categories** group your spending. Rent, Salaries, Software, Marketing, Travel, Office, Utilities, Taxes and fees and Other are added the first time (turn off with `default_categories=False`).

## Reports

Pick a period at the top: this month, last month, this quarter, this or last financial year, or all time. The financial year starts in April (`year_start_month=4`).

- **Invoiced, money in, money out and profit** for the period.
- **Where the money went**: expenses by category.
- **Money in and out** by month.
- **Money customers owe you**, split into not due yet, 1-30, 31-60, 61-90 and over 90 days late.
- **Who owes the most**.
- **Tax (GST)**: charged on invoices, paid on expenses, and what is left to pay.
- **Bank and cash balances**.

Profit is cash based: money in is payments received, money out is expenses. Give the `finance.reports` permission in the Roles screen to people who may see reports.

## Options

```python
FinancePlugin(
    currency="INR",                  # INR, USD, EUR, GBP, AED...
    number_prefix="INV-",
    due_days=15,
    default_tax_rate=18,
    terms="Payment within 15 days.",
    business_name=None,              # defaults to the panel's brand name
    business_address=None, business_tax_id=None, business_email=None, business_phone=None, logo_url=None,
    payment_details=None,            # "How to pay" under unpaid invoices
    public_links=True, public_path="invoice",
    year_start_month=4,
    default_categories=True,
    mailer=None,                     # defaults to Auth(mailer=...)
    dashboard_widgets=True, reports=True,
    navigation_group="Finance",
)
```

## Bill from code

A shop, the Leads plugin or any part of your app can make invoices and book payments:

```python
from tungsten_finance import create_invoice, record_payment

invoice = create_invoice(db, customer="Amit Traders", email="amit@example.com", external_id="order-12",
                         items=[{"description": "Website design", "quantity": 1, "unit_price": 25000,
                                 "tax_rate": 18}])
record_payment(db, invoice, 10000, method="upi", reference="UTR 1234")
db.commit()

panel.get_plugin("finance").send_invoice(db, invoice)
```

The same `external_id` never makes a second invoice. To act when an invoice is sent (for example to send it on WhatsApp too):

```python
panel.get_plugin("finance").on_invoice_sent("whatsapp", lambda db, invoice, link: ...)
```

This is simple bookkeeping for small teams, not a full double-entry ledger. Ask your accountant before you file tax returns.
