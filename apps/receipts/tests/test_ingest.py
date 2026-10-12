from datetime import date

import pytest
from django.core.exceptions import ValidationError

from apps.ai.providers import FakeProvider
from apps.ai.schemas import ReceiptExtraction
from apps.ledger.choices import Direction, TxKind
from apps.ledger.models import Account
from apps.ledger.services.recording import TxData, record_transaction
from apps.receipts.models import Receipt
from apps.receipts.services.ingest import (
    detect_mime,
    find_content_duplicate,
    ingest_receipt,
    normalize,
)
from apps.receipts.services.ocr import doubtful_fields, read_receipt

from .conftest import JPEG, PDF, PNG, upload

pytestmark = pytest.mark.django_db


def extraction(**overrides):
    data = {
        "comercio": "Supermercado Nacional",
        "fecha": "2026-10-05",
        "total": "1250.00",
        "moneda": "DOP",
        "categoria_propuesta": "Alimentación",
        "medio_pago": "tarjeta",
        "confianza": {
            "comercio": 0.95,
            "fecha": 0.9,
            "total": 0.98,
            "categoria_propuesta": 0.8,
            "medio_pago": 0.4,
        },
    }
    data.update(overrides)
    return ReceiptExtraction(**data)


@pytest.mark.parametrize(
    ("head", "mime"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"\x00\x00\x00\x18ftypheic", "image/heic"),
        (PDF, "application/pdf"),
        (b"MZ\x90\x00", None),
        (b"<html>", None),
    ],
)
def test_tipo_real_del_archivo(head, mime):
    assert detect_mime(head) == mime


def test_rechaza_archivos_no_permitidos(personal_ws, user, settings):
    with pytest.raises(ValidationError, match="Formato no admitido"):
        ingest_receipt(personal_ws, user, upload(b"<svg onload=alert(1)>", "x.png"))
    with pytest.raises(ValidationError, match="vacío"):
        ingest_receipt(personal_ws, user, upload(b"", "x.png"))
    settings.RECEIPT_MAX_BYTES = 10
    with pytest.raises(ValidationError, match="máximo"):
        ingest_receipt(personal_ws, user, upload())
    assert not Receipt.objects.exists()


def test_subir_guarda_y_lee_con_ia(personal_ws, user, media, django_capture_on_commit_callbacks):
    user.set_ai_consent(True)
    FakeProvider.queue(extraction())
    with django_capture_on_commit_callbacks(execute=True):
        receipt = ingest_receipt(personal_ws, user, upload(name="mi factura.png"))
    receipt.refresh_from_db()
    assert receipt.status == Receipt.Status.PARA_REVISAR
    assert receipt.content_type == "image/png" and receipt.size == len(PNG)
    assert len(receipt.sha256) == 64
    assert receipt.file.name.startswith(f"comprobantes/{personal_ws.pk}/")
    assert "factura" not in receipt.file.name  # el nombre original no se usa en la ruta
    assert (media / receipt.file.name).exists()
    assert receipt.extracted["comercio"] == "Supermercado Nacional"
    assert "confianza" not in receipt.extracted
    assert receipt.field_confidence["medio_pago"] == 0.4
    assert str(receipt) == "Supermercado Nacional"
    assert FakeProvider.calls[0]["schema"] == "ReceiptExtraction"


def test_mismo_archivo_dos_veces_es_duplicado_sospechoso(
    personal_ws, user, django_capture_on_commit_callbacks
):
    user.set_ai_consent(True)
    FakeProvider.queue(extraction())
    with django_capture_on_commit_callbacks(execute=True):
        first = ingest_receipt(personal_ws, user, upload())
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        second = ingest_receipt(personal_ws, user, upload(name="otra-vez.png"))
    assert second.status == Receipt.Status.DUPLICADO
    assert second.duplicate_of == first
    assert callbacks == []  # no se vuelve a leer con IA
    assert len(FakeProvider.calls) == 1
    assert second.extracted["total"] == "1250.00"


def test_mismo_archivo_en_otro_espacio_no_es_duplicado(
    personal_ws, other_ws, user, other_user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        ingest_receipt(personal_ws, user, upload())
        other = ingest_receipt(other_ws, other_user, upload())
    other.refresh_from_db()
    assert other.status == Receipt.Status.ERROR  # sin consentimiento de IA, pero no duplicado


def test_duplicado_por_contenido_con_un_movimiento(
    personal_ws, user, django_capture_on_commit_callbacks
):
    user.set_ai_consent(True)
    efectivo = Account.objects.for_workspace(personal_ws).get(name="Efectivo")
    tx = record_transaction(
        personal_ws,
        user,
        TxData(
            account=efectivo,
            date=date(2026, 10, 4),
            amount="1250",
            direction=Direction.OUT,
            kind=TxKind.GASTO,
            description="Compra Supermercado Nacional",
        ),
    )
    FakeProvider.queue(extraction())
    with django_capture_on_commit_callbacks(execute=True):
        receipt = ingest_receipt(personal_ws, user, upload(JPEG, "f.jpg"))
    receipt.refresh_from_db()
    assert receipt.status == Receipt.Status.DUPLICADO
    assert receipt.duplicate_tx == tx


def test_duplicado_por_contenido_con_otro_comprobante(
    personal_ws, user, django_capture_on_commit_callbacks
):
    user.set_ai_consent(True)
    FakeProvider.queue(
        extraction(), extraction(comercio="SUPERMERCADO NACIONAL S.A.", fecha="2026-10-06")
    )
    with django_capture_on_commit_callbacks(execute=True):
        first = ingest_receipt(personal_ws, user, upload(PNG))
        second = ingest_receipt(personal_ws, user, upload(PDF, "f.pdf", "application/pdf"))
    second.refresh_from_db()
    assert second.status == Receipt.Status.DUPLICADO
    assert second.duplicate_of == first


def test_no_es_duplicado_si_cambia_monto_o_fecha(personal_ws, user):
    a = Receipt.objects.create(
        workspace=personal_ws,
        content_type="image/png",
        size=1,
        sha256="a",
        status=Receipt.Status.PARA_REVISAR,
        extracted={"comercio": "Colmado Juan", "total": "500.00", "fecha": "2026-10-05"},
    )
    b = Receipt(
        workspace=personal_ws,
        extracted={"comercio": "Colmado Juan", "total": "500.00", "fecha": "2026-10-08"},
    )
    assert find_content_duplicate(b) == (None, None)
    b.extracted["fecha"] = "2026-10-06"
    assert find_content_duplicate(b) == (a, None)
    b.extracted["total"] = "501"
    assert find_content_duplicate(b) == (None, None)
    assert find_content_duplicate(Receipt(workspace=personal_ws, extracted={})) == (None, None)
    b.extracted = {"comercio": "Otro", "total": "x", "fecha": "no"}
    assert find_content_duplicate(b) == (None, None)


def test_sin_consentimiento_queda_para_completar_a_mano(
    personal_ws, user, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        receipt = ingest_receipt(personal_ws, user, upload())
    receipt.refresh_from_db()
    assert receipt.status == Receipt.Status.ERROR
    assert "Activa el uso de IA" in receipt.error_message
    assert receipt.is_reviewable


def test_archivo_ilegible(personal_ws, user, django_capture_on_commit_callbacks):
    user.set_ai_consent(True)
    with django_capture_on_commit_callbacks(execute=False):
        receipt = ingest_receipt(personal_ws, user, upload())
    receipt.file.storage.delete(receipt.file.name)
    read_receipt(receipt.pk)
    receipt.refresh_from_db()
    assert receipt.status == Receipt.Status.ERROR
    assert "a mano" in receipt.error_message
    assert read_receipt(receipt.pk).status == Receipt.Status.ERROR  # ya no está procesando


def test_campos_dudosos():
    data = {
        "comercio": "X",
        "fecha": "2026-10-05",
        "total": "10",
        "categoria_propuesta": None,
        "medio_pago": "efectivo",
    }
    conf = {"comercio": 0.9, "fecha": 0.5, "total": 0.99, "medio_pago": 0.9}
    assert doubtful_fields(data, conf) == {"fecha", "categoria_propuesta"}


def test_normalizar():
    assert normalize("  Súper-Mercado  Nacional, S.A. ") == "super mercado nacional s a"
