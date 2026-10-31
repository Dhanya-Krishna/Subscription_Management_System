from django.contrib.auth import views as auth
from django.urls import path, reverse_lazy

from . import views as v

F = 'core/form.html'
urlpatterns = [
    path('', v.home, name='home'),
    path('login/', auth.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth.LogoutView.as_view(), name='logout'),
    path('signup/', v.signup, name='signup'),
    path('social/<str:provider>/', v.social_login, name='social_login'),
    path('staff/new/', v.add_staff, name='add_staff'),
    path('password-reset/', auth.PasswordResetView.as_view(
        template_name=F, email_template_name='core/reset_email.txt', subject_template_name='core/reset_subject.txt',
        success_url=reverse_lazy('password_reset_done'),
        extra_context={'title': 'Reset your password', 'button': 'Send reset link'}), name='password_reset'),
    path('password-reset/sent/', auth.PasswordResetDoneView.as_view(template_name='core/message.html',
         extra_context={'title': 'Check your email', 'text': 'If that address has an account, a reset link is on its way (in development it prints in the terminal).'}), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth.PasswordResetConfirmView.as_view(
        template_name=F, success_url=reverse_lazy('password_reset_complete'),
        extra_context={'title': 'Choose a new password', 'button': 'Save password'}), name='password_reset_confirm'),
    path('reset/done/', auth.PasswordResetCompleteView.as_view(template_name='core/message.html',
         extra_context={'title': 'Password changed', 'text': 'You can now log in with your new password.'}), name='password_reset_complete'),
    path('subscriptions/', v.subscription_list, name='subscription_list'),
    path('subscriptions/new/', v.subscription_new, name='subscription_new'),
    path('subscriptions/<int:pk>/', v.subscription_detail, name='subscription_detail'),
    path('subscriptions/<int:pk>/<str:action>/', v.subscription_action, name='subscription_action'),
    path('invoices/', v.invoice_list, name='invoice_list'),
    path('invoices/run/', v.run_billing, name='run_billing'),
    path('invoices/<int:pk>/', v.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/<str:action>/', v.invoice_action, name='invoice_action'),
    path('payments/', v.payment_list, name='payment_list'),
    path('portal/', v.portal, name='portal'),
    # Themed admin catalog (same UI as the rest of the app)
    path('manage/products/', v.catalog_products, name='catalog_products'),
    path('manage/products/new/', v.catalog_product_edit, name='catalog_product_new'),
    path('manage/products/<int:pk>/', v.catalog_product_edit, name='catalog_product_edit'),
    path('manage/plans/', v.catalog_plans, name='catalog_plans'),
    path('manage/plans/new/', v.catalog_plan_edit, name='catalog_plan_new'),
    path('manage/plans/<int:pk>/', v.catalog_plan_edit, name='catalog_plan_edit'),
    path('manage/taxes/', v.catalog_taxes, name='catalog_taxes'),
    path('manage/taxes/new/', v.catalog_tax_edit, name='catalog_tax_new'),
    path('manage/taxes/<int:pk>/', v.catalog_tax_edit, name='catalog_tax_edit'),
    path('manage/discounts/', v.catalog_discounts, name='catalog_discounts'),
    path('manage/discounts/new/', v.catalog_discount_edit, name='catalog_discount_new'),
    path('manage/discounts/<int:pk>/', v.catalog_discount_edit, name='catalog_discount_edit'),
    path('manage/templates/', v.catalog_templates, name='catalog_templates'),
    path('manage/templates/new/', v.catalog_template_edit, name='catalog_template_new'),
    path('manage/templates/<int:pk>/', v.catalog_template_edit, name='catalog_template_edit'),
]

