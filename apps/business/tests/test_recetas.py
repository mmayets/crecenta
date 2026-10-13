"""Recetas: el producto elaborado cuesta lo que cuestan sus insumos y, al venderse, los descuenta
(docs/fase4.md §3)."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.business.models import CostComponent, InventoryMovement, Product, RecipeItem
from apps.business.services.costs import refresh_unit_cost
from apps.business.services.inventory import register_adjustment
from apps.business.services.loaders import load_business_plan_inputs
from apps.business.services.product_cost import cost_basis, current_unit_cost, recipe_cost
from apps.business.services.sales import (
    SaleData,
    SaleLineData,
    delete_sale,
    edit_sale,
    register_sale,
)
from apps.ledger.models import Account

pytestmark = pytest.mark.django_db
D = Decimal
HOY = datetime.date(2026, 10, 13)


def insumo(ws, name, qty, cost):
    p = Product.objects.create(
        workspace=ws, name=name, price=0, unit_cost=0, is_supply=True, tracks_inventory=True
    )
    register_adjustment(ws, None, p, "inicial", D(qty), HOY, unit_cost=D(cost))
    p.refresh_from_db()
    return p


@pytest.fixture
def bizcocho(business_ws):
    harina = insumo(business_ws, "Harina (lb)", "50", "40")
    huevos = insumo(business_ws, "Huevos", "60", "9.5")
    biz = Product.objects.create(
        workspace=business_ws, name="Bizcocho", price=D("900"), unit_cost=0
    )
    RecipeItem.objects.create(product=biz, supply=harina, qty=D("2"))
    RecipeItem.objects.create(product=biz, supply=huevos, qty=D("6"))
    CostComponent.objects.create(product=biz, name="Caja", type="empaque", amount=D("35"))
    CostComponent.objects.create(product=biz, name="App", type="comision_pct", amount=D("0.10"))
    return biz


def vender(ws, product, qty="1", **kw):
    data = SaleData(
        date=HOY,
        account=Account.objects.get(workspace=ws, name="Efectivo"),
        lines=[SaleLineData(product=product, qty=D(qty))],
        **kw,
    )
    return register_sale(ws, None, data)[0]


def test_costo_de_receta(bizcocho):
    assert recipe_cost(bizcocho) == D("137.0000")  # 2 × 40 + 6 × 9.5
    assert cost_basis(bizcocho) == (D("172.0000"), D("0.10"))  # + caja; la comisión aparte
    assert current_unit_cost(bizcocho) == D("262.00")  # + 10 % de 900
    assert current_unit_cost(bizcocho, D("1000")) == D("272.00")
    refresh_unit_cost(bizcocho)
    bizcocho.refresh_from_db()
    assert bizcocho.unit_cost == D("262.00")
    assert recipe_cost(Product.objects.get(name="Huevos")) is None


def test_venta_descuenta_insumos(business_ws, bizcocho):
    sale = vender(business_ws, bizcocho, "3")
    line = sale.lines.get()
    assert line.unit_cost_snapshot == D("262.00")
    harina, huevos = Product.objects.get(name="Harina (lb)"), Product.objects.get(name="Huevos")
    assert harina.stock == D("44.000") and huevos.stock == D("42.000")
    salidas = InventoryMovement.objects.filter(sale_line=line).order_by("product__name")
    assert [(m.product.name, m.qty, m.value) for m in salidas] == [
        ("Harina (lb)", D("-6.000"), D("-240.00")),
        ("Huevos", D("-18.000"), D("-171.00")),
    ]
    edit_sale(business_ws, None, sale, SaleData(
        date=HOY, account=Account.objects.get(workspace=business_ws, name="Efectivo"),
        lines=[SaleLineData(product=bizcocho, qty=D("1"))],
    ))  # fmt: skip
    harina.refresh_from_db()
    assert harina.stock == D("48.000")
    delete_sale(business_ws, sale)
    harina.refresh_from_db()
    huevos.refresh_from_db()
    assert harina.stock == D("50.000") and huevos.stock == D("60.000")


def test_insumo_no_se_vende(business_ws, bizcocho):
    with pytest.raises(ValidationError, match="insumo no se vende"):
        vender(business_ws, Product.objects.get(name="Huevos"))


def test_validacion_del_ingrediente(business_ws, bizcocho, other_ws, user):
    from apps.workspaces.services.workspaces import create_workspace

    no_insumo = Product.objects.create(workspace=business_ws, name="Velas", price=50, unit_cost=10)
    with pytest.raises(ValidationError) as exc:
        RecipeItem(product=bizcocho, supply=no_insumo, qty=1).full_clean()
    assert "supply" in exc.value.message_dict
    otro = create_workspace(user, "business", name="Otro")
    ajeno = insumo(otro, "Azúcar", "10", "30")
    with pytest.raises(ValidationError, match="no pertenece"):
        RecipeItem(product=bizcocho, supply=ajeno, qty=1).full_clean()
    harina = Product.objects.get(name="Harina (lb)")
    with pytest.raises(ValidationError, match="sí mismo"):
        RecipeItem(product=harina, supply=harina, qty=1).clean()


def test_plan_usa_costo_de_receta_y_excluye_insumos(business_ws, bizcocho):
    plan = load_business_plan_inputs(business_ws, HOY)
    assert [p.name for p in plan.products] == ["Bizcocho"]
    assert plan.products[0].base_cost == D("172.0000")
    assert plan.products[0].commission_pct == D("0.10")


def form_data(**kw):
    data = {
        "name": "Bizcocho", "price": "900", "unit_cost": "0",
        "componentes-TOTAL_FORMS": "0", "componentes-INITIAL_FORMS": "0",
        "componentes-MIN_NUM_FORMS": "0", "componentes-MAX_NUM_FORMS": "1000",
        "receta-TOTAL_FORMS": "1", "receta-INITIAL_FORMS": "0",
        "receta-MIN_NUM_FORMS": "0", "receta-MAX_NUM_FORMS": "1000",
    }  # fmt: skip
    return {**data, **kw}


def test_pantalla_de_receta(client, user, business_ws):
    client.force_login(user)
    harina = insumo(business_ws, "Harina (lb)", "50", "40")
    url = reverse("business:product_new", kwargs={"ws": business_ws.pk})
    html = client.get(url).content.decode()
    assert "Harina (lb)" in html and "receta-TOTAL_FORMS" in html
    data = form_data(**{"receta-0-supply": str(harina.pk), "receta-0-qty": "2.5"})
    response = client.post(url, data)
    assert response.status_code == 302
    biz = Product.objects.get(name="Bizcocho")
    assert biz.unit_cost == D("100.00") and biz.recipe.get().qty == D("2.5")
    edit = reverse("business:product_edit", kwargs={"ws": business_ws.pk, "product_id": biz.pk})
    assert "RD$100.00" in client.get(edit).content.decode()
    # Con receta no lleva inventario propio.
    malo = {**data, "name": "Otro", "tracks_inventory": "on"}
    response = client.post(url, malo)
    assert response.status_code == 400 and "no lleva inventario propio" in response.content.decode()
    # El selector de la receta solo ofrece insumos del negocio.
    Product.objects.create(workspace=business_ws, name="Velas", price=50, unit_cost=10)
    assert "Velas" not in client.get(edit).content.decode().split("receta-0-supply")[1][:2000]


def test_insumo_requiere_inventario(client, user, business_ws):
    client.force_login(user)
    url = reverse("business:product_new", kwargs={"ws": business_ws.pk})
    data = form_data(**{"name": "Azúcar", "is_supply": "on", "receta-TOTAL_FORMS": "0"})
    response = client.post(url, data)
    assert (
        response.status_code == 400
        and "necesita control de inventario" in response.content.decode()
    )
