"""Aportes de ahorro por período usando los días reales del calendario."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.core.dates import count_days, count_weekdays
from apps.core.money import ZERO, q, split_proportionally
from apps.core.periods import PayEvent, Period
from apps.personal.services.types import DailyMode, SavingsFrequency, SavingsInput, SavingsTiming


def occurrences_in_period(goal: SavingsInput, period: Period) -> int:
    """Cuántos aportes caen en el período.

    - diaria, todos los días: días reales del período (28–31).
    - diaria, días seleccionados: cuántas veces aparecen esos días de la semana.
    - semanal: una vez por cada semana que inicia en el período (mismo día de la semana que el
      inicio del período), es decir 4 o 5.
    - quincenal: 2. mensual: 1.
    """
    if goal.frequency == SavingsFrequency.DIARIA:
        if goal.daily_mode == DailyMode.DIAS_SELECCIONADOS:
            return count_weekdays(period.start, period.end, set(goal.selected_weekdays))
        return period.days
    if goal.frequency == SavingsFrequency.SEMANAL:
        return count_weekdays(period.start, period.end, {period.start.weekday()})
    if goal.frequency == SavingsFrequency.QUINCENAL:
        return 2
    return 1


def remaining_to_target(goal: SavingsInput) -> Decimal | None:
    if goal.target_amount is None:
        return None
    return max(goal.target_amount - goal.saved_so_far, ZERO)


def contributions_in_period(goal: SavingsInput, period: Period) -> Decimal:
    """Aporte total planificado en el período, sin pasarse de lo que falta para la meta."""
    planned = q(goal.contribution_amount * occurrences_in_period(goal, period))
    remaining = remaining_to_target(goal)
    if remaining is not None:
        planned = min(planned, remaining)
    return planned


def split_across_pay_events(
    amount: Decimal, events: list[PayEvent], timing: SavingsTiming = SavingsTiming.PROPORCIONAL
) -> list[Decimal]:
    """Reparte un monto entre los cobros: proporcional al cobro o todo en el último."""
    if not events:
        return []
    if timing == SavingsTiming.ULTIMO_COBRO:
        return [ZERO] * (len(events) - 1) + [q(amount)]
    return split_proportionally(amount, [e.amount for e in events])


@dataclass(frozen=True)
class GoalProgress:
    saved: Decimal
    expected_to_date: Decimal  # lo que debería llevar aportado en el período a la fecha
    planned_in_period: Decimal
    shortfall: Decimal  # cuánto va por detrás (0 si va al día)
    pct_of_target: Decimal | None

    @property
    def at_risk(self) -> bool:
        return self.shortfall > 0


def goal_progress(
    goal: SavingsInput, period: Period, contributed_in_period: Decimal, today: date
) -> GoalProgress:
    """Avance de la meta en el período: lo esperado crece en proporción a los días transcurridos."""
    planned = contributions_in_period(goal, period)
    elapsed = count_days(period.start, min(today, period.end)) if today >= period.start else 0
    expected = q(planned * elapsed / period.days)
    saved_total = goal.saved_so_far + contributed_in_period
    pct = None
    if goal.target_amount:
        pct = q(saved_total * 100 / goal.target_amount)
    return GoalProgress(
        saved=saved_total,
        expected_to_date=expected,
        planned_in_period=planned,
        shortfall=max(expected - contributed_in_period, ZERO),
        pct_of_target=pct,
    )
