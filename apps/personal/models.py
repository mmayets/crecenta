from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import money_field
from apps.core.periods import Frequency, IncomeInput
from apps.ledger.models import Category
from apps.workspaces.models import Workspace, WorkspaceScopedModel

from .services.types import DailyMode, Priority, SavingsFrequency

_POSITIVE = [MinValueValidator(Decimal("0.01"))]
_NON_NEGATIVE = [MinValueValidator(Decimal("0"))]


def _choices(enum) -> list[tuple[str, str]]:
    return [(m.value, m.value.replace("_", " ").capitalize()) for m in enum]


class PersonalProfile(models.Model):
    """Preferencias del plan de un espacio personal."""

    workspace = models.OneToOneField(
        Workspace, on_delete=models.CASCADE, related_name="personal_profile"
    )
    discretionary_wish = money_field(
        "ocio deseado por período", null=True, blank=True, validators=_NON_NEGATIVE
    )
    reserve_pct = models.DecimalField(
        "reserva para variaciones (fracción de esenciales)",
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.10"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("0.5"))],
    )

    class Meta:
        verbose_name = "perfil personal"
        verbose_name_plural = "perfiles personales"

    def __str__(self) -> str:
        return f"Perfil de {self.workspace}"


class IncomeSource(WorkspaceScopedModel):
    name = models.CharField("nombre", max_length=60)
    net_amount = money_field("monto neto de cada cobro", validators=_POSITIVE)
    frequency = models.CharField(
        "frecuencia",
        max_length=10,
        choices=_choices([f for f in Frequency if f != Frequency.ANUAL]),
        default=Frequency.MENSUAL,
    )
    pay_days = ArrayField(
        models.PositiveSmallIntegerField(),
        verbose_name="días de cobro",
        default=list,
        blank=True,
        help_text="Días del mes (1–31); para semanal, día de la semana (0=lunes).",
    )
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "ingreso"
        verbose_name_plural = "ingresos"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        try:
            self.to_input()
        except ValueError as exc:
            raise ValidationError({"pay_days": str(exc)}) from exc

    def to_input(self) -> IncomeInput:
        return IncomeInput(
            ref=str(self.pk),
            net_amount=self.net_amount,
            frequency=Frequency(self.frequency),
            pay_days=tuple(self.pay_days or ()),
        )


class Commitment(WorkspaceScopedModel):
    """Compromiso fijo: `amount` es el monto de cada vencimiento."""

    FREQUENCIES = [
        (Frequency.MENSUAL.value, "Mensual"),
        (Frequency.QUINCENAL.value, "Quincenal"),
        (Frequency.SEMANAL.value, "Semanal"),
        (Frequency.ANUAL.value, "Anual"),
    ]

    name = models.CharField("nombre", max_length=60)
    category = models.ForeignKey(
        Category, verbose_name="categoría", on_delete=models.RESTRICT, related_name="+"
    )
    amount = money_field("monto", validators=_POSITIVE)
    frequency = models.CharField(
        "frecuencia", max_length=10, choices=FREQUENCIES, default=Frequency.MENSUAL
    )
    due_day = models.PositiveSmallIntegerField(
        "día de vencimiento", help_text="Día del mes (1–31); para semanal, día de la semana (0–6)."
    )
    # Solo para compromisos anuales: mes en que vence (1–12).
    due_month = models.PositiveSmallIntegerField(
        "mes de vencimiento",
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    is_fixed = models.BooleanField("monto fijo", default=True)
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "compromiso"
        verbose_name_plural = "compromisos"
        ordering = ["due_day", "name"]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        errors = {}
        if self.due_day is None:
            pass  # el campo obligatorio ya reporta el error
        elif self.frequency == Frequency.SEMANAL:
            if not 0 <= self.due_day <= 6:
                errors["due_day"] = "Para pagos semanales use 0 (lunes) a 6 (domingo)."
        elif not 1 <= self.due_day <= 31:
            errors["due_day"] = "El día debe estar entre 1 y 31."
        if self.frequency == Frequency.ANUAL and not self.due_month:
            errors["due_month"] = "Indica en qué mes vence este pago anual."
        if self.category_id and self.category.workspace_id != self.workspace_id:
            errors["category"] = "La categoría no pertenece a este espacio."
        if errors:
            raise ValidationError(errors)


class Debt(WorkspaceScopedModel):
    name = models.CharField("nombre", max_length=60)
    installment = money_field("cuota mensual", validators=_POSITIVE)
    balance = money_field("saldo pendiente", validators=_NON_NEGATIVE)
    due_day = models.PositiveSmallIntegerField(
        "día de pago", validators=[MinValueValidator(1), MaxValueValidator(31)]
    )
    interest_rate = models.DecimalField(
        "tasa anual (%)", max_digits=6, decimal_places=3, null=True, blank=True
    )
    end_date = models.DateField("fecha final", null=True, blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.RESTRICT, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "deuda"
        verbose_name_plural = "deudas"
        ordering = ["due_day", "name"]

    def __str__(self) -> str:
        return self.name


class EssentialEstimate(WorkspaceScopedModel):
    """Presupuesto estimado por el usuario para un esencial variable en un período."""

    category = models.ForeignKey(Category, on_delete=models.RESTRICT, related_name="+")
    amount = money_field("monto por período", validators=_NON_NEGATIVE)

    class Meta:
        verbose_name = "esencial variable"
        verbose_name_plural = "esenciales variables"
        constraints = [
            models.UniqueConstraint(fields=["workspace", "category"], name="esencial_unico"),
        ]

    def __str__(self) -> str:
        return f"{self.category} · {self.amount}"


class SavingsGoal(WorkspaceScopedModel):
    purpose = models.CharField("propósito", max_length=80)
    target_amount = money_field("meta", null=True, blank=True, validators=_POSITIVE)
    contribution_amount = money_field("aporte", validators=_POSITIVE)
    contribution_frequency = models.CharField(
        "frecuencia del aporte",
        max_length=10,
        choices=_choices(SavingsFrequency),
        default=SavingsFrequency.MENSUAL,
    )
    daily_mode = models.CharField(
        "modo diario", max_length=20, choices=_choices(DailyMode), default=DailyMode.TODOS_LOS_DIAS
    )
    selected_weekdays = ArrayField(
        models.PositiveSmallIntegerField(validators=[MaxValueValidator(6)]),
        verbose_name="días seleccionados",
        default=list,
        blank=True,
    )
    saved_initial = money_field("ahorrado antes de empezar", default=0, validators=_NON_NEGATIVE)
    deadline = models.DateField("plazo", null=True, blank=True)
    category = models.ForeignKey(
        Category, on_delete=models.RESTRICT, null=True, blank=True, related_name="+"
    )
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        verbose_name = "meta de ahorro"
        verbose_name_plural = "metas de ahorro"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.purpose

    def clean(self) -> None:
        if (
            self.contribution_frequency == SavingsFrequency.DIARIA
            and self.daily_mode == DailyMode.DIAS_SELECCIONADOS
            and not self.selected_weekdays
        ):
            raise ValidationError({"selected_weekdays": "Elija al menos un día de la semana."})


class Preference(WorkspaceScopedModel):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="+")
    priority = models.CharField("prioridad", max_length=12, choices=_choices(Priority))

    class Meta:
        verbose_name = "preferencia"
        verbose_name_plural = "preferencias"
        constraints = [
            models.UniqueConstraint(fields=["workspace", "category"], name="preferencia_unica"),
        ]

    def __str__(self) -> str:
        return f"{self.category}: {self.priority}"
