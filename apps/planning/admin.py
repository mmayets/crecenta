from django.contrib import admin

from .models import BudgetLine, BudgetPeriod, PlanVersion


@admin.register(PlanVersion)
class PlanVersionAdmin(admin.ModelAdmin):
    list_display = (
        "workspace",
        "period_start",
        "status",
        "plan_status",
        "narrative_source",
        "created_at",
    )
    list_filter = ("status", "plan_status", "narrative_source")


class BudgetLineInline(admin.TabularInline):
    model = BudgetLine
    extra = 0


@admin.register(BudgetPeriod)
class BudgetPeriodAdmin(admin.ModelAdmin):
    list_display = ("workspace", "start", "end", "is_active")
    inlines = [BudgetLineInline]
