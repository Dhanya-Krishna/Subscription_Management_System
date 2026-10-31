from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.forms import inlineformset_factory

from .models import (
    Discount, Payment, Plan, Product, ProductVariant, QuotationTemplate,
    QuotationTemplateLine, Subscription, SubscriptionLine, Tax,
)

User = get_user_model()


class SignupForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    confirm = forms.CharField(widget=forms.PasswordInput, label='Confirm password')

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        data = super().clean()
        if data.get('password'):
            validate_password(data['password'])
            if data['password'] != data.get('confirm'):
                self.add_error('confirm', 'Passwords do not match.')
        return data

    def save(self, role='customer'):
        u = super().save(commit=False)
        u.username, u.role = u.email, role
        u.is_staff = False
        u.set_password(self.cleaned_data['password'])
        u.save()
        return u


class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ['customer', 'plan', 'template', 'start_date', 'expiry_date', 'payment_terms']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'expiry_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['customer'].queryset = User.objects.filter(role='customer')


LineFormSet = inlineformset_factory(
    Subscription, SubscriptionLine,
    fields=['product', 'variant', 'quantity', 'unit_price', 'tax'],
    extra=4, can_delete=False,
)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['method', 'amount', 'date', 'note']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'type', 'sales_price', 'cost_price', 'notes']


class ProductVariantForm(forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ['attribute', 'value', 'extra_price']


ProductVariantFormSet = inlineformset_factory(
    Product, ProductVariant, form=ProductVariantForm, extra=2, can_delete=True,
)


class PlanForm(forms.ModelForm):
    class Meta:
        model = Plan
        fields = [
            'name', 'price', 'billing_period', 'min_quantity',
            'start_date', 'end_date', 'auto_close', 'closable', 'pausable', 'renewable',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'end_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }


class TaxForm(forms.ModelForm):
    class Meta:
        model = Tax
        fields = ['name', 'percentage']


class DiscountForm(forms.ModelForm):
    class Meta:
        model = Discount
        fields = [
            'name', 'type', 'value', 'product', 'min_purchase', 'min_quantity',
            'start_date', 'end_date', 'usage_limit',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'end_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }


class QuotationTemplateForm(forms.ModelForm):
    class Meta:
        model = QuotationTemplate
        fields = ['name', 'plan', 'validity_days']


class QuotationTemplateLineForm(forms.ModelForm):
    class Meta:
        model = QuotationTemplateLine
        fields = ['product', 'variant', 'quantity']


TemplateLineFormSet = inlineformset_factory(
    QuotationTemplate, QuotationTemplateLine, form=QuotationTemplateLineForm, extra=3, can_delete=True,
)
