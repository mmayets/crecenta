"""Alternativas por reglas cuando el plan no es viable o queda ajustado.

Cada alternativa modifica las entradas y se **recalcula con el mismo motor**: su estado, faltante e
impacto en RD$ son cifras del motor, nunca estimaciones. La IA solo las redacta y prioriza.

Reglas (en orden):
- reducir_discrecional: ocio a cero.
- repartir_entre_cobros: separar el ahorro en el último cobro para aliviar las primeras fechas.
- usar_reserva: dejar la reserva en cero para cubrir el ocio deseado.
- reducir_esenciales: recortar hasta 15 % de los esenciales que marcaste como "reducibles".
- bajar_ahorro: reducir el aporte lo justo para cubrir el faltante.
- aplazar_ahorro: no aportar este período.
- combinada: si ninguna sola basta, ocio a cero + recorte de reducibles + ahorro lo necesario.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal

from apps.core.money import CENT, ZERO, q
from apps.personal.services.savings import contributions_in_period
from apps.personal.services.types import (
    Alternative,
    BudgetResult,
    Change,
    LineKind,
    PersonalInputs,
    PlanStatus,
    Priority,
    SavingsTiming,
)

Compute = Callable[[PersonalInputs], BudgetResult]

MAX_ESSENTIAL_CUT = Decimal("0.15")
_STATUS_RANK = {PlanStatus.VIABLE: 0, PlanStatus.AJUSTADO: 1, PlanStatus.NO_VIABLE: 2}


def _gap(result: BudgetResult) -> Decimal:
    """Lo que falta cubrir: el faltante total o, si el total cuadra, el mayor faltante por fecha."""
    return max(result.deficit, result.max_shortfall)


def _improves(before: BudgetResult, after: BudgetResult) -> bool:
    if _STATUS_RANK[after.status] < _STATUS_RANK[before.status]:
        return True
    return after.status == before.status == PlanStatus.NO_VIABLE and _gap(after) < _gap(before)


def _savings_total(inputs: PersonalInputs) -> Decimal:
    return sum((contributions_in_period(g, inputs.period) for g in inputs.savings), ZERO)


def _scale_savings(inputs: PersonalInputs, reduce_by: Decimal) -> PersonalInputs:
    """Reduce los aportes proporcionalmente para bajar el total del período en `reduce_by`
    (redondeando el aporte hacia abajo para no dejar centavos de faltante)."""
    total = _savings_total(inputs)
    if total <= 0:
        return inputs
    factor = max(total - reduce_by, ZERO) / total
    goals = tuple(
        replace(
            g,
            contribution_amount=(g.contribution_amount * factor).quantize(
                CENT, rounding=ROUND_DOWN
            ),
        )
        for g in inputs.savings
    )
    return replace(inputs, savings=goals)


def _cut_reducible(inputs: PersonalInputs, needed: Decimal) -> PersonalInputs:
    reducible = [
        e
        for e in inputs.essentials
        if e.category_ref and inputs.preferences.get(e.category_ref) == Priority.REDUCIBLE
    ]
    capacity = sum((q(e.amount * MAX_ESSENTIAL_CUT) for e in reducible), ZERO)
    if capacity <= 0:
        return inputs
    share = min(needed, capacity) / capacity
    new = tuple(
        replace(e, amount=q(e.amount - q(e.amount * MAX_ESSENTIAL_CUT) * share))
        if e in reducible
        else e
        for e in inputs.essentials
    )
    return replace(inputs, essentials=new)


def _savings_is_priority(inputs: PersonalInputs) -> bool:
    return any(
        g.category_ref and inputs.preferences.get(g.category_ref) == Priority.PRIORITARIO
        for g in inputs.savings
    )


def _diff(before: BudgetResult, after: BudgetResult) -> tuple[Change, ...]:
    refs = {ln.ref for ln in before.lines} | {ln.ref for ln in after.lines}
    changes = []
    for ref in sorted(refs):
        old, new = before.line(ref), after.line(ref)
        a, b = (old.amount if old else ZERO), (new.amount if new else ZERO)
        if a != b:
            changes.append(Change(ref, (old or new).name, a, b))  # type: ignore[union-attr]
    return tuple(changes)


def _freed(before: BudgetResult, after: BudgetResult, kinds: set[LineKind]) -> Decimal:
    return max(before.total(*kinds) - after.total(*kinds), ZERO)


_Candidate = tuple[str, str, str, PersonalInputs, set[LineKind], bool]


def _candidates(inputs: PersonalInputs, result: BudgetResult) -> list[_Candidate]:
    """Alternativas simples posibles (código, nombre, descripción, entradas nuevas, líneas que
    libera, toca algo prioritario)."""
    gap = _gap(result)
    savings_total = _savings_total(inputs)
    savings_priority = _savings_is_priority(inputs)
    candidates: list[_Candidate] = []

    if result.total(LineKind.DISCRECIONAL) > 0 or (
        inputs.discretionary_wish and result.status == PlanStatus.NO_VIABLE
    ):
        candidates.append(
            (
                "reducir_discrecional",
                "Reducir el ocio",
                "Pospón los gastos de ocio este período.",
                replace(inputs, discretionary_wish=ZERO),
                {LineKind.DISCRECIONAL},
                False,
            )
        )
    if (
        result.shortfalls
        and savings_total > 0
        and len(result.by_pay_event) > 1
        and inputs.savings_timing == SavingsTiming.PROPORCIONAL
    ):
        candidates.append(
            (
                "repartir_entre_cobros",
                "Separar el ahorro en el último cobro",
                "Aparta el ahorro del período cuando recibas tu último cobro, después de cubrir "
                "los pagos de las primeras fechas.",
                replace(inputs, savings_timing=SavingsTiming.ULTIMO_COBRO),
                set(),
                False,
            )
        )
    if (
        result.status == PlanStatus.AJUSTADO
        and inputs.discretionary_wish is not None
        and result.total(LineKind.DISCRECIONAL) < inputs.discretionary_wish
        and result.total(LineKind.RESERVA) > 0
    ):
        candidates.append(
            (
                "usar_reserva",
                "Usar la reserva para el ocio",
                "Destina la reserva para variaciones al ocio que deseas; quedarás sin colchón.",
                replace(inputs, reserve_pct=ZERO),
                {LineKind.RESERVA},
                False,
            )
        )
    if gap > 0:
        cut = _cut_reducible(inputs, gap)
        if cut is not inputs:
            candidates.append(
                (
                    "reducir_esenciales",
                    "Recortar gastos reducibles",
                    "Reduce un poco los gastos esenciales que marcaste como reducibles.",
                    cut,
                    {LineKind.ESENCIAL},
                    False,
                )
            )
        if savings_total > 0 and gap < savings_total:
            candidates.append(
                (
                    "bajar_ahorro",
                    "Bajar el aporte de ahorro",
                    "Aporta menos este período, solo lo necesario para cubrir tus pagos.",
                    _scale_savings(inputs, gap),
                    {LineKind.AHORRO},
                    savings_priority,
                )
            )
        if savings_total > 0:
            candidates.append(
                (
                    "aplazar_ahorro",
                    "Aplazar el ahorro este período",
                    "No aportes a tu meta este período y retómala en el siguiente.",
                    _scale_savings(inputs, savings_total),
                    {LineKind.AHORRO},
                    savings_priority,
                )
            )
    return candidates


def _combined_inputs(
    inputs: PersonalInputs, result: BudgetResult, compute: Compute
) -> PersonalInputs:
    combined = _cut_reducible(replace(inputs, discretionary_wish=ZERO), _gap(result))
    return _scale_savings(combined, _gap(compute(combined)))


def generate_alternatives(
    inputs: PersonalInputs, result: BudgetResult, compute: Compute
) -> tuple[Alternative, ...]:
    alternatives: list[Alternative] = []
    for code, name, description, new_inputs, kinds, touches_priority in _candidates(inputs, result):
        after = compute(new_inputs)
        if not _improves(result, after):
            continue
        alternatives.append(_make(code, name, description, result, after, kinds, touches_priority))

    if result.status == PlanStatus.NO_VIABLE and not any(
        a.status != PlanStatus.NO_VIABLE for a in alternatives
    ):
        after = compute(_combined_inputs(inputs, result, compute))
        if _improves(result, after):
            alternatives.append(
                _make(
                    "combinada",
                    "Combinar ajustes",
                    "Reduce el ocio, recorta los gastos reducibles y baja el ahorro lo necesario.",
                    result,
                    after,
                    {LineKind.DISCRECIONAL, LineKind.ESENCIAL, LineKind.AHORRO},
                    _savings_is_priority(inputs),
                )
            )

    order = {a.code: i for i, a in enumerate(alternatives)}
    return tuple(
        sorted(
            alternatives,
            key=lambda a: (_STATUS_RANK[a.status], a.touches_priority, a.deficit, order[a.code]),
        )
    )


def inputs_for_alternative(
    inputs: PersonalInputs, code: str, compute: Compute
) -> PersonalInputs | None:
    """Entradas que resultan de aplicar la alternativa `code` (None si no aplica a este plan).

    Permite que la persona acepte una alternativa: el motor recalcula el plan con estas entradas.
    """
    result = compute(inputs)
    if code == "combinada":
        return _combined_inputs(inputs, result, compute)
    for candidate in _candidates(inputs, result):
        if candidate[0] == code:
            return candidate[3]
    return None


def _make(
    code: str,
    name: str,
    description: str,
    before: BudgetResult,
    after: BudgetResult,
    kinds: set[LineKind],
    touches_priority: bool,
) -> Alternative:
    return Alternative(
        code=code,
        name=name,
        description=description,
        changes=_diff(before, after),
        freed=_freed(before, after, kinds),
        status=after.status,
        deficit=after.deficit,
        max_shortfall=after.max_shortfall,
        touches_priority=touches_priority,
    )
