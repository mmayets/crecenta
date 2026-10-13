import datetime
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.business.models import InventoryMovement, Payable, Product, Purchase, Receivable, Sale
from apps.business.services.indicators import compute_indicators
from apps.business.services.inventory import (
    MovementInput,
    StockState,
    apply_movement,
    count_stock,
    delete_movement,
    refresh_stock,
    register_adjustment,
    replay,
    weighted_average,
)
from apps.business.services.loaders import load_business_inputs
from apps.business.services.purchases import (
    PurchaseData,
    PurchaseLineData,
    delete_purchase,
    register_purchase,
)
from apps.business.services.sales import (
    SaleData,
    SaleLineData,
    collect_receivable,
    delete_sale,
    edit_sale,
    pay_payable,
    register_sale,
    stock_warnings,
)
from apps.ledger.choices import TxKind
from apps.ledger.models import Account, Transaction
from apps.ledger.services.balances import account_balance
from apps.workspaces.services.workspaces import create_workspace

D = Decimal
HOY = datetime.date(2026, 10, 13)


# ---------------------------------------------------------------------------- puro


def test_promedio_ponderado():
    assert weighted_average(D("10"), D("50"), D("10"), D("70")) == D("60.0000")
    assert weighted_average(D("3"), D("10"), D("7"), D("11")) == D("10.7000")
    assert weighted_average(D("0"), D("99"), D("5"), D("12.345")) == D("12.3450")
    assert weighted_average(D("-2"), D("10"), D("5"), D("20")) == D("20.0000")  # negativo: reinicia
    with pytest.raises(ValueError):
        weighted_average(D("1"), D("1"), D("0"), D("1"))


def test_replay_del_historial():
    state = replay(
        [
            MovementInput("inicial", D("10"), D("50")),
            MovementInput("venta", D("-4")),
            MovementInput("compra", D("6"), D("70")),  # (6×50 + 6×70) / 12 = 60
            MovementInput("merma", D("-2")),
            MovementInput("ajuste", D("1")),
        ]
    )
    assert state == StockState(D("11"), D("60.0000")) and state.value == D("660.00")
    assert StockState(D("-3"), D("10")).value == 0
    after, cost = apply_movement(StockState(D("5"), D("8")), MovementInput("venta", D("-1")))
    assert cost == D("8") and after.stock == 4
    with pytest.raises(ValueError):
        apply_movement(StockState(), MovementInput("venta", D("0")))
    with pytest.raises(ValueError):
        apply_movement(StockState(), MovementInput("compra", D("-1"), D("5")))


# ---------------------------------------------------------------------------- ORM


@pytest.fixture
def caja(business_ws):
    return Account.objects.get(workspace=business_ws)


@pytest.fixture
def refresco(business_ws):
    return Product.objects.create(
        workspace=business_ws, name="Refresco 2L", price=D("120"), unit_cost=D("0"),
        tracks_inventory=True, stock_minimum=D("6"),
    )  # fmt: skip


def comprar(ws, user, product, qty, cost, caja=None, **kw):
    data = PurchaseData(
        date=kw.pop("date", HOY),
        lines=[PurchaseLineData(product, D(qty), D(cost))],
        payment="credito" if caja is None else "contado",
        account=caja,
        **kw,
    )
    return register_purchase(ws, user, data)


def vender(ws, user, product, qty, caja=None, **kw):
    data = SaleData(
        date=kw.pop("date", HOY),
        lines=[SaleLineData(product, D(qty))],
        payment="credito" if caja is None else "contado",
        account=caja,
        **kw,
    )
    return register_sale(ws, user, data)


def test_inventario_inicial_compra_y_venta(business_ws, user, refresco, caja):
    register_adjustment(business_ws, user, refresco, "inicial", D("10"), HOY, unit_cost=D("50"))
    refresco.refresh_from_db()
    assert (refresco.stock, refresco.average_cost) == (D("10.000"), D("50.0000"))

    compra, _ = comprar(business_ws, user, refresco, "10", "70", caja, tax=D("126"),
                        supplier_name="Distribuidora")  # fmt: skip
    refresco.refresh_from_db()
    assert refresco.stock == 20 and refresco.average_cost == D("60.0000")
    assert compra.subtotal == D("700.00") and compra.total == D("826.00")
    tx = Transaction.objects.get(purchase=compra)
    assert tx.kind == TxKind.COMPRA_INVENTARIO and tx.tax_amount == D("126.00")
    assert tx.category.name == "Compras de mercancía" and account_balance(caja) == D("-826.00")

    venta, _ = vender(business_ws, user, refresco, "5", caja)
    line = venta.lines.get()
    assert line.unit_cost_snapshot == D("60.00") and line.movements.get().qty == D("-5.000")
    refresco.refresh_from_db()
    assert refresco.stock == 15 and stock_warnings(venta) == []

    # Las compras de mercancía no son costo variable; el costo entra al vender.
    ind = compute_indicators(load_business_inputs(business_ws, HOY.replace(day=1), HOY, HOY))
    assert ind.cogs == D("300.00") and ind.variable_costs_paid == 0
    assert ind.inventory_value == D("900.00") and ind.inventory_days == D("39.00")


def test_compra_a_credito_no_mueve_efectivo(business_ws, user, refresco, caja):
    compra, created = comprar(business_ws, user, refresco, "12", "55", due_date=HOY,
                              client_uuid=uuid.uuid4())  # fmt: skip
    again, created_again = comprar(business_ws, user, refresco, "12", "55",
                                   client_uuid=compra.client_uuid)  # fmt: skip
    assert created and not created_again and again.pk == compra.pk
    cxp = Payable.objects.get(purchase=compra)
    assert cxp.amount == D("660.00") and not Transaction.objects.exists()
    refresco.refresh_from_db()
    assert refresco.stock == 12
    pay_payable(business_ws, user, cxp, "660", caja, HOY)
    ind = compute_indicators(load_business_inputs(business_ws, HOY.replace(day=1), HOY, HOY))
    assert ind.variable_costs_paid == 0 and ind.cash_out == D("660")
    with pytest.raises(ValidationError):
        delete_purchase(business_ws, compra)  # ya tiene pagos


def test_anular_compra_revierte_existencias(business_ws, user, refresco, caja):
    compra, _ = comprar(business_ws, user, refresco, "8", "50", caja)
    comprar(business_ws, user, refresco, "2", "80", caja)
    delete_purchase(business_ws, compra)
    refresco.refresh_from_db()
    assert refresco.stock == 2 and refresco.average_cost == D("80.0000")
    assert not Purchase.objects.filter(pk=compra.pk).exists()
    assert Transaction.objects.count() == 1


def test_validaciones_de_compra(business_ws, user, refresco, caja):
    normal = Product.objects.create(workspace=business_ws, name="Bizcocho", price=D("1"),
                                    unit_cost=D("1"))  # fmt: skip
    with pytest.raises(ValidationError):
        comprar(business_ws, user, normal, "1", "1", caja)
    with pytest.raises(ValidationError):
        register_purchase(business_ws, user, PurchaseData(date=HOY, lines=[], account=caja))
    with pytest.raises(ValidationError):  # contado sin cuenta
        register_purchase(business_ws, user, PurchaseData(
            date=HOY, lines=[PurchaseLineData(refresco, D("1"), D("1"))]))  # fmt: skip
    with pytest.raises(ValidationError):
        comprar(business_ws, user, refresco, "1", "1", caja, tax=D("-1"))
    with pytest.raises(ValidationError):
        comprar(business_ws, user, refresco, "1", "0", caja)  # total cero
    otro = create_workspace(user, "business", name="Otro")
    with pytest.raises(ValidationError):
        comprar(otro, user, refresco, "1", "1", Account.objects.get(workspace=otro))


def test_vender_sin_existencias_avisa_y_anular_revierte(business_ws, user, refresco, caja):
    comprar(business_ws, user, refresco, "2", "60", caja)
    venta, _ = vender(business_ws, user, refresco, "3", caja)
    refresco.refresh_from_db()
    assert refresco.stock == -1
    assert "Vendiste más Refresco 2L" in stock_warnings(venta)[0]
    delete_sale(business_ws, venta)
    refresco.refresh_from_db()
    assert refresco.stock == 2 and not InventoryMovement.objects.filter(kind="venta").exists()


def test_editar_venta(business_ws, user, refresco, caja):
    comprar(business_ws, user, refresco, "10", "60", caja)
    otro = Product.objects.create(workspace=business_ws, name="Pan", price=D("10"),
                                  unit_cost=D("4"))  # fmt: skip
    venta, _ = vender(business_ws, user, refresco, "4", caja)
    tx_id = Transaction.objects.get(sale=venta).pk
    editada = edit_sale(
        business_ws, user, venta,
        SaleData(date=HOY, lines=[SaleLineData(refresco, D("2")), SaleLineData(otro, D("5"))],
                 payment="credito", customer_name="Luisa"),
    )  # fmt: skip
    assert editada.pk == venta.pk and editada.total == D("290.00")
    assert not Transaction.objects.filter(pk=tx_id).exists()
    assert Receivable.objects.get(sale=editada).amount == D("290.00")
    refresco.refresh_from_db()
    assert refresco.stock == 8 and editada.lines.count() == 2
    collect_receivable(business_ws, user, editada.receivable, "100", caja, HOY)
    with pytest.raises(ValidationError):
        nueva = SaleData(date=HOY, lines=[SaleLineData(refresco, D("1"))], payment="credito")
        edit_sale(business_ws, user, editada, nueva)
    otro_ws = create_workspace(user, "business", name="Otro")
    with pytest.raises(ValidationError):
        edit_sale(otro_ws, user, editada, SaleData(date=HOY, lines=[]))


def test_mermas_ajustes_y_conteo(business_ws, user, refresco, caja):
    comprar(business_ws, user, refresco, "10", "60", caja)
    merma = register_adjustment(business_ws, user, refresco, "merma", D("2"), HOY, note="Rotos")
    assert merma.qty == D("-2.000") and merma.value == D("-120.00")
    conteo = count_stock(business_ws, user, refresco, D("9"), HOY)  # había 8: sobra 1
    assert conteo.qty == D("1.000") and conteo.note == "Conteo: 9"
    ind = compute_indicators(load_business_inputs(business_ws, HOY.replace(day=1), HOY, HOY))
    assert ind.shrinkage == D("60.00") and ind.operating_result == D("-60.00")
    assert ind.cash_out == D("600")  # la merma no mueve efectivo
    uid = uuid.uuid4()
    a = register_adjustment(business_ws, user, refresco, "merma", D("1"), HOY, client_uuid=uid)
    b = register_adjustment(business_ws, user, refresco, "merma", D("1"), HOY, client_uuid=uid)
    assert a.pk == b.pk
    delete_movement(business_ws, a)
    refresco.refresh_from_db()
    assert refresco.stock == 9


def test_validaciones_de_ajustes(business_ws, user, refresco, caja):
    casos = [("inicial", "0", {"unit_cost": D("1")}), ("inicial", "1", {}), ("merma", "0", {}),
             ("ajuste", "0", {}), ("otro", "1", {})]  # fmt: skip
    for kind, qty, extra in casos:
        with pytest.raises(ValidationError):
            register_adjustment(business_ws, user, refresco, kind, D(qty), HOY, **extra)
    with pytest.raises(ValidationError):
        count_stock(business_ws, user, refresco, D("-1"), HOY)
    normal = Product.objects.create(workspace=business_ws, name="X", price=D("1"), unit_cost=D("1"))
    with pytest.raises(ValidationError):
        register_adjustment(business_ws, user, normal, "merma", D("1"), HOY)
    otro = create_workspace(user, "business", name="Otro")
    with pytest.raises(ValidationError):
        register_adjustment(otro, user, refresco, "merma", D("1"), HOY)
    comprar(business_ws, user, refresco, "1", "5", caja)
    movimiento = InventoryMovement.objects.get(kind="compra")
    with pytest.raises(ValidationError):
        delete_movement(business_ws, movimiento)
    with pytest.raises(ValidationError):
        delete_movement(otro, movimiento)
    assert refresh_stock(refresco).stock == 1


def test_carrera_de_ajuste(business_ws, user, refresco, monkeypatch):
    from django.db import IntegrityError

    from apps.business.services import inventory

    uid = uuid.uuid4()
    first = register_adjustment(business_ws, user, refresco, "inicial", D("1"), HOY,
                                unit_cost=D("1"), client_uuid=uid)  # fmt: skip
    calls = {"n": 0}
    real = InventoryMovement.objects.filter

    def fake(*a, **k):
        calls["n"] += 1
        qs = real(*a, **k)
        return qs.none() if calls["n"] == 1 else qs

    monkeypatch.setattr(InventoryMovement.objects, "filter", fake)
    again = register_adjustment(business_ws, user, refresco, "inicial", D("1"), HOY,
                                unit_cost=D("1"), client_uuid=uid)  # fmt: skip
    assert again.pk == first.pk
    monkeypatch.setattr(
        inventory, "_create", lambda *a, **k: (_ for _ in ()).throw(IntegrityError())
    )
    with pytest.raises(IntegrityError):
        register_adjustment(business_ws, user, refresco, "inicial", D("1"), HOY,
                            unit_cost=D("1"), client_uuid=uuid.uuid4())  # fmt: skip


def test_venta_de_producto_sin_inventario_no_crea_movimientos(business_ws, user, caja):
    pan = Product.objects.create(workspace=business_ws, name="Pan", price=D("10"), unit_cost=D("4"))
    venta, _ = vender(business_ws, user, pan, "3", caja)
    assert venta.lines.get().unit_cost_snapshot == D("4") and not InventoryMovement.objects.exists()
    assert Sale.objects.count() == 1
