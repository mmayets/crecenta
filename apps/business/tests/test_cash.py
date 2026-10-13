import datetime
from decimal import Decimal

from apps.business.services.cash import (
    CashItem,
    OpenDebt,
    cash_projection,
    commitments,
    expected_inflows,
    expense_dates,
    operating_reserve,
)
from apps.business.services.indicators import ExpensePlan

D = Decimal
HOY = datetime.date(2026, 10, 13)
FIN = HOY + datetime.timedelta(days=30)


def test_fechas_de_gastos():
    mensual = ExpensePlan("a", "Alquiler", D("1"), "mensual", 31)
    assert expense_dates(mensual, HOY, FIN) == [datetime.date(2026, 10, 31)]
    quincenal = ExpensePlan("b", "Ayudante", D("1"), "quincenal", 30)
    assert expense_dates(quincenal, HOY, FIN) == [
        datetime.date(2026, 10, 15),
        datetime.date(2026, 10, 30),
    ]
    q2 = ExpensePlan("b", "Ayudante", D("1"), "quincenal", 5)
    assert expense_dates(q2, HOY, FIN) == [datetime.date(2026, 10, 20), datetime.date(2026, 11, 5)]
    semanal = ExpensePlan("c", "Gas", D("1"), "semanal", 5)  # viernes
    assert expense_dates(semanal, HOY, FIN)[0] == datetime.date(2026, 10, 16)
    assert len(expense_dates(ExpensePlan("d", "Sin día", D("1"), "semanal"), HOY, FIN)) == 5
    assert expense_dates(ExpensePlan("e", "Sin día", D("1"), "mensual"), HOY, FIN) == [HOY]


def test_compromisos_cxp_y_gastos():
    payables = [
        OpenDebt("Harina (vencida)", D("4000"), datetime.date(2026, 10, 1)),
        OpenDebt("Empaques", D("3000"), None),
        OpenDebt("Horno", D("20000"), datetime.date(2027, 1, 10)),  # fuera del horizonte
        OpenDebt("Pagada", D("0"), HOY),
    ]
    expenses = [
        ExpensePlan("alq", "Alquiler", D("15000"), "mensual", 20),
        ExpensePlan("luz", "Luz", D("2000"), "mensual", 15),
    ]
    items = commitments(HOY, FIN, payables, expenses, paid_this_month=frozenset({"luz"}))
    labels = [(i.date, i.label) for i in items]
    assert labels == [
        (HOY, "Empaques"),
        (HOY, "Harina (vencida)"),
        (datetime.date(2026, 10, 20), "Alquiler"),  # la luz de octubre ya se pagó
    ]


def test_cobros_esperados_solo_con_fecha_futura():
    receivables = [
        OpenDebt("Pedro", D("857.14"), datetime.date(2026, 10, 20)),
        OpenDebt("Vencida", D("500"), datetime.date(2026, 10, 1)),
        OpenDebt("Sin fecha", D("500"), None),
        OpenDebt("Lejana", D("500"), datetime.date(2027, 1, 1)),
    ]
    assert [i.label for i in expected_inflows(HOY, FIN, receivables)] == ["Pedro"]


def test_proyeccion_detecta_el_dia_sin_dinero():
    outflows = [
        CashItem(datetime.date(2026, 10, 15), D("8000"), "Nómina", "gasto"),
        CashItem(datetime.date(2026, 10, 20), D("15000"), "Alquiler", "gasto"),
    ]
    inflows = [CashItem(datetime.date(2026, 10, 20), D("5000"), "Cobro Pedro", "cxc")]
    p = cash_projection(D("20000"), HOY, outflows, inflows)
    assert p.days == [
        (datetime.date(2026, 10, 15), D("12000")),
        (datetime.date(2026, 10, 20), D("2000")),
    ]
    assert p.gaps == [] and p.lowest_balance == D("2000")
    con_reserva = cash_projection(D("20000"), HOY, outflows, inflows, reserve=D("5000"))
    gap = con_reserva.gaps[0]
    assert gap.date == datetime.date(2026, 10, 20) and gap.shortfall == D("3000")
    assert gap.causes == ["Alquiler"]
    sin_cobro = cash_projection(D("20000"), HOY, outflows, [])
    assert sin_cobro.gaps[0].balance == D("-3000") and sin_cobro.lowest_date == datetime.date(
        2026, 10, 20
    )
    vacia = cash_projection(D("100"), HOY, [], [])
    assert vacia.days == [] and vacia.lowest_date == HOY


def test_reserva_operativa_caso_del_encargo():
    outflows = [
        CashItem(datetime.date(2026, 10, 20), D("15000"), "Alquiler", "gasto"),
        CashItem(datetime.date(2026, 10, 30), D("12000"), "Nómina", "gasto"),
        CashItem(HOY, D("5000"), "Harina", "cxp"),
    ]
    r = operating_reserve(D("40000"), HOY, outflows)
    assert r.committed == D("32000") and r.max_safe_withdrawal == D("8000")
    assert r.message("DOP") == (
        "El negocio tiene RD$40,000.00 en efectivo, pero necesita RD$32,000.00 para los "
        "compromisos registrados. Puedes retirar hasta RD$8,000.00 sin dejar pagos sin cubrir."
    )
    con_reserva = operating_reserve(D("40000"), HOY, outflows, reserve=D("10000"))
    assert con_reserva.available == D("-2000") and con_reserva.max_safe_withdrawal == 0
    assert "y la reserva" in con_reserva.message("DOP")
    assert con_reserva.message("DOP").endswith("Ahora mismo no conviene retirar dinero.")
    libre = operating_reserve(D("500"), HOY, [])
    assert "no hay pagos registrados" in libre.message("USD") and "US$500.00" in libre.message(
        "USD"
    )


def test_aviso_antes_de_retirar():
    from apps.business.services.cash import check_withdrawal

    r = operating_reserve(D("40000"), HOY, [CashItem(HOY, D("32000"), "Compromisos", "gasto")])
    ok = check_withdrawal(r, D("8000"), "DOP")
    assert ok.covered and ok.shortfall == 0 and "hasta RD$8,000.00" in ok.message
    no = check_withdrawal(r, D("10000"), "DOP")
    assert not no.covered and no.shortfall == D("2000")
    assert no.message.endswith(
        "Si retiras RD$10,000.00, quedarían RD$2,000.00 de pagos sin cubrir."
    )


def test_aviso_de_retiro_mayor_que_el_efectivo():
    from apps.business.services.cash import check_withdrawal

    r = operating_reserve(D("3000"), HOY, [CashItem(HOY, D("3500"), "Harina", "cxp")])
    check = check_withdrawal(r, D("999999"), "DOP")
    assert check.shortfall == D("3500") and "solo tiene RD$3,000.00" in check.message
    assert check.message.endswith("quedarían RD$3,500.00 de pagos sin cubrir.")
    parcial = check_withdrawal(r, D("100"), "DOP")
    assert parcial.shortfall == D("600")
