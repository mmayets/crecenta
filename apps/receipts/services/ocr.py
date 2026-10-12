"""Lectura del comprobante con un modelo multimodal (tarea asíncrona). El resultado es siempre un
borrador: la persona revisa y confirma antes de que exista un movimiento."""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from django.utils import timezone

from apps.ai.providers import Attachment
from apps.ai.schemas import ReceiptExtraction
from apps.ai.services.client import AIUnavailable, run_structured
from apps.ledger.choices import CategoryGroup
from apps.ledger.models import Category
from apps.receipts.models import Receipt
from apps.receipts.services.ingest import find_content_duplicate

logger = logging.getLogger(__name__)
LOW_CONFIDENCE = 0.6
REVIEW_FIELDS = ("comercio", "fecha", "total", "categoria_propuesta", "medio_pago")


def expense_category_names(receipt: Receipt) -> list[str]:
    return list(
        Category.objects.for_workspace(receipt.workspace)
        .exclude(group__in=[CategoryGroup.INGRESO, CategoryGroup.AHORRO])
        .filter(is_archived=False)
        .values_list("name", flat=True)
    )


def doubtful_fields(extracted: dict, confidence: dict) -> set[str]:
    """Campos a resaltar en la revisión: vacíos o con confianza baja."""
    return {
        name
        for name in REVIEW_FIELDS
        if extracted.get(name) in (None, "") or float(confidence.get(name, 0)) < LOW_CONFIDENCE
    }


def read_receipt(receipt_id: UUID | str, today: date | None = None) -> Receipt:
    receipt = Receipt.objects.select_related("workspace", "uploaded_by").get(pk=receipt_id)
    if receipt.status != Receipt.Status.PROCESANDO:
        return receipt
    try:
        with receipt.file.open("rb") as handle:
            data = handle.read()
        result = run_structured(
            workspace=receipt.workspace,
            user=receipt.uploaded_by,
            purpose="comprobante_ocr",
            prompt_name="comprobante_ocr",
            context={
                "hoy": (today or timezone.localdate()).isoformat(),
                "categorias": expense_category_names(receipt),
            },
            schema=ReceiptExtraction,
            attachments=[Attachment(data, receipt.content_type, "comprobante")],
        )
    except AIUnavailable as exc:
        receipt.status = Receipt.Status.ERROR
        receipt.error_message = str(exc)[:200]
        receipt.save(update_fields=["status", "error_message", "updated_at"])
        return receipt
    except Exception:  # archivo ilegible o falla inesperada: se puede completar a mano
        logger.exception("No se pudo leer el comprobante %s", receipt.pk)
        receipt.status = Receipt.Status.ERROR
        receipt.error_message = "No pudimos leer el comprobante. Completa los datos a mano."
        receipt.save(update_fields=["status", "error_message", "updated_at"])
        return receipt

    extraction = result.data
    receipt.extracted = extraction.model_dump(mode="json", exclude={"confianza"})
    receipt.field_confidence = {k: float(v) for k, v in extraction.confianza.items()}
    receipt.status = Receipt.Status.PARA_REVISAR
    duplicate, duplicate_tx = find_content_duplicate(receipt)
    if duplicate or duplicate_tx:
        receipt.status = Receipt.Status.DUPLICADO
        receipt.duplicate_of = duplicate
        receipt.duplicate_tx = duplicate_tx
    receipt.save()
    return receipt
