"""Serialización del plan calculado a JSON ("computed").

Es lo que se guarda en `PlanVersion.computed` y lo que la IA recibe (sin `ref` internos). Los montos
van como texto con 2 decimales para conservar la exactitud de Decimal.
"""

from __future__ import annotations

from typing import Any

from apps.core.money import q
from apps.personal.services.types import BudgetResult


def _m(value: Any) -> str:
    return str(q(value))


def serialize_plan(result: BudgetResult, *, include_refs: bool = True) -> dict[str, Any]:
    names = {line.ref: line.name for line in result.lines}
    lowest = min(result.timeline, key=lambda p: (p.balance, p.date)) if result.timeline else None

    def ref(value: str) -> dict[str, str]:
        return {"ref": value} if include_refs else {}

    return {
        "periodo": {
            "inicio": result.period.start.isoformat(),
            "fin": result.period.end.isoformat(),
            "dias": result.period.days,
        },
        "estado": result.status.value,
        "ingreso_total": _m(result.income_total),
        "ingreso_es_estimado": result.income_is_estimate,
        "totales": {kind: _m(amount) for kind, amount in result.totals_by_kind.items()},
        "total_asignado": _m(result.total_assigned),
        "reserva_minima": _m(result.reserve_minimum),
        "faltante_total": _m(result.deficit),
        "faltantes_por_fecha": [
            {"fecha": s.date.isoformat(), "monto": _m(s.amount), "conceptos": list(s.labels)}
            for s in result.shortfalls
        ],
        "saldo_mas_bajo": (
            {"fecha": lowest.date.isoformat(), "monto": _m(lowest.balance)} if lowest else None
        ),
        "lineas": [
            {
                **ref(line.ref),
                "tipo": line.kind.value,
                "nombre": line.name,
                "monto": _m(line.amount),
                "vencimientos": [d.isoformat() for d in line.due_dates],
                **({"categoria_ref": line.category_ref} if include_refs else {}),
            }
            for line in result.lines
        ],
        "reparto_por_cobro": [
            {
                "fecha": e.date.isoformat(),
                "cobro": _m(e.income),
                "compromisos": _m(e.commitments),
                "ahorro": _m(e.savings),
                "esenciales": _m(e.essentials),
                "ocio": _m(e.discretionary),
                "reserva": _m(e.reserve),
            }
            for e in result.by_pay_event
        ],
        "alternativas": [
            {
                "codigo": a.code,
                "nombre": a.name,
                "descripcion": a.description,
                "cambios": [
                    {
                        **ref(c.target),
                        "concepto": names.get(c.target, c.label),
                        "de": _m(c.before),
                        "a": _m(c.after),
                    }
                    for c in a.changes
                ],
                "libera": _m(a.freed),
                "estado_resultante": a.status.value,
                "faltante_resultante": _m(a.deficit),
                "faltante_por_fecha_resultante": _m(a.max_shortfall),
                "toca_prioritario": a.touches_priority,
            }
            for a in result.alternatives
        ],
        "supuestos": list(result.assumptions),
    }
