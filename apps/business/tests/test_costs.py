from decimal import Decimal

from apps.business.services.costs import ComponentInput, unit_cost

D = Decimal


def test_costo_unitario_suma_montos_y_comision_sobre_precio():
    result = unit_cost(
        D("857.14"),
        [
            ComponentInput("materia", D("450")),
            ComponentInput("empaque", D("50")),
            ComponentInput("entrega", D("14.29")),
            ComponentInput("comision_pct", D("0.10")),
        ],
    )
    assert result.fixed_part == D("514.29")
    assert result.commission_pct == D("0.10")
    assert result.commission_amount == D("85.71")
    assert result.unit_cost == D("600.00")


def test_sin_componentes_es_cero():
    assert unit_cost(D("100"), []).unit_cost == D("0.00")
