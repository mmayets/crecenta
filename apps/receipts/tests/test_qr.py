from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.receipts.forms import ReviewForm
from apps.receipts.models import Receipt
from apps.receipts.services.qr import parse

pytestmark = pytest.mark.django_db

DGII = (
    "https://ecf.dgii.gov.do/ecf/ConsultaTimbre?RncEmisor=101-01010-1&RncComprador=40212345678"
    "&ENCF=E310000000123&FechaEmision=10-10-2026&MontoTotal=1180.00&FechaFirma=10-10-2026%2010:00:00"
    "&CodigoSeguridad=AbC123"
)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_lee_el_qr_de_una_factura_electronica():
    invoice = parse(DGII)
    assert invoice.found and invoice.es_dgii
    assert (invoice.numero, invoice.total, invoice.fecha, invoice.rnc_emisor) == (
        "E310000000123",
        Decimal("1180.00"),
        date(2026, 10, 10),
        "101010101",
    )
    assert "40212345678" not in str(invoice.as_json())  # nunca el RNC del comprador


@pytest.mark.parametrize(
    ("text", "numero", "total"),
    [
        ("Factura NCF: B0100000045 Total: RD$ 2,350.50", "B0100000045", Decimal("2350.50")),
        ("e-NCF E310000000999", "E310000000999", None),
        ("https://ejemplo.com/?ncf=b0200000001&montototal=500", "B0200000001", Decimal("500.00")),
        ("hola", "", None),
        ("", "", None),
    ],
)
def test_lee_otros_codigos(text, numero, total):
    invoice = parse(text)
    assert (invoice.numero, invoice.total) == (numero, total)


def test_escanear_qr_abre_el_registro_prellenado(client, user, personal_ws):
    client.force_login(user)
    response = client.post(
        reverse("receipts:scan_qr", kwargs={"ws": personal_ws.pk}), {"texto": DGII}
    )
    target = reverse("ledger:new", kwargs={"ws": personal_ws.pk}) + "?factura=1"
    assert response["Location"] == target
    html = client.get(target).content.decode()
    assert 'value="E310000000123"' in html and 'value="1180.00"' in html
    assert "Factura E310000000123 (RNC 101010101)" in html
    # El borrador se usa una sola vez.
    assert f"factura_qr:{personal_ws.pk}" not in client.session


def test_qr_que_no_es_factura(client, user, personal_ws):
    client.force_login(user)
    response = client.post(
        reverse("receipts:scan_qr", kwargs={"ws": personal_ws.pk}), {"texto": "hola"}, follow=True
    )
    assert "No reconocí una factura" in response.content.decode()


def test_foto_con_qr_prellena_numero_y_total(client, user, personal_ws, settings):
    client.force_login(user)
    upload = SimpleUploadedFile("factura.png", PNG, content_type="image/png")
    client.post(reverse("receipts:index", kwargs={"ws": personal_ws.pk}),
                {"file": upload, "qr_texto": DGII})  # fmt: skip
    receipt = Receipt.objects.get()
    assert receipt.qr_data["numero"] == "E310000000123"
    receipt.extracted = {"comercio": "Supermercado", "total": "1100.00", "numero_factura": "X1"}
    receipt.status = Receipt.Status.PARA_REVISAR
    receipt.save()
    form = ReviewForm(receipt)
    # El QR manda sobre lo leído en la foto.
    assert form.initial["invoice_number"] == "E310000000123"
    assert form.initial["amount"] == "1180.00"


def test_numero_de_factura_leido_por_la_ia(personal_ws, user):
    receipt = Receipt.objects.create(
        workspace=personal_ws, file="x.png", content_type="image/png", size=1, sha256="a" * 64,
        status=Receipt.Status.PARA_REVISAR,
        extracted={"comercio": "Farmacia", "total": "300", "numero_factura": "B0100000077"},
    )  # fmt: skip
    form = ReviewForm(receipt)
    assert form.initial["invoice_number"] == "B0100000077"
    assert "rubro" in form.fields
