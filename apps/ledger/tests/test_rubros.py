from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.ledger.choices import Rubro
from apps.ledger.models import Account, Category, Transaction

pytestmark = pytest.mark.django_db
D = Decimal
TODAY = date.today()


def url(name, ws):
    return reverse(f"ledger:{name}", kwargs={"ws": ws.pk})


def cat(ws, name):
    return Category.objects.for_workspace(ws).get(name=name)


def save(client, ws, **extra):
    account = Account.objects.for_workspace(ws).first()
    data = {"kind": "gasto", "amount": "500", "account": account.pk, "date": TODAY.isoformat(),
            "client_uuid": extra.pop("client_uuid", "6f1d2c3b-4a5e-4f60-9a7b-8c9d0e1f2a3b"),
            "source": "manual", **extra}  # fmt: skip
    return client.post(url("new", ws), data)


def test_categorias_personales_traen_rubro(personal_ws):
    assert cat(personal_ws, "Alimentación").rubro == Rubro.ALIMENTACION
    assert cat(personal_ws, "Educación").rubro == Rubro.EDUCACION
    assert cat(personal_ws, "Salud y farmacia").rubro == Rubro.SALUD
    assert cat(personal_ws, "Alquiler o hipoteca").rubro == Rubro.VIVIENDA
    assert cat(personal_ws, "Ropa").rubro == Rubro.VESTIMENTA
    assert cat(personal_ws, "Turismo nacional").rubro == Rubro.TURISMO
    assert cat(personal_ws, "Suscripciones").rubro == Rubro.OTRO
    assert cat(personal_ws, "Salario").rubro == ""  # los ingresos no tienen rubro


def test_el_gasto_toma_el_rubro_de_su_categoria_o_el_elegido(client, user, personal_ws):
    client.force_login(user)
    save(client, personal_ws, category=cat(personal_ws, "Ropa").pk)
    assert Transaction.objects.get().rubro == Rubro.VESTIMENTA
    save(client, personal_ws, category=cat(personal_ws, "Ropa").pk, rubro="turismo_nacional",
         client_uuid="7a1d2c3b-4a5e-4f60-9a7b-8c9d0e1f2a3c")  # fmt: skip
    assert Transaction.objects.filter(rubro=Rubro.TURISMO).count() == 1
    save(client, personal_ws, client_uuid="8a1d2c3b-4a5e-4f60-9a7b-8c9d0e1f2a3d")  # sin categoría
    assert Transaction.objects.filter(rubro=Rubro.OTRO).count() == 1


def test_numero_de_factura_en_el_registro(client, user, personal_ws):
    client.force_login(user)
    save(client, personal_ws, invoice_number="  E310000000123 ")
    assert Transaction.objects.get().invoice_number == "E310000000123"
    html = client.get(url("movements", personal_ws)).content.decode()
    assert "Factura E310000000123" in html


def test_el_negocio_no_usa_rubros(client, user, business_ws):
    client.force_login(user)
    html = client.get(url("new", business_ws)).content.decode()
    assert 'name="rubro"' not in html and 'name="invoice_number"' in html
    assert client.get(url("rubros", business_ws)).status_code == 404


def test_resumen_por_rubro_y_csv(client, user, personal_ws):
    client.force_login(user)
    save(client, personal_ws, category=cat(personal_ws, "Alimentación").pk, amount="1200")
    save(client, personal_ws, category=cat(personal_ws, "Salud y farmacia").pk, amount="800",
         client_uuid="9a1d2c3b-4a5e-4f60-9a7b-8c9d0e1f2a3e")  # fmt: skip
    html = client.get(url("movements", personal_ws)).content.decode()
    assert 'data-rubro="alimentacion"' in html and "Gastos por rubro" in html
    page = client.get(url("rubros", personal_ws), {"anio": TODAY.year}).content.decode()
    for label in ("Alimentación", "Educación, Arte y Cultura", "Salud", "Vivienda", "Vestimenta",
                  "Turismo Nacional", "Otro"):  # fmt: skip
        assert label in page
    csv_text = client.get(
        url("rubros", personal_ws), {"anio": TODAY.year, "formato": "csv"}
    ).content.decode("utf-8-sig")
    lines = {line.split(",")[0]: line for line in csv_text.splitlines()}
    assert lines["Alimentación"].endswith(",1200.00") and lines["Total"].endswith(",2000.00")


def test_cambiar_el_rubro_de_una_categoria(client, user, personal_ws):
    client.force_login(user)
    regalos = cat(personal_ws, "Regalos")
    client.post(
        reverse("ledger:category_edit", kwargs={"ws": personal_ws.pk, "category_id": regalos.pk}),
        {"name": "Regalos", "group": "discrecional", "rubro": "vestimenta"},
    )
    regalos.refresh_from_db()
    assert regalos.rubro == Rubro.VESTIMENTA
