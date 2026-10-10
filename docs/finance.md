---
title: Finance and accounts
description: Double-entry books with GST for your panel. Invoices, quotes, credit notes, bills, payments, stock, P&L, balance sheet, trial balance and GSTR-1/3B, like Tally, Busy or Zoho Books.
---

The `tungsten-finance` plugin adds full double-entry accounts to your panel. It covers what small Indian businesses use Tally, Busy or Zoho Books for: GST invoices, bills, payments, ledgers, stock and the main reports. Every document posts its own voucher, so the books always balance.

## Install

```bash
pip install tungsten-finance
```

```python
from tungsten_finance import FinancePlugin

panel = Panel(..., app_url="https://admin.example.com", auth=Auth(User, mailer=send_mail))
panel.plugin(FinancePlugin(
    state="27",   # your state: code, name or GSTIN
    business_address="12 MG Road, Pune 411001",
    business_tax_id="27ABCDE1234F1Z5",
    payment_details="Bank: HDFC 50200012345678, IFSC HDFC0000123\nUPI: shop@okhdfc",
))
panel.create_tables(engine)
```

This adds four menu groups:

- **Sales**: Invoices, Quotes, Payments received, Credit notes, Customers & vendors.
- **Purchases**: Bills, Payments made, Debit notes, Expenses.
- **Accounting**: Chart of accounts, Bank & cash, Journal vouchers, Items & stock.
- **Finance reports**: Overview, Profit and loss, Balance sheet, Trial balance, Ledger statement, Day book, GST returns, Stock summary, Bank reconciliation.

It needs `tungsten-admin` 0.1.7 or newer. `mailer` is your own `send_mail(to, subject, body)` function. `app_url` makes the invoice links in emails full links.

## First steps

1. Open **Bank & cash** and add your bank account with its opening balance. Cash is already there.
2. Put the owner's money in **Capital** (Chart of accounts) as an opening balance, so the books start balanced.
3. Add your customers and vendors with their GSTIN and state, and any money they owed you on the first day.
4. Add the goods and services you sell under **Items & stock**, with HSN/SAC, price and GST %.

If opening balances don't match, the trial balance shows a **Difference in opening balances** line, like Tally.

## GST

Each line has a GST %. The plugin compares your state with the **place of supply** (the customer's state by default):

- Same state: the tax is split into **CGST** and **SGST**.
- Another state: it is all **IGST**.

Totals are rounded to the rupee, with the round off shown on the invoice. Turn that off with `round_off=False`. Typing a GSTIN fills the state by itself, and a wrong GSTIN shape is refused.

## Sales

- **Invoices** (`INV-00012`) start as drafts. **Mark as sent** or **Send** (email with a link) books them in the ledger.
- **Quotes** (`QT-`) never touch the books. **Make invoice** copies one into a new invoice.
- **Credit notes** (`CN-`) for returns and discounts. Make one from the invoice with **Credit note**; it lowers what the customer owes.
- **Record payment** on an invoice, or add one under **Payments received** (`RCPT-`). The invoice turns part paid or paid by itself, and deleting the payment opens it again.
- **Repeat**: set an invoice to repeat every 1, 3, 6 or 12 months. Press **Make repeat invoices** on the Invoices list, or call `run_recurring(db)` once a day.
- Customers open a sent invoice from a private link and press **Print or save as PDF**. Drafts and bills are never public.

## Purchases

- **Bills** (`BILL-`): the vendor's bill with their bill number, booked to Purchases or any expense account (**Book to**). Its GST goes to input tax credit.
- **Debit notes** (`DN-`) against a bill, for goods you send back.
- **Pay bill**, or **Payments made** (`PAY-`) for advances.
- **Expenses**: a quick way for small spends paid on the spot (rent, tea, software), with the GST inside and the receipt file.

## Accounting

The **Chart of accounts** has Tally-style groups: bank, cash, sundry debtors, input tax, fixed and current assets, sundry creditors, duties and taxes, loans, capital, sales, other income, purchases, direct and indirect expenses. System accounts can't be deleted, and neither can accounts in use.

**Journal vouchers** are for anything else: depreciation, salaries due, owner drawings, a cash deposit to the bank (**Contra**). Debit must equal credit, or the voucher is not saved.

Every invoice, bill, note, payment and expense makes its own voucher. Change the document, and its voucher is rebuilt. Cancel or delete it, and the voucher goes. Open any voucher from the **Day book**.

## Reports

Every report has a period filter (this month, last month, this quarter, this or last financial year, all time) and a **CSV** button.

- **Profit and loss**: sales, less purchases and direct costs, is gross profit. Add other income and take away indirect expenses for net profit.
- **Balance sheet**: liabilities and capital on one side, assets on the other, with the profit for the year. Both sides always match.
- **Trial balance**: every account's debit or credit balance.
- **Ledger statement**: any account, customer or vendor, with a running balance. Open it from a customer with **Statement**.
- **Day book**: every voucher in the period.
- **GST returns**: GSTR-3B summary (tax on sales, input tax credit, what is left to pay) and GSTR-1 tables (B2B invoices, B2C totals by state and rate, credit notes, HSN summary). Check them with your CA before filing.
- **Stock summary**: opening, in, out, closing and value at purchase price, with low stock in red.
- **Bank reconciliation**: payments not yet cleared in the bank. Mark them cleared from the payments list.

## Compared with Tally, Busy and Zoho Books

| | Tally / Busy | Zoho Books | tungsten-finance |
| --- | --- | --- | --- |
| Double-entry ledger, vouchers, groups | Yes | Yes | Yes |
| GST invoices, CGST/SGST/IGST | Yes | Yes | Yes |
| Quotes, credit and debit notes | Yes | Yes | Yes |
| P&L, balance sheet, trial balance, day book | Yes | Yes | Yes |
| GSTR-1 and GSTR-3B data | Yes | Yes | Yes (CSV) |
| Items with HSN and stock | Yes | Yes | Yes (simple) |
| Customer invoice link, email | Add-on | Yes | Yes |
| Runs inside your own app, your own database | No | No | Yes |
| E-invoice, e-way bill, TDS, multi-currency, multi-company | Yes | Yes | Not yet |

## From your own code

```python
from tungsten_finance import create_bill, create_document, create_invoice, record_payment

invoice = create_invoice(db, customer="Amit Traders", email="amit@example.com", external_id="order-12",
                         status="sent", items=[{"description": "Website design", "quantity": 1,
                                                "unit_price": 25000, "tax_rate": 18, "hsn": "998314"}])
record_payment(db, invoice, 10000, method="upi", reference="UTR 1234")
bill = create_bill(db, vendor="Paper Mart", reference="PM/88", items=[{"sku": "PAPER", "quantity": 100}])
db.commit()

panel.get_plugin("finance").send_invoice(db, invoice)
```

The same `external_id` never makes a second document. Reports are plain functions too: `trial_balance(db)`, `profit_and_loss(db, start, end)`, `balance_sheet(db)`, `statement(db, contact_id=1)`, `gstr1(db, start, end)`, `gstr3b(db, start, end)` and `stock_summary(db)`.

```python
finance = panel.get_plugin("finance")
finance.on_invoice_sent("whatsapp", lambda db, invoice, link: send_whatsapp(invoice.contact.phone, link))
```

## Options

```python
FinancePlugin(
    state="27", currency="INR",
    prefixes={"invoice": "INV-", "quote": "QT-", "credit_note": "CN-", "bill": "BILL-", "debit_note": "DN-"},
    due_days=15, default_tax_rate=18, round_off=True,
    terms="Payment within 15 days.",
    business_name=None, business_address=None, business_tax_id=None, business_email=None,
    business_phone=None, logo_url=None, payment_details=None,
    public_links=True, public_path="invoice",
    year_start_month=4,              # April
    default_accounts=True,           # Rent, Salaries, Software... expense accounts
    reports=True, dashboard_widgets=True, mailer=None,
    navigation_groups={"sales": "Sales", "purchases": "Purchases", "accounting": "Accounting",
                       "reports": "Finance reports"},
)
```

Reports have their own permission, `finance.reports`, to give in the Roles screen.

> [!NOTE]
> Stock is counted in quantity and valued at purchase price in the stock summary. Purchases go to the Purchases account; closing stock is not yet moved into the P&L.

With the [MCP plugin](mcp.html) installed, AI assistants like Claude can read and create invoices too.
