from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import billing
from .forms import (
    DiscountForm, LineFormSet, PaymentForm, PlanForm, ProductForm, ProductVariantFormSet,
    QuotationTemplateForm, SignupForm, SubscriptionForm, TaxForm, TemplateLineFormSet,
)
from django.contrib.auth import get_user_model
from .models import D0, Discount, Invoice, Payment, Plan, Product, QuotationTemplate, Subscription, Tax

User = get_user_model()


def role_required(*roles):
    """Backend guard: hiding menu items is not enough, every view checks the role."""
    def deco(view):
        @wraps(view)
        @login_required
        def inner(request, *a, **kw):
            if request.user.role not in roles:
                return render(request, 'core/forbidden.html', status=403)
            return view(request, *a, **kw)
        return inner
    return deco


team = role_required('admin', 'staff')
admin_only = role_required('admin')


def page(request, qs, n=25):
    return Paginator(qs, n).get_page(request.GET.get('page'))


# ---------- accounts ----------
def signup(request):
    """Multi-step signup (Zoho-style): Step 1 email+password → Step 2 name → create account."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    step = 1
    data = {}
    errors = {}

    if request.method == 'POST':
        step = int(request.POST.get('step', 1))
        if request.POST.get('back'):
            # Go back to step 1, keep email
            data = {
                'email': request.POST.get('email', ''),
                'password': request.POST.get('password', ''),
                'confirm': request.POST.get('confirm', ''),
            }
            step = 1
        elif step == 1:
            email = (request.POST.get('email') or '').strip().lower()
            password = request.POST.get('password') or ''
            confirm = request.POST.get('confirm') or ''
            data = {'email': email, 'password': password, 'confirm': confirm}

            if not email:
                errors['email'] = 'Email is required.'
            elif User.objects.filter(email__iexact=email).exists():
                errors['email'] = 'An account with this email already exists.'
            if not password:
                errors['password'] = 'Password is required.'
            else:
                try:
                    validate_password(password)
                except DjangoValidationError as e:
                    errors['password'] = e.messages[0] if e.messages else 'Invalid password.'
            if password != confirm:
                errors['confirm'] = 'Passwords do not match.'

            if not errors:
                step = 2  # advance to name step
        else:
            # Step 2 – create account
            email = (request.POST.get('email') or '').strip().lower()
            password = request.POST.get('password') or ''
            confirm = request.POST.get('confirm') or ''
            first_name = (request.POST.get('first_name') or '').strip()
            last_name = (request.POST.get('last_name') or '').strip()
            data = {
                'email': email, 'password': password, 'confirm': confirm,
                'first_name': first_name, 'last_name': last_name,
            }
            if not first_name:
                errors['first_name'] = 'First name is required.'
            if not last_name:
                errors['last_name'] = 'Last name is required.'
            # Re-validate email uniqueness (in case of race)
            if User.objects.filter(email__iexact=email).exists():
                errors['email'] = 'An account with this email already exists.'
                step = 1

            if not errors:
                form = SignupForm({
                    'email': email, 'password': password, 'confirm': confirm,
                    'first_name': first_name, 'last_name': last_name,
                })
                if form.is_valid():
                    login(request, form.save(), backend='django.contrib.auth.backends.ModelBackend')
                    return redirect('home')
                # Fallback: map form errors
                for k, v in form.errors.items():
                    errors[k] = v[0] if v else 'Invalid'
                step = 1 if 'email' in errors or 'password' in errors else 2

    return render(request, 'core/signup.html', {
        'step': step, 'data': data, 'errors': errors,
    })


def social_login(request, provider):
    """Demo social login – signs in as the demo customer (no real OAuth)."""
    from django.contrib import messages
    allowed = {'google', 'microsoft', 'linkedin', 'facebook', 'x'}
    if provider not in allowed:
        messages.error(request, 'Unknown provider.')
        return redirect('login')
    user = User.objects.filter(role='customer', email='customer@brightloop.com').first()
    if not user:
        user = User.objects.filter(role='customer').first()
    if not user:
        messages.error(request, 'No demo customer account found. Run seed first.')
        return redirect('login')
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    messages.success(request, f'Signed in via {provider.title()} (demo mode).')
    return redirect('portal')



@admin_only
def add_staff(request):
    form = SignupForm(request.POST or None)
    if form.is_valid():
        u = form.save(role='staff')
        messages.success(request, f'Staff member {u.email} added.')
        return redirect('home')
    return render(request, 'core/form.html', {'form': form, 'title': 'Add a staff member', 'button': 'Add staff'})


def home(request):
    if not request.user.is_authenticated:
        return render(request, 'core/landing.html')
    if not request.user.is_team:
        return redirect('portal')
    return dashboard(request)


# ---------- dashboard ----------
@team
def dashboard(request):
    today = date.today()
    d_from, d_to = request.GET.get('from') or None, request.GET.get('to') or None
    plan = request.GET.get('plan') or None
    pays = Payment.objects.all()
    subs = Subscription.objects.all()
    if d_from:
        pays = pays.filter(date__gte=d_from)
    if d_to:
        pays = pays.filter(date__lte=d_to)
    if plan:
        pays = pays.filter(invoice__subscription__plan_id=plan)
        subs = subs.filter(plan_id=plan)
    open_inv = Invoice.objects.filter(status__in=['draft', 'confirmed'])
    if plan:
        open_inv = open_inv.filter(subscription__plan_id=plan)
    billed = open_inv.aggregate(s=Sum('total'))['s'] or D0
    received_on_open = Payment.objects.filter(invoice__in=open_inv).aggregate(s=Sum('amount'))['s'] or D0
    overdue = open_inv.filter(due_date__lt=today)
    monthly = pays.annotate(m=TruncMonth('date')).values('m').annotate(t=Sum('amount')).order_by('m')
    ctx = {
        'active_count': subs.filter(status='active').count(),
        'status_counts': {s: subs.filter(status=s).count() for s, _ in Subscription.STATUSES},
        'revenue': pays.aggregate(s=Sum('amount'))['s'] or D0,
        'payment_count': pays.count(),
        'outstanding': billed - received_on_open,
        'overdue_count': overdue.count(),
        'overdue': overdue.select_related('customer').order_by('due_date')[:10],
        'labels': [r['m'].strftime('%b %Y') for r in monthly],
        'values': [float(r['t']) for r in monthly],
        'plans': Plan.objects.all(), 'f': {'from': d_from or '', 'to': d_to or '', 'plan': plan or ''},
    }
    return render(request, 'core/dashboard.html', ctx)


# ---------- subscriptions ----------
@team
def subscription_list(request):
    qs = Subscription.objects.select_related('customer', 'plan').order_by('-id')
    status, s = request.GET.get('status', ''), request.GET.get('q', '')
    if status:
        qs = qs.filter(status=status)
    if s:
        qs = qs.filter(Q(number__icontains=s) | Q(customer__email__icontains=s) | Q(customer__last_name__icontains=s))
    return render(request, 'core/subscriptions.html', {'page': page(request, qs), 'status': status, 'q': s,
                                                       'statuses': Subscription.STATUSES})


@team
def subscription_new(request):
    initial, tpl = {}, None
    if request.GET.get('template'):
        tpl = get_object_or_404(QuotationTemplate, pk=request.GET['template'])
        initial = {'plan': tpl.plan, 'template': tpl}
    form = SubscriptionForm(request.POST or None, initial=initial)
    line_initial = [{'product': l.product, 'variant': l.variant, 'quantity': l.quantity} for l in tpl.lines.all()] if tpl else []
    formset = LineFormSet(request.POST or None, initial=line_initial, instance=Subscription())
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        lines = [f.cleaned_data for f in formset.forms if f.cleaned_data and not f.cleaned_data.get('DELETE')]
        if not lines:
            form.add_error(None, 'Add at least one product line.')
        elif sum(l['quantity'] for l in lines) < form.cleaned_data['plan'].min_quantity:
            form.add_error(None, f"This plan needs a minimum quantity of {form.cleaned_data['plan'].min_quantity}.")
        else:
            sub = form.save()
            formset.instance = sub
            for l in formset.save(commit=False):
                if not l.unit_price:
                    l.unit_price = l.product.sales_price + (l.variant.extra_price if l.variant else 0)
                l.save()
            messages.success(request, f'{sub.number} created as a draft.')
            return redirect('subscription_detail', pk=sub.pk)
    if request.method != 'POST' and not initial:
        formset.extra = 4
    return render(request, 'core/subscription_form.html', {'form': form, 'formset': formset,
                                                           'templates': QuotationTemplate.objects.all()})


@role_required('admin', 'staff', 'customer')
def subscription_detail(request, pk):
    sub = get_object_or_404(Subscription.objects.select_related('customer', 'plan'), pk=pk)
    if not request.user.is_team and sub.customer_id != request.user.id:
        return HttpResponseForbidden('Not your subscription.')
    return render(request, 'core/subscription_detail.html', {
        'sub': sub, 'lines': sub.lines.select_related('product', 'variant', 'tax'),
        'invoices': sub.invoices.all()[:20], 'steps': Subscription.STATUSES})


@require_POST
@role_required('admin', 'staff', 'customer')
def subscription_action(request, pk, action):
    sub = get_object_or_404(Subscription, pk=pk)
    is_owner = sub.customer_id == request.user.id
    if not request.user.is_team and not is_owner:
        return HttpResponseForbidden('Not your subscription.')

    # Customer: accept a quotation → Confirmed, then optionally activate
    if action == 'accept' and is_owner and sub.status == 'quotation':
        billing.advance(sub)  # quotation → confirmed
        # Auto-activate so recurring billing can start
        if sub.status == 'confirmed':
            billing.advance(sub)  # confirmed → active
        messages.success(request, f'You accepted the quotation. {sub.number} is now Active.')
    elif action == 'advance' and request.user.is_team:
        billing.advance(sub)
    elif action == 'close' and sub.plan.closable and sub.status != 'closed':
        # Customer or team can close; unpaid invoices remain due
        if request.user.is_team or is_owner:
            sub.status = 'closed'
            sub.save()
            messages.info(request, 'Subscription closed. Any unpaid invoices are still due.')
        else:
            messages.error(request, 'That action is not allowed for this subscription.')
    elif action == 'pause' and sub.plan.pausable and sub.status == 'active':
        if request.user.is_team or is_owner:
            sub.paused = not sub.paused
            sub.save(update_fields=['paused'])
            messages.success(request, 'Subscription paused.' if sub.paused else 'Subscription resumed.')
        else:
            messages.error(request, 'That action is not allowed for this subscription.')
    elif action == 'renew' and sub.plan.renewable and sub.status in ('active', 'closed'):
        if request.user.is_team or is_owner:
            base = max(sub.expiry_date or date.today(), date.today())
            # Extend term by one year (or equivalent) so renew has a clear effect
            sub.expiry_date = date(base.year + 1, base.month, min(base.day, 28))
            if sub.status == 'closed':
                sub.status = 'active'
                sub.next_billing_date = date.today()
            sub.paused = False
            sub.save(update_fields=['expiry_date', 'status', 'next_billing_date', 'paused'])
            messages.success(request, f'{sub.number} renewed through {sub.expiry_date}.')
        else:
            messages.error(request, 'That action is not allowed for this subscription.')
    else:
        messages.error(request, 'That action is not allowed for this subscription.')
    return redirect('subscription_detail', pk=pk)


# ---------- invoices ----------
@team
def invoice_list(request):
    qs = Invoice.objects.select_related('customer').order_by('-id')
    f = request.GET.get('filter', '')
    today = date.today()
    if f == 'overdue':
        qs = qs.filter(status__in=['draft', 'confirmed'], due_date__lt=today)
    elif f == 'outstanding':
        qs = qs.filter(status__in=['draft', 'confirmed'])
    elif f:
        qs = qs.filter(status=f)
    s = request.GET.get('q', '')
    if s:
        qs = qs.filter(Q(number__icontains=s) | Q(customer__email__icontains=s))
    return render(request, 'core/invoices.html', {'page': page(request, qs), 'f': f, 'q': s})


@role_required('admin', 'staff', 'customer')
def invoice_detail(request, pk):
    inv = get_object_or_404(Invoice.objects.select_related('customer', 'subscription'), pk=pk)
    if not request.user.is_team and inv.customer_id != request.user.id:
        return HttpResponseForbidden('Not your invoice.')
    return render(request, 'core/invoice_detail.html', {
        'inv': inv, 'lines': inv.lines.all(), 'payments': inv.payments.all(),
        'form': PaymentForm(initial={'amount': inv.balance, 'date': date.today()}),
        'print': 'print' in request.GET})


@require_POST
@role_required('admin', 'staff', 'customer')
def invoice_action(request, pk, action):
    inv = get_object_or_404(Invoice, pk=pk)
    is_owner = inv.customer_id == request.user.id
    if not request.user.is_team and not is_owner:
        return HttpResponseForbidden('Not your invoice.')

    if action == 'confirm' and request.user.is_team and inv.status == 'draft':
        inv.status = 'confirmed'
        inv.save()
    elif action == 'cancel' and request.user.is_team and inv.status in ('draft', 'confirmed') and not inv.payments.exists():
        inv.status = 'cancelled'
        inv.save()
    elif action == 'send' and request.user.is_team and inv.status != 'cancelled':
        billing.email_invoice(inv)
        messages.success(request, f'Invoice emailed to {inv.customer.email}.')
    elif action == 'pay' and inv.status in ('draft', 'confirmed') and inv.balance > 0:
        # Team or customer (self-service payment) can record a payment
        form = PaymentForm(request.POST)
        if form.is_valid():
            c = form.cleaned_data
            amount = min(c['amount'], inv.balance)
            note = c['note'] or ('Customer portal payment' if is_owner and not request.user.is_team else c['note'])
            billing.add_payment(inv, c['method'], amount, c['date'], note)
            messages.success(request, f'Payment of ₹{amount} recorded. Thank you!')
        else:
            messages.error(request, 'Check the payment details.')
    else:
        messages.error(request, 'That action is not allowed for this invoice.')
    return redirect('invoice_detail', pk=pk)


@require_POST
@team
def run_billing(request):
    created, closed = billing.run_billing()
    messages.success(request, f'Billing run finished: {created} invoice(s) created, {closed} subscription(s) auto-closed.')
    return redirect('invoice_list')


@team
def payment_list(request):
    qs = Payment.objects.select_related('invoice', 'invoice__customer').order_by('-date', '-id')
    return render(request, 'core/payments.html', {'page': page(request, qs)})


# ---------- customer portal ----------
@role_required('customer')
def portal(request):
    from collections import defaultdict
    import json

    user = request.user
    # Filters
    f_plan = request.GET.get('plan') or ''
    f_status = request.GET.get('status') or ''
    f_from = request.GET.get('from') or ''
    f_to = request.GET.get('to') or ''
    show = request.GET.get('show')  # 'due' | 'paid' | None

    subs_qs = user.subscriptions.select_related('plan').prefetch_related('lines__product')
    if f_plan:
        subs_qs = subs_qs.filter(plan_id=f_plan)
    if f_status:
        subs_qs = subs_qs.filter(status=f_status)
    subs = list(subs_qs)

    inv_qs = user.invoices.exclude(status='cancelled').select_related('subscription__plan').prefetch_related('payments')
    if f_plan:
        inv_qs = inv_qs.filter(subscription__plan_id=f_plan)
    if f_from:
        inv_qs = inv_qs.filter(issue_date__gte=f_from)
    if f_to:
        inv_qs = inv_qs.filter(issue_date__lte=f_to)
    invoices = list(inv_qs)

    open_invs = [i for i in invoices if i.status in ('draft', 'confirmed')]
    amount_due = sum((i.balance for i in open_invs), D0)

    all_payments = Payment.objects.filter(invoice__customer=user)
    if f_plan:
        all_payments = all_payments.filter(invoice__subscription__plan_id=f_plan)
    if f_from:
        all_payments = all_payments.filter(date__gte=f_from)
    if f_to:
        all_payments = all_payments.filter(date__lte=f_to)
    total_paid = all_payments.aggregate(s=Sum('amount'))['s'] or D0
    months = list(all_payments.dates('date', 'month'))
    avg_monthly = (total_paid / len(months)) if months else D0

    # Per-plan spending (bar chart) – prioritize plans with amount due
    plan_paid = defaultdict(lambda: D0)
    plan_due = defaultdict(lambda: D0)
    plan_name = {}
    for inv in invoices:
        if not inv.subscription_id:
            continue
        pid = inv.subscription.plan_id
        plan_name[pid] = inv.subscription.plan.name
        if inv.paid_amount:
            plan_paid[pid] += inv.paid_amount
        if inv.status in ('draft', 'confirmed'):
            plan_due[pid] += inv.balance

    chart_items = []
    for pid, name in plan_name.items():
        chart_items.append({
            'id': pid, 'name': name,
            'paid': float(plan_paid[pid]),
            'due': float(plan_due[pid]),
            'has_due': plan_due[pid] > 0,
        })
    chart_items.sort(key=lambda x: (not x['has_due'], -x['due'], -x['paid']))

    # Pie chart: paid distribution by plan
    pie_items = [{'name': c['name'], 'value': c['paid']} for c in chart_items if c['paid'] > 0]

    # Line chart: monthly payments
    monthly = (
        all_payments.annotate(m=TruncMonth('date'))
        .values('m').annotate(t=Sum('amount')).order_by('m')
    )
    line_labels = [r['m'].strftime('%b %Y') for r in monthly]
    line_values = [float(r['t']) for r in monthly]

    # Highlights
    active_subs = [s for s in user.subscriptions.select_related('plan') if s.status == 'active']
    most_expensive = max(active_subs, key=lambda s: s.plan.price, default=None)
    cheapest = min(active_subs, key=lambda s: s.plan.price, default=None)

    due_list = sorted(open_invs, key=lambda i: i.balance, reverse=True)
    paid_list = sorted([i for i in invoices if i.paid_amount > 0], key=lambda i: i.paid_amount, reverse=True)

    # Per-subscription cards: paid, due, dates — sorted by highest due first
    sub_paid = defaultdict(lambda: D0)
    sub_due = defaultdict(lambda: D0)
    for inv in invoices:
        if not inv.subscription_id:
            continue
        sid = inv.subscription_id
        if inv.paid_amount:
            sub_paid[sid] += inv.paid_amount
        if inv.status in ('draft', 'confirmed'):
            sub_due[sid] += inv.balance

    sub_cards = []
    for s in subs:
        paid = float(sub_paid[s.id])
        due = float(sub_due[s.id])
        sub_cards.append({
            'sub': s,
            'paid': paid,
            'due': due,
            'has_due': due > 0,
            'start': s.start_date,
            'end': s.expiry_date,
            'next_billing': s.next_billing_date,
        })
    sub_cards.sort(key=lambda x: (-x['due'], -x['paid']))

    # Plan list for filter dropdown
    customer_plans = Plan.objects.filter(subscription__customer=user).distinct().order_by('name')

    # Catalog: plans available to buy / upgrade (currently offered)
    today = date.today()
    owned_plan_ids = set(
        user.subscriptions.filter(status__in=('active', 'confirmed', 'quotation', 'draft'))
        .values_list('plan_id', flat=True)
    )
    catalog_qs = Plan.objects.filter(start_date__lte=today).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).order_by('price')
    catalog_plans = []
    max_owned_price = max((s.plan.price for s in active_subs), default=D0)
    for p in catalog_qs:
        catalog_plans.append({
            'plan': p,
            'owned': p.id in owned_plan_ids,
            'is_upgrade': p.price > max_owned_price and p.id not in owned_plan_ids,
            'is_downgrade': p.price < max_owned_price and p.id not in owned_plan_ids,
        })

    # Products in catalog with linked plans (via quotation templates)
    catalog_products = list(Product.objects.prefetch_related('variants').order_by('name'))
    from .models import QuotationTemplate
    templates = list(
        QuotationTemplate.objects.select_related('plan').prefetch_related('lines__product', 'lines__variant')
    )
    # product_id -> list of {plan, template, qty, variant}
    product_offers = {prod.id: [] for prod in catalog_products}
    for t in templates:
        for line in t.lines.all():
            product_offers.setdefault(line.product_id, []).append({
                'plan': t.plan,
                'template': t,
                'quantity': line.quantity,
                'variant': line.variant,
                'owned': t.plan_id in owned_plan_ids,
                'is_upgrade': t.plan.price > max_owned_price and t.plan_id not in owned_plan_ids,
            })
    # Also attach any plan not linked to a template as a generic offer under each product? No — keep template-based.
    product_catalog = []
    for prod in catalog_products:
        offers = product_offers.get(prod.id, [])
        # Deduplicate by plan id
        seen = set()
        unique_offers = []
        for o in offers:
            if o['plan'].id in seen:
                continue
            seen.add(o['plan'].id)
            unique_offers.append(o)
        product_catalog.append({'product': prod, 'offers': unique_offers, 'variants': list(prod.variants.all())})

    # Extra stats for richer charts / dashboard
    overdue_list = [i for i in open_invs if getattr(i, 'is_overdue', False)]
    overdue_count = len(overdue_list)
    overdue_amount = sum((i.balance for i in overdue_list), D0)
    closed_count = user.subscriptions.filter(status='closed').count()
    total_subs = user.subscriptions.count()

    # Payment method breakdown
    method_rows = (
        all_payments.values('method').annotate(t=Sum('amount')).order_by('-t')
    )
    method_labels = []
    method_values = []
    method_map = dict(Payment.METHODS) if hasattr(Payment, 'METHODS') else {}
    for r in method_rows:
        method_labels.append(method_map.get(r['method'], r['method'] or 'Other'))
        method_values.append(float(r['t']))

    # Month-over-month growth from line chart
    growth_pct = None
    if len(line_values) >= 2 and line_values[-2] > 0:
        growth_pct = round((line_values[-1] - line_values[-2]) / line_values[-2] * 100, 1)
    elif len(line_values) >= 2 and line_values[-1] > 0:
        growth_pct = 100.0

    # Invoice status counts for doughnut
    status_counts = defaultdict(int)
    for inv in invoices:
        status_counts[inv.status] += 1
    status_pie = [{'name': k.title(), 'value': v} for k, v in status_counts.items()]

    return render(request, 'core/portal.html', {
        'subs': subs,
        'sub_cards': sub_cards,
        'sub_cards_json': json.dumps([
            {'id': c['sub'].id, 'paid': c['paid'], 'due': c['due'], 'name': c['sub'].plan.name}
            for c in sub_cards
        ]),
        'invoices': invoices[:30],
        'active_count': len(active_subs),
        'amount_due': amount_due,
        'paid_till_date': total_paid,
        'avg_monthly': avg_monthly,
        'chart_items': chart_items,
        'chart_json': json.dumps(chart_items),
        'pie_json': json.dumps(pie_items),
        'line_labels': json.dumps(line_labels),
        'line_values': json.dumps(line_values),
        'most_expensive': most_expensive,
        'cheapest': cheapest,
        'due_list': due_list,
        'paid_list': paid_list,
        'show': show,
        'plans': customer_plans,
        'f': {'plan': f_plan, 'status': f_status, 'from': f_from, 'to': f_to},
        # catalog / upgrades
        'catalog_plans': catalog_plans,
        'catalog_products': catalog_products,
        'product_catalog': product_catalog,
        'owned_plan_ids': list(owned_plan_ids),
        # richer stats
        'overdue_count': overdue_count,
        'overdue_amount': overdue_amount,
        'closed_count': closed_count,
        'total_subs': total_subs,
        'method_labels': json.dumps(method_labels),
        'method_values': json.dumps(method_values),
        'growth_pct': growth_pct,
        'status_pie_json': json.dumps(status_pie),
        'open_invoice_count': len(open_invs),
    })


# ---------- admin catalog (themed in-app, not Django admin) ----------
@admin_only
def catalog_products(request):
    qs = Product.objects.prefetch_related('variants').order_by('name')
    rows = []
    for p in qs:
        variants = ', '.join(f'{v.value} (+₹{v.extra_price})' for v in p.variants.all()) or '—'
        rows.append({
            'cells': [p.name, p.type, f'₹{p.sales_price}', f'₹{p.cost_price}', variants],
            'edit_url': f'/manage/products/{p.pk}/',
        })
    return render(request, 'core/catalog_list.html', {
        'title': 'Products',
        'help_text': 'Products and optional brand/variant price add-ons used on subscriptions and invoices.',
        'headers': ['Name', 'Type', 'Sales price', 'Cost', 'Variants'],
        'rows': rows,
        'create_url': '/manage/products/new/',
        'create_label': 'Add product',
    })


@admin_only
def catalog_product_edit(request, pk=None):
    obj = get_object_or_404(Product, pk=pk) if pk else None
    form = ProductForm(request.POST or None, instance=obj)
    formset = ProductVariantFormSet(request.POST or None, instance=obj or Product())
    if request.method == 'POST' and form.is_valid():
        product = form.save()
        formset = ProductVariantFormSet(request.POST, instance=product)
        if formset.is_valid():
            formset.save()
            messages.success(request, f'Product “{product.name}” saved.')
            return redirect('catalog_products')
        messages.error(request, 'Please fix the variant rows.')
    elif request.method == 'GET' and obj:
        formset = ProductVariantFormSet(instance=obj)
    elif request.method == 'GET':
        formset = ProductVariantFormSet(instance=Product())
    return render(request, 'core/catalog_form.html', {
        'title': 'Edit product' if obj else 'New product',
        'form': form,
        'formset': formset,
        'formset_title': 'Variants (optional)',
        'button': 'Save product',
        'back_url': '/manage/products/',
    })


@admin_only
def catalog_plans(request):
    qs = Plan.objects.order_by('name')
    rows = [{
        'cells': [
            p.name, f'₹{p.price}', p.get_billing_period_display(),
            p.min_quantity, p.start_date, p.end_date or '—',
            'Yes' if p.renewable else 'No',
        ],
        'edit_url': f'/manage/plans/{p.pk}/',
    } for p in qs]
    return render(request, 'core/catalog_list.html', {
        'title': 'Plans',
        'help_text': 'Billing plans: price, period, and whether subscriptions can be paused, closed early, or renewed.',
        'headers': ['Name', 'Price', 'Period', 'Min qty', 'Start', 'End', 'Renewable'],
        'rows': rows,
        'create_url': '/manage/plans/new/',
        'create_label': 'Add plan',
    })


@admin_only
def catalog_plan_edit(request, pk=None):
    obj = get_object_or_404(Plan, pk=pk) if pk else None
    form = PlanForm(request.POST or None, instance=obj)
    if form.is_valid():
        plan = form.save()
        messages.success(request, f'Plan “{plan.name}” saved.')
        return redirect('catalog_plans')
    return render(request, 'core/catalog_form.html', {
        'title': 'Edit plan' if obj else 'New plan',
        'form': form,
        'button': 'Save plan',
        'back_url': '/manage/plans/',
    })


@admin_only
def catalog_taxes(request):
    qs = Tax.objects.order_by('name')
    rows = [{
        'cells': [t.name, f'{t.percentage}%'],
        'edit_url': f'/manage/taxes/{t.pk}/',
    } for t in qs]
    return render(request, 'core/catalog_list.html', {
        'title': 'Taxes',
        'help_text': 'Tax rules applied automatically when invoices are generated.',
        'headers': ['Name', 'Rate'],
        'rows': rows,
        'create_url': '/manage/taxes/new/',
        'create_label': 'Add tax',
    })


@admin_only
def catalog_tax_edit(request, pk=None):
    obj = get_object_or_404(Tax, pk=pk) if pk else None
    form = TaxForm(request.POST or None, instance=obj)
    if form.is_valid():
        tax = form.save()
        messages.success(request, f'Tax “{tax.name}” saved.')
        return redirect('catalog_taxes')
    return render(request, 'core/catalog_form.html', {
        'title': 'Edit tax' if obj else 'New tax',
        'form': form,
        'button': 'Save tax',
        'back_url': '/manage/taxes/',
    })


@admin_only
def catalog_discounts(request):
    qs = Discount.objects.select_related('product').order_by('name')
    rows = [{
        'cells': [
            d.name, d.get_type_display(), d.value,
            d.product.name if d.product_id else 'Whole subscription',
            d.start_date, d.end_date or '—',
            d.usage_limit if d.usage_limit is not None else 'Unlimited',
        ],
        'edit_url': f'/manage/discounts/{d.pk}/',
    } for d in qs]
    return render(request, 'core/catalog_list.html', {
        'title': 'Discounts',
        'help_text': 'Fixed or percentage discounts with optional product, quantity, and date limits.',
        'headers': ['Name', 'Type', 'Value', 'Applies to', 'Start', 'End', 'Usage limit'],
        'rows': rows,
        'create_url': '/manage/discounts/new/',
        'create_label': 'Add discount',
    })


@admin_only
def catalog_discount_edit(request, pk=None):
    obj = get_object_or_404(Discount, pk=pk) if pk else None
    form = DiscountForm(request.POST or None, instance=obj)
    if form.is_valid():
        disc = form.save()
        messages.success(request, f'Discount “{disc.name}” saved.')
        return redirect('catalog_discounts')
    return render(request, 'core/catalog_form.html', {
        'title': 'Edit discount' if obj else 'New discount',
        'form': form,
        'button': 'Save discount',
        'back_url': '/manage/discounts/',
    })


@admin_only
def catalog_templates(request):
    qs = QuotationTemplate.objects.select_related('plan').prefetch_related('lines').order_by('name')
    rows = [{
        'cells': [
            t.name, t.plan.name, t.validity_days,
            t.lines.count(),
        ],
        'edit_url': f'/manage/templates/{t.pk}/',
    } for t in qs]
    return render(request, 'core/catalog_list.html', {
        'title': 'Quotation templates',
        'help_text': 'Reusable quote packages: a plan plus product lines staff can load when creating a subscription.',
        'headers': ['Name', 'Plan', 'Validity (days)', 'Lines'],
        'rows': rows,
        'create_url': '/manage/templates/new/',
        'create_label': 'Add template',
    })


@admin_only
def catalog_template_edit(request, pk=None):
    obj = get_object_or_404(QuotationTemplate, pk=pk) if pk else None
    form = QuotationTemplateForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        template = form.save()
        formset = TemplateLineFormSet(request.POST, instance=template)
        if formset.is_valid():
            formset.save()
            messages.success(request, f'Template “{template.name}” saved.')
            return redirect('catalog_templates')
        messages.error(request, 'Please fix the product lines.')
    else:
        formset = TemplateLineFormSet(instance=obj or QuotationTemplate())
        if request.method == 'POST':
            formset = TemplateLineFormSet(request.POST, instance=obj or QuotationTemplate())
    return render(request, 'core/catalog_form.html', {
        'title': 'Edit template' if obj else 'New quotation template',
        'form': form,
        'formset': formset,
        'formset_title': 'Product lines',
        'button': 'Save template',
        'back_url': '/manage/templates/',
    })
