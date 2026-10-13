import datetime
from decimal import Decimal

from apps.business.services.indicators import (
    BusinessPeriodInputs,
    ExpensePlan,
    GoalInputs,
    SoldLine,
    compute_indicators,
    product_margins,
)

D = Decimal
INI, FIN = datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)


def lines():
    return [
        SoldLine("p1", "Bizcocho", D("20"), D("17142.80"), D("600")),
        SoldLine("p1", "Bizcocho", D("10"), D("8571.40"), D("600")),
        SoldLine("p2", "Cupcake", D("50"), D("5000"), D("85")),
        SoldLine("", "Arreglo especial", D("1"), D("1500"), D("0")),
    ]


def test_ventas_costo_ganancia_y_flujo_separados():
    ind = compute_indicators(
        BusinessPeriodInputs(
            start=INI,
            end=FIN,
            currency="DOP",
            lines=lines(),
            tax_collected=D("5000"),
            operating_expenses=D("15000"),
            variable_costs_paid=D("9000"),
            cash_in=D("20000"),
            cash_out=D("26000"),
            receivables_open=D("12214.20"),
            receivables_overdue=D("2000"),
            payables_open=D("4000"),
            expense_plan=[
                ExpensePlan("e1", "Alquiler", D("12000"), "mensual", 5),
                ExpensePlan("e2", "Ayudante", D("1500"), "quincenal", 15),
            ],
            goal=GoalInputs(
                target_sales=D("40000"), target_margin=D("0.30"), target_profit=D("10000")
            ),
        )
    )
    assert ind.sales == D("32214.20")
    assert ind.cogs == D("22250.00")  # 30 × 600 + 50 × 85
    assert ind.gross_profit == D("9964.20") and ind.gross_margin_pct == D("30.93")
    assert ind.operating_result == D("-5035.80")
    # El efectivo va por su lado: salieron más de lo que entró aunque hubo ventas.
    assert ind.net_cash_flow == D("-6000") and ind.receivables == D("12214.20")
    assert ind.tax_collected == D("5000")
    assert ind.fixed_costs_month == D("15000.00")
    assert ind.break_even_sales == D("48494.91")  # 15000 / 0.3093…
    assert ind.goal.sales_pct == D("80.54") and ind.goal.margin_gap_pct == D("0.93")
    assert ind.goal.profit_pct == D("-50.36")
    assert [m.name for m in ind.by_product] == ["Bizcocho", "Arreglo especial", "Cupcake"]
    biz = ind.by_product[0]
    assert biz.units == 30 and biz.gross_profit == D("7714.20") and biz.margin_pct == D("30.00")
    assert biz.as_stats().ref == "p1"
    assert any("sin costo registrado" in n for n in ind.notes)


def test_sin_datos_no_inventa_cifras():
    ind = compute_indicators(BusinessPeriodInputs(start=INI, end=FIN, currency="DOP", lines=[]))
    assert ind.sales == 0 and ind.gross_margin_pct == 0 and ind.break_even_sales is None
    assert ind.goal.sales_pct is None and ind.goal.margin_gap_pct is None
    assert ind.goal.profit_pct is None
    assert any("punto de equilibrio" in n for n in ind.notes)


def test_ventas_sin_detalle_y_gastos_sin_categoria_se_avisan():
    ind = compute_indicators(
        BusinessPeriodInputs(
            start=INI,
            end=FIN,
            currency="USD",
            lines=[],
            untracked_sales=D("300"),
            operating_expenses=D("50"),
            uncategorized_expenses=D("50"),
            expense_plan=[ExpensePlan("e", "Local", D("100"), "semanal")],
        )
    )
    assert ind.sales == D("300") and ind.gross_margin_pct == D("100.00")
    assert ind.fixed_costs_month == D("433.33")
    assert ind.break_even_sales == D("433.33")
    assert "US$300.00 en ventas registradas sin detalle" in ind.notes[0]
    assert "US$50.00 en gastos sin categoría" in ind.notes[1]


def test_equilibrio_sin_ganancia_bruta_no_existe():
    ind = compute_indicators(
        BusinessPeriodInputs(
            start=INI,
            end=FIN,
            currency="DOP",
            lines=[SoldLine("p", "X", D("1"), D("100"), D("150"))],
            expense_plan=[ExpensePlan("e", "Local", D("100"), "mensual")],
        )
    )
    assert ind.gross_profit == D("-50") and ind.break_even_sales is None


def test_margenes_por_producto_vacio():
    assert product_margins([]) == []
