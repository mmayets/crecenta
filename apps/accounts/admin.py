from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "is_active", "ai_consent", "date_joined")
    search_fields = ("email", "first_name")
    readonly_fields = ("date_joined", "last_login", "ai_consent_at")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Perfil", {"fields": ("first_name", "ai_consent", "ai_consent_at")}),
        ("Permisos", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Fechas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
