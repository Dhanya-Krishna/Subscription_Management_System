# Brightloop Subscription Management System

A unified platform for running a subscription business end to end: products and plans, quotations, subscriptions, automated recurring invoicing, payments, discounts, taxes and revenue reporting. Built with **Django** and **SQLite**, with a role-based web interface for admins, internal staff and customers.

---

## Background

Brightloop Software sells business software on monthly and yearly subscriptions, plus add-ons and product variants. Before this system, subscriptions lived in a spreadsheet, renewals were remembered by whoever noticed first, invoices were typed by hand, payments were matched by scrolling bank statements, and nobody could say what the recurring revenue was.

This project replaces that with one system covering the whole lifecycle: **set up products and plans → quote → subscribe → invoice → collect payment → report**.

---

## Features

### Accounts and roles
- Sign-up with email and password. **Each email can belong to only one account** (enforced at both form and database level).
- Password rules: more than 8 characters, with an uppercase letter, a lowercase letter and a special character (`core/validators.py`).
- Password reset: a reset link is sent to the registered email.
- Three roles, enforced in the backend on every view (not just hidden in the menu):

| Role | Access |
|---|---|
| **Admin** | Everything: products, plans, taxes, discounts, quotation templates, staff accounts, and all day-to-day screens |
| **Internal staff** | Day-to-day work: subscriptions, invoices, payments, dashboard, billing run. No configuration screens |
| **Customer** | Self-service portal showing only their own subscriptions and invoices. Other customers' records return **403** |

- Only the admin can add a new staff member.

### Products, variants and plans
- **Products** with name, type, sales price, cost price and notes.
- **Variants** by attribute, each with an extra price (e.g. `Brand = Odoo` adds 560).
- **Plans** with price, billing period (**daily, weekly, monthly, yearly**), minimum quantity and availability dates.
- Per-plan behaviour set by the admin: **auto-close on expiry, closable, pausable, renewable**.

### Quotation templates and subscriptions
- **Quotation templates** pre-load a plan, product lines and a validity period (in days).
- Each subscription gets an auto-generated number (`SUB-00001`), a customer, plan, start and expiry date, and payment terms (e.g. Net 15), with lines for product, quantity, unit price, tax and amount.
- Status flow: **Draft → Quotation → Confirmed → Active → Closed**, visible to the whole team.
- Customers can accept a quotation, and close, pause or renew a subscription where the plan allows it.

### Automated invoicing
- **Run billing** creates invoices for every active, unpaused subscription whose billing date has arrived, with customer details, lines, taxes, discounts and totals already filled in.
- **Nothing is billed twice:** a database unique constraint on `(subscription, period_start)` makes the run safe to repeat or run concurrently. Missed periods are caught up in the same run.
- Invoice numbers are generated automatically (`INV-000001`).
- Invoice actions: **confirm, cancel, send by email, print**. Status flow: **Draft → Confirmed → Paid** (or Cancelled; a cancelled invoice cannot have payments).
- Subscriptions on auto-close plans close themselves when they expire.

### Taxes
- The admin defines tax rules. Tax is applied per subscription line and calculated on the **discounted** amount.

### Discounts
- Admin-only. **Percentage or fixed amount**, with minimum purchase, minimum quantity, start and end dates, and a usage limit.
- Applies to a **specific product** or the **whole subscription**.
- Applied to the next invoice automatically, and stops when it expires or its usage limit is reached. Discounts used are recorded on the invoice.

### Payments
- Record a payment against an invoice with **method** (card, UPI, bank transfer, cash, cheque), **amount, date and note**.
- Partial payments are supported; when the total paid reaches the invoice total, the invoice becomes **Paid**.
- Paid and outstanding invoices are visible at any time, and overdue invoices can be filtered for chasing.

### Dashboard and reporting
One place for the finance lead to see:
- Active subscriptions (and counts by status)
- Revenue received and amount still owed
- Overdue invoices
- Monthly payments chart
- Filters by **date range and plan**

Lists are paginated (25 per page) and the test suite asserts that key pages respond in **under 2 seconds**.

---

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python, Django 5+ |
| Database | SQLite (swap for PostgreSQL in production via `settings.py`) |
| Frontend | Django templates, Bootstrap 5, Chart.js-style dashboard chart |
| Auth | Django auth with a custom `User` model (email unique, `role` field) |
| Email | Console backend in development (emails print in the terminal) |

---

## Getting started

**Requirements:** Python 3.10+

```bash
cd brightloop
pip install -r requirements.txt
python manage.py runserver
```

Open <http://127.0.0.1:8000>.

A demo database with **300 customers** is included. To reset and re-seed it:

```bash
# Mac/Linux
rm db.sqlite3
# Windows
del db.sqlite3

python manage.py migrate
python manage.py seed --count 300
```

### Demo logins

Password for all accounts: `Passw0rd!x`

| Role | Email |
|---|---|
| Admin | `admin@brightloop.com` |
| Staff | `staff@brightloop.com` |
| Customer | `customer@brightloop.com` |

---

## Demo walkthrough

This follows the scenes in "A Month at Brightloop".

1. **New customer:** go to `/signup/`. Try a weak password and a duplicate email to see the validation. For password reset, the link prints in the terminal.
2. **Launch a plan (Admin):** use the left menu for Products (add a variant such as Brand = Odoo, +560), Plans, Taxes, Discounts and Quotation templates. Use **Add staff** to create a staff account.
3. **Quote to subscription:** Subscriptions → New subscription (try loading a quotation template). Use **Move to…** to go Draft → Quotation → Confirmed → Active.
4. **Billing day:** Dashboard or Invoices → **Run billing for today**. Click it twice; no duplicate invoices are created.
5. **Invoice handling:** open an invoice to Confirm, Send by email (prints in the terminal), Print, Cancel, or Record a payment (partial, then full, turns it Paid).
6. **Month end:** the Dashboard shows active subscriptions, revenue, amount still owed, overdue invoices, filters and the monthly chart.
7. **Customer view:** log in as the customer. Only their own subscriptions and invoices appear; other IDs return 403.

---

## Project structure

```
brightloop/
├── manage.py
├── requirements.txt
├── db.sqlite3                  # demo database (300 customers)
├── brightloop/                 # project settings and root URLs
└── core/
    ├── models.py               # User, Tax, Product, ProductVariant, Plan, QuotationTemplate(+Line),
    │                           # Discount, Subscription(+Line), Invoice(+Line), Payment
    ├── billing.py              # pricing, discounts, tax, billing run, status transitions, payments, email
    ├── views.py                # screens and role-based access checks
    ├── forms.py                # signup, subscription, line and payment forms
    ├── validators.py           # password strength rules
    ├── urls.py                 # routes
    ├── admin.py                # admin configuration for products, templates, users
    ├── tests.py                # automated tests
    ├── templates/core/         # landing, login, signup, dashboard, subscriptions, invoices, payments, portal
    └── management/commands/
        └── seed.py             # demo data generator
```

### Data model (summary)

```
User ─┬─< Subscription >── Plan
      │        │  └──────< SubscriptionLine >── Product ──< ProductVariant
      │        │                      └── Tax
      │        └──< Invoice ──< InvoiceLine
      │                  └──< Payment
      └─< Invoice (customer)

QuotationTemplate ──< QuotationTemplateLine >── Product
Discount ── Product (optional; empty = whole subscription)
```

Key constraints and indexes:
- `User.email` is unique.
- `Invoice` has a unique `(subscription, period_start)` constraint, which prevents double billing.
- Indexes on `Subscription.status`, `Invoice.status`, `Invoice.due_date` and `Payment.date` keep dashboards and lists fast.

---

## Testing

```bash
python manage.py test
```

The suite covers:
- Role access and page loads
- Sign-up rules (duplicate email, password strength)
- Password reset email
- Billing idempotency (running twice creates no duplicates)
- Discount, tax and payment calculations
- Response time under 2 seconds on the dashboard, subscription, invoice and payment pages

---

## Automating the billing run

Billing is triggered by a button, but the same function can run unattended. Schedule this daily with cron, Windows Task Scheduler or similar:

```bash
python manage.py shell -c "from core.billing import run_billing; run_billing()"
```

It is safe to run repeatedly.

---

## Known limitations

- **Billing is not scheduled out of the box.** It runs from the button, or from a daily cron job as above.
- **No PDF generation.** The Print button uses the browser's *Save as PDF*.
- **No online payment gateway.** Payments are recorded manually (or marked as a customer portal payment).
- **Social login is a demo stub.** The Google/Microsoft/LinkedIn/Facebook/X buttons sign in as the demo customer and are not real OAuth.
- **Configuration screens use Django admin.** Products, plans, taxes, discounts and quotation templates are managed through `/admin/`.
- **Emails print to the console** until a real email backend is configured.

---

## Before deploying to production

- Set `DEBUG = False` and configure `ALLOWED_HOSTS`.
- Move `SECRET_KEY` out of source control (environment variable).
- Replace SQLite with PostgreSQL.
- Configure a real email backend (SMTP or a transactional email service).
- Remove the demo social-login route and demo accounts.
- Serve static files properly and run behind HTTPS.
- Schedule the daily billing run.
