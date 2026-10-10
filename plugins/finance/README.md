# tungsten-finance

Finance and accounts plugin for [Tungsten](https://tungsten.prisminfoways.com/), the admin panel for FastAPI.
Bill customers, record payments and expenses, and see your profit, without a separate accounting app.

## What you get

- **Invoices** with a number (`INV-00012`), customer, invoice and due dates, line items with quantity, price and **tax % (GST)**, discount, notes and terms. Totals update while you type.
- Status: *Draft*, *Sent*, *Part paid*, *Paid*, *Cancelled*, and *Overdue* when the due date has passed.
- **Record payment** on an invoice: it becomes part paid or paid by itself. Deleting a payment opens it again.
- **Send** an invoice: the customer gets an email with a link to a clean page they can **print or save as PDF**. No login needed.
- **Payments** list (money in) with method (bank, UPI, cash, card, cheque) and the account it went into.
- **Expenses** (money out) with category, vendor, the tax inside the bill, and the receipt file.
- **Customers & vendors** with GSTIN, address and how much each one owes you.
- **Bank & cash** accounts with live balances.
- **Reports** page for this month, last month, this quarter, this or last financial year, or all time: invoiced, money in, money out, profit, where the money went, who owes you (by how late), tax charged vs paid, and bank balances.
- Dashboard numbers and a money in / money out chart.
- Tabs for *Unpaid*, *Overdue*, *Drafts* and *Paid*; filters; search; export to CSV and Excel.

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
panel.create_tables(engine)   # creates the finance tables too
```

`mailer` is your function `send_mail(to, subject, body)`. `app_url` makes the links in emails full links.

### Options

```python
FinancePlugin(
    currency="INR",                  # ISO code: INR, USD, EUR, GBP, AED...
    number_prefix="INV-",
    due_days=15,                     # due date when none is picked
    default_tax_rate=18,             # Tax % of new invoice lines (0 for none)
    terms="Payment within 15 days.", # printed at the bottom of invoices
    business_name=None,              # defaults to the panel's brand name
    business_address=None, business_tax_id=None, business_email=None, business_phone=None, logo_url=None,
    payment_details=None,            # "How to pay" under unpaid invoices
    public_links=True, public_path="invoice",   # <panel>/invoice/<number>/<key>
    year_start_month=4,              # financial year starts in April
    default_categories=True,         # adds Rent, Salaries, Software... when there are none
    mailer=None,                     # defaults to Auth(mailer=...)
    navigation_group="Finance",
)
```

The Reports page has its own permission, `finance.reports`, to give in the Roles screen.

## Bill from code

Other parts of your app (a shop, the Leads plugin...) can make invoices and book payments:

```python
from tungsten_finance import create_invoice, record_payment

invoice = create_invoice(db, customer="Amit Traders", email="amit@example.com", external_id="order-12",
                         items=[{"description": "Website design", "quantity": 1, "unit_price": 25000,
                                 "tax_rate": 18}])
record_payment(db, invoice, 10000, method="upi", reference="UTR 1234")
db.commit()

panel.get_plugin("finance").send_invoice(db, invoice)   # email the link
```

The same `external_id` never makes a second invoice.

## Hooks

```python
finance = panel.get_plugin("finance")
finance.on_invoice_sent("whatsapp", lambda db, invoice, link: ...)
```

## Good to know

- Profit in reports is **cash based**: money in is payments received, money out is expenses.
- Expense amounts include tax; put the tax part in "Tax in it" so the GST card can net it off.
- This is simple bookkeeping for small teams, not a full double-entry ledger. Ask your accountant before filing returns.

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
| [`tungsten-hr`](https://pypi.org/project/tungsten-hr/) | HR: employees, departments, attendance with check-in, leave with balances and approval | [Guide](https://tungsten.prisminfoways.com/docs/hr.html) |

Core package: [`tungsten-admin`](https://pypi.org/project/tungsten-admin/). Website and docs: https://tungsten.prisminfoways.com/
