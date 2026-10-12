"""Las dos cifras del inicio: "Disponible en tus cuentas" y "Disponible para gastar según tu plan".

Disponible para gastar = saldos − compromisos pendientes − ahorro pendiente − reservas
(y sin contar el saldo de las cuentas marcadas como de ahorro: ese dinero ya está apartado).

Qué se descuenta (docs/decisiones.md §49): lo que el plan asignó a los cobros **ya recibidos**,
porque ese dinero está hoy en tus cuentas:
- compromisos y cuotas no pagados cubiertos por esos cobros (incluye los vencidos sin pagar);
- ahorro de esos cobros que aún no apartas;
- la reserva para variaciones de esos cobros.
Los pagos se reconocen por categoría: lo gastado en la categoría del compromiso durante el período
se aplica a sus vencimientos en orden de fecha. Una salida sin categoría se da por pagada cuando su
fecha ya pasó.

El resultado puede ser negativo: se muestra como faltante, nunca se trunca a cero.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.core.money import ZERO
from apps.personal.services.types import BudgetResult, LineKind, ScheduledItem

_FIXED = {LineKind.COMPROMISO, LineKind.DEUDA}


@dataclass(frozen=True)
class Availability:
    in_accounts: Decimal
    in_savings_accounts: Decimal
    pending_commitments: Decimal
    pending_savings: Decimal
    reserves: Decimal
    next_pay_date: date | None

    @property
    def committed(self) -> Decimal:
        return self.pending_commitments + self.pending_savings + self.reserves

    @property
    def for_spending(self) -> Decimal:
        """Saldos de las cuentas de uso diario (sin las cuentas de ahorro)."""
        return self.in_accounts - self.in_savings_accounts

    @property
    def spendable(self) -> Decimal:
        return self.for_spending - self.committed

    @property
    def is_short(self) -> bool:
        return self.spendable < 0


def _unpaid(items: list[ScheduledItem], paid: Decimal) -> list[tuple[ScheduledItem, Decimal]]:
    """Aplica lo pagado a los vencimientos en orden de fecha; devuelve lo que queda de cada uno."""
    result = []
    for item in sorted(items, key=lambda i: i.date):
        applied = min(paid, item.amount)
        paid -= applied
        result.append((item, item.amount - applied))
    return result


def compute_availability(
    plan: BudgetResult,
    today: date,
    in_accounts: Decimal,
    spent_by_category: dict[str, Decimal],
    savings_contributed: Decimal,
    in_savings_accounts: Decimal = ZERO,
) -> Availability:
    """Función pura: recibe saldos y lo gastado/aportado en el período (ya consultado)."""
    received = {e.date for e in plan.by_pay_event if e.date <= today}

    def covered_by_received(item: ScheduledItem) -> bool:
        return item.pay_event_date is None or item.pay_event_date in received

    by_category: dict[str | None, list[ScheduledItem]] = defaultdict(list)
    for item in plan.scheduled:
        if item.kind in _FIXED:
            by_category[item.category_ref].append(item)

    pending_commitments = ZERO
    for category_ref, items in by_category.items():
        if category_ref is None:
            pending_commitments += sum(
                (i.amount for i in items if i.date >= today and covered_by_received(i)), ZERO
            )
            continue
        for item, left in _unpaid(items, spent_by_category.get(category_ref, ZERO)):
            if covered_by_received(item):
                pending_commitments += left

    savings_due = sum(
        (i.amount for i in plan.scheduled if i.kind == LineKind.AHORRO and covered_by_received(i)),
        ZERO,
    )
    pending_savings = max(savings_due - savings_contributed, ZERO)
    reserves = sum((e.reserve for e in plan.by_pay_event if e.date in received), ZERO)
    upcoming = [e.date for e in plan.by_pay_event if e.date > today]

    return Availability(
        in_accounts=in_accounts,
        in_savings_accounts=in_savings_accounts,
        pending_commitments=pending_commitments,
        pending_savings=pending_savings,
        reserves=reserves,
        next_pay_date=min(upcoming) if upcoming else None,
    )
