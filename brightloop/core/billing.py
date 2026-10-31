"""All billing logic lives here: pricing, invoice generation, payments, transitions."""
from datetime import date, timedelta
from decimal import Decimal

from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import F

from .models import D0, Discount, Invoice, InvoiceLine, Payment, Subscription


def q(x):
    return Decimal(x).quantize(D0)


def price_lines(sub, today):
    """Returns (lines, subtotal, discount_total, tax_total, total, applied_discounts)."""
    lines = list(sub.lines.select_related('product', 'variant', 'tax'))
    subtotal = sum((l.amount for l in lines), D0)
    total_qty = sum(l.quantity for l in lines)
    discount_total, applied = D0, []
    for d in Discount.objects.filter(start_date__lte=today).select_related('product'):
        if not d.is_live(today):
            continue
        scope = [l for l in lines if l.product_id == d.product_id] if d.product_id else lines
        base = sum((l.amount for l in scope), D0)
        qty = sum(l.quantity for l in scope)
        if not scope or base < d.min_purchase or qty < d.min_quantity:
            continue
        amt = q(base * d.value / 100) if d.type == 'percent' else q(d.value)
        amt = min(amt, base, subtotal - discount_total)
        if amt > 0:
            discount_total += amt
            applied.append((d, amt))
    tax_total = sum((l.tax_amount for l in lines), D0)
    if subtotal:  # tax is charged on the discounted amount
        tax_total = q(tax_total * (subtotal - discount_total) / subtotal)
    total = subtotal - discount_total + tax_total
    return lines, subtotal, discount_total, tax_total, total, applied


def create_invoice(sub, period_start, today):
    """Creates the invoice for one billing period. Safe to call twice: the second call returns None."""
    if Invoice.objects.filter(subscription=sub, period_start=period_start).exists():
        return None
    lines, subtotal, disc, tax, total, applied = price_lines(sub, today)
    try:
        with transaction.atomic():
            inv = Invoice.objects.create(
                subscription=sub, customer=sub.customer, period_start=period_start, issue_date=today,
                due_date=today + timedelta(days=sub.net_days), subtotal=subtotal, discount_total=disc,
                tax_total=tax, total=total, discounts_applied=', '.join(d.name for d, _ in applied))
            InvoiceLine.objects.bulk_create([
                InvoiceLine(invoice=inv, description=l.product.name + (f' - {l.variant.value}' if l.variant else ''),
                            quantity=l.quantity, unit_price=l.unit_price, tax_name=l.tax.name if l.tax else '',
                            tax_amount=l.tax_amount, amount=l.amount) for l in lines])
            for d, _ in applied:
                Discount.objects.filter(pk=d.pk).update(times_used=F('times_used') + 1)
            return inv
    except IntegrityError:  # another run created it first
        return None


def run_billing(today=None):
    """Bills every active, unpaused subscription whose billing date has arrived. Returns (created, closed)."""
    today = today or date.today()
    created = closed = 0
    subs = Subscription.objects.filter(status='active', paused=False, next_billing_date__lte=today) \
        .select_related('plan', 'customer')
    for sub in subs:
        guard = 0
        while sub.next_billing_date and sub.next_billing_date <= today and guard < 60:
            guard += 1
            if sub.expiry_date and sub.next_billing_date > sub.expiry_date:
                break
            if create_invoice(sub, sub.next_billing_date, today):
                created += 1
            sub.next_billing_date = sub.plan.next_date(sub.next_billing_date)
        if sub.plan.auto_close and sub.expiry_date and sub.expiry_date < today:
            sub.status = 'closed'
            closed += 1
        sub.save(update_fields=['next_billing_date', 'status'])
    # subscriptions that have expired without anything due still auto-close
    n = Subscription.objects.filter(status='active', plan__auto_close=True, expiry_date__lt=today).update(status='closed')
    return created, closed + n


def advance(sub):
    """Moves a subscription one step forward in Draft > Quotation > Confirmed > Active."""
    nxt = sub.next_status
    if not nxt:
        return False
    if nxt == 'quotation':
        days = sub.template.validity_days if sub.template else 30
        sub.quote_valid_until = date.today() + timedelta(days=days)
    if nxt == 'active' and not sub.next_billing_date:
        sub.next_billing_date = sub.start_date
    sub.status = nxt
    sub.save()
    return True


def add_payment(invoice, method, amount, pay_date, note=''):
    with transaction.atomic():
        if invoice.status == 'draft':
            invoice.status = 'confirmed'
        Payment.objects.create(invoice=invoice, method=method, amount=amount, date=pay_date, note=note)
        if invoice.paid_amount >= invoice.total:
            invoice.status = 'paid'
        invoice.save()


def email_invoice(inv):
    send_mail(f'Invoice {inv.number} from Brightloop',
              f'Hello {inv.customer},\n\nInvoice {inv.number} for {inv.total} is due on {inv.due_date}.\n\nThank you,\nBrightloop',
              None, [inv.customer.email])
    inv.sent = True
    inv.save(update_fields=['sent'])
