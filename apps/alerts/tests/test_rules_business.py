import datetime
from dataclasses import replace
from decimal import Decimal

from apps.alerts.services.rules_business import (
    BusinessAlertContext,
    Withdrawal,
    cash_risk_dates,
    evaluate_business,
    low_margin,
    variable_costs_growing,
    withdrawal_without_coverage,
)
from apps.business.services.cash import CashItem, cash_projection, operating_reserve
from apps.business.services.indicators import BusinessPeriodInputs, SoldLine, compute_indicators

D = Decimal
HOY = datetime.date(2026, 10, 13)
INI = datetime.date(2026, 10, 1)


def indicators(lines=(), variable=None, start=INI, end=HOY):
    return compute_indicators(
        BusinessPeriodInputs(
            start=start,
            end=end,
            currency="DOP",
            lines=list(lines),
            variable_costs_paid=variable or D("0"),
        )
    )


BIZ = SoldLine("biz", "Bizcocho", D("10"), D("8571.40"), D("600"))  # 30 %
CUP = SoldLine("cup", "Cupcake", D("100"), D("10000"), D("80"))  # 20 %


def ctx(**kw):
    base = BusinessAlertContext(
        today=HOY,
        currency="DOP",
        month=indicators([BIZ]),
        previous_same_days=indicators(),
        projection=cash_projection(D("10000"), HOY, [], []),
        reserve=operating_reserve(D("10000"), HOY, []),
        withdrawals=[],
        target_margin=D("0.30"),
    )
    return replace(base, **kw)


def test_sin_problemas_no_hay_alertas():
    assert evaluate_business(ctx()) == []


def test_margen_bajo_objetivo():
    drafts = low_margin(ctx(month=indicators([BIZ, CUP])))
    assert len(drafts) == 1
    d = drafts[0]
    assert d.title == "Tu margen está bajo el objetivo" and d.severity == "media"
    assert "Este mes te queda 24.62 % de cada venta y tu objetivo es 30.00 %" in d.message
    assert "Cupcake (20.00 %)" in d.message and d.suggested_action["productos"] == ["cup"]
    # Margen global bien, pero un producto bajo el objetivo.
    mucho_biz = SoldLine("biz", "Bizcocho", D("100"), D("85714"), D("400"))
    solo_producto = low_margin(ctx(month=indicators([mucho_biz, CUP])))
    assert solo_producto[0].title == "Algunos productos dejan menos margen del objetivo"
    # Con pérdida es urgente.
    perdida = SoldLine("x", "X", D("1"), D("100"), D("150"))
    assert low_margin(ctx(month=indicators([perdida])))[0].severity == "alta"
    # Sin objetivo, sin ventas o con la regla tolerante: nada.
    assert low_margin(ctx(month=indicators([CUP]), target_margin=None)) == []
    assert low_margin(ctx(month=indicators())) == []
    tolerante = ctx(
        month=indicators([CUP]), params={"margen_bajo_objetivo": {"puntos_tolerancia": 15}}
    )
    assert low_margin(tolerante) == []


def test_costos_variables_crecen_mas_que_las_ventas():
    antes = indicators([BIZ], variable=D("2000"), start=datetime.date(2026, 9, 1))
    ahora = indicators([BIZ], variable=D("3000"))
    d = variable_costs_growing(ctx(month=ahora, previous_same_days=antes))[0]
    assert d.code == "costos_variables_crecen" and "subió 50.00 %" in d.message
    assert "las ventas cambiaron 0.00 %" in d.message
    # Si las ventas crecen igual, no hay alerta.
    mas_ventas = indicators([BIZ, BIZ], variable=D("3000"))
    assert variable_costs_growing(ctx(month=mas_ventas, previous_same_days=antes)) == []
    # Sin datos del mes anterior, no se compara.
    assert variable_costs_growing(ctx(month=ahora)) == []


def test_riesgo_de_caja_en_fechas():
    pagos = [CashItem(datetime.date(2026, 10, 20), D("15000"), "Alquiler", "gasto")]
    proj = cash_projection(D("10000"), HOY, pagos, [])
    d = cash_risk_dates(ctx(projection=proj))[0]
    assert d.severity == "alta" and d.is_projection and d.title == "Riesgo de caja el 20 de octubre"
    assert "faltarían RD$5,000.00" in d.message
    assert d.dedupe_key == "riesgo_caja_fechas:2026-10-20"
    reserva = cash_projection(D("20000"), HOY, pagos, [], reserve=D("6000"))
    bajo = cash_risk_dates(
        ctx(projection=reserva, reserve=operating_reserve(D("20000"), HOY, pagos, D("6000")))
    )
    assert bajo[0].severity == "media" and "por debajo de la reserva" in bajo[0].message
    assert "(RD$6,000.00)" in bajo[0].message


def test_retiro_sin_cobertura():
    pagos = [CashItem(datetime.date(2026, 10, 20), D("15000"), "Alquiler", "gasto")]
    reserva = operating_reserve(D("10000"), HOY, pagos)
    retiros = [
        Withdrawal(datetime.date(2026, 10, 5), D("5000")),
        Withdrawal(datetime.date(2026, 10, 10), D("3000")),
    ]
    d = withdrawal_without_coverage(ctx(reserve=reserva, withdrawals=retiros))[0]
    assert d.severity == "alta"
    assert "retiraste RD$8,000.00 del negocio (el último, el 10 de octubre)" in d.message
    assert "faltan RD$5,000.00" in d.message and "más la reserva" not in d.message
    con_reserva = operating_reserve(D("10000"), HOY, [], reserve=D("12000"))
    assert (
        "más la reserva"
        in withdrawal_without_coverage(ctx(reserve=con_reserva, withdrawals=retiros))[0].message
    )
    # Sin retiros, o con efectivo suficiente, no hay alerta.
    assert withdrawal_without_coverage(ctx(reserve=reserva)) == []
    assert withdrawal_without_coverage(ctx(withdrawals=retiros)) == []


def test_reglas_desactivadas():
    contexto = ctx(month=indicators([CUP]), enabled=frozenset())
    assert evaluate_business(contexto) == []


def test_alertas_de_inventario():
    from apps.alerts.services.rules_business import (
        StockInfo,
        idle_inventory,
        low_stock,
        negative_stock,
    )

    stocks = [
        StockInfo("a", "Refresco 2L", D("4"), D("6"), D("240"), HOY),
        StockInfo("b", "Galletas", D("-2"), D("0"), D("0"), HOY),
        StockInfo("c", "Vino", D("10"), D("2"), D("5000"), datetime.date(2026, 7, 1)),
        StockInfo("d", "Velas", D("3"), D("0"), D("1500"), None),
        StockInfo("e", "Agua", D("50"), D("10"), D("500"), HOY),
    ]
    contexto = ctx(stocks=stocks)
    baja = low_stock(contexto)
    assert [d.title for d in baja] == ["Quedan pocas unidades de Refresco 2L"]
    assert "Tienes 4 y tu mínimo es 6" in baja[0].message
    negativa = negative_stock(contexto)
    assert negativa[0].title == "Vendiste más Galletas de lo registrado"
    quieto = idle_inventory(contexto)
    assert [d.title for d in quieto] == [
        "Tienes RD$5,000.00 parados en Vino",
        "Tienes RD$1,500.00 parados en Velas",
    ]
    assert "no se vende desde el 1 de julio" in quieto[0].message
    assert "no se ha vendido" in quieto[1].message
    assert {d.code for d in evaluate_business(contexto)} >= {
        "existencia_baja", "existencia_negativa", "inventario_quieto",
    }  # fmt: skip
