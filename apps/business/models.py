"""Modelos mínimos de negocio para la Fase 1 (perfil y productos). Ventas, costos detallados,
CxC/CxP y el tablero de negocio llegan en la Fase 2 (docs/decisiones.md §24)."""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import money_field
from apps.workspaces.models import Workspace, WorkspaceScopedModel


class BusinessProfile(models.Model):
    class Model(models.TextChoices):
        PRODUCTOS = "productos", "Productos"
        SERVICIOS = "servicios", "Servicios"
        MIXTO = "mixto", "Productos y servicios"

    workspace = models.OneToOneField(
        Workspace, on_delete=models.CASCADE, related_name="business_profile"
    )
    activity = models.CharField("actividad", max_length=120)
    model = models.CharField(
        "modelo", max_length=10, choices=Model.choices, default=Model.PRODUCTOS
    )
    tax_rate_itbis = models.DecimalField(
        "ITBIS",
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.18"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("0.5"))],
    )
    prices_include_tax = models.BooleanField("los precios incluyen ITBIS", default=False)
    analysis_period = models.CharField("período de análisis", max_length=10, default="mensual")

    class Meta:
        verbose_name = "perfil de negocio"
        verbose_name_plural = "perfiles de negocio"

    def __str__(self) -> str:
        return f"{self.workspace} · {self.activity}"


class Product(WorkspaceScopedModel):
    name = models.CharField("nombre", max_length=120)
    unit = models.CharField("unidad", max_length=30, default="unidad")
    price = money_field("precio de venta", validators=[MinValueValidator(Decimal("0"))])
    unit_cost = money_field("costo unitario", validators=[MinValueValidator(Decimal("0"))])
    is_service = models.BooleanField("es un servicio", default=False)
    labor_minutes = models.PositiveIntegerField("minutos de trabajo", null=True, blank=True)

    class Meta:
        verbose_name = "producto o servicio"
        verbose_name_plural = "productos y servicios"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
