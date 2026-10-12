"""Ciclo de vida de un plan: aceptar, editar, descartar y comparar.

La IA nunca aplica un plan: solo la persona, al aceptar. Al aceptar se crea el presupuesto del
período (`BudgetPeriod` + `BudgetLine`) y la versión aceptada anterior pasa a `reemplazado`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.ledger.models import Category
from apps.personal.services.budget_engine import build_personal_plan
from apps.personal.services.serialize import inputs_from_dict
from apps.personal.services.types import BudgetResult
from apps.planning.models import BudgetLine, BudgetPeriod, PlanVersion
from apps.planning.services.editing import apply_edits
from apps.planning.services.generate import request_personal_plan
from apps.workspaces.models import Workspace

S = PlanVersion.Status


class PlanError(Exception):
    """Transición de estado no permitida."""


def _lock_open(plan: PlanVersion) -> PlanVersion:
    locked = PlanVersion.objects.select_for_update().get(pk=plan.pk)
    if not locked.is_open:
        raise PlanError(f"Este plan ya está {locked.get_status_display().lower()}.")
    return locked


@transaction.atomic
def accept_plan(plan: PlanVersion, user: User | None) -> PlanVersion:
    plan = _lock_open(plan)
    workspace = plan.workspace
    same_period = (
        PlanVersion.objects.for_workspace(workspace)
        .filter(period_start=plan.period_start)
        .exclude(pk=plan.pk)
    )
    same_period.filter(status__in=[S.ACEPTADO, S.PROPUESTA, S.GENERANDO]).update(
        status=S.REEMPLAZADO, updated_at=timezone.now()
    )
    BudgetPeriod.objects.for_workspace(workspace).filter(
        start=plan.period_start, is_active=True
    ).update(is_active=False)

    categories = {str(c.pk): c for c in Category.objects.for_workspace(workspace)}
    budget = BudgetPeriod.objects.create(
        workspace=workspace,
        plan=plan,
        start=plan.period_start,
        end=plan.period_end,
        pay_events=plan.computed.get("reparto_por_cobro", []),
    )
    BudgetLine.objects.bulk_create(
        BudgetLine(
            period=budget,
            category=categories.get(line.get("categoria_ref") or ""),
            kind=line["tipo"],
            name=line["nombre"],
            ref=line["ref"],
            assigned=Decimal(line["monto"]),
            due_dates=line["vencimientos"],
        )
        for line in plan.computed["lineas"]
    )
    plan.status = S.ACEPTADO
    plan.accepted_at = timezone.now()
    plan.save(update_fields=["status", "accepted_at", "updated_at"])
    return plan


@transaction.atomic
def discard_plan(plan: PlanVersion, user: User | None) -> PlanVersion:
    plan = _lock_open(plan)
    plan.status = S.DESCARTADO
    plan.save(update_fields=["status", "updated_at"])
    return plan


@transaction.atomic
def edit_plan(
    plan: PlanVersion, user: User | None, edits: dict[str, Any], today: date
) -> PlanVersion:
    """Crea una nueva propuesta con los cambios (recalculada por el motor); la anterior queda
    `reemplazado`. Lanza ValidationError si los cambios no son válidos."""
    plan = _lock_open(plan)
    new_inputs = apply_edits(inputs_from_dict(plan.inputs_snapshot), edits)
    new_plan = request_personal_plan(
        plan.workspace, user, today, inputs=new_inputs, parent=plan, edits=edits
    )
    plan.status = S.REEMPLAZADO
    plan.save(update_fields=["status", "updated_at"])
    return new_plan


def active_budget(workspace: Workspace, today: date) -> BudgetPeriod | None:
    budget: BudgetPeriod | None = (
        BudgetPeriod.objects.for_workspace(workspace)
        .filter(is_active=True, start__lte=today, end__gte=today)
        .select_related("plan")
        .first()
    )
    return budget


def accepted_result(workspace: Workspace, today: date) -> BudgetResult | None:
    """Resultado del plan aceptado vigente, recalculado desde su snapshot (es determinístico)."""
    budget = active_budget(workspace, today)
    if budget is None:
        return None
    return build_personal_plan(inputs_from_dict(budget.plan.inputs_snapshot))


@dataclass(frozen=True)
class ComparisonRow:
    concept: str
    a: Decimal
    b: Decimal

    @property
    def difference(self) -> Decimal:
        return self.b - self.a


_CONCEPTS = [
    ("ingreso_total", "Ingreso del período"),
    ("compromiso", "Compromisos"),
    ("deuda", "Deudas"),
    ("esencial", "Esenciales"),
    ("ahorro", "Ahorro"),
    ("discrecional", "Ocio"),
    ("reserva", "Reserva"),
    ("faltante_total", "Faltante"),
]


def compare_plans(a: PlanVersion, b: PlanVersion) -> list[ComparisonRow]:
    def value(plan: PlanVersion, key: str) -> Decimal:
        computed = plan.computed
        raw = computed[key] if key in computed else computed["totales"].get(key, "0")
        return Decimal(raw)

    return [ComparisonRow(label, value(a, key), value(b, key)) for key, label in _CONCEPTS]
