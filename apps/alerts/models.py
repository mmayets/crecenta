from django.db import models

from apps.workspaces.models import WorkspaceScopedModel


class AlertRule(WorkspaceScopedModel):
    """Configuración de una regla en un espacio (si no existe, se usan los valores por defecto)."""

    code = models.CharField("regla", max_length=40)
    enabled = models.BooleanField("activa", default=True)
    params = models.JSONField("parámetros", default=dict, blank=True)

    class Meta:
        verbose_name = "regla de alerta"
        verbose_name_plural = "reglas de alerta"
        constraints = [
            models.UniqueConstraint(fields=["workspace", "code"], name="regla_unica"),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({'activa' if self.enabled else 'inactiva'})"


class Alert(WorkspaceScopedModel):
    class Severity(models.TextChoices):
        INFO = "info", "Informativa"
        MEDIA = "media", "Atención"
        ALTA = "alta", "Urgente"

    class Status(models.TextChoices):
        NUEVA = "nueva", "Nueva"
        VISTA = "vista", "Vista"
        RESUELTA = "resuelta", "Resuelta"
        DESCARTADA = "descartada", "Descartada"

    OPEN = (Status.NUEVA, Status.VISTA)

    code = models.CharField("regla", max_length=40)
    severity = models.CharField("gravedad", max_length=8, choices=Severity.choices)
    title = models.CharField("título", max_length=140)
    message = models.TextField("explicación")
    data_used = models.JSONField("datos usados", default=dict)
    is_projection = models.BooleanField("es proyección", default=False)
    status = models.CharField("estado", max_length=12, choices=Status.choices, default=Status.NUEVA)
    suggested_action = models.JSONField("acción sugerida", null=True, blank=True)
    dedupe_key = models.CharField(max_length=200)
    period_start = models.DateField("inicio del período")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "alerta"
        verbose_name_plural = "alertas"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "dedupe_key"], name="alerta_unica"),
        ]
        indexes = [models.Index(fields=["workspace", "status"], name="alerta_ws_estado")]

    def __str__(self) -> str:
        return self.title

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN
