"""Carga de comprobantes: valida el tipo real del archivo, calcula su huella (sha256), detecta
duplicados exactos y encola la lectura con IA."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from apps.accounts.models import User
from apps.ledger.choices import Direction, TxStatus
from apps.ledger.models import Transaction
from apps.ledger.services.categories import normalize
from apps.receipts.models import Receipt
from apps.workspaces.models import Workspace

ALLOWED = "JPG, PNG, WEBP, HEIC o PDF"


def detect_mime(head: bytes) -> str | None:
    """Tipo del archivo según sus primeros bytes (no se confía en el nombre ni en el navegador)."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"heis"):
        return "image/heic"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def file_sha256(upload: UploadedFile) -> str:
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def validate_upload(upload: UploadedFile) -> str:
    if upload.size is None or upload.size == 0:
        raise ValidationError("El archivo está vacío.")
    if upload.size > settings.RECEIPT_MAX_BYTES:
        limit = settings.RECEIPT_MAX_BYTES // (1024 * 1024)
        raise ValidationError(f"El archivo supera el máximo de {limit} MB.")
    head = upload.read(16)
    upload.seek(0)
    mime = detect_mime(head)
    if mime is None:
        raise ValidationError(f"Formato no admitido. Sube una foto o PDF ({ALLOWED}).")
    return mime


@transaction.atomic
def ingest_receipt(
    workspace: Workspace, user: User | None, upload: UploadedFile, qr_text: str = ""
) -> Receipt:
    """Guarda el comprobante y programa su lectura. `qr_text`: el código QR que el teléfono
    leyó de la misma foto (si lo tenía)."""
    from .qr import parse as parse_qr

    mime = validate_upload(upload)
    sha = file_sha256(upload)
    receipt = Receipt(
        workspace=workspace,
        uploaded_by=user,
        original_name=(upload.name or "")[:200],
        content_type=mime,
        size=upload.size or 0,
        sha256=sha,
    )
    invoice = parse_qr(qr_text)
    if invoice.found:
        receipt.qr_data = invoice.as_json()
    receipt.file.save("comprobante", upload, save=False)
    original = (
        Receipt.objects.for_workspace(workspace).filter(sha256=sha).order_by("created_at").first()
    )
    if original is not None:
        # Mismo archivo ya subido: no se vuelve a leer con IA.
        receipt.status = Receipt.Status.DUPLICADO
        receipt.duplicate_of = original
        receipt.extracted = original.extracted
        receipt.field_confidence = original.field_confidence
        receipt.save()
        return receipt
    receipt.save()
    schedule_ocr(receipt)
    return receipt


def schedule_ocr(receipt: Receipt) -> None:
    from apps.receipts.tasks import read_receipt_task

    receipt_id = str(receipt.pk)
    transaction.on_commit(lambda: read_receipt_task.delay(receipt_id))


# ---------------------------------------------------------------- duplicados por contenido


def _amount(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _same_merchant(a: str | None, b: str | None) -> bool:
    na, nb = normalize(a), normalize(b)
    return bool(na and nb) and (na in nb or nb in na)


def find_content_duplicate(receipt: Receipt) -> tuple[Receipt | None, Transaction | None]:
    """Mismo comercio + mismo total + fecha ±1 día, contra otros comprobantes y movimientos."""
    data = receipt.extracted
    total, on = _amount(data.get("total")), _date(data.get("fecha"))
    merchant = data.get("comercio")
    if total is None or on is None or not merchant:
        return None, None
    window = (on - timedelta(days=1), on + timedelta(days=1))
    candidates = (
        Receipt.objects.for_workspace(receipt.workspace)
        .exclude(pk=receipt.pk)
        .exclude(status=Receipt.Status.ERROR)
    )
    for other in candidates:
        other_date = _date(other.extracted.get("fecha"))
        if (
            _amount(other.extracted.get("total")) == total
            and other_date
            and window[0] <= other_date <= window[1]
            and _same_merchant(merchant, other.extracted.get("comercio"))
        ):
            return other, other.transactions.first()
    txs = Transaction.objects.for_workspace(receipt.workspace).filter(
        amount=total, date__range=window, direction=Direction.OUT, status=TxStatus.CONFIRMADO
    )
    for tx in txs:
        if _same_merchant(merchant, tx.description):
            return None, tx
    return None, None
