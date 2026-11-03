from decimal import Decimal

from django.conf import settings
from django.db import models


class Departamento(models.Model):
    nombre = models.CharField(max_length=80)
    anio = models.PositiveSmallIntegerField("año fiscal")
    aprobado = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    ejecutado = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    comprometido = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["anio", "orden", "nombre"]
        unique_together = [("nombre", "anio")]

    def __str__(self) -> str:
        return f"{self.nombre} {self.anio}"

    @property
    def porcentaje_ejecutado(self) -> int:
        return round(self.ejecutado * 100 / self.aprobado) if self.aprobado else 0


class SolicitudCompra(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        EN_CURSO = "en_curso", "En curso"
        APROBADO = "aprobado", "Aprobado"
        RECHAZADO = "rechazado", "Rechazado"

    numero = models.PositiveIntegerField("número", unique=True, editable=False)
    descripcion = models.CharField("descripción", max_length=160)
    departamento = models.ForeignKey(Departamento, on_delete=models.PROTECT, related_name="solicitudes")
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-numero"]
        verbose_name = "solicitud de compra"
        verbose_name_plural = "solicitudes de compra"
        permissions = [("decidir_solicitudcompra", "Puede aprobar o rechazar solicitudes de compra")]

    def __str__(self) -> str:
        return f"#{self.numero} {self.descripcion}"

    def save(self, *args, **kwargs):
        if not self.numero:
            ultimo = SolicitudCompra.objects.aggregate(m=models.Max("numero"))["m"] or 2300
            self.numero = ultimo + 1
        super().save(*args, **kwargs)


def totales(anio: int) -> dict[str, Decimal]:
    agg = Departamento.objects.filter(anio=anio).aggregate(
        aprobado=models.Sum("aprobado"), ejecutado=models.Sum("ejecutado"), comprometido=models.Sum("comprometido")
    )
    agg = {k: v or Decimal(0) for k, v in agg.items()}
    agg["disponible"] = agg["aprobado"] - agg["ejecutado"] - agg["comprometido"]
    agg["porcentaje"] = round(agg["ejecutado"] * 100 / agg["aprobado"], 1) if agg["aprobado"] else 0
    return agg
