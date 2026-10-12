from django.contrib import admin

from .models import Receipt


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "content_type", "size", "workspace", "created_at")
    list_filter = ("status", "content_type")
    readonly_fields = ("sha256", "extracted", "field_confidence")
