# Brightloop Subscription Management System (Django)

One website, three roles. Run it:

    pip install -r requirements.txt
    python manage.py runserver        # open http://127.0.0.1:8000

A demo database (300 customers) is included. To reset it:

    del db.sqlite3            (Windows)   /  rm db.sqlite3   (Mac/Linux)
    python manage.py migrate
    python manage.py seed --count 300

## Demo logins (password for all: Passw0rd!x)
| Role | Email |
|---|---|
| Admin | admin@brightloop.com |
| Staff | staff@brightloop.com |
| Customer | customer@brightloop.com |

## Demo script (follows "A month at Brightloop")
1. Sign up a new customer at /signup/ (try a weak password and a duplicate email). Password reset: the link prints in the terminal.
2. Admin: Products (add a variant like Brand=Odoo, +560), Plans, Taxes, Discounts, Quotation templates (left menu). Add staff via "Add staff".
3. Subscriptions > New subscription (try loading a quotation template). Use "Move to ..." to go Draft > Quotation > Confirmed > Active.
4. Dashboard (or Invoices) > "Run billing for today". Click it twice: no duplicate invoices (database unique constraint).
5. Open an invoice: Confirm, Send by email (prints in terminal), Print, Cancel, Record a payment (partial then full turns it Paid).
6. Dashboard: active subscriptions, revenue, still owed, overdue invoices, filters, monthly chart.
7. Log in as the customer: only their own subscriptions and invoices are visible (other IDs return 403).

## Where things are
- core/models.py: all tables. core/billing.py: pricing, discounts, tax, billing run, payments.
- core/views.py: screens and role checks. core/tests.py: `python manage.py test`.

## Not built (honest list)
Billing runs from a button (call `python manage.py shell -c "from core.billing import run_billing; run_billing()"` from a daily cron/scheduler for automation), PDF download (the Print button uses the browser's Save as PDF), online payment gateway.
