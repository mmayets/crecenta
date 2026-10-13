"""Riesgo de caja por fechas y reserva operativa del negocio (funciones puras).

Reglas conservadoras (docs/decisiones.md):
- Lo que **sale** cuenta siempre: CxP en su vencimiento (vencidas o sin fecha: hoy) y gastos
  operativos previstos en sus fechas.
- Lo que **entra** solo se proyecta para CxC con fecha futura; las vencidas o sin fecha no se
  cuentan (no se sabe cuándo llegarán).
- El **retiro seguro** del propietario no cuenta ningún cobro futuro: es lo que sobra del efectivo
  después de cubrir todos los compromisos del horizonte y la reserva fijada.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.dates import clamp_day, monthly_dates, weekly_dates
from apps.core.money import ZERO, fmt

from .indicators import ExpensePlan

DEFAULT_HORIZON_DAYS = 30


@dataclass(frozen=True)
class CashItem:
    date: datetime.date
    amount: Decimal  # siempre positivo
    label: str
    kind: str  # cxc | cxp | gasto


@dataclass(frozen=True)
class OpenDebt:
    label: str
    balance: Decimal
    due_date: datetime.date | None


@dataclass(frozen=True)
class CashGap:
    date: datetime.date
    balance: Decimal  # saldo proyectado (negativo o bajo la reserva)
    shortfall: Decimal  # cuánto falta para cubrir ese día (y la reserva)
    causes: list[str]


@dataclass(frozen=True)
class CashProjection:
    start_cash: Decimal
    days: list[tuple[datetime.date, Decimal]]  # saldo al cierre de cada día con movimientos
    gaps: list[CashGap]
    lowest_balance: Decimal
    lowest_date: datetime.date


@dataclass(frozen=True)
class ReserveResult:
    cash: Decimal
    committed: Decimal  # salidas del horizonte
    reserve: Decimal  # reserva de efectivo fijada por la persona
    available: Decimal  # efectivo − comprometido − reserva (puede ser negativo)
    max_safe_withdrawal: Decimal  # nunca negativo
    horizon_end: datetime.date
    items: list[CashItem] = field(default_factory=list)

    def message(self, currency: str) -> str:
        if self.committed == 0 and self.reserve == 0:
            return (
                f"El negocio tiene {fmt(self.cash, currency)} en efectivo y no hay pagos "
                "registrados en los próximos días."
            )
        needed = self.committed + self.reserve
        base = (
            f"El negocio tiene {fmt(self.cash, currency)} en efectivo, pero necesita "
            f"{fmt(needed, currency)} para los compromisos registrados"
            + (" y la reserva" if self.reserve else "")
            + ". "
        )
        if self.max_safe_withdrawal > 0:
            return base + (
                f"Puedes retirar hasta {fmt(self.max_safe_withdrawal, currency)} sin dejar pagos "
                "sin cubrir."
            )
        return base + "Ahora mismo no conviene retirar dinero."


def expense_dates(
    expense: ExpensePlan, start: datetime.date, end: datetime.date
) -> list[datetime.date]:
    """Fechas de un gasto previsto en [start, end].

    - mensual: el `due_day` de cada mes; quincenal: `due_day` y 15 días después (o antes).
    - semanal: `due_day` es el día de la semana (1 = lunes … 7 = domingo).
    - sin día: se asume que vence al inicio del rango (y luego cada semana o mes).
    """
    if expense.frequency == "semanal":
        weekday = (expense.due_day - 1) % 7 if expense.due_day else start.weekday()
        return weekly_dates(start, end, weekday)
    if expense.due_day is None:
        return monthly_dates(start, end, start.day)
    days = [expense.due_day]
    if expense.frequency == "quincenal":
        days.append(expense.due_day + 15 if expense.due_day <= 15 else expense.due_day - 15)
    result: list[datetime.date] = []
    for day in days:
        result.extend(monthly_dates(start, end, day))
    return sorted(result)


def commitments(
    today: datetime.date,
    horizon_end: datetime.date,
    payables: list[OpenDebt],
    expenses: list[ExpensePlan],
    paid_this_month: frozenset[str] = frozenset(),
) -> list[CashItem]:
    """Salidas previstas entre hoy y `horizon_end`.

    `paid_this_month`: refs de gastos mensuales que ya se pagaron este mes (no se vuelven a contar
    en lo que queda del mes)."""
    items = [
        CashItem(
            date=max(today, p.due_date) if p.due_date else today,
            amount=p.balance,
            label=p.label,
            kind="cxp",
        )
        for p in payables
        if p.balance > 0 and (p.due_date is None or p.due_date <= horizon_end)
    ]
    month_end = clamp_day(today.year, today.month, 31)
    for e in expenses:
        for when in expense_dates(e, today, horizon_end):
            if e.frequency == "mensual" and e.ref in paid_this_month and when <= month_end:
                continue
            items.append(CashItem(date=when, amount=e.amount, label=e.name, kind="gasto"))
    return sorted(items, key=lambda i: (i.date, i.label))


def expected_inflows(
    today: datetime.date, horizon_end: datetime.date, receivables: list[OpenDebt]
) -> list[CashItem]:
    return sorted(
        (
            CashItem(date=r.due_date, amount=r.balance, label=r.label, kind="cxc")
            for r in receivables
            if r.balance > 0 and r.due_date is not None and today <= r.due_date <= horizon_end
        ),
        key=lambda i: (i.date, i.label),
    )


def cash_projection(
    cash_now: Decimal,
    today: datetime.date,
    outflows: list[CashItem],
    inflows: list[CashItem],
    reserve: Decimal = ZERO,
) -> CashProjection:
    """Saldo día a día con los movimientos previstos; marca los días en que no alcanza.

    En un mismo día primero entran los cobros y luego salen los pagos."""
    by_day: dict[datetime.date, list[CashItem]] = defaultdict(list)
    for item in [*inflows, *outflows]:
        by_day[item.date].append(item)
    balance = cash_now
    days: list[tuple[datetime.date, Decimal]] = []
    gaps: list[CashGap] = []
    lowest, lowest_date = cash_now, today
    for day in sorted(by_day):
        items = by_day[day]
        for i in items:
            balance += i.amount if i.kind == "cxc" else -i.amount
        days.append((day, balance))
        if balance < lowest:
            lowest, lowest_date = balance, day
        if balance < reserve:
            gaps.append(
                CashGap(
                    date=day,
                    balance=balance,
                    shortfall=reserve - balance,
                    causes=[i.label for i in items if i.kind != "cxc"],
                )
            )
    return CashProjection(
        start_cash=cash_now, days=days, gaps=gaps, lowest_balance=lowest, lowest_date=lowest_date
    )


def operating_reserve(
    cash_now: Decimal,
    today: datetime.date,
    outflows: list[CashItem],
    reserve: Decimal = ZERO,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> ReserveResult:
    committed = sum((i.amount for i in outflows), ZERO)
    available = cash_now - committed - reserve
    return ReserveResult(
        cash=cash_now,
        committed=committed,
        reserve=reserve,
        available=available,
        max_safe_withdrawal=max(ZERO, available),
        horizon_end=today + datetime.timedelta(days=horizon_days),
        items=outflows,
    )
