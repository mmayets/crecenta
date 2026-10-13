"""Sincronización idempotente de movimientos registrados en el dispositivo (modo sin conexión).

El dispositivo genera un `client_uuid` por movimiento. Reenviar el mismo movimiento (reintentos,
Background Sync, doble toque) devuelve el registro existente sin duplicarlo: gana la primera
escritura. La restricción única (workspace, client_uuid) protege también ante envíos concurrentes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.core.money import MoneyError, q, to_money
from apps.ledger.choices import TxKind, TxSource
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.classification import (
    LINKED_KINDS,
    TRANSFER_KINDS,
    allowed_directions,
)
from apps.ledger.services.recording import TxData, record_transaction, record_transfer
from apps.workspaces.models import Workspace

ALLOWED_SOURCES = {TxSource.MANUAL, TxSource.OFFLINE, TxSource.TEXTO, TxSource.VOZ}
MAX_BATCH = 100


@dataclass(frozen=True)
class SyncItem:
    client_uuid: uuid.UUID
    account: Account
    date: date
    amount: Decimal
    kind: str
    direction: str
    category: Category | None = None
    to_account: Account | None = None
    description: str = ""
    source: str = TxSource.OFFLINE
    tax_amount: Decimal = Decimal("0")


@dataclass(frozen=True)
class SyncResult:
    transaction: Transaction
    created: bool


def _get_in_workspace(model: type[Account] | type[Category], workspace: Workspace, pk: Any) -> Any:
    """Busca un objeto solo dentro del espacio: un id de otro espacio se trata como inexistente."""
    try:
        return model.objects.for_workspace(workspace).get(pk=pk, is_archived=False)
    except (model.DoesNotExist, ValueError, ValidationError, TypeError):
        return None


def parse_item(workspace: Workspace, raw: dict[str, Any]) -> SyncItem:
    """Valida un elemento recibido del dispositivo. Lanza ValidationError con mensajes por campo."""
    errors: dict[str, str] = {}

    try:
        client_uuid = uuid.UUID(str(raw.get("client_uuid", "")))
    except ValueError:
        errors["client_uuid"] = "Identificador del dispositivo inválido."

    account = _get_in_workspace(Account, workspace, raw.get("account_id"))
    if account is None:
        errors["account_id"] = "Cuenta no encontrada."

    try:
        on = date.fromisoformat(str(raw.get("date", "")))
    except ValueError:
        errors["date"] = "Fecha inválida (use AAAA-MM-DD)."

    try:
        amount = q(to_money(str(raw.get("amount", ""))))
        if amount <= 0:
            errors["amount"] = "El monto debe ser mayor que cero."
    except MoneyError:
        errors["amount"] = "Monto inválido."

    kind = str(raw.get("kind", ""))
    direction = str(raw.get("direction", ""))
    if kind not in TxKind.values:
        errors["kind"] = "Tipo de movimiento inválido."
    elif kind in LINKED_KINDS:
        errors["kind"] = "Este tipo de movimiento se registra desde su propia pantalla."
    else:
        allowed = allowed_directions(kind)
        if not direction and len(allowed) == 1:
            direction = next(iter(allowed))
        if kind in TRANSFER_KINDS:
            direction = "out"  # la transferencia se registra desde la cuenta de origen
        elif direction not in allowed:
            errors["direction"] = "Indique si es entrada o salida."

    category = None
    if raw.get("category_id"):
        category = _get_in_workspace(Category, workspace, raw.get("category_id"))
        if category is None:
            errors["category_id"] = "Categoría no encontrada."

    to_account = None
    if kind in TRANSFER_KINDS:
        to_account = _get_in_workspace(Account, workspace, raw.get("to_account_id"))
        if to_account is None:
            errors["to_account_id"] = "Cuenta de destino no encontrada."

    tax_amount = Decimal("0")
    if raw.get("tax_amount"):
        try:
            tax_amount = q(to_money(str(raw["tax_amount"])))
        except MoneyError:
            errors["tax_amount"] = "ITBIS inválido."
        else:
            if tax_amount < 0 or ("amount" not in errors and tax_amount > amount):
                errors["tax_amount"] = "El ITBIS no puede ser negativo ni mayor que el monto."

    source = str(raw.get("source") or TxSource.OFFLINE)
    if source not in ALLOWED_SOURCES:
        errors["source"] = "Origen inválido."

    if errors:
        raise ValidationError(errors)
    return SyncItem(
        client_uuid=client_uuid,
        account=account,
        date=on,
        amount=amount,
        kind=kind,
        direction=direction,
        category=category,
        to_account=to_account,
        description=str(raw.get("description", ""))[:140],
        source=source,
        tax_amount=tax_amount,
    )


def _existing(workspace: Workspace, client_uuid: uuid.UUID) -> Transaction | None:
    return Transaction.objects.for_workspace(workspace).filter(client_uuid=client_uuid).first()


def upsert_from_client(workspace: Workspace, user: User | None, item: SyncItem) -> SyncResult:
    """Crea el movimiento si su `client_uuid` no existe en el espacio; si existe, lo devuelve."""
    found = _existing(workspace, item.client_uuid)
    if found is not None:
        return SyncResult(found, created=False)
    try:
        with transaction.atomic():
            if item.kind in TRANSFER_KINDS:
                assert item.to_account is not None
                tx, _ = record_transfer(
                    workspace,
                    user,
                    from_account=item.account,
                    to_account=item.to_account,
                    amount=item.amount,
                    on=item.date,
                    kind=item.kind,
                    category=item.category,
                    description=item.description,
                    source=item.source,
                    client_uuid=item.client_uuid,
                )
            else:
                tx = record_transaction(
                    workspace,
                    user,
                    TxData(
                        account=item.account,
                        date=item.date,
                        amount=item.amount,
                        direction=item.direction,
                        kind=item.kind,
                        category=item.category,
                        description=item.description,
                        source=item.source,
                        client_uuid=item.client_uuid,
                        tax_amount=item.tax_amount,
                    ),
                )
    except IntegrityError:
        # Otro envío del mismo movimiento ganó la carrera: devolver el existente.
        found = _existing(workspace, item.client_uuid)
        if found is None:
            raise
        return SyncResult(found, created=False)
    return SyncResult(tx, created=True)


def sync_batch(
    workspace: Workspace, user: User | None, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Procesa un lote; cada elemento se resuelve por separado (uno inválido no frena al resto)."""
    if len(items) > MAX_BATCH:
        raise ValidationError(f"Máximo {MAX_BATCH} movimientos por envío.")
    results: list[dict[str, Any]] = []
    for raw in items:
        client_uuid = str(raw.get("client_uuid", "")) if isinstance(raw, dict) else ""
        if not isinstance(raw, dict):
            results.append({"client_uuid": "", "estado": "error", "errores": {"": "Formato"}})
            continue
        try:
            item = parse_item(workspace, raw)
            result = upsert_from_client(workspace, user, item)
        except ValidationError as exc:
            errors = exc.message_dict if hasattr(exc, "error_dict") else {"": exc.messages}
            results.append({"client_uuid": client_uuid, "estado": "error", "errores": errors})
            continue
        results.append(
            {
                "client_uuid": client_uuid,
                "estado": "creado" if result.created else "existente",
                "id": str(result.transaction.pk),
            }
        )
    return results
