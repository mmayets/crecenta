from decimal import Decimal

import pytest

from apps.pricing.services.margins import (
    margin_vs_markup,
    price_from_margin,
    price_from_markup,
    with_tax,
)

D = Decimal


def test_precio_por_margen_caso_del_encargo():
    r = price_from_margin(D("600"), D("0.30"))
    assert r.price == D("857.14")
    assert r.gross_profit == D("257.14")
    assert r.margin_pct == D("30.00")
    assert r.markup_pct == D("42.86")
    assert r.method == "margen"


def test_precio_por_recargo_y_diferencia_con_margen():
    r = price_from_markup(D("600"), D("0.30"))
    assert (r.price, r.gross_profit) == (D("780.00"), D("180.00"))
    assert r.margin_pct == D("23.08")  # un recargo del 30 % NO es un margen del 30 %
    assert margin_vs_markup(D("600"), D("857.14")) == (D("30.00"), D("42.86"))


def test_casos_limite():
    assert price_from_margin(D("0"), D("0.5")).price == D("0.00")
    assert price_from_margin(D("100"), D("0")).price == D("100.00")
    for bad in (D("1"), D("-0.1")):
        with pytest.raises(ValueError):
            price_from_margin(D("100"), bad)
    with pytest.raises(ValueError):
        price_from_margin(D("-1"), D("0.3"))
    with pytest.raises(ValueError):
        price_from_markup(D("-1"), D("0.3"))
    with pytest.raises(ValueError):
        price_from_markup(D("1"), D("-0.3"))


def test_itbis():
    sin = with_tax(D("857.14"), D("0.18"), included=False)
    assert (sin.net, sin.tax, sin.gross) == (D("857.14"), D("154.29"), D("1011.43"))
    con = with_tax(D("1180"), D("0.18"), included=True)
    assert (con.net, con.tax, con.gross) == (D("1000.00"), D("180.00"), D("1180.00"))
