from django.contrib import admin

from .models import Account, Category, Transaction


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "currency", "opening_balance", "workspace")
    list_filter = ("type",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "group", "is_system", "workspace")
    list_filter = ("group", "is_system")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "kind", "direction", "amount", "category", "account", "status")
    list_filter = ("kind", "status", "source")
    raw_id_fields = ("account", "category", "transfer_pair")
