from datetime import date

from apps.core.periods import PayEvent, Period
from apps.personal.services.cash_timeline import (
    ScheduledOutflow,
    build_timeline,
    find_shortfalls,
    lowest_point,
)

from .builders import D

PERIODO = Period(date(2026, 10, 1), date(2026, 10, 10))


def test_cobro_se_acredita_antes_del_pago_del_mismo_dia():
    pays = [PayEvent(date(2026, 10, 1), D("1000"), "s")]
    outs = [ScheduledOutflow(date(2026, 10, 1), D("1000"), "renta", "Renta")]
    points = build_timeline(PERIODO, D("0"), pays, outs, D("0"))
    assert points[0].balance == 0
    assert find_shortfalls(points, outs) == []


def test_faltante_en_vencimiento_y_tramos():
    pays = [PayEvent(date(2026, 10, 5), D("1000"), "s")]
    outs = [
        ScheduledOutflow(date(2026, 10, 3), D("300"), "luz", "Luz"),
        ScheduledOutflow(date(2026, 10, 4), D("100"), "agua", "Agua"),
        ScheduledOutflow(date(2026, 10, 8), D("2000"), "renta", "Renta"),
    ]
    points = build_timeline(PERIODO, D("0"), pays, outs, D("0"))
    shortfalls = find_shortfalls(points, outs)
    assert [(s.date.day, s.amount, s.refs) for s in shortfalls] == [
        (3, D("300"), ("luz",)),
        (4, D("400"), ("agua",)),
        (8, D("1400"), ("renta",)),
    ]


def test_gasto_variable_lineal_cuadra_exacto():
    points = build_timeline(PERIODO, D("100"), [], [], D("100"))
    assert sum(p.variable_spend for p in points) == D("100")
    assert points[-1].balance == 0
    shortfalls = find_shortfalls(build_timeline(PERIODO, D("50"), [], [], D("100")), [])
    assert len(shortfalls) == 1  # un solo tramo negativo
    assert shortfalls[0].date == date(2026, 10, 6)
    assert shortfalls[0].labels == ("Gastos del día a día",)


def test_punto_mas_bajo():
    assert lowest_point([]) is None
    points = build_timeline(PERIODO, D("10"), [], [], D("10"))
    assert lowest_point(points).date == date(2026, 10, 10)
