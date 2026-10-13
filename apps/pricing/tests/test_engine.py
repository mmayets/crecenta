from decimal import Decimal

import pytest

from apps.pricing.services.engine import (
    PricingInputs,
    ProductStats,
    break_even_units,
    compute_price,
    margin_after_discount,
    minimum_price,
    service_capacity,
    supplier_increase,
    unit_economics,
    volume_margin_matrix,
)

D = Decimal


def test_caso_del_encargo_600_al_30_es_857_14():
    result = compute_price(PricingInputs(unit_cost=D("600"), target_margin=D("0.30")))
    assert result.net_price == D("857.14")
    assert result.published_price == D("857.14") and result.tax == 0
    assert result.economics.profit == D("257.14")
    assert result.economics.margin_pct == D("30.00")
    assert result.minimum_price == D("600.00")
    assert result.assumptions[0] == "Costo por unidad: RD$600.00."


def test_precio_con_comision_descuento_entrega_e_itbis():
    inputs = PricingInputs(
        unit_cost=D("500"),
        delivery_cost=D("100"),
        target_margin=D("0.30"),
        commission_pct=D("0.10"),
        discount_pct=D("0.05"),
        tax_rate=D("0.18"),
    )
    result = compute_price(inputs)
    # 600 / (0.95 × 0.60) = 1052.63
    assert result.net_price == D("1052.63")
    assert result.tax == D("189.47") and result.gross_price == D("1242.10")
    assert result.published_price == result.net_price
    eco = result.economics
    assert eco.effective_price == D("1000.00") and eco.commission == D("100.00")
    assert eco.profit == D("300.00") and eco.margin_pct == D("30.00")
    # Mínimo: 600 / (0.95 × 0.90)
    assert result.minimum_price == minimum_price(inputs) == D("701.75")
    texto = " ".join(result.assumptions)
    assert "más entrega RD$100.00" in texto and "Comisión de 10 %" in texto
    assert "Descuento habitual de 5 %" in texto and "se suma al precio" in texto


def test_precio_publicado_con_itbis_incluido_y_usd():
    result = compute_price(
        PricingInputs(
            unit_cost=D("10"),
            target_margin=D("0.5"),
            tax_rate=D("0.18"),
            prices_include_tax=True,
            currency="USD",
        )
    )
    assert result.net_price == D("20.00") and result.published_price == D("23.60")
    assert "ya lo incluye" in result.assumptions[-1]
    assert result.assumptions[0] == "Costo por unidad: US$10.00."


@pytest.mark.parametrize(
    "kwargs",
    [
        {"unit_cost": D("-1"), "target_margin": D("0.3")},
        {"unit_cost": D("1"), "target_margin": D("1")},
        {"unit_cost": D("1"), "target_margin": D("0.6"), "commission_pct": D("0.4")},
        {"unit_cost": D("1"), "target_margin": D("0.3"), "discount_pct": D("1")},
        {"unit_cost": D("1"), "target_margin": D("0.3"), "tax_rate": D("-0.1")},
    ],
)
def test_entradas_invalidas(kwargs):
    with pytest.raises(ValueError):
        compute_price(PricingInputs(**kwargs))


def test_economia_unitaria_y_validaciones():
    eco = unit_economics(D("857.14"), D("600"))
    assert eco.margin_pct == D("30.00") and eco.markup_pct == D("42.86")
    gratis = unit_economics(D("100"), D("50"), discount_pct=D("1"))
    assert gratis.effective_price == 0 and gratis.margin_pct == 0 and gratis.profit == D("-50.00")
    with pytest.raises(ValueError):
        unit_economics(D("-1"), D("1"))
    with pytest.raises(ValueError):
        unit_economics(D("1"), D("1"), commission_pct=D("1"))


def test_margen_tras_descuento():
    r = margin_after_discount(D("857.14"), D("600"), D("0.10"))
    assert r.economics.effective_price == D("771.43")
    assert r.economics.profit == D("171.43") and r.economics.margin_pct == D("22.22")
    assert r.max_discount_pct == D("30.00")  # con 30 % de descuento se vende al costo
    con_comision = margin_after_discount(D("1000"), D("600"), D("0"), D("0.10"))
    assert con_comision.max_discount_pct == D("33.33")
    assert margin_after_discount(D("500"), D("600"), D("0")).max_discount_pct == 0
    assert margin_after_discount(D("0"), D("0"), D("0")).max_discount_pct == 0


def test_punto_de_equilibrio():
    r = break_even_units(D("15000"), D("857.14"), D("600"))
    assert r is not None
    assert r.units == 59  # 15000 / 257.14 = 58.33 → 59
    assert r.sales == D("50571.26") and r.contribution_per_unit == D("257.14")
    assert r.contribution_margin_pct == D("30.00")
    con_ganancia = break_even_units(D("15000"), D("857.14"), D("600"), target_profit=D("10000"))
    assert con_ganancia is not None and con_ganancia.units == 98
    assert break_even_units(D("0"), D("10"), D("5")).units == 0
    assert break_even_units(D("1000"), D("600"), D("600")) is None
    with pytest.raises(ValueError):
        break_even_units(D("-1"), D("10"), D("5"))


def test_aumento_del_proveedor():
    inputs = PricingInputs(unit_cost=D("600"), target_margin=D("0.30"))
    r = supplier_increase(inputs, D("857.14"), D("0.10"))
    assert r.increase_pct == D("10.00") and r.old_cost == D("600.00") and r.new_cost == D("660.00")
    assert r.before.margin_pct == D("30.00")
    assert r.after.profit == D("197.14") and r.after.margin_pct == D("23.00")
    assert r.price_to_keep_margin == D("942.86")  # 660 / 0.70 (margen actual 30.00 %)
    assert r.price_change_pct == D("10.00")
    with pytest.raises(ValueError):
        supplier_increase(inputs, D("857.14"), D("-1"))


def test_aumento_cuando_ya_se_pierde_dinero_busca_margen_cero():
    inputs = PricingInputs(unit_cost=D("600"), delivery_cost=D("50"), target_margin=D("0.3"))
    r = supplier_increase(inputs, D("600"), D("0.20"))
    assert r.new_cost == D("770.00")  # la entrega no sube
    assert r.price_to_keep_margin == D("770.00")


def test_matriz_volumen_margen():
    productos = [
        ProductStats("Bizcocho", D("40"), D("34285.60"), D("10285.60")),  # 30 %, mucho volumen
        ProductStats("Cupcake", D("120"), D("12000"), D("1800")),  # 15 %, mucho volumen
        ProductStats("Torta boda", D("2"), D("10000"), D("5000")),  # 50 %, poco volumen
        ProductStats("Galletas", D("10"), D("500"), D("50")),  # 10 %, poco volumen
        ProductStats("Nuevo", D("0"), D("0"), D("0")),
    ]
    cells = volume_margin_matrix(productos, target_margin=D("0.25"))
    by_name = {c.stats.name: c for c in cells}
    assert [c.stats.name for c in cells][:2] == ["Bizcocho", "Torta boda"]
    assert by_name["Bizcocho"].quadrant == "estrella"
    assert by_name["Cupcake"].quadrant == "vende_mucho_deja_poco"
    assert "revisa su precio" in by_name["Cupcake"].advice
    assert by_name["Torta boda"].quadrant == "deja_mucho_vende_poco"
    assert by_name["Galletas"].quadrant == "revisar"
    assert by_name["Nuevo"].quadrant == "revisar" and by_name["Nuevo"].margin_pct == 0
    assert by_name["Bizcocho"].profit_share_pct == D("60.02")
    # Sin objetivo, el umbral es el margen global (30.31 %).
    sin_objetivo = {c.stats.name: c for c in volume_margin_matrix(productos)}
    assert sin_objetivo["Bizcocho"].quadrant == "vende_mucho_deja_poco"
    assert volume_margin_matrix([]) == []
    perdida = volume_margin_matrix([ProductStats("A", D("1"), D("10"), D("-5"))])
    assert perdida[0].profit_share_pct == 0


def test_capacidad_de_servicios():
    r = service_capacity(labor_minutes=45, hours_available=120, price=D("1500"), unit_cost=D("300"))
    assert r.max_units == 160
    assert r.max_sales == D("240000.00") and r.max_gross_profit == D("192000.00")
    assert r.price_per_hour == D("2000.00") and r.profit_per_hour == D("1600.00")
    assert service_capacity(50, 1, D("100")).max_units == 1
    with pytest.raises(ValueError):
        service_capacity(0, 10, D("1"))
    with pytest.raises(ValueError):
        service_capacity(10, -1, D("1"))
