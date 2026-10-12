"""Saldos y totales calculados en la base de datos (agregaciones con Decimal).

Solo cuentan los movimientos confirmados: un borrador pendiente de revisión (p. ej. un comprobante
leído por IA) no mueve saldos hasta que el usuario lo confirma.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db.models import Case, DecimalField, F, Q, QuerySet, Sum, Value, When

from apps.core.money import ZERO
from apps.ledger.choices import Direction, TxStatus
from apps.ledger.models import Account, Transaction
from apps.ledger.services.classification import EXPENSE_KINDS, INCOME_KINDS
from apps.workspaces.models import Workspace

_MONEY = DecimalField(max_digits=16, decimal_places=2)
_SIGNED = Case(
    When(direction=Direction.IN, then=F("amount")),
    default=-F("amount"),
    output_field=_MONEY,
)


def confirmed(workspace: Workspace) -> QuerySet[Transaction]:
    return Transaction.objects.for_workspace(workspace).filter(status=TxStatus.CONFIRMADO)


def _as_of(qs: QuerySet[Transaction], as_of: date | None) -> QuerySet[Transaction]:
    return qs.filter(date__lte=as_of) if as_of else qs


def balances_by_account(workspace: Workspace, as_of: date | None = None) -> dict[UUID, Decimal]:
    """Saldo de cada cuenta del espacio (saldo inicial + movimientos confirmados hasta `as_of`)."""
    tx_filter = Q(transactions__status=TxStatus.CONFIRMADO)
    if as_of:
        tx_filter &= Q(transactions__date__lte=as_of)
    signed = Case(
        When(transactions__direction=Direction.IN, then=F("transactions__amount")),
        When(transactions__direction=Direction.OUT, then=-F("transactions__amount")),
        default=Value(ZERO),
        output_field=_MONEY,
    )
    rows = (
        Account.objects.for_workspace(workspace)
        .annotate(movements=Sum(signed, filter=tx_filter, default=ZERO))
        .values_list("id", "opening_balance", "movements")
    )
    return {pk: opening + movements for pk, opening, movements in rows}


def account_balance(account: Account, as_of: date | None = None) -> Decimal:
    qs = _as_of(confirmed(account.workspace).filter(account=account), as_of)
    movements: Decimal = qs.aggregate(total=Sum(_SIGNED, default=ZERO))["total"]
    balance: Decimal = account.opening_balance + movements
    return balance


def total_balance(workspace: Workspace, as_of: date | None = None) -> Decimal:
    """'Disponible en tus cuentas': suma de los saldos de todas las cuentas."""
    return sum(balances_by_account(workspace, as_of).values(), ZERO)


def spent_by_category(workspace: Workspace, start: date, end: date) -> dict[UUID | None, Decimal]:
    """Gasto confirmado por categoría en [start, end]. Excluye transferencias y préstamos."""
    rows = (
        confirmed(workspace)
        .filter(date__range=(start, end), kind__in=EXPENSE_KINDS, direction=Direction.OUT)
        .values("category_id")
        .annotate(total=Sum("amount"))
    )
    return {row["category_id"]: row["total"] for row in rows}


def income_total(workspace: Workspace, start: date, end: date) -> Decimal:
    """Ingresos confirmados en [start, end]. Excluye préstamos y transferencias."""
    total: Decimal = (
        confirmed(workspace)
        .filter(date__range=(start, end), kind__in=INCOME_KINDS, direction=Direction.IN)
        .aggregate(total=Sum("amount", default=ZERO))["total"]
    )
    return total


def expense_total(workspace: Workspace, start: date, end: date) -> Decimal:
    return sum(spent_by_category(workspace, start, end).values(), ZERO)
