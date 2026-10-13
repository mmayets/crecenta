"""Onboarding conversacional del negocio: el dueño describe su negocio con sus palabras, la IA lo
extrae a un esquema estricto y se muestra prellenado para revisar. Nada se guarda sin confirmar."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from apps.accounts.models import User
from apps.ai.schemas import BusinessOnboardingExtraction
from apps.ai.services.client import run_structured
from apps.ledger.choices import CategoryGroup
from apps.ledger.services.categories import match_category
from apps.workspaces.models import Workspace

MAX_TEXT = 4000
FIELD_MAP: dict[str, dict[str, str]] = {
    "productos": {"nombre": "name", "precio": "price", "costo": "unit_cost",
                  "unidades_mes": "expected_monthly_units", "minutos": "labor_minutes"},
    "gastos": {"nombre": "name", "monto": "amount", "frecuencia": "frequency", "dia": "due_day"},
}  # fmt: skip


def extract_business_from_text(
    workspace: Workspace, user: User | None, text: str, today: date
) -> BusinessOnboardingExtraction:
    """Extrae con IA (lanza AIUnavailable si no hay consentimiento o respuesta válida)."""
    result = run_structured(
        workspace=workspace,
        user=user,
        purpose="onboarding_negocio",
        prompt_name="onboarding_negocio",
        context={"hoy": today.isoformat(), "texto": text[:MAX_TEXT]},
        schema=BusinessOnboardingExtraction,
    )
    return result.data


def to_business_initial(workspace: Workspace, ext: BusinessOnboardingExtraction) -> dict[str, Any]:
    """Valores iniciales de la confirmación y campos a resaltar ("productos-0-unit_cost")."""
    doubtful: set[str] = set()
    for path in ext.campos_dudosos:
        parts = path.split(".")
        if len(parts) == 3 and parts[0] in FIELD_MAP and parts[1].isdigit():
            field = FIELD_MAP[parts[0]].get(parts[2])
            if field:
                doubtful.add(f"{parts[0]}-{parts[1]}-{field}")

    products = []
    for i, p in enumerate(ext.productos):
        if p.costo is None:
            doubtful.add(f"productos-{i}-unit_cost")
        if p.unidades_mes is None:
            doubtful.add(f"productos-{i}-expected_monthly_units")
        products.append(
            {
                "name": p.nombre,
                "price": p.precio,
                "unit_cost": p.costo if p.costo is not None else Decimal("0"),
                "expected_monthly_units": p.unidades_mes,
                "is_service": p.es_servicio,
                "labor_minutes": p.minutos,
            }
        )

    expenses = []
    for i, g in enumerate(ext.gastos):
        category = match_category(workspace, g.nombre, CategoryGroup.GASTO_OPERATIVO)
        if g.dia is None:
            doubtful.add(f"gastos-{i}-due_day")
        expenses.append(
            {
                "name": g.nombre,
                "amount": g.monto,
                "frequency": g.frecuencia,
                "due_day": g.dia,
                "category": category.pk if category else None,
                "is_reducible": False,
            }
        )

    profile: dict[str, Any] = {}
    if ext.actividad:
        profile["activity"] = ext.actividad
    profile["model"] = ext.modelo or (
        "servicios" if products and all(p["is_service"] for p in products) else "productos"
    )
    profile["cobra_itbis"] = bool(ext.cobra_itbis)
    profile["tasa_pct"] = Decimal("18")

    goals = {
        "margen_pct": ext.margen_objetivo_pct,
        "target_profit": ext.ganancia_objetivo,
        "planned_owner_draw": ext.retiro_mensual,
        "cash_reserve": None,
    }
    return {
        "perfil": profile,
        "productos": products,
        "gastos": expenses,
        "efectivo": ext.efectivo,
        "objetivos": goals,
        "dudosos": doubtful,
    }
