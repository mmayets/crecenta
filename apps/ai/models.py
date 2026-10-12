from django.conf import settings
from django.db import models

from apps.core.models import UUIDModel
from apps.workspaces.models import Workspace


class AIInteraction(UUIDModel):
    """Registro de uso de IA (consumo, latencia y validez). No guarda prompts ni respuestas salvo
    con AI_DEBUG_LOG=True."""

    class Outcome(models.TextChoices):
        OK = "ok", "Válida al primer intento"
        RETRY_OK = "reintento_ok", "Válida tras reintento"
        FALLBACK = "fallback", "Se usó la respuesta por reglas"
        ERROR = "error", "Falló sin respaldo"
        NO_CONSENT = "sin_consentimiento", "Sin consentimiento"
        RATE_LIMITED = "limite", "Límite de uso alcanzado"

    workspace = models.ForeignKey(
        Workspace, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    purpose = models.CharField("propósito", max_length=40)
    prompt_version = models.CharField("versión del prompt", max_length=40, blank=True)
    provider = models.CharField("proveedor", max_length=20)
    model = models.CharField("modelo", max_length=80, blank=True)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField("intentos", default=0)
    schema_valid = models.BooleanField("respuesta válida", default=False)
    outcome = models.CharField("resultado", max_length=20, choices=Outcome.choices)
    errors = models.JSONField("errores de validación", default=list, blank=True)
    debug_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "uso de IA"
        verbose_name_plural = "usos de IA"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.purpose} · {self.provider} · {self.outcome}"
