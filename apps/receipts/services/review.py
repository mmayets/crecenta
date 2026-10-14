"""Revisión obligatoria del comprobante: solo al confirmar se crea el movimiento."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import User
from apps.ledger.choices import AccountType, Direction, TxKind, TxSource
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.categories import normalize
from apps.ledger.services.recording import TxData, record_transaction
from apps.receipts.models import Receipt
from apps.receipts.services.ingest import schedule_ocr

_PAYMENT_ACCOUNT = {"efectivo": AccountType.EFECTIVO, "tarjeta": AccountType.TARJETA}


class ReceiptError(Exception):
    pass


@dataclass(frozen=True)
class ReceiptConfirmation:
    account: Account
    date: date
    amount: Decimal
    description: str
    category: Category | None = None
    rubro: str = ""
    invoice_number: str = ""


def _lock_reviewable(receipt: Receipt) -> Receipt:
    locked = Receipt.objects.select_for_update().get(pk=receipt.pk)
    if not locked.is_reviewable:
        raise ReceiptError(f"Este comprobante está {locked.get_status_display().lower()}.")
    return locked


def suggested_category(receipt: Receipt) -> Category | None:
    name = normalize(receipt.extracted.get("categoria_propuesta"))
    if not name:
        return None
    categories: list[Category] = list(
        Category.objects.for_workspace(receipt.workspace).filter(is_archived=False)
    )
    return next((c for c in categories if normalize(c.name) == name), None)


def suggested_account(receipt: Receipt) -> Account | None:
    accounts = Account.objects.for_workspace(receipt.workspace).filter(is_archived=False)
    account_type = _PAYMENT_ACCOUNT.get(receipt.extracted.get("medio_pago") or "")
    if account_type:
        match: Account | None = accounts.filter(type=account_type).first()
        if match:
            return match
    first: Account | None = accounts.first()
    return first


@transaction.atomic
def confirm_receipt(receipt: Receipt, user: User | None, data: ReceiptConfirmation) -> Transaction:
    """Crea el gasto respaldado por el comprobante (también si la persona indica que no es un
    duplicado)."""
    receipt = _lock_reviewable(receipt)
    if data.account.workspace_id != receipt.workspace_id:
        raise ValidationError({"account": "La cuenta no pertenece a este espacio."})
    tx = record_transaction(
        receipt.workspace,
        user,
        TxData(
            account=data.account,
            date=data.date,
            amount=data.amount,
            direction=Direction.OUT,
            kind=TxKind.GASTO,
            category=data.category,
            description=data.description,
            source=TxSource.COMPROBANTE,
            receipt=receipt,
            rubro=data.rubro,
            invoice_number=data.invoice_number,
        ),
    )
    receipt.status = Receipt.Status.CONFIRMADO
    receipt.save(update_fields=["status", "updated_at"])
    return tx


@transaction.atomic
def link_to_existing(receipt: Receipt, user: User | None) -> Transaction:
    """El comprobante respalda un movimiento ya registrado: se vincula sin crear otro gasto."""
    receipt = _lock_reviewable(receipt)
    tx = receipt.duplicate_tx or (
        receipt.duplicate_of.transactions.first() if receipt.duplicate_of else None
    )
    if tx is None:
        raise ReceiptError("No hay un movimiento registrado para vincular.")
    if tx.receipt_id is None:
        tx.receipt = receipt
        tx.save(update_fields=["receipt", "updated_at"])
    receipt.status = Receipt.Status.CONFIRMADO
    receipt.save(update_fields=["status", "updated_at"])
    return tx


@transaction.atomic
def discard_receipt(receipt: Receipt, user: User | None) -> None:
    """Elimina el comprobante y su archivo (p. ej. un duplicado)."""
    receipt = _lock_reviewable(receipt)
    storage, name = receipt.file.storage, receipt.file.name or ""
    receipt.delete()
    if name:
        transaction.on_commit(lambda: storage.delete(name))


@transaction.atomic
def reprocess(receipt: Receipt, user: User | None) -> Receipt:
    """Vuelve a leer con IA (tras un error, o un duplicado que la persona quiere revisar)."""
    receipt = _lock_reviewable(receipt)
    receipt.status = Receipt.Status.PROCESANDO
    receipt.error_message = ""
    receipt.duplicate_of = None
    receipt.duplicate_tx = None
    receipt.save()
    schedule_ocr(receipt)
    return receipt
