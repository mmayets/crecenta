from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.workspaces.models import Workspace


class OnboardingState(models.Model):
    """Progreso del onboarding de un espacio: se guarda paso a paso para poder salir y volver."""

    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name="onboarding")
    answered_steps = models.JSONField("pasos respondidos", default=list, blank=True)
    skipped_steps = models.JSONField("pasos omitidos", default=list, blank=True)
    last_step = models.CharField("último paso", max_length=20, blank=True)
    # Extracción del modo conversacional pendiente de confirmar (no es dato de dominio todavía).
    pending_extraction = models.JSONField(null=True, blank=True)
    finished_at = models.DateTimeField("terminado", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "progreso de bienvenida"
        verbose_name_plural = "progresos de bienvenida"

    def __str__(self) -> str:
        return f"Bienvenida de {self.workspace}"

    def mark(self, step: str, *, skipped: bool = False) -> None:
        target, other = (
            (self.skipped_steps, self.answered_steps)
            if skipped
            else (self.answered_steps, self.skipped_steps)
        )
        if step not in target:
            target.append(step)
        if step in other:
            other.remove(step)
        self.last_step = step


class AssistantSession(TimeStampedModel):
    """Conversación con el asistente que guía la creación de espacios.

    Guarda el borrador y los mensajes para poder salir y volver. No es dato de dominio: los
    espacios se crean solo cuando la persona pulsa «Crear» y cada bloque de datos pasa por la
    pantalla de confirmación del onboarding.
    """

    class Stage(models.TextChoices):
        CHAT = "chat", "Reuniendo datos del espacio"
        SUMMARY = "resumen", "Esperando confirmación"
        FILLING = "llenado", "Llenando los espacios creados"
        DONE = "fin", "Terminada"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_sessions"
    )
    stage = models.CharField("etapa", max_length=10, choices=Stage.choices, default=Stage.CHAT)
    # {"uso": …, "nombre_negocio": …, "moneda": …, "moneda_negocio": …}
    draft = models.JSONField("borrador", default=dict, blank=True)
    # [{"rol": "asistente" | "usuario", "texto": …, "enlaces": [{"texto": …, "url": …}]}]
    messages = models.JSONField("mensajes", default=list, blank=True)
    # Ids de los espacios creados que faltan por llenar, en orden.
    queue = models.JSONField("espacios por llenar", default=list, blank=True)
    created_ids = models.JSONField("espacios creados", default=list, blank=True)
    turns = models.PositiveSmallIntegerField("turnos", default=0)

    class Meta:
        verbose_name = "sesión del asistente"
        verbose_name_plural = "sesiones del asistente"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Asistente de {self.user} ({self.stage})"

    def say(self, text: str, links: list[dict[str, str]] | None = None) -> None:
        self.messages.append({"rol": "asistente", "texto": text, "enlaces": links or []})

    def hear(self, text: str) -> None:
        self.messages.append({"rol": "usuario", "texto": text, "enlaces": []})
