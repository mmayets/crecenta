from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.balances import spent_by_category
from apps.ledger.services.recording import create_account
from apps.receipts.models import Receipt
from apps.receipts.services.review import (
    ReceiptConfirmation,
    ReceiptError,
    confirm_receipt,
    discard_receipt,
    link_to_existing,
    reprocess,
    suggested_account,
    suggested_category,
)

from .conftest import PNG, upload

pytestmark = pytest.mark.django_db
D = Decimal


def make(ws, status=Receipt.Status.PARA_REVISAR, **extracted):
    receipt = Receipt(
        workspace=ws,
        content_type="image/png",
        size=len(PNG),
        sha256="x",
        status=status,
        extracted=extracted,
    )
    receipt.file.save("c", upload(), save=False)
    receipt.save()
    return receipt


def efectivo(ws):
    return Account.objects.for_workspace(ws).get(name="Efectivo")


def confirmation(ws, **kw):
    data = {
        "account": efectivo(ws),
        "date": date(2026, 10, 5),
        "amount": D("1250"),
        "description": "Supermercado Nacional",
        "category": Category.objects.for_workspace(ws).get(name="Alimentación"),
    }
    data.update(kw)
    return ReceiptConfirmation(**data)


def test_confirmar_crea_el_gasto_y_actualiza_el_presupuesto(personal_ws, user):
    receipt = make(personal_ws)
    tx = confirm_receipt(receipt, user, confirmation(personal_ws))
    receipt.refresh_from_db()
    assert receipt.status == Receipt.Status.CONFIRMADO
    assert (tx.source, tx.kind, tx.status, tx.receipt) == (
        "comprobante",
        "gasto",
        "confirmado",
        receipt,
    )
    alimentacion = Category.objects.for_workspace(personal_ws).get(name="Alimentación")
    spent = spent_by_category(personal_ws, date(2026, 10, 1), date(2026, 10, 31))
    assert spent[alimentacion.pk] == D("1250.00")
    with pytest.raises(ReceiptError, match="confirmado"):
        confirm_receipt(receipt, user, confirmation(personal_ws))


def test_confirmar_con_cuenta_ajena_falla(personal_ws, other_ws, user):
    with pytest.raises(ValidationError):
        confirm_receipt(
            make(personal_ws), user, confirmation(personal_ws, account=efectivo(other_ws))
        )


def test_vincular_a_movimiento_existente(personal_ws, user):
    original = make(personal_ws)
    tx = confirm_receipt(original, user, confirmation(personal_ws))
    copia = make(personal_ws, status=Receipt.Status.DUPLICADO)
    copia.duplicate_of = original
    copia.save()
    assert link_to_existing(copia, user) == tx
    copia.refresh_from_db()
    tx.refresh_from_db()
    assert copia.status == Receipt.Status.CONFIRMADO
    assert tx.receipt == original  # conserva su comprobante original
    assert Transaction.objects.for_workspace(personal_ws).count() == 1

    sin_comprobante = Transaction.objects.create(
        workspace=personal_ws,
        account=efectivo(personal_ws),
        date=date(2026, 10, 1),
        amount=D("10"),
        direction="out",
        kind="gasto",
    )
    otro = make(personal_ws, status=Receipt.Status.DUPLICADO)
    otro.duplicate_tx = sin_comprobante
    otro.save()
    link_to_existing(otro, user)
    sin_comprobante.refresh_from_db()
    assert sin_comprobante.receipt == otro

    huerfano = make(personal_ws, status=Receipt.Status.DUPLICADO)
    with pytest.raises(ReceiptError):
        link_to_existing(huerfano, user)


def test_descartar_elimina_archivo(personal_ws, user, media, django_capture_on_commit_callbacks):
    receipt = make(personal_ws, status=Receipt.Status.DUPLICADO)
    path = media / receipt.file.name
    assert path.exists()
    with django_capture_on_commit_callbacks(execute=True):
        discard_receipt(receipt, user)
    assert not Receipt.objects.filter(pk=receipt.pk).exists()
    assert not path.exists()


def test_volver_a_leer(personal_ws, user, django_capture_on_commit_callbacks):
    receipt = make(personal_ws, status=Receipt.Status.ERROR)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        reprocess(receipt, user)
    receipt.refresh_from_db()
    assert receipt.status == Receipt.Status.PROCESANDO and len(callbacks) == 1


def test_sugerencias(personal_ws):
    tarjeta = create_account(personal_ws, "Visa", "tarjeta")
    receipt = make(personal_ws, categoria_propuesta="alimentacion", medio_pago="tarjeta")
    assert suggested_category(receipt).name == "Alimentación"
    assert suggested_account(receipt) == tarjeta
    receipt.extracted = {"categoria_propuesta": "Inventada", "medio_pago": "transferencia"}
    assert suggested_category(receipt) is None
    assert suggested_account(receipt) == efectivo(personal_ws)
    receipt.extracted = {}
    assert suggested_category(receipt) is None
