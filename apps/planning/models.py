from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import money_field
from apps.ledger.models import Category
from apps.workspaces.models import WorkspaceScopedModel


class PlanVersion(WorkspaceScopedModel):
    """Una versión del plan. Las cifras (`computed`) son del motor; la narrativa es de la IA o de
    reglas. Nada se aplica hasta que la persona acepta."""

    class Kind(models.TextChoices):
        PERSONAL = "personal", "Personal"
        BUSINESS = "business", "Negocio"

    class Status(models.TextChoices):
        GENERANDO = "generando", "Generando explicación"
        PROPUESTA = "propuesta", "Propuesta"
        ACEPTADO = "aceptado", "Aceptado"
        DESCARTADO = "descartado", "Descartado"
        REEMPLAZADO = "reemplazado", "Reemplazado"

    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, default=Kind.PERSONAL)
    status = models.CharField(
        "estado", max_length=12, choices=Status.choices, default=Status.GENERANDO
    )
    period_start = models.DateField("inicio del período")
    period_end = models.DateField("fin del período")
    plan_status = models.CharField("resultado del plan", max_length=10)  # viable/ajustado/no_viable
    inputs_snapshot = models.JSONField("datos usados")
    computed = models.JSONField("cálculo del motor")
    ai_narrative = models.JSONField("explicación", null=True, blank=True)
    narrative_source = models.CharField("origen de la explicación", max_length=10, blank=True)
    assumptions = models.JSONField("supuestos", default=list)
    missing_data = models.JSONField("datos faltantes", default=list)
    edits = models.JSONField("cambios de la persona", default=dict, blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    ai_interaction = models.ForeignKey(
        "ai.AIInteraction", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    accepted_at = models.DateTimeField("aceptado el", null=True, blank=True)

    class Meta:
        verbose_name = "versión del plan"
        verbose_name_plural = "versiones del plan"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["workspace", "status"], name="plan_ws_estado")]

    def __str__(self) -> str:
        return f"Plan {self.period_start:%d/%m/%Y} · {self.get_status_display()}"

    @property
    def is_open(self) -> bool:
        """Se puede aceptar, editar o descartar."""
        return self.status == self.Status.PROPUESTA


class BudgetPeriod(WorkspaceScopedModel):
    """Presupuesto vigente de un período, creado al aceptar un plan."""

    plan = models.OneToOneField(PlanVersion, on_delete=models.CASCADE, related_name="budget")
    start = models.DateField("inicio")
    end = models.DateField("fin")
    is_active = models.BooleanField("vigente", default=True)
    pay_events = models.JSONField("reparto por cobro", default=list)

    class Meta:
        verbose_name = "período de presupuesto"
        verbose_name_plural = "períodos de presupuesto"
        ordering = ["-start"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "start"],
                condition=Q(is_active=True),
                name="un_presupuesto_vigente_por_periodo",
            )
        ]

    def __str__(self) -> str:
        return f"{self.start:%d/%m/%Y} – {self.end:%d/%m/%Y}"


class BudgetLine(models.Model):
    class Kind(models.TextChoices):
        COMPROMISO = "compromiso", "Compromiso"
        DEUDA = "deuda", "Deuda"
        ESENCIAL = "esencial", "Esencial"
        AHORRO = "ahorro", "Ahorro"
        DISCRECIONAL = "discrecional", "Ocio"
        RESERVA = "reserva", "Reserva"

    period = models.ForeignKey(BudgetPeriod, on_delete=models.CASCADE, related_name="lines")
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    kind = models.CharField("tipo", max_length=12, choices=Kind.choices)
    name = models.CharField("concepto", max_length=80)
    ref = models.CharField("referencia", max_length=64)
    assigned = money_field("asignado")
    due_dates = models.JSONField("vencimientos", default=list, blank=True)

    class Meta:
        verbose_name = "línea de presupuesto"
        verbose_name_plural = "líneas de presupuesto"
        ordering = ["kind", "name"]

    def __str__(self) -> str:
        return f"{self.name}: {self.assigned}"
