import time
from datetime import date

from django.core import mail
from django.test import TestCase, Client

from core import billing
from core.models import *


class Flow(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command('seed', count=20)

    def login(self, email):
        c = Client()
        assert c.login(username=email, password='Passw0rd!x'), email
        return c

    def test_roles_and_pages(self):
        admin, staff, cust = (self.login(f'{r}@brightloop.com') for r in ('admin', 'staff', 'customer'))
        for url in ['/', '/subscriptions/', '/invoices/', '/payments/', '/subscriptions/new/', '/staff/new/', '/admin/']:
            r = admin.get(url)
            self.assertIn(r.status_code, (200,), url)
        self.assertEqual(staff.get('/staff/new/').status_code, 403)   # only admin adds staff
        self.assertEqual(staff.get('/admin/').status_code, 302)       # staff cannot use the catalog admin
        for url in ['/', '/subscriptions/', '/invoices/', '/payments/']:
            r = cust.get(url)
            self.assertIn(r.status_code, (302, 403), url)             # customers are kept out
        self.assertEqual(cust.get('/portal/').status_code, 200)
        other = Invoice.objects.exclude(customer__email='customer@brightloop.com').first()
        self.assertEqual(cust.get(f'/invoices/{other.pk}/').status_code, 403)

    def test_signup_rules(self):
        c = Client()
        bad = c.post('/signup/', {'first_name': 'A', 'last_name': 'B', 'email': 'new@x.com', 'password': 'short1!', 'confirm': 'short1!'})
        self.assertContains(bad, 'Password needs')
        ok = {'first_name': 'A', 'last_name': 'B', 'email': 'new@x.com', 'password': 'Strong#Pass1', 'confirm': 'Strong#Pass1'}
        self.assertEqual(c.post('/signup/', ok).status_code, 302)
        dup = Client().post('/signup/', ok)
        self.assertContains(dup, 'already exists')

    def test_password_reset_email(self):
        Client().post('/password-reset/', {'email': 'admin@brightloop.com'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/reset/', mail.outbox[0].body)

    def test_billing_is_idempotent(self):
        before = Invoice.objects.count()
        self.assertEqual(billing.run_billing(), (0, 0))
        self.assertEqual(Invoice.objects.count(), before)
        sub = Subscription.objects.filter(status='active', paused=False).first()
        self.assertIsNone(billing.create_invoice(sub, sub.invoices.first().period_start, date.today()))

    def test_discount_tax_and_payment(self):
        cust = User.objects.get(email='customer@brightloop.com')
        plan = Plan.objects.get(name='Starter Monthly')
        crm = Product.objects.get(name='Brightloop CRM')
        gst = Tax.objects.get(name='GST')
        sub = Subscription.objects.create(customer=cust, plan=plan, start_date=date.today())
        SubscriptionLine.objects.create(subscription=sub, product=crm, quantity=5, unit_price=1500, tax=gst)
        for _ in range(3):
            billing.advance(sub)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        billing.run_billing()
        inv = sub.invoices.get()
        # 5 x 1500 = 7500; 10% volume discount = 750 (the 'Welcome' discount is used up by the seed, so it is skipped); tax 18% on 6750
        self.assertEqual((inv.subtotal, inv.discount_total, inv.tax_total, inv.total), (7500, 750, 1215, 7965))
        billing.run_billing()
        self.assertEqual(sub.invoices.count(), 1)
        billing.add_payment(inv, 'upi', 5000, date.today(), 'part')
        inv.refresh_from_db(); self.assertEqual(inv.status, 'confirmed')
        billing.add_payment(inv, 'card', inv.balance, date.today(), 'rest')
        inv.refresh_from_db(); self.assertEqual(inv.status, 'paid')

    def test_speed(self):
        admin = self.login('admin@brightloop.com')
        for url in ['/', '/subscriptions/', '/invoices/?filter=overdue', '/payments/']:
            t = time.time(); admin.get(url); self.assertLess(time.time() - t, 2, url)
