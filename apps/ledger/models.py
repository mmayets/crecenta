from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import money_field
from apps.core.money import CURRENCY_CHOICES
from apps.workspaces.models import WorkspaceScopedModel

from .choices import (
    BUSINESS_GROUPS,
    PERSONAL_GROUPS,
    AccountType,
    CategoryGroup,
    Direction,
    TxKind,
    TxSource,
    TxStatus,
)
from .services.classification import allowed_directions, is_income_kind


class Account(WorkspaceScopedModel):
    """Cuenta donde está el dinero. No se guardan números de cuenta (privacidad)."""

    name = models.CharField("nombre", max_length=60)
    type = models.CharField("tipo", max_length=10, choices=AccountType.choices)
    currency = models.CharField("moneda", max_length=3, choices=CURRENCY_CHOICES)
    opening_balance = money_field("saldo inicial", default=0)
    is_archived = models.BooleanField("archivada", default=False)

    class Meta:
        verbose_name = "cuenta"
        verbose_name_plural = "cuentas"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="cuenta_nombre_unico"),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if self.workspace_id and self.currency != self.workspace.currency:
            raise ValidationError({"currency": "La cuenta debe usar la moneda del espacio."})


class Category(WorkspaceScopedModel):
    name = models.CharField("nombre", max_length=60)
    group = models.CharField("grupo", max_length=20, choices=CategoryGroup.choices)
    is_system = models.BooleanField("del sistema", default=False)
    is_archived = models.BooleanField("archivada", default=False)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["group", "name"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="categoria_nombre_unico"),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        if not self.workspace_id:
            return
        allowed = PERSONAL_GROUPS if self.workspace.is_personal else BUSINESS_GROUPS
        if self.group not in allowed:
            raise ValidationError({"group": "Este grupo no aplica para este tipo de espacio."})


class Transaction(WorkspaceScopedModel):
    """Movimiento de dinero. El monto siempre es positivo; el sentido lo da `direction`."""

    account = models.ForeignKey(
        Account, verbose_name="cuenta", on_delete=models.PROTECT, related_name="transactions"
    )
    date = models.DateField("fecha")
    amount = money_field("monto")
    direction = models.CharField("sentido", max_length=3, choices=Direction.choices)
    category = models.ForeignKey(
        Category,
        verbose_name="categoría",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
    )
    kind = models.CharField("tipo", max_length=24, choices=TxKind.choices)
    status = models.CharField(
        "estado", max_length=20, choices=TxStatus.choices, default=TxStatus.CONFIRMADO
    )
    description = models.CharField("descripción", max_length=140, blank=True)
    source = models.CharField(
        "origen", max_length=12, choices=TxSource.choices, default=TxSource.MANUAL
    )
    # Identificador generado en el dispositivo: hace idempotente la sincronización offline.
    client_uuid = models.UUIDField("id del dispositivo", null=True, blank=True, editable=False)
    # Pata contraria de una transferencia interna o retiro de efectivo.
    transfer_pair = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "movimiento"
        verbose_name_plural = "movimientos"
        ordering = ["-date", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="movimiento_monto_positivo"),
            models.UniqueConstraint(
                fields=["workspace", "client_uuid"],
                condition=Q(client_uuid__isnull=False),
                name="movimiento_client_uuid_unico",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "date"], name="mov_ws_fecha"),
            models.Index(fields=["workspace", "category", "date"], name="mov_ws_cat_fecha"),
        ]

    def __str__(self) -> str:
        sign = "+" if self.direction == Direction.IN else "-"
        return f"{self.date} {sign}{self.amount} {self.description or self.get_kind_display()}"

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "El monto debe ser mayor que cero."
        if self.kind and self.direction and self.direction not in allowed_directions(self.kind):
            errors["direction"] = "El sentido no corresponde al tipo de movimiento."
        if self.account_id and self.workspace_id and self.account.workspace_id != self.workspace_id:
            errors["account"] = "La cuenta no pertenece a este espacio."
        category = self.category if self.category_id else None
        if category is not None and self.workspace_id:
            if category.workspace_id != self.workspace_id:
                errors["category"] = "La categoría no pertenece a este espacio."
            elif self.kind and is_income_kind(self.kind) != (
                category.group == CategoryGroup.INGRESO
            ):
                errors["category"] = "La categoría no corresponde al tipo de movimiento."
        if errors:
            raise ValidationError(errors)
