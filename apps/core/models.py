import uuid

from django.db import models


class UUIDModel(models.Model):
    """Base con UUID como clave primaria pública."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(UUIDModel):
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        abstract = True


def money_field(verbose_name: str, **kwargs) -> models.DecimalField:
    """Campo monetario estándar del proyecto: 14 dígitos, 2 decimales."""
    kwargs.setdefault("max_digits", 14)
    kwargs.setdefault("decimal_places", 2)
    return models.DecimalField(verbose_name, **kwargs)
