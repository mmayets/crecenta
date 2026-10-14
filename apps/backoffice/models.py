from django.conf import settings
from django.db import models

from apps.core.models import UUIDModel


class AuditEvent(UUIDModel):
    """Registro de auditoría: quién hizo qué, cuándo, dónde y con qué resultado.

    Nunca guarda el contenido de los formularios (montos, contraseñas): solo la acción, la ruta y
    el resultado. No tiene llave foránea al espacio para que el registro sobreviva aunque el
    espacio se elimine.
    """

    class Kind(models.TextChoices):
        ACCION = "accion", "Acción"
        VISITA = "visita", "Visita"
        ACCESO = "acceso", "Acceso"
        ADMIN = "admin", "Administración"

    created_at = models.DateTimeField("fecha", auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuario",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    user_email = models.CharField("correo", max_length=254, blank=True)
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, db_index=True)
    action = models.CharField("acción", max_length=80, db_index=True)
    description = models.CharField("descripción", max_length=200)
    method = models.CharField("método", max_length=8, blank=True)
    path = models.CharField("ruta", max_length=300, blank=True)
    status = models.PositiveSmallIntegerField("resultado HTTP", null=True, blank=True)
    workspace_id = models.UUIDField("espacio", null=True, blank=True, db_index=True)
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("navegador", max_length=200, blank=True)
    duration_ms = models.PositiveIntegerField("duración (ms)", null=True, blank=True)
    data = models.JSONField("detalle", default=dict, blank=True)

    class Meta:
        verbose_name = "evento de auditoría"
        verbose_name_plural = "auditoría"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "created_at"], name="audit_usuario_fecha")]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} · {self.user_email or 'anónimo'} · {self.action}"

    @property
    def failed(self) -> bool:
        return bool(self.status and self.status >= 400)
