from django.contrib import admin

from .models import Alert, AlertRule


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "code",
        "severity",
        "status",
        "is_projection",
        "workspace",
        "updated_at",
    )
    list_filter = ("code", "severity", "status")


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ("code", "enabled", "workspace")
