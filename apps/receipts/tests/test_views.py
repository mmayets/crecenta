import pytest
from django.urls import reverse

from apps.ai.providers import FakeProvider
from apps.ledger.models import Account, Category, Transaction
from apps.receipts.models import Receipt

from .conftest import PDF, PNG, upload
from .test_ingest import extraction

pytestmark = pytest.mark.django_db


def url(name, ws, **kw):
    return reverse(f"receipts:{name}", kwargs={"ws": ws.pk, **kw})


@pytest.fixture
def logged(client, user):
    user.set_ai_consent(True)
    client.force_login(user)
    return client


def subir(client, ws, capture, content=PNG, name="f.png"):
    with capture(execute=True):
        response = client.post(url("index", ws), {"file": upload(content, name)})
    return Receipt.objects.for_workspace(ws).latest("created_at"), response


def test_flujo_completo(logged, personal_ws, django_capture_on_commit_callbacks):
    FakeProvider.queue(extraction())
    receipt, response = subir(logged, personal_ws, django_capture_on_commit_callbacks)
    assert response["Location"] == url("detail", personal_ws, receipt_id=receipt.pk)
    html = logged.get(response["Location"]).content.decode()
    assert "Supermercado Nacional" in html
    assert 'class="dudoso"' in html  # medio de pago con confianza 0.4
    assert "Revisa este dato" in html
    assert 'capture="environment"' in logged.get(url("index", personal_ws)).content.decode()
    data = {
        "description": "Supermercado Nacional",
        "date": "2026-10-05",
        "amount": "1250.00",
        "category": Category.objects.for_workspace(personal_ws).get(name="Alimentación").pk,
        "account": Account.objects.for_workspace(personal_ws).get(name="Efectivo").pk,
    }
    response = logged.post(url("detail", personal_ws, receipt_id=receipt.pk), data)
    assert response["Location"] == url("index", personal_ws)
    tx = Transaction.objects.for_workspace(personal_ws).get()
    assert tx.receipt == receipt and tx.amount == 1250
    # ya confirmado: no se puede volver a enviar
    response = logged.post(url("detail", personal_ws, receipt_id=receipt.pk), data, follow=True)
    assert "ya no se puede modificar" in response.content.decode()


def test_formulario_invalido_y_aviso_previo(
    logged, personal_ws, django_capture_on_commit_callbacks
):
    FakeProvider.queue(extraction(total="999999"))
    receipt, _ = subir(logged, personal_ws, django_capture_on_commit_callbacks)
    response = logged.post(url("detail", personal_ws, receipt_id=receipt.pk), {"amount": "-1"})
    assert response.status_code == 200
    assert Transaction.objects.count() == 0


def test_subida_invalida(logged, personal_ws):
    response = logged.post(
        url("index", personal_ws), {"file": upload(b"hola", "x.txt", "text/plain")}
    )
    assert response.status_code == 400
    assert "Formato no admitido" in response.content.decode()


def test_duplicado_vincular_y_descartar(logged, personal_ws, django_capture_on_commit_callbacks):
    FakeProvider.queue(extraction())
    first, _ = subir(logged, personal_ws, django_capture_on_commit_callbacks)
    second, _ = subir(logged, personal_ws, django_capture_on_commit_callbacks)
    html = logged.get(url("detail", personal_ws, receipt_id=second.pk)).content.decode()
    assert "ya está registrado" in html and "Descartar este" in html
    response = logged.post(url("link", personal_ws, receipt_id=second.pk), follow=True)
    assert "No hay un movimiento registrado" in response.content.decode()
    with django_capture_on_commit_callbacks(execute=True):
        logged.post(url("discard", personal_ws, receipt_id=second.pk))
    assert not Receipt.objects.filter(pk=second.pk).exists()
    logged.post(url("discard", personal_ws, receipt_id=first.pk))  # no revisable aún: mensaje
    first.status = "confirmado"
    first.save()
    response = logged.post(url("discard", personal_ws, receipt_id=first.pk), follow=True)
    assert "confirmado" in response.content.decode()


def test_vincular_con_movimiento(logged, personal_ws, django_capture_on_commit_callbacks, user):
    from datetime import date

    from apps.ledger.services.recording import TxData, record_transaction

    record_transaction(
        personal_ws,
        user,
        TxData(
            account=Account.objects.for_workspace(personal_ws).get(name="Efectivo"),
            date=date(2026, 10, 5),
            amount="1250",
            direction="out",
            kind="gasto",
            description="Supermercado Nacional",
        ),
    )
    FakeProvider.queue(extraction())
    receipt, _ = subir(logged, personal_ws, django_capture_on_commit_callbacks)
    assert (
        "Movimiento existente"
        in logged.get(url("detail", personal_ws, receipt_id=receipt.pk)).content.decode()
    )
    logged.post(url("link", personal_ws, receipt_id=receipt.pk))
    receipt.refresh_from_db()
    assert receipt.status == "confirmado"


def test_error_y_reintentar(client, user, personal_ws, django_capture_on_commit_callbacks):
    client.force_login(user)  # sin consentimiento de IA
    receipt, _ = subir(client, personal_ws, django_capture_on_commit_callbacks, PDF, "f.pdf")
    html = client.get(url("detail", personal_ws, receipt_id=receipt.pk)).content.decode()
    assert "Activa el uso de IA" in html and "Ver PDF" in html
    with django_capture_on_commit_callbacks(execute=False):
        client.post(url("retry", personal_ws, receipt_id=receipt.pk))
    receipt.refresh_from_db()
    assert receipt.status == "procesando"
    partial = client.get(url("detail", personal_ws, receipt_id=receipt.pk), HTTP_HX_REQUEST="true")
    assert b'hx-trigger="every 2s"' in partial.content
    response = client.post(url("retry", personal_ws, receipt_id=receipt.pk), follow=True)
    assert "leyendo comprobante" in response.content.decode().lower()


def test_descarga_autenticada(
    logged, client, personal_ws, other_user, django_capture_on_commit_callbacks
):
    FakeProvider.queue(extraction())
    receipt, _ = subir(logged, personal_ws, django_capture_on_commit_callbacks)
    response = logged.get(url("file", personal_ws, receipt_id=receipt.pk))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PNG
    assert response["Content-Type"] == "image/png"
    assert response["Cache-Control"] == "private, no-store"
    assert "sandbox" in response["Content-Security-Policy"]
    assert "inline" in response["Content-Disposition"]
    descarga = logged.get(url("file", personal_ws, receipt_id=receipt.pk), {"descargar": "1"})
    assert "attachment" in descarga["Content-Disposition"]
    client.logout()
    client.force_login(other_user)
    assert client.get(url("file", personal_ws, receipt_id=receipt.pk)).status_code == 404
    client.logout()
    assert client.get(url("file", personal_ws, receipt_id=receipt.pk)).status_code == 302


def test_no_hay_url_publica_de_archivos(personal_ws, user):
    from django.urls import Resolver404, resolve

    with pytest.raises(Resolver404):
        resolve(f"/media/comprobantes/{personal_ws.pk}/x.png")


def test_limite_de_subidas(logged, personal_ws, settings):
    settings.UPLOAD_RATE_LIMITS = [(1, 3600)]
    assert (
        logged.post(
            url("index", personal_ws), {"file": upload(PDF, "a.pdf", "application/pdf")}
        ).status_code
        == 302
    )
    response = logged.post(
        url("index", personal_ws), {"file": upload(PDF, "b.pdf", "application/pdf")}
    )
    assert response.status_code == 400
    assert "muchos comprobantes" in response.content.decode()
