from decimal import Decimal

import pytest

from apps.business.services.sale_math import LineInput, line_amount, sale_totals

D = Decimal


def test_precios_sin_itbis_se_suma_el_impuesto():
    t = sale_totals(
        [LineInput(D("2"), D("857.14")), LineInput(D("3"), D("100"), D("0.10"))],
        D("0.18"),
        prices_include_tax=False,
    )
    assert t.line_nets == [D("1714.28"), D("270.00")]
    assert t.subtotal == D("1984.28") and t.tax == D("357.17") and t.total == D("2341.45")


def test_precios_con_itbis_incluido_se_separa_y_las_lineas_cuadran():
    t = sale_totals(
        [LineInput(D("1"), D("1000")), LineInput(D("1"), D("180")), LineInput(D("1"), D("0.01"))],
        D("0.18"),
        prices_include_tax=True,
    )
    assert t.total == D("1180.01") and t.subtotal == D("1000.01") and t.tax == D("180.00")
    assert sum(t.line_nets) == t.subtotal


def test_sin_impuesto():
    t = sale_totals([LineInput(D("1.5"), D("10"))], D("0"), prices_include_tax=True)
    assert (t.subtotal, t.tax, t.total) == (D("15.00"), D("0.00"), D("15.00"))


@pytest.mark.parametrize(
    "line",
    [
        LineInput(D("0"), D("1")),
        LineInput(D("1"), D("-1")),
        LineInput(D("1"), D("1"), D("1.5")),
    ],
)
def test_lineas_invalidas(line):
    with pytest.raises(ValueError):
        line_amount(line)


def test_venta_vacia_o_impuesto_negativo():
    with pytest.raises(ValueError):
        sale_totals([], D("0"), prices_include_tax=False)
    with pytest.raises(ValueError):
        sale_totals([LineInput(D("1"), D("1"))], D("-0.1"), prices_include_tax=False)
