import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Sum

D0 = Decimal('0.00')


class User(AbstractUser):
    ROLES = [('admin', 'Admin'), ('staff', 'Internal staff'), ('customer', 'Customer')]
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=ROLES, default='customer')

    def save(self, *a, **kw):
        self.is_superuser = self.is_staff = (self.role == 'admin')  # admins may use /admin/
        super().save(*a, **kw)

    @property
    def is_admin_role(self):
        return self.role == 'admin'

    @property
    def is_team(self):
        return self.role in ('admin', 'staff')

    def __str__(self):
        return self.get_full_name() or self.email


class Tax(models.Model):
    name = models.CharField(max_length=60)
    percentage = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        verbose_name_plural = 'taxes'

    def __str__(self):
        return f'{self.name} ({self.percentage}%)'


class Product(models.Model):
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=60, default='Service')
    sales_price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    attribute = models.CharField(max_length=60, default='Brand')
    value = models.CharField(max_length=60)
    extra_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f'{self.product.name} - {self.attribute}: {self.value} (+{self.extra_price})'


class Plan(models.Model):
    PERIODS = [('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly'), ('yearly', 'Yearly')]
    name = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    billing_period = models.CharField(max_length=10, choices=PERIODS, default='monthly')
    min_quantity = models.PositiveIntegerField(default=1)
    start_date = models.DateField(default=date.today)
    end_date = models.DateField(null=True, blank=True)
    auto_close = models.BooleanField(default=False, help_text='Close subscriptions automatically when they expire')
    closable = models.BooleanField(default=True)
    pausable = models.BooleanField(default=False)
    renewable = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.name} ({self.get_billing_period_display()})'

    def next_date(self, d):
        p = self.billing_period
        if p == 'daily':
            return d + timedelta(days=1)
        if p == 'weekly':
            return d + timedelta(days=7)
        months = 1 if p == 'monthly' else 12
        m = d.month - 1 + months
        y, m = d.year + m // 12, m % 12 + 1
        return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


class QuotationTemplate(models.Model):
    name = models.CharField(max_length=120)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    validity_days = models.PositiveIntegerField(default=30)

    def __str__(self):
        return self.name


class QuotationTemplateLine(models.Model):
    template = models.ForeignKey(QuotationTemplate, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)


class Discount(models.Model):
    TYPES = [('percent', 'Percentage'), ('fixed', 'Fixed amount')]
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=10, choices=TYPES, default='percent')
    value = models.DecimalField(max_digits=10, decimal_places=2)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.CASCADE,
                                help_text='Leave empty to apply to the whole subscription')
    min_purchase = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    min_quantity = models.PositiveIntegerField(default=0)
    start_date = models.DateField(default=date.today)
    end_date = models.DateField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text='Empty = unlimited')
    times_used = models.PositiveIntegerField(default=0, editable=False)

    def __str__(self):
        return self.name

    def is_live(self, today):
        if self.start_date > today or (self.end_date and self.end_date < today):
            return False
        return self.usage_limit is None or self.times_used < self.usage_limit


class Subscription(models.Model):
    STATUSES = [('draft', 'Draft'), ('quotation', 'Quotation'), ('confirmed', 'Confirmed'),
                ('active', 'Active'), ('closed', 'Closed')]
    FLOW = {'draft': 'quotation', 'quotation': 'confirmed', 'confirmed': 'active'}
    number = models.CharField(max_length=20, unique=True, blank=True)
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='subscriptions')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    template = models.ForeignKey(QuotationTemplate, null=True, blank=True, on_delete=models.SET_NULL)
    start_date = models.DateField(default=date.today)
    expiry_date = models.DateField(null=True, blank=True)
    quote_valid_until = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=60, default='Net 15')
    next_billing_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default='draft', db_index=True)
    paused = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.number

    def save(self, *a, **kw):
        super().save(*a, **kw)
        if not self.number:
            self.number = f'SUB-{self.pk:05d}'
            super().save(update_fields=['number'])

    @property
    def next_status(self):
        return self.FLOW.get(self.status)

    @property
    def net_days(self):
        digits = ''.join(c for c in self.payment_terms if c.isdigit())
        return int(digits) if digits else 0

    @property
    def total(self):
        return sum((l.amount for l in self.lines.all()), D0)


class SubscriptionLine(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.SET_NULL)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, blank=True)
    tax = models.ForeignKey(Tax, null=True, blank=True, on_delete=models.SET_NULL)

    @property
    def amount(self):
        return self.quantity * self.unit_price

    @property
    def tax_amount(self):
        return (self.amount * self.tax.percentage / 100).quantize(D0) if self.tax else D0


class Invoice(models.Model):
    STATUSES = [('draft', 'Draft'), ('confirmed', 'Confirmed'), ('paid', 'Paid'), ('cancelled', 'Cancelled')]
    number = models.CharField(max_length=20, unique=True, blank=True)
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name='invoices')
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='invoices')
    period_start = models.DateField()
    issue_date = models.DateField(default=date.today)
    due_date = models.DateField(db_index=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUSES, default='draft', db_index=True)
    sent = models.BooleanField(default=False)
    discounts_applied = models.CharField(max_length=250, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['subscription', 'period_start'], name='one_invoice_per_period')]
        ordering = ['-id']

    def __str__(self):
        return self.number

    def save(self, *a, **kw):
        super().save(*a, **kw)
        if not self.number:
            self.number = f'INV-{self.pk:06d}'
            super().save(update_fields=['number'])

    @property
    def paid_amount(self):
        return self.payments.aggregate(s=Sum('amount'))['s'] or D0

    @property
    def balance(self):
        return self.total - self.paid_amount

    @property
    def is_overdue(self):
        return self.status in ('draft', 'confirmed') and self.due_date < date.today()


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='lines')
    description = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    tax_name = models.CharField(max_length=60, blank=True)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2)


class Payment(models.Model):
    METHODS = [('card', 'Card'), ('upi', 'UPI'), ('bank', 'Bank transfer'), ('cash', 'Cash'), ('cheque', 'Cheque')]
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    method = models.CharField(max_length=10, choices=METHODS)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=date.today, db_index=True)
    note = models.CharField(max_length=250, blank=True)
