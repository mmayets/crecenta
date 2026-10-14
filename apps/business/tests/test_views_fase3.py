import uuid
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.business.models import InventoryMovement, Payable, Product, Purchase, Sale
from apps.business.services.sales import (
    SaleData,
    SaleLineData,
    collect_receivable,
    register_sale,
)
from apps.ledger.models import Account, Transaction

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def logged(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def caja(business_ws):
    return Account.objects.get(workspace=business_ws)


@pytest.fixture
def refresco(business_ws):
    return Product.objects.create(
        workspace=business_ws, name="Refresco 2L", price=D("120"), unit_cost=D("0"),
        tracks_inventory=True, stock_minimum=D("5"),
    )  # fmt: skip


def u(name, ws, **kw):
    return reverse(f"business:{name}", kwargs={"ws": ws.pk, **kw})


def hoy():
    return timezone.localdate().isoformat()


def test_compra_inventario_y_conteo(logged, business_ws, refresco, caja):
    html = logged.get(u("inventory", business_ws)).content.decode()
    assert "Refresco 2L" in html and 'data-testid="valor-inventario"' in html
    data = {
        "client_uuid": str(uuid.uuid4()), "date": hoy(), "payment": "contado",
        "account": str(caja.pk), "supplier_name": "Distribuidora", "tax": "108",
        "producto_1": str(refresco.pk), "cantidad_1": "12", "costo_1": "50",
    }  # fmt: skip
    assert "Compra de mercancía" in logged.get(u("purchase_new", business_ws)).content.decode()
    response = logged.post(u("purchase_new", business_ws), data)
    purchase = Purchase.objects.get()
    assert response["Location"] == u("purchase_detail", business_ws, purchase_id=purchase.pk)
    logged.post(u("purchase_new", business_ws), data)  # doble envío
    assert Purchase.objects.count() == 1
    refresco.refresh_from_db()
    assert refresco.stock == 12 and purchase.total == D("708.00")
    detalle = logged.get(u("purchase_detail", business_ws, purchase_id=purchase.pk)).content
    assert "Distribuidora" in detalle.decode()
    assert "Distribuidora" in logged.get(u("purchases", business_ws)).content.decode()
    inv = logged.get(u("inventory", business_ws)).content.decode()
    assert "RD$600.00" in inv

    # Conteo: hay 10 en vez de 12; merma de 1; inventario inicial sin costo da error.
    stock_url = u("stock_product", business_ws, product_id=refresco.pk)
    logged.post(stock_url, {"client_uuid": str(uuid.uuid4()), "action": "contar", "qty": "10",
                            "date": hoy()})  # fmt: skip
    logged.post(stock_url, {"client_uuid": str(uuid.uuid4()), "action": "merma", "qty": "1",
                            "date": hoy(), "note": "Rota"})  # fmt: skip
    refresco.refresh_from_db()
    assert refresco.stock == 9
    bad = logged.post(stock_url, {"client_uuid": str(uuid.uuid4()), "action": "inicial",
                                  "qty": "1", "date": hoy()})  # fmt: skip
    assert bad.status_code == 400
    bad = logged.post(stock_url, {"client_uuid": str(uuid.uuid4()), "action": "merma", "qty": "0",
                                  "date": hoy()})  # fmt: skip
    assert bad.status_code == 400
    historial = logged.get(stock_url).content.decode()
    assert "Ajuste por conteo" in historial and "Rota" in historial and "Ver compra" in historial

    merma = InventoryMovement.objects.get(kind="merma")
    logged.post(u("movement_delete", business_ws, movement_id=merma.pk))
    compra_mov = InventoryMovement.objects.get(kind="compra")
    logged.post(u("movement_delete", business_ws, movement_id=compra_mov.pk))  # no se permite
    assert InventoryMovement.objects.filter(pk=compra_mov.pk).exists()
    refresco.refresh_from_db()
    assert refresco.stock == 10

    logged.post(u("purchase_delete", business_ws, purchase_id=purchase.pk))
    assert not Purchase.objects.exists() and not Transaction.objects.exists()


def test_compra_a_credito_y_anular_con_pagos(logged, business_ws, refresco, caja, user):
    data = {"client_uuid": str(uuid.uuid4()), "date": hoy(), "payment": "credito",
            "producto_1": str(refresco.pk), "cantidad_1": "6", "costo_1": "50"}  # fmt: skip
    logged.post(u("purchase_new", business_ws), data)
    purchase = Purchase.objects.get()
    cxp = Payable.objects.get(purchase=purchase)
    from apps.business.services.sales import pay_payable

    pay_payable(business_ws, user, cxp, "100", caja, timezone.localdate())
    response = logged.post(u("purchase_delete", business_ws, purchase_id=purchase.pk))
    assert response["Location"] == u("purchase_detail", business_ws, purchase_id=purchase.pk)
    assert Purchase.objects.exists()
    invalida = {**data, "client_uuid": str(uuid.uuid4()), "payment": "contado", "costo_1": ""}
    assert logged.post(u("purchase_new", business_ws), invalida).status_code == 400


def test_compra_sin_productos_con_inventario(logged, business_ws):
    assert logged.get(u("purchase_new", business_ws))["Location"] == u("products", business_ws)


def test_producto_sin_inventario_redirige(logged, business_ws):
    pan = Product.objects.create(workspace=business_ws, name="Pan", price=D("1"), unit_cost=D("1"))
    response = logged.get(u("stock_product", business_ws, product_id=pan.pk))
    assert response["Location"] == u("product_edit", business_ws, product_id=pan.pk)


def test_editar_venta_y_aviso_sin_existencias(logged, business_ws, refresco, caja, user):
    data = {"client_uuid": str(uuid.uuid4()), "date": hoy(), "payment": "contado",
            "account": str(caja.pk), "producto_1": str(refresco.pk), "cantidad_1": "2"}  # fmt: skip
    response = logged.post(u("sale_new", business_ws), data, follow=True)
    assert "Vendiste más Refresco 2L" in response.content.decode()
    sale = Sale.objects.get()
    edit_url = u("sale_edit", business_ws, sale_id=sale.pk)
    form_html = logged.get(edit_url).content.decode()
    assert "Editar venta" in form_html and 'value="2' in form_html
    logged.post(edit_url, {**data, "cantidad_1": "1", "payment": "credito", "account": "",
                           "customer_name": "Ariel"})  # fmt: skip
    sale.refresh_from_db()
    assert sale.total == D("120.00") and sale.receivable.customer.name == "Ariel"
    collect_receivable(business_ws, user, sale.receivable, "10", caja, timezone.localdate())
    assert logged.get(edit_url)["Location"] == u("sale_detail", business_ws, sale_id=sale.pk)
    libre = register_sale(business_ws, user, SaleData(
        date=timezone.localdate(), lines=[SaleLineData(None, D("1"), D("5"), description="Otro")],
        account=caja))[0]  # fmt: skip
    url = u("sale_edit", business_ws, sale_id=libre.pk)
    assert logged.get(url)["Location"] == u("sale_detail", business_ws, sale_id=libre.pk)
    assert logged.post(url, {}).status_code == 302


def test_reportes_y_csv(logged, business_ws, refresco, caja, user):
    register_sale(business_ws, user, SaleData(date=timezone.localdate(),
                  lines=[SaleLineData(refresco, D("2"))], account=caja))  # fmt: skip
    html = logged.get(u("reports", business_ws)).content.decode()
    assert 'data-type="bar"' in html and "Estimado por pagar" in html and "DGII" in html
    month = timezone.localdate().strftime("%Y-%m")
    assert logged.get(u("reports", business_ws) + f"?mes={month}").status_code == 200
    assert logged.get(u("reports", business_ws) + "?mes=nope").status_code == 200
    assert logged.get(u("reports", business_ws) + "?mes=2999-01").status_code == 200
    csv = logged.get(u("reports_csv", business_ws))
    assert csv["Content-Type"].startswith("text/csv")
    text = csv.content.decode("utf-8-sig")
    assert text.startswith("Mes,Ventas sin ITBIS") and "240.00" in text


def test_registro_rapido_con_itbis_solo_en_negocio(logged, business_ws, personal_ws, caja):
    html = logged.get(reverse("ledger:new", kwargs={"ws": business_ws.pk})).content.decode()
    assert "ITBIS incluido en la factura" in html
    html = logged.get(reverse("ledger:new", kwargs={"ws": personal_ws.pk})).content.decode()
    assert "ITBIS incluido" not in html
    logged.post(reverse("ledger:new", kwargs={"ws": business_ws.pk}), {
        "client_uuid": str(uuid.uuid4()), "kind": "gasto", "amount": "1180", "tax_amount": "180",
        "account": str(caja.pk), "date": hoy(), "source": "manual",
    })  # fmt: skip
    assert Transaction.objects.get(workspace=business_ws).tax_amount == D("180")
