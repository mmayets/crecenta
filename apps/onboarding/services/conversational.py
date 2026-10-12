"""Onboarding conversacional: la persona describe su situación en lenguaje natural, la IA la
extrae a un esquema estricto y el sistema muestra una tabla editable. Nada se guarda hasta que la
persona confirma."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.accounts.models import User
from apps.ai.schemas import OnboardingExtraction
from apps.ai.services.client import run_structured
from apps.ledger.choices import CategoryGroup
from apps.ledger.services.categories import match_category
from apps.workspaces.models import Workspace

MAX_TEXT = 4000

# Campo de la extracción → campo del formulario, por sección.
FIELD_MAP: dict[str, dict[str, str]] = {
    "ingresos": {"nombre": "name", "monto": "net_amount", "frecuencia": "frequency",
                 "dias_cobro": "dia_1"},
    "cuentas": {"nombre": "name", "tipo": "type", "saldo": "opening_balance"},
    "compromisos": {"nombre": "name", "monto": "amount", "frecuencia": "frequency",
                    "dia_vencimiento": "due_day", "categoria": "category"},
    "deudas": {"nombre": "name", "cuota": "installment", "saldo": "balance",
               "dia_pago": "due_day", "tasa_anual": "interest_rate"},
    "metas_ahorro": {"proposito": "purpose", "meta": "target_amount",
                     "aporte": "contribution_amount", "frecuencia": "contribution_frequency",
                     "plazo": "deadline"},
}  # fmt: skip
SECTION_PREFIX = {"metas_ahorro": "ahorro"}


def extract_from_text(
    workspace: Workspace, user: User | None, text: str, today: date
) -> OnboardingExtraction:
    """Extrae con IA (lanza AIUnavailable si no hay consentimiento o no hay respuesta válida)."""
    result = run_structured(
        workspace=workspace,
        user=user,
        purpose="onboarding_extraccion",
        prompt_name="onboarding_extraccion",
        context={"hoy": today.isoformat(), "texto": text[:MAX_TEXT]},
        schema=OnboardingExtraction,
    )
    return result.data


def to_initial(workspace: Workspace, ext: OnboardingExtraction) -> dict[str, Any]:
    """Valores iniciales de la tabla de confirmación y campos a resaltar.

    Devuelve {"ingresos": [...], "cuentas": [...], "compromisos": [...], "deudas": [...],
    "ahorro": [...], "esenciales": {cat_<pk>: monto}, "ocio_deseado": …,
    "dudosos": {"compromisos-0-due_day", …}}.
    """
    doubtful: set[str] = set()
    for path in ext.campos_dudosos:
        parts = path.split(".")
        if len(parts) == 3 and parts[0] in FIELD_MAP and parts[1].isdigit():
            field = FIELD_MAP[parts[0]].get(parts[2])
            if field:
                doubtful.add(f"{SECTION_PREFIX.get(parts[0], parts[0])}-{parts[1]}-{field}")

    incomes = []
    for i, item in enumerate(ext.ingresos):
        row: dict[str, Any] = {
            "name": item.nombre,
            "net_amount": item.monto,
            "frequency": item.frecuencia,
        }
        if item.frecuencia == "semanal":
            row["dia_semana"] = item.dias_cobro[0] if item.dias_cobro else None
        else:
            row["dia_1"] = item.dias_cobro[0] if item.dias_cobro else None
            row["dia_2"] = item.dias_cobro[1] if len(item.dias_cobro) > 1 else None
        if not item.dias_cobro:
            doubtful.add(f"ingresos-{i}-dia_1")
        incomes.append(row)

    commitments = []
    for i, c in enumerate(ext.compromisos):
        category = match_category(
            workspace,
            c.categoria or c.nombre,
            CategoryGroup.COMPROMISO_FIJO,
            CategoryGroup.ESENCIAL_VARIABLE,
            CategoryGroup.DISCRECIONAL,
        )
        if category is None:
            doubtful.add(f"compromisos-{i}-category")
        if c.dia_vencimiento is None:
            doubtful.add(f"compromisos-{i}-due_day")
        commitments.append(
            {
                "name": c.nombre,
                "amount": c.monto,
                "frequency": c.frecuencia,
                "due_day": c.dia_vencimiento,
                "category": category.pk if category else None,
                "is_fixed": True,
            }
        )

    essentials: dict[str, Any] = {}
    unmatched: list[dict[str, Any]] = []
    for e in ext.esenciales:
        category = match_category(workspace, e.categoria, CategoryGroup.ESENCIAL_VARIABLE)
        if category is None:
            unmatched.append({"nombre": e.categoria, "monto": e.monto})
            continue
        key = f"cat_{category.pk}"
        essentials[key] = essentials.get(key, 0) + e.monto

    debts = []
    for i, d in enumerate(ext.deudas):
        if d.dia_pago is None:
            doubtful.add(f"deudas-{i}-due_day")
        debts.append(
            {
                "name": d.nombre,
                "installment": d.cuota,
                "balance": d.saldo,
                "due_day": d.dia_pago,
                "interest_rate": d.tasa_anual,
            }
        )

    return {
        "ingresos": incomes,
        "cuentas": [
            {"name": a.nombre, "type": a.tipo, "opening_balance": a.saldo} for a in ext.cuentas
        ],
        "compromisos": commitments,
        "deudas": debts,
        "ahorro": [
            {
                "purpose": g.proposito,
                "target_amount": g.meta,
                "contribution_amount": g.aporte,
                "contribution_frequency": g.frecuencia,
                "daily_mode": "todos_los_dias",
                "deadline": g.plazo,
            }
            for g in ext.metas_ahorro
        ],
        "esenciales": essentials,
        "sin_categoria": unmatched,
        "ocio_deseado": ext.ocio_deseado,
        "dudosos": doubtful,
    }
