from django.db import models

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
