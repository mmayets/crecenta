from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Solo lectura: la auditoría no se edita ni se borra a mano."""

    list_display = ("created_at", "user_email", "kind", "action", "status", "ip")
    list_filter = ("kind",)
    search_fields = ("user_email", "action", "description", "path")
    date_hierarchy = "created_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
