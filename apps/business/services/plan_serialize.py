"""JSON del plan de negocio: entradas (`inputs_snapshot`) y cálculo (`computed`).

Montos como texto con 2 decimales; márgenes como "30.00 %" (así el verificador de la narrativa
reconoce los porcentajes calculados)."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from apps.core.money import q

from .cash import OpenDebt
from .indicators import ExpensePlan
from .plan import BusinessPlanInputs, BusinessPlanResult, PlanProduct


def _m(value: Decimal) -> str:
    return str(q(value))


def _p(value: Decimal) -> str:
    return f"{q(value)} %"


def _u(value: Decimal) -> str:
    """Unidades sin ceros de más (10, 2.5)."""
    return f"{value.normalize():f}"


def serialize_business_plan(result: BusinessPlanResult) -> dict[str, Any]:
    proj = result.projection
    return {
        "tipo": "negocio",
        "estado": result.status.value,
        "motivos": result.reasons,
        "ventas": _m(result.sales),
        "costo_de_lo_vendido": _m(result.cogs),
        "ganancia_bruta": _m(result.gross_profit),
        "margen_bruto": _p(result.gross_margin_pct),
        "gastos_operativos": _m(result.operating_expenses),
        "resultado": _m(result.operating_result),
        "ventas_equilibrio": _m(result.break_even_sales) if result.break_even_sales else None,
        "ventas_para_meta": (
            _m(result.sales_for_target_profit) if result.sales_for_target_profit else None
        ),
        "productos": [
            {
                "ref": p.ref,
                "nombre": p.name,
                "unidades": _u(p.units),
                "unidades_estimadas": p.units_estimated,
                "precio": _m(p.price),
                "costo_unitario": _m(p.unit_cost),
                "ventas": _m(p.sales),
                "costo": _m(p.cogs),
                "ganancia_bruta": _m(p.gross_profit),
                "margen": _p(p.margin_pct),
            }
            for p in result.products
        ],
        "caja": {
            "efectivo_inicial": _m(proj.start_cash),
            "saldo_mas_bajo": {
                "fecha": proj.lowest_date.isoformat(),
                "monto": _m(proj.lowest_balance),
            },
            "faltantes_por_fecha": [
                {"fecha": g.date.isoformat(), "monto": _m(g.shortfall), "conceptos": g.causes}
                for g in proj.gaps
            ],
            "saldos": [{"fecha": d.isoformat(), "monto": _m(b)} for d, b in proj.days],
        },
        "retiro_planeado": _m(result.planned_withdrawal),
        "retiro_maximo": _m(result.max_withdrawal),
        "capacidad": (
            {"minutos_disponibles": result.capacity_minutes, "minutos_usados": result.used_minutes}
            if result.capacity_minutes is not None
            else None
        ),
        "supuestos": result.assumptions,
        "alternativas": [
            {
                "codigo": a.code,
                "nombre": a.name,
                "descripcion": a.description,
                "cambios": [
                    {"concepto": c.concept, "de": _m(c.before), "a": _m(c.after)} for c in a.changes
                ],
                "estado": a.status.value,
                "resultado": _m(a.operating_result),
                "saldo_mas_bajo": _m(a.lowest_balance),
                "mejora_resultado": _m(a.result_gain),
                "mejora_caja": _m(a.cash_gain),
                "libera": _m(a.improvement),
            }
            for a in result.alternatives
        ],
    }


def _opt(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _debt(d: OpenDebt) -> dict[str, Any]:
    return {
        "concepto": d.label,
        "saldo": str(d.balance),
        "vence": d.due_date.isoformat() if d.due_date else None,
    }


def business_inputs_to_dict(inputs: BusinessPlanInputs) -> dict[str, Any]:
    return {
        "tipo": "negocio",
        "inicio": inputs.start.isoformat(),
        "fin": inputs.end.isoformat(),
        "hoy": inputs.today.isoformat(),
        "moneda": inputs.currency,
        "productos": [
            {
                "ref": p.ref,
                "nombre": p.name,
                "precio": str(p.price),
                "costo_base": str(p.base_cost),
                "comision": str(p.commission_pct),
                "unidades": str(p.expected_units),
                "unidades_estimadas": p.units_estimated,
                "es_servicio": p.is_service,
                "minutos": p.labor_minutes,
            }
            for p in inputs.products
        ],
        "gastos": [
            {
                "ref": e.ref,
                "nombre": e.name,
                "monto": str(e.amount),
                "frecuencia": e.frequency,
                "dia": e.due_day,
                "reducible": e.is_reducible,
            }
            for e in inputs.expenses
        ],
        "efectivo": str(inputs.cash_now),
        "por_cobrar": [_debt(d) for d in inputs.receivables],
        "por_pagar": [_debt(d) for d in inputs.payables],
        "gastos_pagados_mes": sorted(inputs.paid_this_month),
        "margen_objetivo": _opt(inputs.target_margin),
        "ganancia_objetivo": _opt(inputs.target_profit),
        "reserva": str(inputs.cash_reserve),
        "retiro": str(inputs.planned_withdrawal),
        "horas_disponibles": inputs.hours_available,
    }


def business_inputs_from_dict(data: dict[str, Any]) -> BusinessPlanInputs:
    def debt(d: dict[str, Any]) -> OpenDebt:
        due = datetime.date.fromisoformat(d["vence"]) if d["vence"] else None
        return OpenDebt(label=d["concepto"], balance=Decimal(d["saldo"]), due_date=due)

    def opt(value: str | None) -> Decimal | None:
        return None if value is None else Decimal(value)

    return BusinessPlanInputs(
        start=datetime.date.fromisoformat(data["inicio"]),
        end=datetime.date.fromisoformat(data["fin"]),
        today=datetime.date.fromisoformat(data["hoy"]),
        currency=data["moneda"],
        products=tuple(
            PlanProduct(
                ref=p["ref"],
                name=p["nombre"],
                price=Decimal(p["precio"]),
                base_cost=Decimal(p["costo_base"]),
                commission_pct=Decimal(p["comision"]),
                expected_units=Decimal(p["unidades"]),
                units_estimated=p["unidades_estimadas"],
                is_service=p["es_servicio"],
                labor_minutes=p["minutos"],
            )
            for p in data["productos"]
        ),
        expenses=tuple(
            ExpensePlan(
                ref=e["ref"],
                name=e["nombre"],
                amount=Decimal(e["monto"]),
                frequency=e["frecuencia"],
                due_day=e["dia"],
                is_reducible=e["reducible"],
            )
            for e in data["gastos"]
        ),
        cash_now=Decimal(data["efectivo"]),
        receivables=tuple(debt(d) for d in data["por_cobrar"]),
        payables=tuple(debt(d) for d in data["por_pagar"]),
        paid_this_month=frozenset(data["gastos_pagados_mes"]),
        target_margin=opt(data["margen_objetivo"]),
        target_profit=opt(data["ganancia_objetivo"]),
        cash_reserve=Decimal(data["reserva"]),
        planned_withdrawal=Decimal(data["retiro"]),
        hours_available=data["horas_disponibles"],
    )
