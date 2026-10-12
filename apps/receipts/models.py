import uuid

from django.conf import settings
from django.db import models

from apps.workspaces.models import WorkspaceScopedModel

EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "application/pdf": "pdf",
}


def receipt_path(instance: "Receipt", filename: str) -> str:
    """Ruta no adivinable y sin el nombre original del archivo."""
    extension = EXTENSIONS.get(instance.content_type, "bin")
    return f"comprobantes/{instance.workspace_id}/{uuid.uuid4().hex}.{extension}"


class Receipt(WorkspaceScopedModel):
    class Status(models.TextChoices):
        PROCESANDO = "procesando", "Leyendo comprobante"
        PARA_REVISAR = "para_revisar", "Para revisar"
        CONFIRMADO = "confirmado", "Confirmado"
        DUPLICADO = "duplicado_sospechoso", "Posible duplicado"
        ERROR = "error", "No se pudo leer"

    REVIEWABLE = (Status.PARA_REVISAR, Status.DUPLICADO, Status.ERROR)

    file = models.FileField("archivo", upload_to=receipt_path)
    original_name = models.CharField("nombre original", max_length=200, blank=True)
    content_type = models.CharField("tipo", max_length=40)
    size = models.PositiveIntegerField("tamaño (bytes)")
    sha256 = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        "estado", max_length=22, choices=Status.choices, default=Status.PROCESANDO
    )
    extracted = models.JSONField("datos leídos", default=dict, blank=True)
    field_confidence = models.JSONField("confianza por campo", default=dict, blank=True)
    error_message = models.CharField("motivo", max_length=200, blank=True)
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    duplicate_tx = models.ForeignKey(
        "ledger.Transaction", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "comprobante"
        verbose_name_plural = "comprobantes"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.extracted.get("comercio") or self.original_name or "Comprobante"

    @property
    def is_reviewable(self) -> bool:
        return self.status in self.REVIEWABLE

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")
