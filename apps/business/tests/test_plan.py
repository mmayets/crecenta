import datetime
from dataclasses import replace
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.business.services.cash import OpenDebt
from apps.business.services.indicators import ExpensePlan
from apps.business.services.plan import (
    BusinessPlanInputs,
    PlanProduct,
    PlanStatus,
    alternative_inputs,
    build_business_plan,
)
from apps.business.services.plan_edits import apply_business_edits, business_missing_data
from apps.business.services.plan_serialize import (
    business_inputs_from_dict,
    business_inputs_to_dict,
    serialize_business_plan,
)

D = Decimal
INI, FIN = datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)


def dulces_ana(**kw):
    """Repostería: bizcocho (costo 600, a 857.14 = 30 %) y cupcakes de poco margen."""
    base = BusinessPlanInputs(
        start=INI,
        end=FIN,
        today=INI,
        currency="DOP",
        products=(
            PlanProduct("biz", "Bizcocho", D("857.14"), D("600"), expected_units=D("40")),
            PlanProduct("cup", "Cupcake", D("100"), D("75"), expected_units=D("150")),
        ),
        expenses=(
            ExpensePlan("alq", "Alquiler", D("8000"), "mensual", 5),
            ExpensePlan("pub", "Publicidad", D("2500"), "mensual", 20, is_reducible=True),
        ),
        cash_now=D("15000"),
        target_margin=D("0.30"),
        target_profit=D("5000"),
    )
    return replace(base, **kw)


def test_plan_viable_separa_ventas_ganancia_y_caja():
    r = build_business_plan(dulces_ana(products=dulces_ana().products[:1]))
    assert r.sales == D("34285.60") and r.cogs == D("24000.00")
    assert r.gross_profit == D("10285.60") and r.gross_margin_pct == D("30.00")
    assert r.operating_expenses == D("10500.00") and r.operating_result == D("-214.40")
    assert r.status == PlanStatus.NO_VIABLE
    assert "pierde RD$214.40" in r.reasons[0]
    assert r.break_even_sales == D("35000.27")
    assert r.sales_for_target_profit == D("51667.07")


def test_plan_con_dos_productos_ajustado_por_margen_y_meta():
    r = build_business_plan(dulces_ana())
    # 150 cupcakes: 15000 en ventas, 11250 de costo.
    assert r.sales == D("49285.60") and r.gross_profit == D("14035.60")
    assert r.operating_result == D("3535.60")
    assert r.status == PlanStatus.AJUSTADO
    assert "no llega a la meta" in r.reasons[0] and "bajo el objetivo" in r.reasons[1]
    assert [p.name for p in r.products] == ["Bizcocho", "Cupcake"]
    assert r.products[1].margin_pct == D("25.00")
    # Caja: 15000 + ganancia pareja del mes − alquiler (5) − publicidad (20). Nunca baja de cero.
    assert r.projection.gaps == [] and r.max_withdrawal == r.projection.lowest_balance
    codes = [a.code for a in r.alternatives]
    assert set(codes) == {"subir_precio", "bajar_costo", "vender_mas", "reducir_gastos"}
    subir = next(a for a in r.alternatives if a.code == "subir_precio")
    assert subir.changes[0].concept == "Precio de Cupcake" and subir.changes[0].after == D("107.14")
    assert subir.result_gain == D("1071.00")  # 150 × 7.14
    reducir = next(a for a in r.alternatives if a.code == "reducir_gastos")
    assert reducir.changes[0].after == D("2000.00") and reducir.result_gain == D("500.00")
    # Ordenadas de mayor a menor mejora.
    gains = [a.improvement for a in r.alternatives]
    assert gains == sorted(gains, reverse=True)


def test_viable_no_trae_alternativas():
    r = build_business_plan(dulces_ana(target_profit=None, target_margin=None))
    assert r.status == PlanStatus.VIABLE and r.reasons == [] and r.alternatives == []


def test_retiro_planeado_que_deja_sin_efectivo():
    r = build_business_plan(
        dulces_ana(planned_withdrawal=D("20000"), today=datetime.date(2026, 10, 3))
    )
    assert r.status == PlanStatus.NO_VIABLE
    assert any("faltarían" in reason for reason in r.reasons)
    gap = r.projection.gaps[0]
    assert gap.date == datetime.date(2026, 10, 3) and gap.causes == ["Retiro del propietario"]
    assert r.max_withdrawal < D("20000")
    posponer = next(a for a in r.alternatives if a.code == "posponer_retiro")
    assert posponer.cash_gain == D("20000.00") and posponer.result_gain == 0
    assert "Retiro del propietario de RD$20,000.00 hecho hoy." in r.assumptions


def test_cobros_pagos_y_reserva_en_la_caja():
    r = build_business_plan(
        dulces_ana(
            target_profit=None,
            target_margin=None,
            cash_now=D("1000"),
            payables=(OpenDebt("Harina", D("3000"), None),),
            receivables=(OpenDebt("Pedro", D("5000"), datetime.date(2026, 10, 2)),),
            cash_reserve=D("500"),
        )
    )
    # El día 1 se paga la harina (3000) y solo entra la ganancia del día: faltan.
    assert r.status == PlanStatus.NO_VIABLE and r.projection.gaps[0].causes == ["Harina"]
    assert r.max_withdrawal == 0


def test_sin_ventas_ni_gastos():
    r = build_business_plan(
        dulces_ana(products=(), expenses=(), target_profit=None, target_margin=None)
    )
    assert r.sales == 0 and r.break_even_sales is None and r.sales_for_target_profit is None
    assert r.status == PlanStatus.VIABLE and r.projection.days == []


def test_perdida_en_ventas_sale_de_la_caja():
    r = build_business_plan(
        dulces_ana(
            products=(PlanProduct("x", "Mal precio", D("50"), D("60"), expected_units=D("31")),),
            expenses=(),
            target_profit=None,
            target_margin=None,
        )
    )
    assert r.gross_profit == D("-310.00") and r.status == PlanStatus.NO_VIABLE
    assert r.projection.lowest_balance == D("14690.00")
    assert [a.code for a in r.alternatives] == ["bajar_costo"]


def test_servicios_y_capacidad():
    servicios = (
        PlanProduct("c", "Corte", D("500"), D("50"), expected_units=D("100"), is_service=True,
                    labor_minutes=45),
    )  # fmt: skip
    r = build_business_plan(
        dulces_ana(products=servicios, hours_available=60, target_profit=None, target_margin=None)
    )
    assert r.used_minutes == 4500 and r.capacity_minutes == 3600
    assert r.status == PlanStatus.AJUSTADO and "más horas" in r.reasons[0]


def test_plan_pasado_el_fin_de_mes_no_proyecta_ventas():
    r = build_business_plan(dulces_ana(today=datetime.date(2026, 11, 2)))
    assert all(day[0] >= datetime.date(2026, 11, 2) for day in r.projection.days)


def test_alternativas_que_no_aplican():
    sin = dulces_ana(
        target_margin=None,
        products=(PlanProduct("z", "Gratis", D("10"), D("0"), expected_units=D("0")),),
        expenses=(ExpensePlan("a", "Alquiler", D("1"), "mensual"),),
    )
    for code in ("subir_precio", "bajar_costo", "vender_mas", "reducir_gastos", "posponer_retiro"):
        assert alternative_inputs(sin, code) is None
    with pytest.raises(ValueError):
        alternative_inputs(sin, "otra")
    comision_alta = dulces_ana(
        products=(PlanProduct("c", "App", D("100"), D("10"), D("0.75"), expected_units=D("5")),)
    )
    assert alternative_inputs(comision_alta, "subir_precio") is None


def test_serializacion_ida_y_vuelta():
    inputs = dulces_ana(
        receivables=(OpenDebt("Pedro", D("100"), None),),
        payables=(OpenDebt("Harina", D("50"), datetime.date(2026, 10, 9)),),
        paid_this_month=frozenset({"alq"}),
        hours_available=10,
    )
    assert business_inputs_from_dict(business_inputs_to_dict(inputs)) == inputs
    computed = serialize_business_plan(build_business_plan(inputs))
    assert computed["tipo"] == "negocio" and computed["estado"] == "ajustado"
    assert computed["margen_bruto"] == "28.48 %" and computed["productos"][0]["unidades"] == "40"
    assert computed["alternativas"][0]["libera"]
    assert computed["capacidad"] == {"minutos_disponibles": 600, "minutos_usados": 0}
    sin = serialize_business_plan(build_business_plan(dulces_ana(products=(), expenses=())))
    assert sin["ventas_equilibrio"] is None and sin["capacidad"] is None


def test_ediciones():
    inputs = dulces_ana()
    edited = apply_business_edits(
        inputs,
        {
            "unidades": {"cup": "100"},
            "precios": {"biz": "900"},
            "gastos": {"pub": "1000"},
            "retiro": "3000",
        },
    )
    cup = next(p for p in edited.products if p.ref == "cup")
    biz = next(p for p in edited.products if p.ref == "biz")
    assert cup.expected_units == 100 and biz.price == D("900.00")
    assert edited.expenses[1].amount == D("1000.00") and edited.planned_withdrawal == D("3000.00")
    alt = apply_business_edits(inputs, {"alternativa": "reducir_gastos"})
    assert alt.expenses[1].amount == D("2000.00")
    assert apply_business_edits(inputs, {"retiro": ""}).planned_withdrawal == 0
    for bad in (
        {"otra": 1},
        {"alternativa": "inventada"},
        {"alternativa": "posponer_retiro"},  # no hay retiro planeado
        {"unidades": {"nope": "1"}},
        {"unidades": "40"},
        {"gastos": {"nope": "1"}},
        {"precios": {"biz": "-1"}},
        {"retiro": "abc"},
    ):
        with pytest.raises(ValidationError):
            apply_business_edits(inputs, bad)


def test_datos_faltantes():
    vacio = dulces_ana(products=(), expenses=(), target_margin=None, cash_now=D("0"))
    campos = [i["campo"] for i in business_missing_data(vacio)]
    assert campos == ["productos", "gastos", "margen_objetivo", "efectivo"]
    sin_datos = dulces_ana(
        products=(PlanProduct("x", "Torta", D("1000"), D("0")),),
    )
    items = business_missing_data(sin_datos)
    assert [i["campo"] for i in items] == ["unidades", "costos"]
    assert all(i["pregunta"] for i in items)


def test_reserva_bajo_el_minimo_deja_el_plan_ajustado():
    r = build_business_plan(
        dulces_ana(target_profit=None, target_margin=None, cash_reserve=D("20000"))
    )
    assert r.status == PlanStatus.AJUSTADO and "por debajo de la reserva" in r.reasons[0]
    assert r.max_withdrawal == 0


@pytest.mark.parametrize(
    ("kw", "inicio"),
    [
        ({"target_profit": None, "target_margin": None}, "Tu plan del mes funciona."),
        ({"planned_withdrawal": D("90000")}, "Tu plan del mes no funciona tal como está."),
    ],
)
def test_narrativa_por_reglas_usa_solo_cifras_del_motor(kw, inicio):
    from apps.ai.services.fallback import fallback_business_narrative
    from apps.ai.services.guards import verify_narrative
    from apps.personal.services.serialize import strip_refs

    computed = strip_refs(serialize_business_plan(build_business_plan(dulces_ana(**kw))))
    narrative = fallback_business_narrative(computed, [], "DOP")
    assert narrative.resumen.startswith(inicio)
    assert verify_narrative(narrative, computed) == []
    if "planned_withdrawal" in kw:
        assert "El retiro que planeas (RD$90,000.00) supera" in narrative.resumen


def test_si_la_caja_esta_bien_no_propone_posponer_el_retiro():
    r = build_business_plan(dulces_ana(planned_withdrawal=D("1000")))
    assert r.status == PlanStatus.AJUSTADO and r.projection.gaps == []
    assert "posponer_retiro" not in [a.code for a in r.alternatives]


def test_alternativas_que_arreglan_el_estado_van_primero():
    r = build_business_plan(
        dulces_ana(planned_withdrawal=D("20000"), today=datetime.date(2026, 10, 3))
    )
    assert r.alternatives[0].code == "posponer_retiro"  # es la única que quita el faltante
    assert r.alternatives[0].status != PlanStatus.NO_VIABLE
