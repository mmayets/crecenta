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


class Parameter(TimeStampedModel):
    """Valor de configuración por entorno (lo que antes vivía en `.env`).

    `config/parameters.py` lee esta tabla al arrancar; un cambio requiere reiniciar el servidor.
    """

    key = models.CharField("clave", max_length=100, unique=True)
    value = models.TextField("valor", blank=True)
    description = models.CharField("descripción", max_length=255, blank=True)

    class Meta:
        db_table = "parameters"
        ordering = ["key"]
        verbose_name = "parámetro"
        verbose_name_plural = "parámetros"

    def __str__(self) -> str:
        return self.key


def money_field(verbose_name: str, **kwargs) -> models.DecimalField:
    """Campo monetario estándar del proyecto: 14 dígitos, 2 decimales."""
    kwargs.setdefault("max_digits", 14)
    kwargs.setdefault("decimal_places", 2)
    return models.DecimalField(verbose_name, **kwargs)
