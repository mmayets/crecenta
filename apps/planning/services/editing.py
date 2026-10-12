"""Ediciones de la persona sobre una propuesta. El motor recalcula todo con las entradas editadas.

Formato de `edits` (todos opcionales):
    {"alternativa": "bajar_ahorro",
     "ocio_deseado": "4000.00" | None,
     "reserva_pct": "0.05",
     "esenciales": {"<ref>": "9000.00"},
     "ahorro": {"<ref>": "5000.00"}}       # nuevo aporte por ocurrencia
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError

from apps.core.money import MoneyError, q, to_money
from apps.personal.services.alternatives import inputs_for_alternative
from apps.personal.services.budget_engine import compute_plan
from apps.personal.services.types import PersonalInputs

MAX_RESERVE_PCT = Decimal("0.5")


def _amount(value: Any, field: str) -> Decimal:
    try:
        amount = q(to_money(str(value)))
    except MoneyError as exc:
        raise ValidationError({field: "Monto inválido."}) from exc
    if amount < 0:
        raise ValidationError({field: "El monto no puede ser negativo."})
    return amount


def apply_edits(inputs: PersonalInputs, edits: dict[str, Any]) -> PersonalInputs:
    unknown = set(edits) - {"alternativa", "ocio_deseado", "reserva_pct", "esenciales", "ahorro"}
    if unknown:
        raise ValidationError(f"Cambios no permitidos: {', '.join(sorted(unknown))}")

    if code := edits.get("alternativa"):
        applied = inputs_for_alternative(inputs, str(code), compute_plan)
        if applied is None:
            raise ValidationError({"alternativa": "Esa alternativa no aplica a este plan."})
        inputs = applied

    if "ocio_deseado" in edits:
        value = edits["ocio_deseado"]
        wish = None if value in (None, "") else _amount(value, "ocio_deseado")
        inputs = replace(inputs, discretionary_wish=wish)

    if "reserva_pct" in edits:
        try:
            pct = Decimal(str(edits["reserva_pct"]))
        except ArithmeticError as exc:
            raise ValidationError({"reserva_pct": "Porcentaje inválido."}) from exc
        if not Decimal("0") <= pct <= MAX_RESERVE_PCT:
            raise ValidationError({"reserva_pct": "Debe estar entre 0 % y 50 %."})
        inputs = replace(inputs, reserve_pct=pct)

    essentials = edits.get("esenciales") or {}
    known = {e.ref for e in inputs.essentials}
    if set(essentials) - known:
        raise ValidationError({"esenciales": "Hay un esencial que no está en el plan."})
    inputs = replace(
        inputs,
        essentials=tuple(
            replace(e, amount=_amount(essentials[e.ref], f"esenciales.{e.ref}"), from_history=False)
            if e.ref in essentials
            else e
            for e in inputs.essentials
        ),
    )

    savings = edits.get("ahorro") or {}
    known = {g.ref for g in inputs.savings}
    if set(savings) - known:
        raise ValidationError({"ahorro": "Hay una meta que no está en el plan."})
    return replace(
        inputs,
        savings=tuple(
            replace(g, contribution_amount=_amount(savings[g.ref], f"ahorro.{g.ref}"))
            if g.ref in savings
            else g
            for g in inputs.savings
        ),
    )
