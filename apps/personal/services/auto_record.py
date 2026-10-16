"""Registro automático de cobros y pagos fijos en su fecha.

Si la persona lo activó (`PersonalProfile.auto_record`), cada día de cobro entra el monto de cada
ingreso y cada vencimiento de un compromiso de monto fijo sale de la cuenta elegida. Así el saldo
sube y baja solo, sin tener que anotar el sueldo o la luz cada mes.

- Idempotente: cada movimiento lleva un `client_uuid` derivado de (origen, fecha); correr dos veces
  el mismo día no duplica nada.
- No repite lo que la persona ya anotó: si hay un movimiento manual parecido cerca de la fecha
  (mismo ingreso o misma categoría), ese vencimiento se da por registrado.
- Los compromisos de monto variable (luz que cambia cada mes) nunca se registran solos.
- Solo mira hacia atrás `CATCH_UP_DAYS` días y nunca antes de `auto_since`: activarlo hoy no llena
  el historial con meses pasados.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from apps.core.dates import monthly_dates
from apps.core.periods import Frequency, Period, scheduled_dates
from apps.ledger.choices import CategoryGroup, Direction, TxKind, TxSource
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.recording import TxData, record_transaction
from apps.personal.models import Commitment, IncomeSource, PersonalProfile
from apps.personal.services.types import CommitmentInput
from apps.workspaces.models import Workspace

CATCH_UP_DAYS = 7
# Ventanas para reconocer algo que la persona ya anotó a mano.
INCOME_WINDOW = timedelta(days=3)
PAYMENT_WINDOW = timedelta(days=20)
_NAMESPACE = uuid.UUID("6f0e3c55-2b6a-4f1e-9a43-6d1c2a0b7e21")


def auto_uuid(kind: str, ref: object, day: date) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{kind}:{ref}:{day.isoformat()}")


def _account(workspace: Workspace, profile: PersonalProfile) -> Account | None:
    account = profile.auto_account
    if account is not None and not account.is_archived:
        return account
    return (
        Account.objects.for_workspace(workspace).filter(is_archived=False, is_savings=False).first()
    )


def _commitment_dates(commitment: Commitment, period: Period) -> list[date]:
    if commitment.frequency == Frequency.ANUAL:
        return [
            d
            for d in monthly_dates(period.start, period.end, commitment.due_day)
            if d.month == commitment.due_month
        ]
    days = CommitmentInput(
        ref=str(commitment.pk),
        name=commitment.name,
        amount=commitment.amount,
        frequency=Frequency(commitment.frequency),
        due_day=commitment.due_day,
    ).due_days()
    return scheduled_dates(commitment.frequency, days, period)


def _already_noted(workspace: Workspace, direction: str, category: Category | None,
                   day: date, window: timedelta) -> bool:  # fmt: skip
    """¿La persona ya anotó a mano algo de esta categoría cerca de la fecha?"""
    return (
        Transaction.objects.for_workspace(workspace)
        .filter(direction=direction, category=category, date__range=(day - window, day))
        .exclude(source=TxSource.AUTOMATICO)
        .exists()
    )


@transaction.atomic
def record_due(workspace: Workspace, today: date) -> int:
    """Registra lo que venció hasta hoy y aún no está anotado. Devuelve cuántos movimientos creó."""
    if not workspace.is_personal:
        return 0
    profile = PersonalProfile.objects.filter(workspace=workspace, auto_record=True).first()
    if profile is None:
        return 0
    account = _account(workspace, profile)
    if account is None:
        return 0
    start = max(today - timedelta(days=CATCH_UP_DAYS), profile.auto_since or today)
    if start > today:
        return 0
    period = Period(start=start, end=today)
    existing = set(
        Transaction.objects.for_workspace(workspace)
        .filter(source=TxSource.AUTOMATICO, date__gte=start)
        .values_list("client_uuid", flat=True)
    )
    salary = (
        Category.objects.for_workspace(workspace)
        .filter(group=CategoryGroup.INGRESO, name="Salario")
        .first()
    )
    created = 0

    def post(key: uuid.UUID, day: date, amount: Decimal, direction: str, kind: str,
             category: Category | None, description: str) -> None:  # fmt: skip
        nonlocal created
        record_transaction(
            workspace,
            None,
            TxData(
                account=account,
                date=day,
                amount=amount,
                direction=direction,
                kind=kind,
                category=category,
                description=description,
                source=TxSource.AUTOMATICO,
                client_uuid=key,
            ),
        )
        existing.add(key)
        created += 1

    for income in IncomeSource.objects.for_workspace(workspace).filter(is_active=True):
        if not income.pay_days:
            continue  # ingreso variable sin fecha: no se puede adivinar cuándo llega
        for day in scheduled_dates(income.frequency, tuple(income.pay_days), period):
            key = auto_uuid("ingreso", income.pk, day)
            if key in existing or _already_noted(
                workspace, Direction.IN, salary, day, INCOME_WINDOW
            ):
                continue
            post(key, day, income.net_amount, Direction.IN, TxKind.INGRESO, salary, income.name)

    commitments = Commitment.objects.for_workspace(workspace).filter(is_active=True, is_fixed=True)
    for commitment in commitments.select_related("category"):
        for day in _commitment_dates(commitment, period):
            key = auto_uuid("compromiso", commitment.pk, day)
            if key in existing or _already_noted(
                workspace, Direction.OUT, commitment.category, day, PAYMENT_WINDOW
            ):
                continue
            post(key, day, commitment.amount, Direction.OUT, TxKind.GASTO,
                 commitment.category, commitment.name)  # fmt: skip
    return created


def record_due_all(today: date) -> int:
    ids = PersonalProfile.objects.filter(auto_record=True).values_list("workspace_id", flat=True)
    return sum(record_due(w, today) for w in Workspace.objects.filter(pk__in=list(ids)))
