"""Alta de movimientos y transferencias, con validación de pertenencia al espacio."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import User
from apps.core.money import q, to_money
from apps.ledger.choices import AccountType, Direction, TxKind, TxSource, TxStatus
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.classification import TRANSFER_KINDS
from apps.ledger.system_categories import BUSINESS, DEFAULT_ACCOUNT_NAME, PERSONAL
from apps.workspaces.models import Workspace

# Espacio de nombres para derivar el id de la pata de entrada de una transferencia offline.
_TRANSFER_NS = uuid.UUID("6f1c2a7e-3b0d-4c55-9a7e-2f0b8e5c1d42")


def ensure_system_categories(workspace: Workspace) -> int:
    """Crea las categorías del sistema y la cuenta 'Efectivo' si faltan. Devuelve cuántas creó."""
    catalog = PERSONAL if workspace.is_personal else BUSINESS
    existing = set(Category.objects.for_workspace(workspace).values_list("name", flat=True))
    missing = [
        Category(workspace=workspace, name=name, group=group, is_system=True)
        for name, group in catalog
        if name not in existing
    ]
    Category.objects.bulk_create(missing)
    if not Account.objects.for_workspace(workspace).exists():
        Account.objects.create(
            workspace=workspace,
            name=DEFAULT_ACCOUNT_NAME,
            type=AccountType.EFECTIVO,
            currency=workspace.currency,
        )
    return len(missing)


def create_account(
    workspace: Workspace,
    name: str,
    type: str,
    opening_balance: Decimal | str = "0",
    is_savings: bool = False,
) -> Account:
    account = Account(
        workspace=workspace,
        name=name,
        type=type,
        currency=workspace.currency,
        opening_balance=q(to_money(opening_balance)),
        is_savings=is_savings,
    )
    account.full_clean()
    account.save()
    return account


@dataclass(frozen=True)
class TxData:
    account: Account
    date: date
    amount: Decimal
    direction: str
    kind: str
    category: Category | None = None
    description: str = ""
    source: str = TxSource.MANUAL
    status: str = TxStatus.CONFIRMADO
    client_uuid: uuid.UUID | None = None


def record_transaction(workspace: Workspace, user: User | None, data: TxData) -> Transaction:
    """Valida y guarda un movimiento simple (no transferencias)."""
    if data.kind in TRANSFER_KINDS:
        raise ValidationError({"kind": "Use record_transfer para movimientos entre cuentas."})
    tx = Transaction(
        workspace=workspace,
        account=data.account,
        date=data.date,
        amount=q(to_money(data.amount)),
        direction=data.direction,
        kind=data.kind,
        category=data.category,
        description=data.description.strip(),
        source=data.source,
        status=data.status,
        client_uuid=data.client_uuid,
        created_by=user,
    )
    tx.full_clean(validate_constraints=False)
    tx.save()
    return tx


@transaction.atomic
def record_transfer(
    workspace: Workspace,
    user: User | None,
    *,
    from_account: Account,
    to_account: Account,
    amount: Decimal | str,
    on: date,
    kind: str = TxKind.TRANSFERENCIA_INTERNA,
    category: Category | None = None,
    description: str = "",
    source: str = TxSource.MANUAL,
    client_uuid: uuid.UUID | None = None,
) -> tuple[Transaction, Transaction]:
    """Transferencia entre cuentas propias: dos movimientos enlazados que no son gasto ni ingreso.

    `category` (opcional) etiqueta el destino del dinero, p. ej. 'Ahorro' al mover a una cuenta de
    ahorro; sigue sin contar como gasto.
    """
    if kind not in TRANSFER_KINDS:
        raise ValidationError({"kind": "Tipo de transferencia no válido."})
    if from_account.pk == to_account.pk:
        raise ValidationError({"to_account": "Elija una cuenta de destino distinta."})
    common = {
        "workspace": workspace,
        "date": on,
        "amount": q(to_money(amount)),
        "kind": kind,
        "category": category,
        "description": description.strip(),
        "source": source,
        "created_by": user,
    }
    out_leg = Transaction(
        account=from_account, direction=Direction.OUT, client_uuid=client_uuid, **common
    )
    in_uuid = uuid.uuid5(_TRANSFER_NS, str(client_uuid)) if client_uuid else None
    in_leg = Transaction(account=to_account, direction=Direction.IN, client_uuid=in_uuid, **common)
    for leg in (out_leg, in_leg):
        leg.full_clean(validate_constraints=False)
    out_leg.save()
    in_leg.transfer_pair = out_leg
    in_leg.save()
    out_leg.transfer_pair = in_leg
    out_leg.save(update_fields=["transfer_pair"])
    return out_leg, in_leg
