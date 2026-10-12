"""Línea de tiempo de caja del período: ¿hay dinero cobrado antes de cada vencimiento?

Modelo (docs/decisiones.md §10, §46):
- Entradas: efectivo inicial + cada cobro en su fecha (se acreditan antes de los pagos del día).
- Salidas fechadas: compromisos y cuotas en su vencimiento; el ahorro en el cobro al que se asigna.
- Gasto variable (esenciales + ocio): se consume de forma lineal a lo largo del período.
- La reserva no es una salida: es dinero que debe seguir disponible.

Se evalúa el saldo al cierre de cada día. Un faltante se marca en cada vencimiento con saldo
negativo y en el primer día de cada tramo negativo causado por el gasto variable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.core.dates import iter_days
from apps.core.money import ZERO, q
from apps.core.periods import PayEvent, Period
from apps.personal.services.types import Shortfall, TimelinePoint


@dataclass(frozen=True)
class ScheduledOutflow:
    date: date
    amount: Decimal
    ref: str
    label: str


def build_timeline(
    period: Period,
    opening_cash: Decimal,
    pay_events: list[PayEvent],
    outflows: list[ScheduledOutflow],
    variable_total: Decimal,
) -> list[TimelinePoint]:
    inflows_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for event in pay_events:
        inflows_by_day[event.date] += event.amount
    outflows_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for out in outflows:
        outflows_by_day[out.date] += out.amount

    points: list[TimelinePoint] = []
    balance = opening_cash
    spent_variable = ZERO
    for index, day in enumerate(iter_days(period.start, period.end), start=1):
        # Acumulado redondeado: la suma diaria cuadra exactamente con el total del período.
        cumulative = q(variable_total * index / period.days)
        variable_today = cumulative - spent_variable
        spent_variable = cumulative
        balance = balance + inflows_by_day[day] - outflows_by_day[day] - variable_today
        points.append(
            TimelinePoint(
                date=day,
                inflows=inflows_by_day[day],
                outflows=outflows_by_day[day],
                variable_spend=variable_today,
                balance=balance,
            )
        )
    return points


def find_shortfalls(
    points: list[TimelinePoint], outflows: list[ScheduledOutflow]
) -> list[Shortfall]:
    by_day: dict[date, list[ScheduledOutflow]] = defaultdict(list)
    for out in outflows:
        by_day[out.date].append(out)

    shortfalls: list[Shortfall] = []
    previous_negative = False
    for point in points:
        negative = point.balance < 0
        due = by_day.get(point.date, [])
        if negative and (due or not previous_negative):
            shortfalls.append(
                Shortfall(
                    date=point.date,
                    amount=-point.balance,
                    refs=tuple(o.ref for o in due),
                    labels=tuple(o.label for o in due) or ("Gastos del día a día",),
                )
            )
        previous_negative = negative
    return shortfalls


def lowest_point(points: list[TimelinePoint]) -> TimelinePoint | None:
    return min(points, key=lambda p: (p.balance, p.date)) if points else None
