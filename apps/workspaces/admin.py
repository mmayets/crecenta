from django.contrib import admin

from .models import Membership, Workspace, WorkspaceTransfer


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "currency", "owner", "created_at")
    list_filter = ("kind", "currency")
    search_fields = ("name", "owner__email")
    inlines = [MembershipInline]


@admin.register(WorkspaceTransfer)
class WorkspaceTransferAdmin(admin.ModelAdmin):
    list_display = ("date", "kind", "amount", "from_workspace", "to_workspace")
