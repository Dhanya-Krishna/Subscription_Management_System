import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction

from core import billing
from core.models import *

FIRST = ['Aarav', 'Diya', 'Kabir', 'Meera', 'Rohan', 'Sneha', 'Vikram', 'Anaya', 'Arjun', 'Isha', 'Nikhil', 'Priya']
LAST = ['Nair', 'Menon', 'Iyer', 'Sharma', 'Patel', 'Reddy', 'Das', 'Khan', 'Joseph', 'Pillai']


class Command(BaseCommand):
    help = 'Load demo data: python manage.py seed --count 50'

    def add_arguments(self, p):
        p.add_argument('--count', type=int, default=50)

    def handle(self, *a, count, **kw):
        random.seed(1)
        pw = 'Passw0rd!x'
        hashed = make_password(pw)

        # --- Users ---
        for email, role, fn in [
            ('admin@brightloop.com', 'admin', 'Asha'),
            ('staff@brightloop.com', 'staff', 'Sam'),
            ('customer@brightloop.com', 'customer', 'Carla'),
        ]:
            u, _ = User.objects.get_or_create(
                email=email,
                defaults={'username': email, 'role': role, 'first_name': fn, 'last_name': 'Demo'},
            )
            u.password = hashed
            u.role = role
            u.save()

        # --- Catalog ---
        gst, _ = Tax.objects.get_or_create(name='GST', defaults={'percentage': Decimal('18')})
        crm, _ = Product.objects.get_or_create(
            name='Brightloop CRM',
            defaults=dict(type='Software', sales_price=Decimal('1500'), cost_price=Decimal('400')),
        )
        erp, _ = Product.objects.get_or_create(
            name='Brightloop ERP',
            defaults=dict(type='Software', sales_price=Decimal('2500'), cost_price=Decimal('900')),
        )
        addon, _ = Product.objects.get_or_create(
            name='Extra storage add-on',
            defaults=dict(type='Add-on', sales_price=Decimal('300'), cost_price=Decimal('60')),
        )
        odood, _ = ProductVariant.objects.get_or_create(
            product=erp, attribute='Brand', value='Odoo', defaults={'extra_price': Decimal('560')}
        )
        std, _ = ProductVariant.objects.get_or_create(
            product=erp, attribute='Brand', value='Standard', defaults={'extra_price': Decimal('0')}
        )

        m, _ = Plan.objects.get_or_create(
            name='Starter Monthly',
            defaults=dict(price=Decimal('1500'), billing_period='monthly', closable=True, pausable=True, renewable=True),
        )
        y, _ = Plan.objects.get_or_create(
            name='Business Yearly',
            defaults=dict(price=Decimal('25000'), billing_period='yearly', min_quantity=1, auto_close=True, closable=False, renewable=True),
        )
        w, _ = Plan.objects.get_or_create(
            name='Trial Weekly',
            defaults=dict(price=Decimal('200'), billing_period='weekly', closable=True),
        )
        pro, _ = Plan.objects.get_or_create(
            name='Pro Monthly',
            defaults=dict(price=Decimal('3500'), billing_period='monthly', closable=True, pausable=True, renewable=True),
        )

        t, _ = QuotationTemplate.objects.get_or_create(name='Standard CRM offer', defaults=dict(plan=m, validity_days=30))
        if not t.lines.exists():
            QuotationTemplateLine.objects.create(template=t, product=crm, quantity=1)

        Discount.objects.get_or_create(
            name='Volume 10% (5+ seats)',
            defaults=dict(type='percent', value=Decimal('10'), min_quantity=5, usage_limit=500),
        )
        Discount.objects.get_or_create(
            name='Welcome 200 off',
            defaults=dict(
                type='fixed', value=Decimal('200'), min_purchase=Decimal('1000'),
                usage_limit=20, end_date=date.today() + timedelta(days=60),
            ),
        )

        # --- Bulk customers ---
        customers = []
        for i in range(count):
            email = f'cust{i}@example.com'
            c, created = User.objects.get_or_create(
                email=email,
                defaults=dict(
                    username=email, role='customer',
                    first_name=random.choice(FIRST), last_name=random.choice(LAST),
                ),
            )
            if created:
                c.password = hashed
                c.save(update_fields=['password'])
            customers.append(c)

        plans_pool = [m, m, m, y, w, pro]
        products_pool = [crm, erp]

        for c in customers:
            if c.subscriptions.exists():
                continue
            plan = random.choice(plans_pool)
            start = date.today() - timedelta(days=random.randint(0, 150))
            sub = Subscription.objects.create(
                customer=c, plan=plan, start_date=start,
                payment_terms=random.choice(['Net 15', 'Net 30', 'Net 7']),
                expiry_date=(start + timedelta(days=365)) if plan.auto_close else None,
            )
            prod = random.choice(products_pool)
            var = odood if prod == erp else None
            qty = random.choice([1, 1, 2, 5, 6])
            unit = prod.sales_price + (var.extra_price if var else Decimal('0'))
            SubscriptionLine.objects.create(
                subscription=sub, product=prod, variant=var, quantity=qty, tax=gst, unit_price=unit,
            )
            for _ in range(random.choice([1, 2, 3, 3])):
                billing.advance(sub)

        billing.run_billing()

        for inv in Invoice.objects.filter(status='draft'):
            r = random.random()
            if r < 0.6:
                billing.add_payment(
                    inv, random.choice(['card', 'upi', 'bank']), inv.total,
                    inv.issue_date + timedelta(days=random.randint(0, 10)), 'Demo payment',
                )
            elif r < 0.85:
                inv.status = 'confirmed'
                inv.save()

        # --- Rich demo customer (customer@brightloop.com) ---
        # One subscription per status so filters work: Active, Confirmed, Quotation, Draft, Closed
        demo = User.objects.get(email='customer@brightloop.com')
        with transaction.atomic():
            Payment.objects.filter(invoice__customer=demo).delete()
            Invoice.objects.filter(customer=demo).delete()
            SubscriptionLine.objects.filter(subscription__customer=demo).delete()
            demo.subscriptions.all().delete()

        # (plan, product, variant, qty, status, days_ago_start)
        rich = [
            (m, crm, None, 2, 'active', 90),
            (y, erp, odood, 1, 'active', 120),
            (pro, erp, std, 1, 'confirmed', 45),
            (w, addon, None, 3, 'quotation', 20),
            (m, crm, None, 1, 'draft', 5),
            (pro, crm, None, 2, 'closed', 180),
            (y, erp, odood, 1, 'closed', 400),
            (w, addon, None, 1, 'active', 60),
        ]
        created_subs = []
        for plan, prod, var, qty, status, days_ago in rich:
            start = date.today() - timedelta(days=days_ago)
            expiry = None
            if status == 'closed':
                expiry = date.today() - timedelta(days=random.randint(5, 40))
            elif plan.auto_close:
                expiry = start + timedelta(days=365)

            sub = Subscription.objects.create(
                customer=demo, plan=plan, start_date=start,
                payment_terms=random.choice(['Net 15', 'Net 30']),
                status='draft',  # start draft, advance as needed
                expiry_date=expiry,
                next_billing_date=date.today() + timedelta(days=random.randint(1, 25)) if status == 'active' else None,
            )
            unit = prod.sales_price + (var.extra_price if var else Decimal('0'))
            SubscriptionLine.objects.create(
                subscription=sub, product=prod, variant=var, quantity=qty, tax=gst, unit_price=unit,
            )
            # Advance through workflow to target status
            target_order = ['draft', 'quotation', 'confirmed', 'active']
            if status in target_order:
                target_idx = target_order.index(status)
                for _ in range(target_idx):
                    billing.advance(sub)
            # Force exact status (closed is terminal)
            sub.status = status
            if status == 'active' and not sub.next_billing_date:
                sub.next_billing_date = sub.start_date
            if status == 'quotation' and not sub.quote_valid_until:
                sub.quote_valid_until = date.today() + timedelta(days=30)
            sub.save()
            created_subs.append(sub)

        billing.run_billing()

        # Ensure active/confirmed/closed subs have invoices (for card due/paid amounts)
        for sub in created_subs:
            if sub.status not in ('active', 'confirmed', 'closed'):
                continue
            if sub.invoices.exists():
                continue
            try:
                period = sub.start_date or date.today()
                billing.create_invoice(sub, period, date.today())
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'Could not create invoice for {sub.number}: {e}'))

        # Mix payment states on demo invoices
        demo_invs = list(Invoice.objects.filter(customer=demo).order_by('issue_date'))
        for idx, inv in enumerate(demo_invs):
            if inv.status == 'cancelled':
                continue
            inv.status = 'confirmed'
            if idx % 3 == 0:
                inv.due_date = date.today() - timedelta(days=random.randint(5, 25))
            inv.save()
            if idx % 3 == 1:
                billing.add_payment(inv, 'upi', inv.total, inv.issue_date + timedelta(days=2), 'Full payment')
            elif idx % 3 == 2 and inv.total > 0:
                half = (inv.total / 2).quantize(Decimal('0.01'))
                billing.add_payment(inv, 'card', half, inv.issue_date + timedelta(days=1), 'Partial')

        self.stdout.write(self.style.SUCCESS(
            f'Seeded OK.\n'
            f'  Logins (password {pw}):\n'
            f'    admin@brightloop.com\n'
            f'    staff@brightloop.com\n'
            f'    customer@brightloop.com\n'
            f'  Demo customer: {demo.subscriptions.count()} subscriptions, '
            f'{Invoice.objects.filter(customer=demo).count()} invoices.'
        ))
