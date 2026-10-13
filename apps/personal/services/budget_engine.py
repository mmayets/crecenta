"""Motor determinístico del plan personal por período (docs/arquitectura.md §3, encargo §7).

Pasos:
1. Ingreso neto del período según frecuencia y días reales de cobro.
2. Reserva de compromisos fijos y cuotas de deuda con su fecha de vencimiento.
3. Esenciales variables (estimado del usuario o promedio del historial).
4. Meta de ahorro (meta diaria con días reales y días seleccionados).
5. Restante → ocio/discrecional y reserva para variaciones (mínimo `reserve_pct` de esenciales).
6. Viabilidad doble: total del período y línea de tiempo de caja por fechas.
7. Si no es viable (o queda ajustado), alternativas calculadas por reglas y recalculadas aquí.

La IA nunca calcula: recibe este resultado ya hecho.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal

from apps.core.dates import monthly_dates
from apps.core.money import ZERO, fmt, q, split_proportionally
from apps.core.periods import (
    Frequency,
    PayEvent,
    Period,
    pay_events,
    scheduled_dates,
    total_income,
)
from apps.personal.services.cash_timeline import (
    ScheduledOutflow,
    build_timeline,
    find_shortfalls,
    lowest_point,
)
from apps.personal.services.savings import contributions_in_period, split_across_pay_events
from apps.personal.services.types import (
    BudgetResult,
    CommitmentInput,
    LineKind,
    PayEventAllocation,
    PersonalInputs,
    PlanLine,
    PlanStatus,
    ScheduledItem,
)

DISCRETIONARY_REF = "discrecional"
RESERVE_REF = "reserva"

Compute = Callable[[PersonalInputs], BudgetResult]


def build_personal_plan(inputs: PersonalInputs, *, with_alternatives: bool = True) -> BudgetResult:
    result = compute_plan(inputs)
    if with_alternatives and result.status != PlanStatus.VIABLE:
        from apps.personal.services.alternatives import generate_alternatives

        result = replace(result, alternatives=generate_alternatives(inputs, result, compute_plan))
    return result


def covering_event_index(day: date, events: list[PayEvent]) -> int:
    """Cobro que cubre una salida: el último anterior o igual a su fecha
    (si vence antes del primer cobro, el primero)."""
    index = 0
    for i, event in enumerate(events):
        if event.date <= day:
            index = i
    return index


def _assign_to_pay_event(due: list[ScheduledOutflow], events: list[PayEvent]) -> list[Decimal]:
    totals = [ZERO] * len(events)
    for out in due:
        totals[covering_event_index(out.date, events)] += out.amount
    return totals


MONTH_NAMES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip


def _annual_provision(
    c: CommitmentInput,
    period: Period,
    events: list[PayEvent],
    lines: list[PlanLine],
    dated: list[ScheduledOutflow],
    assumptions: list[str],
) -> None:
    """Un pago anual se cubre apartando 1/12 en cada período (docs/fase3.md, decisión 5); el pago
    completo sale de lo apartado en su fecha, así que no se vuelve a descontar en el período."""
    if c.amount <= 0:
        return
    provision = q(c.amount / 12)
    when = events[0].date if events else period.start
    lines.append(
        PlanLine(
            ref=c.ref,
            kind=LineKind.COMPROMISO,
            name=f"Apartar para {c.name}",
            amount=provision,
            category_ref=c.category_ref,
            due_dates=(when,),
        )
    )
    dated.append(ScheduledOutflow(when, provision, c.ref, f"Apartar para {c.name}"))
    month = MONTH_NAMES[(c.due_month or 1) - 1]
    assumptions.append(
        f"{c.name}: pago anual de {fmt(q(c.amount))} en {month}; se apartan "
        f"{fmt(provision)} en cada período para tenerlo listo."
    )


def compute_plan(inputs: PersonalInputs) -> BudgetResult:
    period = inputs.period
    events = pay_events(list(inputs.incomes), period)
    income = total_income(events)
    lines: list[PlanLine] = []
    dated: list[ScheduledOutflow] = []
    assumptions: list[str] = []

    # 2. Compromisos y deudas, con sus fechas.
    for c in inputs.commitments:
        if c.frequency == Frequency.ANUAL:
            _annual_provision(c, period, events, lines, dated, assumptions)
            continue
        dates = scheduled_dates(c.frequency, c.due_days(), period)
        if c.amount <= 0 or not dates:
            continue
        lines.append(
            PlanLine(
                ref=c.ref,
                kind=LineKind.COMPROMISO,
                name=c.name,
                amount=q(c.amount * len(dates)),
                category_ref=c.category_ref,
                due_dates=tuple(dates),
            )
        )
        dated.extend(ScheduledOutflow(d, q(c.amount), c.ref, c.name) for d in dates)

    for debt in inputs.debts:
        if debt.balance <= 0 or (debt.end_date and debt.end_date < period.start):
            continue
        left = debt.balance
        debt_dates = []
        for d in monthly_dates(period.start, period.end, debt.due_day):
            if debt.end_date and d > debt.end_date:
                break
            payment = q(min(debt.installment, left))
            if payment <= 0:
                break
            left -= payment
            debt_dates.append(d)
            dated.append(ScheduledOutflow(d, payment, debt.ref, debt.name))
        amount = sum((o.amount for o in dated if o.ref == debt.ref), ZERO)
        if amount > 0:
            lines.append(
                PlanLine(
                    ref=debt.ref,
                    kind=LineKind.DEUDA,
                    name=debt.name,
                    amount=amount,
                    category_ref=debt.category_ref,
                    due_dates=tuple(debt_dates),
                )
            )

    # 3. Esenciales variables.
    essentials_total = ZERO
    for e in inputs.essentials:
        if e.amount <= 0:
            continue
        essentials_total += q(e.amount)
        lines.append(PlanLine(e.ref, LineKind.ESENCIAL, e.name, q(e.amount), e.category_ref))
        if e.from_history:
            assumptions.append(f"{e.name}: promedio de tus últimos períodos registrados.")

    # 4. Ahorro.
    savings_total = ZERO
    savings_by_event = [ZERO] * len(events)
    for goal in inputs.savings:
        amount = contributions_in_period(goal, period)
        if amount <= 0:
            continue
        savings_total += amount
        lines.append(PlanLine(goal.ref, LineKind.AHORRO, goal.purpose, amount, goal.category_ref))
        parts = split_across_pay_events(amount, events, inputs.savings_timing)
        if not parts:
            dated.append(ScheduledOutflow(period.start, amount, goal.ref, goal.purpose))
        for i, (event, part) in enumerate(zip(events, parts, strict=True)):
            savings_by_event[i] += part
            if part > 0:
                dated.append(ScheduledOutflow(event.date, part, goal.ref, goal.purpose))

    fixed_total = sum((ln.amount for ln in lines if ln.kind in _FIXED_KINDS), ZERO)
    core_total = fixed_total + essentials_total + savings_total

    # 5. Discrecional y reserva.
    reserve_min = q(essentials_total * inputs.reserve_pct)
    remaining = income - core_total
    deficit = max(-remaining, ZERO)
    discretionary = reserve = ZERO
    if remaining > 0:
        if inputs.discretionary_wish is not None:
            discretionary = min(q(inputs.discretionary_wish), max(remaining - reserve_min, ZERO))
            reserve = remaining - discretionary
        else:
            reserve = min(reserve_min, remaining)
            discretionary = remaining - reserve
    if discretionary > 0:
        lines.append(
            PlanLine(
                DISCRETIONARY_REF, LineKind.DISCRECIONAL, "Ocio y gastos personales", discretionary
            )
        )
    if reserve > 0:
        lines.append(PlanLine(RESERVE_REF, LineKind.RESERVA, "Reserva para variaciones", reserve))

    # 6. Línea de tiempo de caja.
    dated.sort(key=lambda o: (o.date, o.ref))
    points = build_timeline(
        period, inputs.opening_cash, events, dated, essentials_total + discretionary
    )
    shortfalls = find_shortfalls(points, dated)

    lowest = lowest_point(points)
    wish_unmet = inputs.discretionary_wish is not None and discretionary < inputs.discretionary_wish
    if deficit > 0 or shortfalls or not events:
        status = PlanStatus.NO_VIABLE
    elif reserve < reserve_min or wish_unmet or (lowest and lowest.balance < reserve_min):
        status = PlanStatus.AJUSTADO
    else:
        status = PlanStatus.VIABLE

    # Reparto por cobro.
    allocations: list[PayEventAllocation] = []
    if events:
        fixed_refs = {ln.ref for ln in lines if ln.kind in _FIXED_KINDS}
        commitments_by_event = _assign_to_pay_event(
            [o for o in dated if o.ref in fixed_refs], events
        )
        # Lo flexible (esenciales, ocio, reserva) se reparte según lo que le queda a cada cobro
        # después de sus vencimientos y su ahorro; si ninguno tiene margen, según su monto.
        capacity = [
            max(e.amount - commitments_by_event[i] - savings_by_event[i], ZERO)
            for i, e in enumerate(events)
        ]
        weights = capacity if any(capacity) else [e.amount for e in events]
        essentials_by_event = split_proportionally(essentials_total, weights)
        discretionary_by_event = split_proportionally(discretionary, weights)
        reserve_by_event = split_proportionally(reserve, weights)
        for i, event in enumerate(events):
            allocations.append(
                PayEventAllocation(
                    date=event.date,
                    income=event.amount,
                    commitments=commitments_by_event[i],
                    savings=savings_by_event[i],
                    essentials=essentials_by_event[i],
                    discretionary=discretionary_by_event[i],
                    reserve=reserve_by_event[i],
                )
            )

    totals = {kind.value: ZERO for kind in LineKind}
    for line in lines:
        totals[line.kind.value] += line.amount

    # Detalle de salidas fechadas con el cobro que las cubre. El ahorro va en su propio cobro.
    line_by_ref = {ln.ref: ln for ln in lines}
    scheduled = []
    for out in dated:
        line = line_by_ref[out.ref]
        event_date = events[covering_event_index(out.date, events)].date if events else None
        scheduled.append(
            ScheduledItem(out.date, out.amount, out.ref, line.kind, line.category_ref, event_date)
        )

    income_is_estimate = any(e.is_estimate for e in events)
    if income_is_estimate:
        assumptions.append("Parte del ingreso es variable: se usó tu estimado.")
    if inputs.opening_cash == 0:
        assumptions.append(
            "El plan solo cuenta con lo que cobras en el período, no con dinero guardado antes."
        )
    assumptions.append(
        f"Reserva mínima para variaciones: {q(inputs.reserve_pct * 100)}% de los esenciales "
        f"({fmt(reserve_min)})."
    )
    if not events:
        assumptions.append("No hay cobros registrados en este período.")

    return BudgetResult(
        period=period,
        income_total=income,
        lines=tuple(lines),
        totals_by_kind=totals,
        reserve_minimum=reserve_min,
        deficit=deficit,
        status=status,
        shortfalls=tuple(shortfalls),
        timeline=tuple(points),
        by_pay_event=tuple(allocations),
        scheduled=tuple(scheduled),
        alternatives=(),
        assumptions=tuple(assumptions),
        income_is_estimate=income_is_estimate,
    )


_FIXED_KINDS = frozenset({LineKind.COMPROMISO, LineKind.DEUDA})
