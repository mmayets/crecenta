import datetime
from decimal import Decimal

import pytest

from apps.business.models import BusinessGoal, OperatingExpense, Product
from apps.business.services.loaders import business_snapshot, month_bounds
from apps.business.services.sales import (
    DebtData,
    SaleData,
    SaleLineData,
    collect_receivable,
    register_payable,
    register_sale,
)
from apps.ledger.models import Account, Category, Transaction
from apps.ledger.services.recording import create_account, record_transfer

D = Decimal
HOY = datetime.date(2026, 10, 13)


@pytest.fixture
def negocio(business_ws, user):
    ws = business_ws
    caja = Account.objects.get(workspace=ws)
    caja.opening_balance = D("40000")
    caja.save()
    cat = {c.name: c for c in Category.objects.for_workspace(ws)}
    biz = Product.objects.create(
        workspace=ws, name="Bizcocho", price=D("857.14"), unit_cost=D("600")
    )
    register_sale(ws, user, SaleData(date=HOY, lines=[SaleLineData(biz, D("10"))], account=caja))
    venta, _ = register_sale(
        ws, user,
        SaleData(date=HOY, lines=[SaleLineData(biz, D("5"))], payment="credito",
                 due_date=datetime.date(2026, 10, 25)),
    )  # fmt: skip
    collect_receivable(ws, user, venta.receivable, "1000", caja, HOY)

    def tx(amount, kind, direction, category=None, **kw):
        return Transaction.objects.create(
            workspace=ws, account=caja, date=HOY, amount=D(amount), kind=kind,
            direction=direction, category=category, **kw,
        )  # fmt: skip

    tx("15000", "gasto", "out", cat["Alquiler del local"])
    tx("2000", "gasto", "out", cat["Comisiones"])
    tx("3000", "compra_inventario", "out", cat["Materia prima"])
    tx("500", "gasto", "out")  # sin categoría
    tx("1000", "venta", "in", cat["Ventas"])  # venta sin detalle
    tx("700", "ingreso", "in", cat["Otros ingresos del negocio"])
    tx("999", "gasto", "out", cat["Alquiler del local"], status="pendiente_revision")
    banco = create_account(ws, "Banco", "banco")
    record_transfer(ws, user, from_account=caja, to_account=banco, amount="5000", on=HOY)
    ahorro = create_account(ws, "Ahorro", "banco", opening_balance="9000", is_savings=True)
    assert ahorro.pk
    OperatingExpense.objects.create(
        workspace=ws, name="Alquiler", amount=D("15000"), due_day=10,
        category=cat["Alquiler del local"],
    )  # fmt: skip
    OperatingExpense.objects.create(workspace=ws, name="Nómina", amount=D("12000"), due_day=30)
    OperatingExpense.objects.create(workspace=ws, name="Viejo", amount=D("1"), is_active=False)
    register_payable(
        ws, user,
        DebtData(concept="Harina", amount=D("5000"), due_date=datetime.date(2026, 10, 5),
                 category=cat["Materia prima"]),
    )  # fmt: skip
    BusinessGoal.objects.create(workspace=ws, target_sales=D("20000"), cash_reserve=D("1000"))
    return ws


def test_periodo_mensual():
    assert month_bounds(HOY) == (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))


def test_indicadores_desde_la_base(negocio):
    snap = business_snapshot(negocio, HOY)
    ind = snap.indicators
    assert ind.sales == D("13857.10")  # 15 × 857.14 + 1000 sin detalle
    assert ind.cogs == D("9000.00")
    assert ind.operating_expenses == D("15500")  # alquiler + gasto sin categoría
    assert ind.variable_costs_paid == D("5000")  # comisión + materia prima
    assert ind.other_income == D("700")
    # Entradas: contado 8571.40 + cobro 1000 + venta sin detalle 1000 + ingreso 700.
    assert ind.cash_in == D("11271.40") and ind.cash_out == D("20500")
    assert ind.receivables == D("3285.70") and ind.receivables_overdue == 0
    assert ind.payables == D("5000") and ind.payables_overdue == D("5000")
    assert ind.fixed_costs_month == D("27000.00") and ind.goal.sales_pct == D("69.29")
    assert len(ind.notes) == 2


def test_caja_y_reserva_desde_la_base(negocio):
    cash = business_snapshot(negocio, HOY).cash
    # 40000 + 11271.40 − 20500 (la transferencia y el ahorro no cambian el efectivo operativo)
    assert cash.cash_now == D("30771.40")
    labels = [(i.label, i.amount) for i in cash.outflows]
    # El alquiler de octubre ya se pagó: el próximo es el de noviembre.
    assert labels == [("Harina", D("5000")), ("Nómina", D("12000")), ("Alquiler", D("15000"))]
    assert [i.label for i in cash.inflows] == ["Venta: 5 Bizcocho"]
    assert cash.reserve.committed == D("32000") and cash.reserve.reserve == D("1000")
    assert cash.reserve.max_safe_withdrawal == 0
    # Contando el cobro esperado de Pedro no faltaría dinero, pero el retiro seguro no lo cuenta.
    assert cash.projection.gaps == [] and cash.projection.lowest_balance == D("2057.10")


def test_negocio_vacio(business_ws):
    snap = business_snapshot(business_ws, HOY)
    assert snap.indicators.sales == 0 and snap.cash.cash_now == 0
    assert snap.cash.reserve.max_safe_withdrawal == 0 and snap.cash.outflows == []
