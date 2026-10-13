"""Períodos de presupuesto y eventos de cobro.

Ver docs/decisiones.md (§7, §8):
- El período es un ciclo mensual anclado al primer día de cobro del ingreso principal
  (p. ej. cobro el 25 → del 25 al 24 del mes siguiente).
- `IncomeInput.net_amount` es el monto neto de **cada cobro** (no el mensual).
- `pay_days` son días del mes (1–31) para mensual/quincenal/variable, o días de la semana
  (0=lunes … 6=domingo) para semanal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from apps.core.dates import add_months, clamp_day, count_days, monthly_dates, weekly_dates
from apps.core.money import ZERO


class Frequency(StrEnum):
    MENSUAL = "mensual"
    QUINCENAL = "quincenal"
    SEMANAL = "semanal"
    VARIABLE = "variable"
    ANUAL = "anual"  # solo compromisos (marbete, seguro, inscripción); nunca ingresos


# Cobros esperados por frecuencia (número de días de cobro requeridos).
_REQUIRED_PAY_DAYS = {Frequency.MENSUAL: 1, Frequency.QUINCENAL: 2, Frequency.SEMANAL: 1}


@dataclass(frozen=True)
class IncomeInput:
    ref: str
    net_amount: Decimal
    frequency: Frequency
    pay_days: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.net_amount < 0:
            raise ValueError("El ingreso neto no puede ser negativo")
        required = _REQUIRED_PAY_DAYS.get(self.frequency)
        if required is not None and len(self.pay_days) != required:
            raise ValueError(f"La frecuencia {self.frequency} requiere {required} día(s) de cobro")
        if self.frequency == Frequency.SEMANAL:
            if not all(0 <= d <= 6 for d in self.pay_days):
                raise ValueError("Para cobro semanal, el día debe estar entre 0 y 6")
        elif not all(1 <= d <= 31 for d in self.pay_days):
            raise ValueError("Los días de cobro deben estar entre 1 y 31")

    @property
    def is_estimate(self) -> bool:
        return self.frequency == Frequency.VARIABLE

    def monthly_equivalent(self) -> Decimal:
        """Ingreso mensual aproximado (solo para elegir el ingreso principal y para resúmenes)."""
        if self.frequency == Frequency.QUINCENAL:
            return self.net_amount * 2
        if self.frequency == Frequency.SEMANAL:
            return self.net_amount * 52 / 12
        if self.frequency == Frequency.VARIABLE and self.pay_days:
            return self.net_amount * len(self.pay_days)
        return self.net_amount


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("El fin del período no puede ser anterior al inicio")

    @property
    def days(self) -> int:
        return count_days(self.start, self.end)

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def days_elapsed(self, today: date) -> int:
        """Días transcurridos del período hasta `today` inclusive (acotado al período)."""
        if today < self.start:
            return 0
        return count_days(self.start, min(today, self.end))


@dataclass(frozen=True)
class PayEvent:
    date: date
    amount: Decimal
    source_ref: str
    is_estimate: bool = False


def anchor_day(sources: list[IncomeInput]) -> int:
    """Día del mes que inicia el período: primer día de cobro del ingreso principal.

    El ingreso principal es el de mayor equivalente mensual con días de cobro mensuales.
    Si solo hay ingresos semanales o sin fecha, el período es el mes calendario (día 1).
    """
    candidates = [s for s in sources if s.frequency != Frequency.SEMANAL and s.pay_days]
    if not candidates:
        return 1
    primary = max(candidates, key=lambda s: s.monthly_equivalent())
    return min(primary.pay_days)


def period_for(sources: list[IncomeInput], today: date) -> Period:
    """Período que contiene `today` según el día ancla de los ingresos."""
    day = anchor_day(sources)
    start = clamp_day(today.year, today.month, day)
    if start > today:
        year, month = add_months(today.year, today.month, -1)
        start = clamp_day(year, month, day)
    next_year, next_month = add_months(start.year, start.month, 1)
    end = clamp_day(next_year, next_month, day) - timedelta(days=1)
    return Period(start=start, end=end)


def scheduled_dates(frequency: str, days: tuple[int, ...], period: Period) -> list[date]:
    """Fechas en que ocurre algo periódico (cobro o vencimiento) dentro del período.

    - semanal: `days[0]` es el día de la semana (0=lunes).
    - mensual / quincenal / variable con días: cada día del mes indicado (ajustado a fin de mes).
    - sin días: una sola vez, al inicio del período.
    """
    if frequency == Frequency.SEMANAL:
        return weekly_dates(period.start, period.end, days[0])
    if not days:
        return [period.start]
    result: list[date] = []
    for day in days:
        result.extend(monthly_dates(period.start, period.end, day))
    return sorted(result)


def pay_events(sources: list[IncomeInput], period: Period) -> list[PayEvent]:
    """Cobros que ocurren dentro del período, ordenados por fecha.

    Un ingreso variable sin días de cobro se considera recibido al inicio del período y se marca
    como estimado.
    """
    events: list[PayEvent] = []
    for source in sources:
        if source.net_amount == ZERO:
            continue
        dates = scheduled_dates(source.frequency, source.pay_days, period)
        events.extend(
            PayEvent(
                date=d,
                amount=source.net_amount,
                source_ref=source.ref,
                is_estimate=source.is_estimate,
            )
            for d in dates
        )
    return sorted(events, key=lambda e: (e.date, e.source_ref))


def total_income(events: list[PayEvent]) -> Decimal:
    return sum((e.amount for e in events), ZERO)
