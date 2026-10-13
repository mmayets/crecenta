"""Ediciones de la persona sobre una propuesta de plan de negocio y datos que faltan.

Formato de `edits` (todos opcionales):
    {"alternativa": "subir_precio",
     "unidades": {"<ref producto>": "40"},
     "precios": {"<ref producto>": "900.00"},
     "gastos": {"<ref gasto>": "12000.00"},
     "retiro": "5000.00"}
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError

from apps.core.money import MoneyError, q, to_money

from .plan import ALTERNATIVE_CODES, BusinessPlanInputs, alternative_inputs

ALLOWED = {"alternativa", "unidades", "precios", "gastos", "retiro"}


def _amount(value: Any, field: str) -> Decimal:
    try:
        amount = to_money(str(value))
    except MoneyError as exc:
        raise ValidationError({field: "Valor inválido."}) from exc
    if amount < 0:
        raise ValidationError({field: "No puede ser negativo."})
    return amount


def _mapping(edits: dict[str, Any], key: str) -> dict[str, Any]:
    value = edits.get(key) or {}
    if not isinstance(value, dict):
        raise ValidationError({key: "Formato inválido."})
    return value


def apply_business_edits(inputs: BusinessPlanInputs, edits: dict[str, Any]) -> BusinessPlanInputs:
    unknown = set(edits) - ALLOWED
    if unknown:
        raise ValidationError(f"Cambios no permitidos: {', '.join(sorted(unknown))}")
    code = edits.get("alternativa")
    if code:
        if code not in ALTERNATIVE_CODES:
            raise ValidationError({"alternativa": "Alternativa desconocida."})
        modified = alternative_inputs(inputs, code)
        if modified is None:
            raise ValidationError({"alternativa": "Esta alternativa no aplica a tu plan."})
        inputs = modified[0]

    products = {p.ref: p for p in inputs.products}
    units, prices = _mapping(edits, "unidades"), _mapping(edits, "precios")
    for ref in {*units, *prices}:
        if ref not in products:
            raise ValidationError({"unidades": "Producto desconocido."})
    new_products = tuple(
        replace(
            p,
            expected_units=_amount(units[p.ref], "unidades")
            if p.ref in units
            else p.expected_units,
            units_estimated=p.units_estimated and p.ref not in units,
            price=q(_amount(prices[p.ref], "precios")) if p.ref in prices else p.price,
        )
        for p in inputs.products
    )
    expenses_edit = _mapping(edits, "gastos")
    known = {e.ref for e in inputs.expenses}
    if set(expenses_edit) - known:
        raise ValidationError({"gastos": "Gasto desconocido."})
    new_expenses = tuple(
        replace(e, amount=q(_amount(expenses_edit[e.ref], "gastos")))
        if e.ref in expenses_edit
        else e
        for e in inputs.expenses
    )
    withdrawal = inputs.planned_withdrawal
    if edits.get("retiro") not in (None, ""):
        withdrawal = q(_amount(edits["retiro"], "retiro"))
    return replace(
        inputs, products=new_products, expenses=new_expenses, planned_withdrawal=withdrawal
    )


def business_missing_data(inputs: BusinessPlanInputs) -> list[dict[str, str]]:
    """Qué falta para un plan de negocio confiable (prioridad alta primero)."""
    items: list[dict[str, str]] = []

    def add(campo: str, mensaje: str, impacto: str, prioridad: str, pregunta: str = "") -> None:
        item = {"campo": campo, "mensaje": mensaje, "impacto": impacto, "prioridad": prioridad}
        if pregunta:
            item["pregunta"] = pregunta
        items.append(item)

    if not inputs.products:
        add(
            "productos",
            "No registraste productos o servicios.",
            "Sin productos no se pueden estimar ventas ni ganancia.",
            "alta",
            "¿Qué vendes y a qué precio?",
        )
    without_units = [p.name for p in inputs.products if p.expected_units == 0]
    if without_units:
        add(
            "unidades",
            "Sin ventas esperadas para: " + ", ".join(without_units[:5]) + ".",
            "El plan los cuenta como cero ventas.",
            "alta",
            "¿Cuántas unidades esperas vender al mes de cada uno?",
        )
    without_cost = [p.name for p in inputs.products if p.base_cost == 0]
    if without_cost:
        add(
            "costos",
            "Sin costo registrado: " + ", ".join(without_cost[:5]) + ".",
            "La ganancia de esos productos queda sobrestimada.",
            "alta",
            "¿Cuánto te cuesta hacer o comprar cada uno?",
        )
    if not inputs.expenses:
        add(
            "gastos",
            "No registraste gastos fijos del negocio.",
            "Sin ellos el resultado y el punto de equilibrio quedan inflados.",
            "media",
            "¿Pagas alquiler, nómina, luz o internet del negocio? ¿Cuánto al mes?",
        )
    if inputs.target_margin is None:
        add(
            "margen_objetivo",
            "No definiste un margen objetivo.",
            "No se puede sugerir a qué precio vender.",
            "media",
            "¿Qué porcentaje de cada venta quieres que te quede de ganancia?",
        )
    if inputs.cash_now == 0:
        add(
            "efectivo",
            "Las cuentas del negocio están en cero.",
            "El flujo de caja puede verse peor de lo que es.",
            "baja",
            "¿Cuánto dinero tiene hoy el negocio?",
        )
    order = {"alta": 0, "media": 1, "baja": 2}
    return sorted(items, key=lambda i: order[i["prioridad"]])
