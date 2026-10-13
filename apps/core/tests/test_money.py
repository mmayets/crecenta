from decimal import Decimal

import pytest

from apps.core.money import (
    MoneyError,
    fmt,
    pct,
    q,
    split_evenly,
    split_proportionally,
    to_money,
)


class TestToMoney:
    def test_rechaza_float(self):
        with pytest.raises(MoneyError):
            to_money(0.1)

    def test_rechaza_bool(self):
        with pytest.raises(MoneyError):
            to_money(True)

    def test_rechaza_tipo_desconocido(self):
        with pytest.raises(MoneyError):
            to_money([1])  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("50,000", Decimal("50000")),
            ("RD$ 1,250.50", Decimal("1250.50")),
            ("US$12", Decimal("12")),
            (7, Decimal("7")),
            (Decimal("3.333"), Decimal("3.333")),
        ],
    )
    def test_convierte(self, value, expected):
        assert to_money(value) == expected

    @pytest.mark.parametrize("value", ["abc", "", "NaN", "Infinity"])
    def test_texto_invalido(self, value):
        with pytest.raises(MoneyError):
            to_money(value)


class TestRedondeo:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2.345", "2.35"),
            ("2.344", "2.34"),
            ("-2.345", "-2.35"),
            ("857.142857", "857.14"),
            ("0.005", "0.01"),
        ],
    )
    def test_half_up(self, value, expected):
        assert q(Decimal(value)) == Decimal(expected)


class TestReparto:
    def test_partes_iguales_suman_total(self):
        parts = split_evenly(Decimal("100"), 3)
        assert parts == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
        assert sum(parts) == Decimal("100.00")

    def test_quincena_ahorro(self):
        assert split_evenly(Decimal("7000"), 2) == [Decimal("3500.00"), Decimal("3500.00")]

    def test_partes_invalidas(self):
        with pytest.raises(ValueError):
            split_evenly(Decimal("10"), 0)

    def test_proporcional(self):
        parts = split_proportionally(Decimal("7000"), [Decimal("25000"), Decimal("25000")])
        assert parts == [Decimal("3500.00"), Decimal("3500.00")]

    def test_proporcional_mayor_residuo(self):
        parts = split_proportionally(Decimal("100"), [Decimal("1"), Decimal("1"), Decimal("1")])
        assert sum(parts) == Decimal("100.00")
        assert sorted(parts) == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]

    def test_proporcional_desigual(self):
        parts = split_proportionally(Decimal("1000"), [Decimal("30000"), Decimal("20000")])
        assert parts == [Decimal("600.00"), Decimal("400.00")]

    def test_proporcional_pesos_cero(self):
        assert split_proportionally(Decimal("10"), [Decimal("0"), Decimal("0")]) == [
            Decimal("5.00"),
            Decimal("5.00"),
        ]

    def test_proporcional_vacio_o_negativo(self):
        with pytest.raises(ValueError):
            split_proportionally(Decimal("10"), [])
        with pytest.raises(ValueError):
            split_proportionally(Decimal("10"), [Decimal("-1"), Decimal("2")])


class TestFormato:
    def test_dop(self):
        assert fmt(Decimal("50000")) == "RD$50,000.00"

    def test_usd(self):
        assert fmt(Decimal("12.5"), "USD") == "US$12.50"

    def test_negativo(self):
        assert fmt(Decimal("-1250.505")) == "-RD$1,250.51"

    def test_moneda_desconocida(self):
        assert fmt(Decimal("1"), "EUR") == "EUR 1.00"

    def test_porcentaje(self):
        assert pct(Decimal("257.14"), Decimal("857.14")) == Decimal("30.00")
        assert pct(Decimal("1"), Decimal("0")) == Decimal("0.00")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("150.50", "150.50"), ("1,000", "1000"), (None, "0"), ("", "0"), ("abc", "0"),
     ("1e999999", "0"), ("NaN", "0"), ("Infinity", "0"), ("-5", "0"),
     ("1000000000000", "0")],
)  # fmt: skip
def test_monto_de_parametro_libre(raw, expected):
    from apps.core.money import amount_or_zero

    assert amount_or_zero(raw) == Decimal(expected)
