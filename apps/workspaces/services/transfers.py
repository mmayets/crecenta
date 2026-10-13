"""Dinero entre la persona y su negocio (docs/fase2.md §2).

- Retiro del propietario: en el negocio, salida `retiro_propietario`; en la persona, entrada
  `ingreso` con la categoría "Retiros de mi negocio".
- Aporte: en la persona, salida `aporte_propietario` (neutra, no consume presupuesto); en el
  negocio, entrada `aporte_propietario`.

Los dos movimientos se crean juntos (todo o nada) y se borran juntos.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.accounts.models import User
from apps.core.money import q, to_money
from apps.ledger.choices import CategoryGroup, Direction, TxKind
from apps.ledger.models import Account, Category, Transaction
from apps.workspaces.models import Membership, Workspace, WorkspaceTransfer

PERSONAL_WITHDRAWAL_CATEGORY = "Retiros de mi negocio"
BUSINESS_WITHDRAWAL_CATEGORY = "Retiros del propietario"
BUSINESS_CONTRIBUTION_CATEGORY = "Aportes del propietario"
_NS = uuid.UUID("9d4f7a51-2c3e-4b8a-a6f0-5e1d2c3b4a90")


def _is_owner(user: User, workspace: Workspace) -> bool:
    return (
        workspace.owner_id == user.pk
        and Membership.objects.filter(
            user=user, workspace=workspace, role=Membership.Role.OWNER
        ).exists()
    )


def _system_category(workspace: Workspace, name: str, group: str) -> Category:
    """Categoría del sistema; la crea si falta (espacios creados antes de la Fase 2)."""
    category, _ = Category.objects.get_or_create(
        workspace=workspace, name=name, defaults={"group": group, "is_system": True}
    )
    return category


def validate_transfer(
    user: User,
    from_ws: Workspace,
    to_ws: Workspace,
    kind: str,
    from_account: Account,
    to_account: Account,
) -> None:
    errors: dict[str, str] = {}
    if not (_is_owner(user, from_ws) and _is_owner(user, to_ws)):
        raise ValidationError(
            "Solo puedes mover dinero entre espacios de los que eres propietario."
        )
    if kind == WorkspaceTransfer.Kind.RETIRO_PROPIETARIO:
        if not (from_ws.is_business and to_ws.is_personal):
            errors["kind"] = "Un retiro va de tu negocio a tus finanzas personales."
    elif kind == WorkspaceTransfer.Kind.APORTE:
        if not (from_ws.is_personal and to_ws.is_business):
            errors["kind"] = "Un aporte va de tus finanzas personales a tu negocio."
    else:
        errors["kind"] = "Tipo de transferencia no válido."
    if from_ws.currency != to_ws.currency:
        errors["to_workspace"] = "Los dos espacios deben usar la misma moneda."
    if from_account.workspace_id != from_ws.pk or from_account.is_archived:
        errors["from_account"] = "La cuenta de origen no pertenece a ese espacio."
    if to_account.workspace_id != to_ws.pk or to_account.is_archived:
        errors["to_account"] = "La cuenta de destino no pertenece a ese espacio."
    if errors:
        raise ValidationError(errors)


def transfer_between(
    user: User,
    from_ws: Workspace,
    to_ws: Workspace,
    amount: Decimal | str,
    on: datetime.date,
    kind: str,
    from_account: Account,
    to_account: Account,
    note: str = "",
    client_uuid: uuid.UUID | None = None,
) -> tuple[WorkspaceTransfer, bool]:
    """Crea la transferencia y sus dos movimientos espejo. Devuelve (transferencia, creada)."""
    validate_transfer(user, from_ws, to_ws, kind, from_account, to_account)
    value = q(to_money(amount))
    if value <= 0:
        raise ValidationError({"amount": "El monto debe ser mayor que cero."})

    def existing() -> WorkspaceTransfer | None:
        if client_uuid is None:
            return None
        return WorkspaceTransfer.objects.filter(created_by=user, client_uuid=client_uuid).first()

    found = existing()
    if found is not None:
        return found, False
    try:
        with transaction.atomic():
            return _create(user, from_ws, to_ws, value, on, kind, from_account, to_account, note,
                           client_uuid), True  # fmt: skip
    except IntegrityError:
        found = existing()
        if found is None:
            raise
        return found, False


def _create(
    user: User,
    from_ws: Workspace,
    to_ws: Workspace,
    value: Decimal,
    on: datetime.date,
    kind: str,
    from_account: Account,
    to_account: Account,
    note: str,
    client_uuid: uuid.UUID | None,
) -> WorkspaceTransfer:
    note = note.strip()[:140]
    if kind == WorkspaceTransfer.Kind.RETIRO_PROPIETARIO:
        out_kind, out_cat = (
            TxKind.RETIRO_PROPIETARIO,
            _system_category(from_ws, BUSINESS_WITHDRAWAL_CATEGORY, CategoryGroup.PROPIETARIO),
        )
        in_kind, in_cat = (
            TxKind.INGRESO,
            _system_category(to_ws, PERSONAL_WITHDRAWAL_CATEGORY, CategoryGroup.INGRESO),
        )
        out_text, in_text = f"Retiro hacia {to_ws.name}", f"Retiro de {from_ws.name}"
    else:
        out_kind, out_cat = TxKind.APORTE_PROPIETARIO, None
        in_kind, in_cat = (
            TxKind.APORTE_PROPIETARIO,
            _system_category(to_ws, BUSINESS_CONTRIBUTION_CATEGORY, CategoryGroup.PROPIETARIO),
        )
        out_text, in_text = f"Aporte a {to_ws.name}", f"Aporte desde {from_ws.name}"

    def leg(
        ws: Workspace,
        account: Account,
        direction: str,
        tx_kind: str,
        category: Category | None,
        text: str,
        suffix: str,
    ) -> Transaction:
        tx = Transaction(
            workspace=ws,
            account=account,
            date=on,
            amount=value,
            direction=direction,
            kind=tx_kind,
            category=category,
            description=(f"{text} · {note}" if note else text)[:140],
            client_uuid=uuid.uuid5(_NS, f"{client_uuid}:{suffix}") if client_uuid else None,
            created_by=user,
        )
        tx.full_clean(validate_constraints=False)
        tx.save()
        return tx

    out_tx = leg(from_ws, from_account, Direction.OUT, out_kind, out_cat, out_text, "out")
    in_tx = leg(to_ws, to_account, Direction.IN, in_kind, in_cat, in_text, "in")
    return WorkspaceTransfer.objects.create(
        from_workspace=from_ws,
        to_workspace=to_ws,
        kind=kind,
        amount=value,
        date=on,
        note=note,
        out_tx=out_tx,
        in_tx=in_tx,
        client_uuid=client_uuid,
        created_by=user,
    )


def transfer_for(tx: Transaction) -> WorkspaceTransfer | None:
    """Transferencia entre espacios a la que pertenece un movimiento (si alguna)."""
    return WorkspaceTransfer.objects.filter(Q(out_tx=tx) | Q(in_tx=tx)).first()


@transaction.atomic
def delete_transfer(user: User, transfer: WorkspaceTransfer) -> None:
    """Borra la transferencia y sus dos movimientos (uno en cada espacio)."""
    if not (_is_owner(user, transfer.from_workspace) and _is_owner(user, transfer.to_workspace)):
        raise ValidationError("Solo el propietario de ambos espacios puede borrarla.")
    ids = [pk for pk in (transfer.out_tx_id, transfer.in_tx_id) if pk]
    transfer.delete()
    Transaction.objects.filter(pk__in=ids).delete()
