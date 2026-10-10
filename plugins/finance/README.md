# tungsten-finance

Finance and accounts plugin for [Tungsten](https://tungsten.prisminfoways.com/), the admin panel for FastAPI.
Double-entry books with GST, built to cover what small Indian businesses use Tally, Busy or Zoho Books for.

## What you get

**Sales**
- **Invoices** (`INV-00012`) with items, HSN/SAC, quantity, unit, price, discount % and GST %. Totals update while you type.
- **GST split by place of supply**: CGST + SGST inside your state, IGST for other states. Round off to the rupee.
- **Quotes** (`QT-`) that turn into an invoice in one click.
- **Credit notes** (`CN-`) against an invoice, for returns and discounts.
- **Payments received** (`RCPT-`) into a bank or cash account. Invoices turn part paid or paid by themselves.
- **Repeat invoices** every 1, 3, 6 or 12 months.
- **Send** an invoice by email with a link to a printable page. No login needed for the customer.

**Purchases**
- **Bills** (`BILL-`) from vendors, booked to purchases or any expense account, with input GST.
- **Debit notes** (`DN-`) against a bill, **payments made** (`PAY-`) and quick **expenses** with the receipt file.

**Accounting**
- **Double-entry ledger**: every invoice, bill, payment, note and expense posts a voucher by itself.
- **Chart of accounts** in Tally-style groups (bank, cash, sundry debtors, duties and taxes, capital, sales, purchases, direct and indirect expenses...).
- **Journal and contra vouchers**. Debit must equal credit, or the voucher is not saved.
- **Bank & cash** accounts with live balances and **opening balances** (accounts, customers, vendors).
- **Items & stock**: goods and services with HSN, prices, GST %, opening stock and reorder level.
- **Customers & vendors** with GSTIN check, state, credit days and running balance.

**Reports** (each with a period filter and CSV download)
- **Profit and loss** (trading account with gross profit, then net profit), **balance sheet**, **trial balance**.
- **Ledger statement** of any account, customer or vendor, with running balance.
- **Day book**, **stock summary** (in, out, closing, value, low stock), **bank reconciliation**.
- **GST returns**: GSTR-3B summary and GSTR-1 tables (B2B, B2C, credit notes, HSN summary).
- Overview with money in and out, who owes you (by how late), and dashboard numbers.

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

## Install

```bash
pip install tungsten-finance
```

```python
from tungsten_finance import FinancePlugin

panel = Panel(..., app_url="https://admin.example.com", auth=Auth(User, mailer=send_mail))
panel.plugin(FinancePlugin(
    state="27",                       # your state (code, name or GSTIN): decides CGST+SGST or IGST
    business_address="12 MG Road, Pune 411001",
    business_tax_id="27ABCDE1234F1Z5",
    payment_details="Bank: HDFC 50200012345678, IFSC HDFC0000123\nUPI: shop@okhdfc",
))
panel.create_tables(engine)   # creates the finance tables too
```

On first start it adds the system accounts (Cash, Accounts receivable, Output and Input GST, Sales, Purchases,
Capital...) and common expense accounts (Rent, Salaries, Software...). Add your bank under **Bank & cash**.

### Options

```python
FinancePlugin(
    state=None,                      # home state; taken from business_tax_id when not given
    currency="INR",                  # ISO code: INR, USD, EUR, GBP, AED...
    prefixes={"invoice": "INV-", "quote": "QT-", "credit_note": "CN-", "bill": "BILL-", "debit_note": "DN-"},
    due_days=15,                     # due date when the customer has no credit days
    default_tax_rate=18,             # GST % of new lines
    round_off=True,                  # round totals to the rupee
    terms="Payment within 15 days.", # printed at the bottom of invoices and quotes
    business_name=None,              # defaults to the panel's brand name
    business_address=None, business_tax_id=None, business_email=None, business_phone=None, logo_url=None,
    payment_details=None,            # "How to pay" under unpaid invoices
    public_links=True, public_path="invoice",   # <panel>/invoice/<number>/<key>
    year_start_month=4,              # financial year starts in April
    default_accounts=True,           # adds Rent, Salaries, Software... expense accounts
    reports=True, dashboard_widgets=True,
    mailer=None,                     # defaults to Auth(mailer=...)
    navigation_groups={"sales": "Sales", "purchases": "Purchases", "accounting": "Accounting", "reports": "Finance reports"},
)
```

Reports have their own permission, `finance.reports`, to give in the Roles screen.

## From code

Other parts of your app (a shop, the Leads plugin...) can make documents and book payments:

```python
from tungsten_finance import create_bill, create_document, create_invoice, record_payment

invoice = create_invoice(db, customer="Amit Traders", email="amit@example.com", external_id="order-12",
                         place_of_supply="27", status="sent",
                         items=[{"description": "Website design", "quantity": 1, "unit_price": 25000,
                                 "tax_rate": 18, "hsn": "998314"},
                                {"sku": "PEN", "quantity": 10}])     # an Item by sku or item_id
record_payment(db, invoice, 10000, method="upi", reference="UTR 1234")

bill = create_bill(db, vendor="Paper Mart", reference="PM/88", items=[{"sku": "PEN", "quantity": 100}])
note = create_document(db, "credit_note", contact=invoice.contact, against=invoice, status="sent", items=[...])
db.commit()

panel.get_plugin("finance").send_invoice(db, invoice)   # email the link
```

The same `external_id` never makes a second document. Reports are plain functions too: `trial_balance(db)`,
`profit_and_loss(db, start, end)`, `balance_sheet(db)`, `statement(db, contact_id=1)`, `gstr1(db, start, end)`,
`gstr3b(db, start, end)`, `stock_summary(db)`. Call `run_recurring(db)` once a day to make repeat invoices
(the Invoices list also has a **Make repeat invoices** button).

## Hooks

```python
finance = panel.get_plugin("finance")
finance.on_invoice_sent("whatsapp", lambda db, invoice, link: ...)
```

## Good to know

- Drafts and cancelled documents never touch the books. Quotes never do.
- Stock is counted in quantity and valued at purchase price in the stock summary; purchases go to the Purchases account (closing stock is not yet moved into the P&L).
- GST return tables are a starting point for your CA, not a filing.

## Try it

```bash
pip install -e . -e plugins/finance uvicorn
uvicorn plugins.finance.example:app --reload     # from the repo root
```

Sign in at http://127.0.0.1:8000/admin with admin@example.com / password.

## More Tungsten plugins

| Package | What it adds | Docs |
| --- | --- | --- |
| [`tungsten-leads`](https://pypi.org/project/tungsten-leads/) | Leads list, stages, timeline and your own lead form fields | [README](https://github.com/Prism-Infoways/Tungsten/tree/claude/tungsten-admin-panel/plugins/leads) |
| [`tungsten-meta-leads`](https://pypi.org/project/tungsten-meta-leads/) | Facebook and Instagram lead form leads, with one-click setup | [Guide](https://tungsten.prisminfoways.com/docs/facebook-leads.html) |
| [`tungsten-whatsapp`](https://pypi.org/project/tungsten-whatsapp/) | WhatsApp for leads: click-to-chat, Cloud API or WhatsApp Web | [Guide](https://tungsten.prisminfoways.com/docs/whatsapp.html) |
| [`tungsten-mcp`](https://pypi.org/project/tungsten-mcp/) | MCP server, so AI assistants like Claude can read and change your data | [Guide](https://tungsten.prisminfoways.com/docs/mcp.html) |
| [`tungsten-tickets`](https://pypi.org/project/tungsten-tickets/) | Help desk: tickets, replies, notes, SLA and a customer support page | [Guide](https://tungsten.prisminfoways.com/docs/tickets.html) |
| [`tungsten-blog`](https://pypi.org/project/tungsten-blog/) | Blog built for SEO, GEO and AEO, with a live score, sitemap and llms.txt | [Guide](https://tungsten.prisminfoways.com/docs/blog.html) |
| [`tungsten-seo-audit`](https://pypi.org/project/tungsten-seo-audit/) | SEO audit of your website: score, fix tips, AI search checks, history | [Guide](https://tungsten.prisminfoways.com/docs/seo-audit.html) |
| [`tungsten-security-audit`](https://pypi.org/project/tungsten-security-audit/) | Security audit with a score and fix tips, plus a login log with lockout | [Guide](https://tungsten.prisminfoways.com/docs/security-audit.html) |
| [`tungsten-hr`](https://pypi.org/project/tungsten-hr/) | HR: employees, attendance with check-in and biometric machines, leave with approval | [Guide](https://tungsten.prisminfoways.com/docs/hr.html) |

Core package: [`tungsten-admin`](https://pypi.org/project/tungsten-admin/). Website and docs: https://tungsten.prisminfoways.com/
