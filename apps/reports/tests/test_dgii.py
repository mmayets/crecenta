"""NCF en ventas y compras y archivos de apoyo 606/607 (docs/fase4.md, decisión 7)."""

import csv
import datetime
import io
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.business.models import BusinessProfile, Customer, Product, Supplier
from apps.business.services.purchases import PurchaseData, PurchaseLineData, register_purchase
from apps.business.services.sales import SaleData, SaleLineData, pay_payable, register_sale
from apps.ledger.models import Account
from apps.reports.services.dgii import (
    HEADERS_606,
    HEADERS_607,
    id_type,
    purchases_606,
    sales_607,
    totals,
)

pytestmark = pytest.mark.django_db
D = Decimal
OCT = (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))


@pytest.fixture
def negocio(business_ws):
    BusinessProfile.objects.create(
        workspace=business_ws, activity="Colmado", tax_rate_itbis=D("0.18")
    )
    Product.objects.create(
        workspace=business_ws, name="Refresco", price=D("100"), unit_cost=D("60")
    )
    Product.objects.create(
        workspace=business_ws, name="Arroz", price=D("50"), unit_cost=0, tracks_inventory=True
    )
    banco = Account.objects.create(
        workspace=business_ws, name="Banco", type="banco", currency="DOP"
    )
    return business_ws, banco


def caja(ws):
    return Account.objects.get(workspace=ws, name="Efectivo")


def venta(ws, account="caja", **kw):
    data = SaleData(
        date=datetime.date(2026, 10, 5),
        account=caja(ws) if account == "caja" else account,
        lines=[SaleLineData(product=Product.objects.get(name="Refresco"), qty=D("2"))],
        **kw,
    )
    return register_sale(ws, None, data)[0]


def compra(ws, **kw):
    data = PurchaseData(
        date=datetime.date(2026, 10, 3),
        lines=[PurchaseLineData(Product.objects.get(name="Arroz"), D("10"), D("30"))],
        tax=D("54"),
        **{"account": caja(ws), **kw},
    )
    return register_purchase(ws, None, data)[0]


def test_ncf_y_rnc_en_la_venta(negocio):
    ws, banco = negocio
    sale = venta(ws, banco, ncf=" b01-00000001 ", customer_name="Ferretería Sol",
                 customer_tax_id="1-01-12345-6")  # fmt: skip
    assert sale.ncf == "B0100000001"
    assert Customer.objects.get(name="Ferretería Sol").tax_id == "101123456"
    with pytest.raises(ValidationError, match="ya está en otra venta"):
        venta(ws, ncf="B0100000001")
    with pytest.raises(ValidationError):
        venta(ws, ncf="X123")
    with pytest.raises(ValidationError) as exc:
        venta(ws, customer_name="Pedro", customer_tax_id="123")
    assert "tax_id" in exc.value.message_dict
    with pytest.raises(ValidationError, match="nombre"):
        venta(ws, customer_tax_id="101123456")


def test_ncf_en_la_compra(negocio):
    ws, _ = negocio
    p = compra(ws, ncf="B0100000099", supplier_name="Distribuidora", supplier_tax_id="40212345678")
    assert p.ncf == "B0100000099" and Supplier.objects.get().tax_id == "40212345678"
    with pytest.raises(ValidationError) as exc:
        compra(ws, ncf="B01")
    assert "ncf" in exc.value.message_dict


def test_archivo_607(negocio):
    ws, banco = negocio
    venta(ws, banco, ncf="B0100000001", customer_name="Ferretería Sol", customer_tax_id="101123456")
    venta(ws, ncf="B0200000001")  # consumidor final, en efectivo
    venta(ws, payment="credito", account=None, customer_name="Ariel", ncf="E310000000001")
    venta(ws)  # sin NCF
    f = sales_607(ws, *OCT)
    assert f.missing_ncf == 1 and f.missing_tax_id == 2 and len(f.rows) == 3
    first = dict(zip(HEADERS_607, f.rows[0], strict=True))
    assert first["RNC/Cédula o Pasaporte"] == "101123456" and first["Tipo Identificación"] == "1"
    assert first["Fecha Comprobante"] == "20261005" and first["Tipo de Ingreso"] == "01"
    assert first["Monto Facturado"] == "200.00" and first["ITBIS Facturado"] == "36.00"
    assert first["Cheque/Transferencia/Depósito"] == "236.00" and first["Efectivo"] == "0.00"
    rows = {r[2]: dict(zip(HEADERS_607, r, strict=True)) for r in f.rows}
    assert rows["B0200000001"]["Efectivo"] == "236.00"
    assert rows["E310000000001"]["Venta a Crédito"] == "236.00"
    assert totals(f, 7, 8) == (D("600.00"), D("108.00"))
    assert sales_607(ws, datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)).rows == []


def test_archivo_606(negocio):
    ws, banco = negocio
    compra(ws, ncf="B0100000099", supplier_name="Distribuidora", supplier_tax_id="40212345678")
    compra(ws, ncf="B0100000100", account=banco)
    credito = compra(ws, ncf="B0100000101", payment="credito", account=None,
                     due_date=datetime.date(2026, 11, 1))  # fmt: skip
    compra(ws)  # sin NCF
    f = purchases_606(ws, *OCT)
    assert f.missing_ncf == 1 and f.missing_tax_id == 2
    rows = {r[3]: dict(zip(HEADERS_606, r, strict=True)) for r in f.rows}
    a = rows["B0100000099"]
    assert a["Tipo Id"] == "2" and a["Tipo Bienes y Servicios Comprados"] == "09"
    assert a["Monto Facturado en Bienes"] == "300.00" and a["ITBIS Facturado"] == "54.00"
    assert a["Fecha Pago"] == "20261003" and a["Forma de Pago"] == "01"
    assert rows["B0100000100"]["Forma de Pago"] == "02"
    assert rows["B0100000101"]["Forma de Pago"] == "04" and rows["B0100000101"]["Fecha Pago"] == ""
    pay_payable(ws, None, credito.payable, D("354"), caja(ws), datetime.date(2026, 10, 20),
                uuid.uuid4())  # fmt: skip
    pagada = {r[3]: r for r in purchases_606(ws, *OCT).rows}["B0100000101"]
    assert pagada[HEADERS_606.index("Fecha Pago")] == "20261020"


def test_tipo_de_identificacion():
    assert id_type("") == "" and id_type("101123456") == "1" and id_type("40212345678") == "2"
    assert id_type("123") == ""


def test_pantalla_y_descarga(client, user, negocio):
    ws, banco = negocio
    venta(ws, banco, ncf="B0100000001")
    client.force_login(user)
    html = client.get(reverse("business:reports", kwargs={"ws": ws.pk}), {"mes": "2026-10"})
    text = html.content.decode()
    assert "Archivos de apoyo 606 y 607" in text and "No son el envío oficial" in text
    assert "1 con NCF" in text and "1 sin RNC o cédula" in text
    url = reverse("business:dgii_csv", kwargs={"ws": ws.pk, "form": "607"})
    response = client.get(url, {"mes": "2026-10"})
    assert 'filename="crecenta-607-apoyo-202610.csv"' in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[0] == HEADERS_607 and rows[1][2] == "B0100000001"
    url606 = reverse("business:dgii_csv", kwargs={"ws": ws.pk, "form": "606"})
    assert client.get(url606).content.decode("utf-8-sig").startswith("RNC o Cédula")
    bad = reverse("business:dgii_csv", kwargs={"ws": ws.pk, "form": "608"})
    assert client.get(bad).status_code == 404


def test_formularios_con_ncf(client, user, negocio):
    ws, _ = negocio
    client.force_login(user)
    url = reverse("business:sale_new", kwargs={"ws": ws.pk})
    assert "NCF que emitiste" in client.get(url).content.decode()
    data = {
        "client_uuid": str(uuid.uuid4()), "date": "2026-10-05", "payment": "contado",
        "account": str(caja(ws).pk), "producto_1": str(Product.objects.get(name="Refresco").pk),
        "cantidad_1": "1", "ncf": "B0100000007", "customer_name": "Sol",
        "customer_tax_id": "101123456",
    }  # fmt: skip
    response = client.post(url, data)
    assert response.status_code == 302
    detail = client.get(response["Location"]).content.decode()
    assert "NCF B0100000007" in detail
    malo = {**data, "client_uuid": str(uuid.uuid4()), "ncf": "B0100000007"}
    response = client.post(url, malo)
    assert response.status_code == 400 and "ya está en otra venta" in response.content.decode()
    compra_url = reverse("business:purchase_new", kwargs={"ws": ws.pk})
    assert "NCF de la factura" in client.get(compra_url).content.decode()
