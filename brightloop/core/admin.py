from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import models as m


class VariantInline(admin.TabularInline):
    model = m.ProductVariant
    extra = 1


class TemplateLineInline(admin.TabularInline):
    model = m.QuotationTemplateLine
    extra = 2


@admin.register(m.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'type', 'sales_price', 'cost_price']
    inlines = [VariantInline]


@admin.register(m.QuotationTemplate)
class TemplateAdmin(admin.ModelAdmin):
    inlines = [TemplateLineInline]


@admin.register(m.User)
class BLUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Role', {'fields': ('role',)}),)
    list_display = ['email', 'role', 'is_active']


admin.site.register([m.Plan, m.Tax, m.Discount])
