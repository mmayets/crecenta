"""Respuestas por defecto del proveedor de prueba (AI_PROVIDER=fake, desarrollo sin claves)."""

from typing import Any

from apps.ai.schemas import AssistantTurn, PlanNarrative
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


@FakeProvider.responder("AssistantTurn")
def assistant_turn(context: dict[str, Any]) -> AssistantTurn:
    # Import diferido: el asistente vive en onboarding, que depende de esta app.
    from apps.onboarding.services.assistant import interpret_by_rules

    return interpret_by_rules(context["mensaje"], context["faltantes"])
