import datetime
import uuid
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.business.models import (
    BusinessGoal,
    BusinessProfile,
    CostComponent,
    OperatingExpense,
    Payable,
    Product,
    Receivable,
    Sale,
)
from apps.ledger.models import Account, Category, Transaction
from apps.workspaces.models import WorkspaceTransfer

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def logged(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def negocio(business_ws):
    caja = Account.objects.get(workspace=business_ws)
    caja.opening_balance = D("40000")
    caja.save()
    BusinessProfile.objects.create(workspace=business_ws, activity="Repostería")
    BusinessGoal.objects.create(workspace=business_ws, target_margin_pct=D("0.30"))
    Product.objects.create(
        workspace=business_ws, name="Bizcocho", price=D("857.14"), unit_cost=D("600")
    )
    Product.objects.create(workspace=business_ws, name="Cupcake", price=D("100"), unit_cost=D("80"))
    OperatingExpense.objects.create(
        workspace=business_ws, name="Alquiler", amount=D("32000"), due_day=28
    )
    return business_ws


def u(name, ws, **kw):
    return reverse(f"business:{name}", kwargs={"ws": ws.pk, **kw})


def test_venta_de_contado_y_a_credito(logged, negocio):
    biz = Product.objects.get(name="Bizcocho")
    caja = Account.objects.get(workspace=negocio)
    html = logged.get(u("sale_new", negocio)).content.decode()
    assert "Registrar venta" in html and "Cobrar ITBIS en esta venta" in html
    data = {
        "client_uuid": str(uuid.uuid4()),
        "date": timezone.localdate().isoformat(),
        "payment": "contado",
        "account": str(caja.pk),
        "producto_1": str(biz.pk),
        "cantidad_1": "2",
        "apply_tax": "on",
    }
    response = logged.post(u("sale_new", negocio), data)
    sale = Sale.objects.get()
    assert response["Location"] == u("sale_detail", negocio, sale_id=sale.pk)
    assert sale.subtotal == D("1714.28") and sale.tax == D("308.57")
    logged.post(u("sale_new", negocio), data)  # doble envío
    assert Sale.objects.count() == 1
    detail = logged.get(u("sale_detail", negocio, sale_id=sale.pk)).content.decode()
    assert "Ganancia bruta" in detail and "RD$514.28" in detail

    credito = {**data, "client_uuid": str(uuid.uuid4()), "payment": "credito", "account": "",
               "customer_name": "Pedro", "due_date": "2026-12-01"}  # fmt: skip
    logged.post(u("sale_new", negocio), credito)
    venta = Sale.objects.get(payment="credito")
    assert venta.receivable.customer.name == "Pedro"
    assert not Transaction.objects.filter(sale=venta).exists()
    lista = logged.get(u("sales", negocio)).content.decode()
    assert "Pedro" in lista and "Crédito" in lista


def test_venta_invalida_y_sin_productos(logged, negocio, business_ws, user):
    response = logged.post(
        u("sale_new", negocio),
        {"client_uuid": str(uuid.uuid4()), "date": "2026-10-13", "payment": "contado",
         "producto_1": str(Product.objects.first().pk), "cantidad_1": ""},
    )  # fmt: skip
    assert response.status_code == 400
    Product.objects.update(is_active=False)
    assert logged.get(u("sale_new", negocio))["Location"] == u("product_new", negocio)


def test_anular_venta(logged, negocio):
    from apps.business.services.sales import SaleData, SaleLineData, register_sale

    biz = Product.objects.get(name="Bizcocho")
    sale, _ = register_sale(
        negocio, None, SaleData(date=timezone.localdate(), lines=[SaleLineData(biz, D("1"))],
                                payment="credito")
    )  # fmt: skip
    from apps.business.services.sales import collect_receivable

    collect_receivable(
        negocio, None, sale.receivable, "100", Account.objects.get(), timezone.localdate()
    )
    response = logged.post(u("sale_delete", negocio, sale_id=sale.pk))
    assert response["Location"] == u("sale_detail", negocio, sale_id=sale.pk)
    assert Sale.objects.exists()
    Transaction.objects.all().delete()
    Receivable.objects.update(paid=0)
    logged.post(u("sale_delete", negocio, sale_id=sale.pk))
    assert not Sale.objects.exists()


def test_productos_margen_y_componentes(logged, negocio):
    html = logged.get(u("products", negocio)).content.decode()
    assert "Margen 20.00 %" in html and "Precio sugerido para tu margen: RD$114.29" in html
    assert html.index("Cupcake") < html.index("Bizcocho")  # primero el de menor margen
    cup = Product.objects.get(name="Cupcake")
    data = {
        "name": "Cupcake",
        "price": "100",
        "unit_cost": "0",
        "componentes-TOTAL_FORMS": "2",
        "componentes-INITIAL_FORMS": "0",
        "componentes-MIN_NUM_FORMS": "0",
        "componentes-MAX_NUM_FORMS": "1000",
        "componentes-0-name": "Harina y más",
        "componentes-0-type": "materia",
        "componentes-0-amount": "60",
        "componentes-1-name": "App",
        "componentes-1-type": "comision_pct",
        "componentes-1-amount": "0.10",
        "receta-TOTAL_FORMS": "0",
        "receta-INITIAL_FORMS": "0",
        "receta-MIN_NUM_FORMS": "0",
        "receta-MAX_NUM_FORMS": "1000",
    }
    response = logged.post(u("product_edit", negocio, product_id=cup.pk), data)
    assert response["Location"] == u("products", negocio)
    cup.refresh_from_db()
    assert cup.unit_cost == D("70.00") and CostComponent.objects.count() == 2
    bad = {**data, "componentes-1-amount": "10"}
    assert logged.post(u("product_edit", negocio, product_id=cup.pk), bad).status_code == 400
    nuevo = {**data, "name": "Galletas", "componentes-TOTAL_FORMS": "0"}
    logged.post(u("product_new", negocio), nuevo)
    assert Product.objects.filter(name="Galletas", unit_cost=0).exists()


def test_calculadora_de_precios(logged, negocio):
    html = logged.get(u("pricing", negocio)).content.decode()
    assert "¿A cuánto vendo?" in html and 'data-testid="precio-sugerido"' in html
    assert "RD$857.14" in html  # 600 al 30 % con los valores iniciales
    data = {
        "unit_cost": "600", "target_margin": "30", "commission": "10", "discount": "5",
        "delivery": "0", "tax": "18", "current_price": "900", "fixed_costs": "32000",
        "increase": "10", "labor_minutes": "", "hours": "",
    }  # fmt: skip
    response = logged.post(u("pricing", negocio), data, headers={"HX-Request": "true"})
    html = response.content.decode()
    assert "<html" not in html  # parcial para htmx
    assert "RD$1,052.63" in html and "Precio mínimo para no perder" in html
    assert "No descuentes más de" in html and "unidades</strong> al mes" in html
    assert "Si el proveedor sube 10.00 %" in html
    servicio = {**data, "labor_minutes": "45", "hours": "120"}
    assert (
        "caben 160 servicios"
        in logged.post(
            u("pricing", negocio), servicio, headers={"HX-Request": "true"}
        ).content.decode()
    )
    mal = logged.post(
        u("pricing", negocio), {**data, "target_margin": "95"}, headers={"HX-Request": "true"}
    )
    assert "menor que 100 %" in mal.content.decode()
    full = logged.post(u("pricing", negocio), data)
    assert "<html" in full.content.decode()
    biz = Product.objects.get(name="Bizcocho")
    assert (
        "Con los datos de Bizcocho"
        in logged.get(u("pricing", negocio) + f"?producto={biz.pk}").content.decode()
    )


def test_por_cobrar_y_por_pagar(logged, negocio):
    caja = Account.objects.get(workspace=negocio)
    nueva = {"client_uuid": str(uuid.uuid4()), "concept": "Saldo viejo", "amount": "2500",
             "counterpart_name": "Ariel"}  # fmt: skip
    logged.post(u("receivables", negocio), nueva)
    cxc = Receivable.objects.get()
    html = logged.get(u("receivables", negocio)).content.decode()
    assert "Saldo viejo" in html and "Cobrar" in html
    response = logged.post(
        u("collect", negocio, debt_id=cxc.pk),
        {"client_uuid": str(uuid.uuid4()), "amount": "3000", "account": str(caja.pk),
         "date": "2026-10-13"},
    )  # fmt: skip
    assert response.status_code == 400 and "RD$2,500.00" in response.content.decode()
    logged.post(
        u("collect", negocio, debt_id=cxc.pk),
        {"client_uuid": str(uuid.uuid4()), "amount": "1000", "account": str(caja.pk),
         "date": "2026-10-13"},
    )  # fmt: skip
    cxc.refresh_from_db()
    assert cxc.paid == D("1000")

    materia = Category.objects.get(workspace=negocio, name="Materia prima")
    html = logged.get(u("payables", negocio)).content.decode()
    assert "Proveedor" in html
    logged.post(u("payables", negocio), {"client_uuid": str(uuid.uuid4()), "concept": "Harina",
                                         "amount": "5000", "category": str(materia.pk),
                                         "due_date": "2026-10-01"})  # fmt: skip
    cxp = Payable.objects.get()
    assert "vencida" in logged.get(u("payables", negocio)).content.decode()
    logged.post(u("pay", negocio, debt_id=cxp.pk),
                {"client_uuid": str(uuid.uuid4()), "amount": "5000", "account": str(caja.pk),
                 "date": "2026-10-13"})  # fmt: skip
    cxp.refresh_from_db()
    assert cxp.status == "pagada"
    assert (
        logged.post(u("payables", negocio), {"client_uuid": str(uuid.uuid4())}).status_code == 400
    )


def test_retiro_con_aviso_de_reserva(logged, negocio, personal_ws):
    html = logged.get(u("owner", negocio)).content.decode()
    assert "necesita RD$32,000.00" in html and "Puedes retirar hasta RD$8,000.00" in html
    aviso = logged.post(
        u("owner_check", negocio), {"amount": "10000", "kind": "retiro_propietario"}
    )
    assert "quedarían RD$2,000.00 de pagos sin cubrir" in aviso.content.decode()
    assert "Puedes hacerlo igual" in aviso.content.decode()
    assert logged.post(u("owner_check", negocio), {"amount": "x"}).content.decode().strip() == ""
    data = {
        "client_uuid": str(uuid.uuid4()),
        "kind": "retiro_propietario",
        "amount": "10000",
        "account": str(Account.objects.get(workspace=negocio).pk),
        "personal_account": str(Account.objects.get(workspace=personal_ws).pk),
        "date": "2026-10-13",
    }
    assert logged.post(u("owner", negocio), data)["Location"] == reverse(
        "espacio:dashboard", kwargs={"ws": negocio.pk}
    )
    transfer = WorkspaceTransfer.objects.get()
    assert transfer.from_workspace == negocio and transfer.to_workspace == personal_ws
    aporte = {**data, "client_uuid": str(uuid.uuid4()), "kind": "aporte", "amount": "500"}
    logged.post(u("owner", negocio), aporte)
    assert WorkspaceTransfer.objects.filter(kind="aporte", to_workspace=negocio).exists()


def test_retiro_sin_espacio_personal(logged, negocio):
    assert logged.get(u("owner", negocio))["Location"] == reverse("workspaces:usage")


def test_inicio_del_negocio_con_datos(logged, negocio, user, personal_ws):
    from apps.business.services.sales import SaleData, SaleLineData, register_sale

    biz = Product.objects.get(name="Bizcocho")
    hoy = timezone.localdate()
    data = SaleData(
        date=hoy, lines=[SaleLineData(biz, D("10"))], payment="credito",
        due_date=hoy + datetime.timedelta(days=3), customer_name="Luisa",
    )  # fmt: skip
    register_sale(negocio, user, data)
    html = logged.get(reverse("espacio:dashboard", kwargs={"ws": negocio.pk})).content.decode()
    assert 'data-testid="ventas"' in html and "RD$8,571.40" in html
    assert "Luisa" in html and "Tus productos este mes" in html
    assert "Ventas, ganancia y efectivo no son lo mismo" in html


def test_secciones_de_negocio_no_existen_en_la_persona(logged, personal_ws):
    assert logged.get(u("sales", personal_ws)).status_code == 404
    assert logged.get(u("pricing", personal_ws)).status_code == 404


def test_registro_rapido_del_negocio_ofrece_compras(logged, negocio):
    html = logged.get(
        reverse("ledger:new", kwargs={"ws": negocio.pk}) + "?tipo=compra_inventario"
    ).content.decode()
    assert (
        "Compra de materiales" in html
        and 'value="compra_inventario" checked' in html.replace('" checked', '" checked')
        or "compra_inventario" in html
    )


def test_aviso_de_retiro_ignora_montos_absurdos(logged, negocio):
    for value in ("1e999999", "NaN", "-5", "Infinity"):
        response = logged.post(u("owner_check", negocio), {"amount": value})
        assert response.status_code == 200 and response.content.decode().strip() == ""


def test_retiro_entre_monedas_pide_tasa(logged, user, personal_ws):
    from apps.workspaces.services.workspaces import create_workspace

    tienda = create_workspace(user, "business", name="Tienda USD", currency="USD")
    html = logged.get(u("owner", tienda)).content.decode()
    assert "Tasa del día (RD$ por 1 US$)" in html
    data = {
        "client_uuid": str(uuid.uuid4()),
        "kind": "retiro_propietario",
        "amount": "100",
        "account": str(Account.objects.get(workspace=tienda).pk),
        "personal_account": str(Account.objects.get(workspace=personal_ws).pk),
        "date": "2026-10-13",
    }
    assert logged.post(u("owner", tienda), data).status_code == 400
    logged.post(u("owner", tienda), {**data, "exchange_rate": "60.25"})
    transfer = WorkspaceTransfer.objects.get()
    assert transfer.amount == D("100.00") and transfer.in_amount == D("6025.00")
    assert transfer.in_tx.amount == D("6025.00") and transfer.in_tx.workspace == personal_ws


def test_negocio_en_dolares_al_crear(logged):
    logged.post(
        reverse("workspaces:usage"),
        {"usage": "ambos", "currency": "DOP", "business_currency": "USD"},
    )
    from apps.workspaces.models import Workspace

    assert Workspace.objects.get(kind="business").currency == "USD"
