from django.contrib import admin

from .models import (
    BusinessGoal,
    BusinessProfile,
    CostComponent,
    Customer,
    OperatingExpense,
    Payable,
    Product,
    Receivable,
    Sale,
    SaleLine,
    Supplier,
)

admin.site.register(BusinessProfile)
admin.site.register(BusinessGoal)
admin.site.register(Customer)
admin.site.register(Supplier)


class CostComponentInline(admin.TabularInline):
    model = CostComponent
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "unit_cost", "is_active", "workspace")
    inlines = [CostComponentInline]


@admin.register(OperatingExpense)
class OperatingExpenseAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "frequency", "due_day", "workspace")


class SaleLineInline(admin.TabularInline):
    model = SaleLine
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("date", "payment", "total", "workspace")
    inlines = [SaleLineInline]


@admin.register(Receivable)
class ReceivableAdmin(admin.ModelAdmin):
    list_display = ("concept", "amount", "paid", "status", "due_date", "workspace")


@admin.register(Payable)
class PayableAdmin(admin.ModelAdmin):
    list_display = ("concept", "amount", "paid", "status", "due_date", "workspace")
