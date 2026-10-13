"""Serialización del plan calculado a JSON ("computed").

Es lo que se guarda en `PlanVersion.computed` y lo que la IA recibe (sin `ref` internos). Los montos
van como texto con 2 decimales para conservar la exactitud de Decimal.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from apps.core.money import q
from apps.core.periods import Frequency, IncomeInput, Period
from apps.personal.services.types import (
    BudgetResult,
    CommitmentInput,
    DailyMode,
    DebtInput,
    EssentialInput,
    PersonalInputs,
    Priority,
    SavingsFrequency,
    SavingsInput,
    SavingsTiming,
)


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


# ---------------------------------------------------------------- entradas (inputs_snapshot)


def _d(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def inputs_to_dict(inputs: PersonalInputs) -> dict[str, Any]:
    """Snapshot de las entradas del motor. No contiene cuentas, saldos por cuenta ni datos de la
    persona: solo lo necesario para reproducir el cálculo."""
    return {
        "periodo": {
            "inicio": inputs.period.start.isoformat(),
            "fin": inputs.period.end.isoformat(),
        },
        "ingresos": [
            {
                "ref": i.ref,
                "monto": str(i.net_amount),
                "frecuencia": i.frequency.value,
                "dias": list(i.pay_days),
            }
            for i in inputs.incomes
        ],
        "compromisos": [
            {
                "ref": c.ref,
                "nombre": c.name,
                "monto": str(c.amount),
                "frecuencia": c.frequency.value,
                "dia": c.due_day,
                "categoria_ref": c.category_ref,
                "fijo": c.is_fixed,
                "mes": c.due_month,
            }
            for c in inputs.commitments
        ],
        "deudas": [
            {
                "ref": d.ref,
                "nombre": d.name,
                "cuota": str(d.installment),
                "saldo": str(d.balance),
                "dia": d.due_day,
                "fin": _iso(d.end_date),
                "tasa": None if d.interest_rate is None else str(d.interest_rate),
                "categoria_ref": d.category_ref,
            }
            for d in inputs.debts
        ],
        "esenciales": [
            {
                "ref": e.ref,
                "nombre": e.name,
                "monto": str(e.amount),
                "categoria_ref": e.category_ref,
                "historial": e.from_history,
            }
            for e in inputs.essentials
        ],
        "ahorro": [
            {
                "ref": g.ref,
                "proposito": g.purpose,
                "aporte": str(g.contribution_amount),
                "frecuencia": g.frequency.value,
                "modo_diario": g.daily_mode.value,
                "dias_semana": sorted(g.selected_weekdays),
                "meta": None if g.target_amount is None else str(g.target_amount),
                "ahorrado": str(g.saved_so_far),
                "plazo": _iso(g.deadline),
                "categoria_ref": g.category_ref,
            }
            for g in inputs.savings
        ],
        "ocio_deseado": None
        if inputs.discretionary_wish is None
        else str(inputs.discretionary_wish),
        "reserva_pct": str(inputs.reserve_pct),
        "preferencias": {k: v.value for k, v in inputs.preferences.items()},
        "efectivo_inicial": str(inputs.opening_cash),
        "momento_ahorro": inputs.savings_timing.value,
    }


def inputs_from_dict(data: dict[str, Any]) -> PersonalInputs:
    def dec(value: Any) -> Decimal:
        return Decimal(str(value))

    return PersonalInputs(
        period=Period(
            date.fromisoformat(data["periodo"]["inicio"]),
            date.fromisoformat(data["periodo"]["fin"]),
        ),
        incomes=tuple(
            IncomeInput(i["ref"], dec(i["monto"]), Frequency(i["frecuencia"]), tuple(i["dias"]))
            for i in data["ingresos"]
        ),
        commitments=tuple(
            CommitmentInput(
                ref=c["ref"],
                name=c["nombre"],
                amount=dec(c["monto"]),
                frequency=Frequency(c["frecuencia"]),
                due_day=c["dia"],
                category_ref=c["categoria_ref"],
                is_fixed=c["fijo"],
                due_month=c.get("mes"),
            )
            for c in data["compromisos"]
        ),
        debts=tuple(
            DebtInput(
                ref=d["ref"],
                name=d["nombre"],
                installment=dec(d["cuota"]),
                balance=dec(d["saldo"]),
                due_day=d["dia"],
                end_date=_date(d["fin"]),
                interest_rate=_d(d["tasa"]),
                category_ref=d["categoria_ref"],
            )
            for d in data["deudas"]
        ),
        essentials=tuple(
            EssentialInput(
                ref=e["ref"],
                name=e["nombre"],
                amount=dec(e["monto"]),
                category_ref=e["categoria_ref"],
                from_history=e["historial"],
            )
            for e in data["esenciales"]
        ),
        savings=tuple(
            SavingsInput(
                ref=g["ref"],
                purpose=g["proposito"],
                contribution_amount=dec(g["aporte"]),
                frequency=SavingsFrequency(g["frecuencia"]),
                daily_mode=DailyMode(g["modo_diario"]),
                selected_weekdays=frozenset(g["dias_semana"]),
                target_amount=_d(g["meta"]),
                saved_so_far=dec(g["ahorrado"]),
                deadline=_date(g["plazo"]),
                category_ref=g["categoria_ref"],
            )
            for g in data["ahorro"]
        ),
        discretionary_wish=_d(data["ocio_deseado"]),
        reserve_pct=dec(data["reserva_pct"]),
        preferences={k: Priority(v) for k, v in data["preferencias"].items()},
        opening_cash=dec(data["efectivo_inicial"]),
        savings_timing=SavingsTiming(data["momento_ahorro"]),
    )


def strip_refs(computed: dict[str, Any]) -> dict[str, Any]:
    """Copia del plan calculado sin identificadores internos (para enviar a la IA)."""
    if isinstance(computed, dict):
        return {k: strip_refs(v) for k, v in computed.items() if k not in ("ref", "categoria_ref")}
    if isinstance(computed, list):
        return [strip_refs(v) for v in computed]
    return computed
