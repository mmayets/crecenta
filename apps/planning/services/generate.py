"""Generación del plan (encargo §9).

1. `inputs_snapshot`: solo los datos necesarios (sin cuentas ni datos de la persona).
2. Motor determinístico → `computed`.
3. `missing_data`: qué falta y cómo afecta.
4. IA con el plan calculado (sin identificadores internos) + preferencias + faltantes, con salida
   validada por esquema y por `verify_narrative`; si no valida, narrativa por reglas.
5. Se guarda como `propuesta`. Nada se aplica hasta que la persona acepta.

Los pasos 1–3 son síncronos (las cifras se ven de inmediato); la narrativa (4) corre en Celery.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.accounts.models import User
from apps.ai.schemas import PlanNarrative
from apps.ai.services.client import run_structured
from apps.ai.services.fallback import fallback_business_narrative, fallback_plan_narrative
from apps.ai.services.guards import plan_validator
from apps.business.services.loaders import load_business_plan_inputs
from apps.business.services.plan import BusinessPlanInputs, build_business_plan
from apps.business.services.plan_edits import business_missing_data
from apps.business.services.plan_serialize import (
    business_inputs_to_dict,
    serialize_business_plan,
)
from apps.ledger.models import Category
from apps.personal.services.budget_engine import build_personal_plan
from apps.personal.services.loaders import load_personal_inputs
from apps.personal.services.serialize import inputs_to_dict, serialize_plan, strip_refs
from apps.personal.services.types import PersonalInputs
from apps.planning.models import PlanVersion
from apps.planning.services.missing_data import missing_for_workspace
from apps.workspaces.models import Workspace

logger = logging.getLogger(__name__)


def request_personal_plan(
    workspace: Workspace,
    user: User | None,
    today: date,
    *,
    inputs: PersonalInputs | None = None,
    parent: PlanVersion | None = None,
    edits: dict[str, Any] | None = None,
) -> PlanVersion:
    """Calcula el plan, lo guarda en estado `generando` y encola la explicación."""
    inputs = inputs or load_personal_inputs(workspace, today)
    result = build_personal_plan(inputs)
    plan = PlanVersion.objects.create(
        workspace=workspace,
        kind=PlanVersion.Kind.PERSONAL,
        status=PlanVersion.Status.GENERANDO,
        period_start=result.period.start,
        period_end=result.period.end,
        plan_status=result.status.value,
        inputs_snapshot=inputs_to_dict(inputs),
        computed=serialize_plan(result),
        assumptions=list(result.assumptions),
        missing_data=missing_for_workspace(workspace, inputs),
        edits=edits or {},
        parent=parent,
        created_by=user,
    )
    from apps.planning.tasks import narrate_plan_task

    plan_id = str(plan.pk)
    transaction.on_commit(lambda: narrate_plan_task.delay(plan_id))
    return plan


def request_business_plan(
    workspace: Workspace,
    user: User | None,
    today: date,
    *,
    inputs: BusinessPlanInputs | None = None,
    parent: PlanVersion | None = None,
    edits: dict[str, Any] | None = None,
) -> PlanVersion:
    """Plan de negocio del mes: mismo flujo y estados que el personal."""
    inputs = inputs or load_business_plan_inputs(workspace, today)
    result = build_business_plan(inputs)
    plan = PlanVersion.objects.create(
        workspace=workspace,
        kind=PlanVersion.Kind.BUSINESS,
        status=PlanVersion.Status.GENERANDO,
        period_start=inputs.start,
        period_end=inputs.end,
        plan_status=result.status.value,
        inputs_snapshot=business_inputs_to_dict(inputs),
        computed=serialize_business_plan(result),
        assumptions=list(result.assumptions),
        missing_data=business_missing_data(inputs),
        edits=edits or {},
        parent=parent,
        created_by=user,
    )
    from apps.planning.tasks import narrate_plan_task

    plan_id = str(plan.pk)
    transaction.on_commit(lambda: narrate_plan_task.delay(plan_id))
    return plan


def _ai_context(plan: PlanVersion, computed_for_ai: dict[str, Any]) -> dict[str, Any]:
    names = {
        str(pk): name
        for pk, name in Category.objects.for_workspace(plan.workspace).values_list("id", "name")
    }
    preferences = {
        names.get(ref, "categoría"): priority
        for ref, priority in plan.inputs_snapshot.get("preferencias", {}).items()
    }
    return {
        "moneda": plan.workspace.currency,
        "estado": plan.computed["estado"],
        "calculado": computed_for_ai,
        "preferencias": preferences,
        "datos_faltantes": plan.missing_data,
    }


def narrate_plan(plan_id: UUID | str) -> PlanVersion:
    """Agrega la explicación al plan y lo deja como propuesta. Nunca lo deja en `generando`."""
    plan = PlanVersion.objects.select_related("workspace", "created_by").get(pk=plan_id)
    if plan.status != PlanVersion.Status.GENERANDO:
        return plan
    computed_for_ai = strip_refs(plan.computed)
    currency = plan.workspace.currency
    is_business = plan.kind == PlanVersion.Kind.BUSINESS
    name = "plan_negocio" if is_business else "plan_personal"

    def fallback() -> PlanNarrative:
        builder = fallback_business_narrative if is_business else fallback_plan_narrative
        return builder(computed_for_ai, plan.missing_data, currency)

    context = (
        {
            "moneda": currency,
            "estado": plan.computed["estado"],
            "calculado": computed_for_ai,
            "datos_faltantes": plan.missing_data,
        }
        if is_business
        else _ai_context(plan, computed_for_ai)
    )
    try:
        result = run_structured(
            workspace=plan.workspace,
            user=plan.created_by,
            purpose=name,
            prompt_name=name,
            context=context,
            schema=PlanNarrative,
            fallback=fallback,
            validator=plan_validator(computed_for_ai),
        )
        narrative, source, interaction = result.data, result.source, result.interaction_id
    except Exception:  # cualquier falla inesperada: la persona igual recibe su plan
        logger.exception("No se pudo generar la explicación del plan %s", plan.pk)
        narrative, source, interaction = fallback(), "reglas", None

    plan.ai_narrative = narrative.model_dump(mode="json")
    plan.narrative_source = source
    plan.ai_interaction_id = interaction
    plan.status = PlanVersion.Status.PROPUESTA
    plan.save(
        update_fields=["ai_narrative", "narrative_source", "ai_interaction", "status", "updated_at"]
    )
    return plan
