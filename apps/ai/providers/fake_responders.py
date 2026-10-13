"""Respuestas por defecto del proveedor de prueba (AI_PROVIDER=fake, desarrollo sin claves)."""

from typing import Any

from apps.ai.schemas import PlanNarrative
from apps.ai.services.fallback import fallback_business_narrative, fallback_plan_narrative

from .fake import FakeProvider


@FakeProvider.responder("PlanNarrative")
def plan_narrative(context: dict[str, Any]) -> PlanNarrative:
    if context["calculado"].get("tipo") == "negocio":
        return fallback_business_narrative(
            context["calculado"], context.get("datos_faltantes"), context.get("moneda", "DOP")
        )
    return fallback_plan_narrative(
        context["calculado"], context.get("datos_faltantes"), context.get("moneda", "DOP")
    )
