"""Modelos de negocio: perfil, productos y sus costos, gastos operativos, objetivos, clientes,
proveedores, ventas, cuentas por cobrar y por pagar (docs/fase2.md §3).

Los montos de dinero se guardan sin ITBIS salvo `Sale.tax`/`Sale.total`; los cálculos viven en
`apps/business/services` y `apps/pricing/services` (funciones puras)."""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel, money_field
from apps.workspaces.models import Workspace, WorkspaceScopedModel

ZERO = Decimal("0")
_NON_NEGATIVE = [MinValueValidator(ZERO)]
_PCT = [MinValueValidator(ZERO), MaxValueValidator(Decimal("1"))]


def pct_field(verbose_name: str, **kwargs) -> models.DecimalField:
    """Porcentaje como fracción (0.30 = 30 %), con 4 decimales."""
    kwargs.setdefault("max_digits", 6)
    kwargs.setdefault("decimal_places", 4)
    kwargs.setdefault("validators", _PCT)
    return models.DecimalField(verbose_name, **kwargs)


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
    # Capacidad de trabajo para negocios de servicios (techo de ingresos).
    hours_available_month = models.PositiveIntegerField(
        "horas disponibles al mes", null=True, blank=True
    )

    class Meta:
        verbose_name = "perfil de negocio"
        verbose_name_plural = "perfiles de negocio"

    def __str__(self) -> str:
        return f"{self.workspace} · {self.activity}"


class Product(WorkspaceScopedModel):
    name = models.CharField("nombre", max_length=120)
    unit = models.CharField("unidad", max_length=30, default="unidad")
    price = money_field("precio de venta", validators=_NON_NEGATIVE)
    # Derivado de los componentes cuando los hay (services.costs.refresh_unit_cost); si no, manual.
    unit_cost = money_field("costo unitario", validators=_NON_NEGATIVE)
    is_service = models.BooleanField("es un servicio", default=False)
    labor_minutes = models.PositiveIntegerField("minutos de trabajo", null=True, blank=True)
    expected_monthly_units = models.DecimalField(
        "unidades esperadas al mes",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=_NON_NEGATIVE,
    )
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "producto o servicio"
        verbose_name_plural = "productos y servicios"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="producto_nombre_unico"),
        ]

    def __str__(self) -> str:
        return self.name


class CostComponent(TimeStampedModel):
    """Parte del costo unitario. La comisión es un porcentaje del precio; el resto, montos."""

    class Type(models.TextChoices):
        MATERIA = "materia", "Materia prima"
        EMPAQUE = "empaque", "Empaque"
        COMISION_PCT = "comision_pct", "Comisión (% del precio)"
        ENTREGA = "entrega", "Entrega"
        MANO_OBRA = "mano_obra", "Mano de obra"

    product = models.ForeignKey(
        Product, verbose_name="producto", on_delete=models.CASCADE, related_name="components"
    )
    name = models.CharField("nombre", max_length=80)
    type = models.CharField("tipo", max_length=14, choices=Type.choices)
    # Monto por unidad, o fracción del precio si el tipo es comisión (0.10 = 10 %).
    amount = models.DecimalField(
        "monto o porcentaje", max_digits=14, decimal_places=4, validators=_NON_NEGATIVE
    )

    class Meta:
        verbose_name = "componente de costo"
        verbose_name_plural = "componentes de costo"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.product} · {self.name}"

    @property
    def is_percentage(self) -> bool:
        return self.type == self.Type.COMISION_PCT

    def clean(self) -> None:
        if self.is_percentage and self.amount is not None and self.amount >= 1:
            raise ValidationError(
                {"amount": "La comisión es un porcentaje: escribe 0.10 para 10 %."}
            )


class Frequency(models.TextChoices):
    MENSUAL = "mensual", "Mensual"
    QUINCENAL = "quincenal", "Quincenal"
    SEMANAL = "semanal", "Semanal"


class OperatingExpense(WorkspaceScopedModel):
    """Gasto operativo recurrente previsto (alquiler, nómina, servicios…)."""

    name = models.CharField("nombre", max_length=80)
    category = models.ForeignKey(
        "ledger.Category",
        verbose_name="categoría",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
    )
    amount = money_field("monto", validators=_NON_NEGATIVE)
    frequency = models.CharField(
        "frecuencia", max_length=10, choices=Frequency.choices, default=Frequency.MENSUAL
    )
    due_day = models.PositiveSmallIntegerField(
        "día de pago",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )
    is_reducible = models.BooleanField("se puede reducir", default=False)
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "gasto operativo"
        verbose_name_plural = "gastos operativos"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        category = self.category if self.category_id else None
        if (
            category is not None
            and self.workspace_id
            and category.workspace_id != self.workspace_id
        ):
            raise ValidationError({"category": "La categoría no pertenece a este espacio."})


class BusinessGoal(models.Model):
    workspace = models.OneToOneField(
        Workspace, on_delete=models.CASCADE, related_name="business_goal"
    )
    target_sales = money_field("ventas objetivo del mes", null=True, blank=True)
    target_margin_pct = pct_field("margen bruto objetivo", null=True, blank=True)
    target_profit = money_field("ganancia objetivo del mes", null=True, blank=True)
    cash_reserve = money_field("reserva de efectivo", default=0, validators=_NON_NEGATIVE)
    # Lo que la persona quiere retirar del negocio cada mes para vivir (lo usa el plan).
    planned_owner_draw = money_field("retiro mensual deseado", default=0, validators=_NON_NEGATIVE)

    class Meta:
        verbose_name = "objetivo del negocio"
        verbose_name_plural = "objetivos del negocio"

    def __str__(self) -> str:
        return f"Objetivos · {self.workspace}"


class Customer(WorkspaceScopedModel):
    name = models.CharField("nombre", max_length=120)
    phone = models.CharField("teléfono", max_length=30, blank=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="cliente_nombre_unico"),
        ]

    def __str__(self) -> str:
        return self.name


class Supplier(WorkspaceScopedModel):
    name = models.CharField("nombre", max_length=120)
    phone = models.CharField("teléfono", max_length=30, blank=True)

    class Meta:
        verbose_name = "proveedor"
        verbose_name_plural = "proveedores"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="proveedor_nombre_unico"),
        ]

    def __str__(self) -> str:
        return self.name


def _same_workspace(obj: models.Model, field: str, workspace_id) -> bool:
    related = getattr(obj, field, None)
    return related is None or related.workspace_id == workspace_id


class Sale(WorkspaceScopedModel):
    class Payment(models.TextChoices):
        CONTADO = "contado", "Contado"
        CREDITO = "credito", "Crédito"

    date = models.DateField("fecha")
    customer = models.ForeignKey(
        Customer,
        verbose_name="cliente",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="sales",
    )
    payment = models.CharField(
        "forma de pago", max_length=8, choices=Payment.choices, default=Payment.CONTADO
    )
    # Cuenta donde entra el dinero de una venta de contado.
    account = models.ForeignKey(
        "ledger.Account",
        verbose_name="cuenta",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
    )
    client_uuid = models.UUIDField("id del dispositivo", null=True, blank=True, editable=False)
    subtotal = money_field("subtotal sin ITBIS", default=0)
    tax = money_field("ITBIS", default=0)
    total = money_field("total", default=0)
    note = models.CharField("nota", max_length=140, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "venta"
        verbose_name_plural = "ventas"
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "client_uuid"],
                condition=Q(client_uuid__isnull=False),
                name="venta_client_uuid_unico",
            ),
            models.CheckConstraint(
                condition=Q(subtotal__gte=0) & Q(tax__gte=0) & Q(total__gte=0),
                name="venta_montos_no_negativos",
            ),
        ]
        indexes = [models.Index(fields=["workspace", "date"], name="venta_ws_fecha")]

    def __str__(self) -> str:
        return f"Venta {self.date} {self.total}"

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.payment == self.Payment.CONTADO and not self.account_id:
            errors["account"] = "Indica en qué cuenta entró el dinero."
        if self.payment == self.Payment.CREDITO and self.account_id:
            errors["account"] = "Una venta a crédito no mueve dinero hasta cobrarse."
        if self.workspace_id:
            for field in ("customer", "account"):
                if getattr(self, f"{field}_id") and not _same_workspace(
                    self, field, self.workspace_id
                ):
                    errors[field] = "No pertenece a este espacio."
        if errors:
            raise ValidationError(errors)


class SaleLine(TimeStampedModel):
    sale = models.ForeignKey(
        Sale, verbose_name="venta", on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product,
        verbose_name="producto",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="sale_lines",
    )
    description = models.CharField("descripción", max_length=120, blank=True)
    qty = models.DecimalField("cantidad", max_digits=10, decimal_places=2)
    # Precio unitario tal como se cobra (con ITBIS si el negocio publica precios con ITBIS),
    # antes del descuento.
    unit_price = money_field("precio unitario", validators=_NON_NEGATIVE)
    discount_pct = pct_field("descuento", default=0)
    # Lo que esta línea aporta a las ventas: con el descuento y sin ITBIS. Las líneas de una venta
    # suman exactamente `Sale.subtotal`.
    net_amount = money_field("importe sin ITBIS", default=0, validators=_NON_NEGATIVE)
    # Costo unitario del producto al momento de vender: las ventas pasadas no cambian.
    unit_cost_snapshot = money_field(
        "costo unitario al vender", default=0, validators=_NON_NEGATIVE
    )

    class Meta:
        verbose_name = "línea de venta"
        verbose_name_plural = "líneas de venta"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(qty__gt=0), name="linea_cantidad_positiva"),
        ]

    def __str__(self) -> str:
        return f"{self.qty} × {self.description or self.product}"

    def clean(self) -> None:
        if not self.product_id and not self.description:
            raise ValidationError({"description": "Indica el producto o una descripción."})
        product = self.product if self.product_id else None
        if product is not None and self.sale_id and product.workspace_id != self.sale.workspace_id:
            raise ValidationError({"product": "El producto no pertenece a este espacio."})


class DebtStatus(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente"
    PARCIAL = "parcial", "Pago parcial"
    PAGADA = "pagada", "Pagada"


def status_for(amount: Decimal, paid: Decimal) -> str:
    """Estado de una cuenta por cobrar o por pagar según lo abonado."""
    if paid <= 0:
        return DebtStatus.PENDIENTE
    if paid < amount:
        return DebtStatus.PARCIAL
    return DebtStatus.PAGADA


class _Debt(WorkspaceScopedModel):
    """Base de CxC y CxP: monto, abonado, vencimiento y estado (derivado de lo abonado)."""

    concept = models.CharField("concepto", max_length=140)
    amount = money_field("monto")
    paid = money_field("abonado", default=0, validators=_NON_NEGATIVE)
    due_date = models.DateField("vence", null=True, blank=True)
    status = models.CharField(
        "estado", max_length=10, choices=DebtStatus.choices, default=DebtStatus.PENDIENTE
    )
    client_uuid = models.UUIDField("id del dispositivo", null=True, blank=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        abstract = True

    @property
    def balance(self) -> Decimal:
        return self.amount - self.paid

    def is_overdue(self, today: datetime.date) -> bool:
        return (
            self.status != DebtStatus.PAGADA and self.due_date is not None and self.due_date < today
        )

    def save(self, *args, **kwargs) -> None:
        self.status = status_for(self.amount, self.paid)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "paid" in update_fields:
            kwargs["update_fields"] = {*update_fields, "status"}
        super().save(*args, **kwargs)

    def clean(self) -> None:
        if self.amount is not None and self.paid is not None and self.paid > self.amount:
            raise ValidationError({"paid": "Lo abonado no puede superar el monto."})


class Receivable(_Debt):
    customer = models.ForeignKey(
        Customer,
        verbose_name="cliente",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="receivables",
    )
    sale = models.OneToOneField(
        Sale,
        verbose_name="venta",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="receivable",
    )

    class Meta:
        verbose_name = "cuenta por cobrar"
        verbose_name_plural = "cuentas por cobrar"
        ordering = ["due_date", "created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="cxc_monto_positivo"),
            models.CheckConstraint(
                condition=Q(paid__gte=0) & Q(paid__lte=models.F("amount")),
                name="cxc_abonado_valido",
            ),
            models.UniqueConstraint(
                fields=["workspace", "client_uuid"],
                condition=Q(client_uuid__isnull=False),
                name="cxc_client_uuid_unico",
            ),
        ]

    def __str__(self) -> str:
        return f"Por cobrar · {self.concept}"


class Payable(_Debt):
    supplier = models.ForeignKey(
        Supplier,
        verbose_name="proveedor",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="payables",
    )
    category = models.ForeignKey(
        "ledger.Category",
        verbose_name="categoría",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "cuenta por pagar"
        verbose_name_plural = "cuentas por pagar"
        ordering = ["due_date", "created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="cxp_monto_positivo"),
            models.CheckConstraint(
                condition=Q(paid__gte=0) & Q(paid__lte=models.F("amount")),
                name="cxp_abonado_valido",
            ),
            models.UniqueConstraint(
                fields=["workspace", "client_uuid"],
                condition=Q(client_uuid__isnull=False),
                name="cxp_client_uuid_unico",
            ),
        ]

    def __str__(self) -> str:
        return f"Por pagar · {self.concept}"
