from django.contrib import admin

from .models import AIInteraction


@admin.register(AIInteraction)
class AIInteractionAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "purpose",
        "provider",
        "model",
        "outcome",
        "attempts",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
    )
    list_filter = ("purpose", "provider", "outcome")
    readonly_fields = [f.name for f in AIInteraction._meta.fields]
