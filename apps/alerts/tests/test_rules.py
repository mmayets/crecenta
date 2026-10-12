from datetime import date
from decimal import Decimal

from apps.alerts.services.rules_personal import (
    PersonalAlertContext,
    check_purchase_impact,
    evaluate_personal,
)
from apps.personal.services.availability import compute_availability
from apps.personal.services.budget_engine import build_personal_plan
from apps.personal.tests.builders import QUINCENAS, caso_50000, quincenal

D = Decimal
DISCRECIONALES = frozenset({"c-ocio"})


def ctx(
    today,
    spent=None,
    in_accounts="30000",
    contributed="0",
    inputs=None,
    params=None,
    enabled=None,
):
    plan = build_personal_plan(inputs or caso_50000(), with_alternatives=False)
    spent = {k: D(v) for k, v in (spent or {}).items()}
    availability = compute_availability(
        plan,
        today,
        in_accounts=D(in_accounts),
        spent_by_category={k: v for k, v in spent.items() if k},
        savings_contributed=D(contributed),
    )
    kwargs = {"params": params or {}}
    if enabled is not None:
        kwargs["enabled"] = frozenset(enabled)
    return PersonalAlertContext(
        today=today,
        plan=plan,
        plan_source="calculado",
        spent=spent,
        discretionary_refs=DISCRECIONALES,
        availability=availability,
        **kwargs,
    )


def codes(c, only=None):
    drafts = evaluate_personal(c)
    return [d for d in drafts if only is None or d.code == only]


# Pagado todo lo fijo y apartado el ahorro: aísla la regla que se prueba.
AL_DIA = {"c-alquiler": "15000", "c-luz": "2500", "c-internet": "2500"}


class TestCategoria80:
    def test_80_por_ciento(self):
        (alert,) = codes(
            ctx(date(2026, 10, 25), {**AL_DIA, "c-alimentacion": "8000"}, contributed="7000"),
            "categoria_80",
        )
        assert alert.severity == "media"
        assert alert.title == "Llevas el 80.00% de Alimentación"
        assert "Te quedan RD$2,000.00" in alert.message
        assert alert.dedupe_key == "categoria_80:2026-10-01:alimentacion:80"
        assert alert.data_used["asignado"] == "10000.00"

    def test_te_pasaste(self):
        (alert,) = codes(ctx(date(2026, 10, 25), {"c-alimentacion": "10500"}), "categoria_80")
        assert alert.severity == "alta"
        assert "Te pasaste por RD$500.00" in alert.message
        assert alert.dedupe_key.endswith(":100")

    def test_bajo_el_umbral_y_umbral_configurable(self):
        assert codes(ctx(date(2026, 10, 25), {"c-alimentacion": "7000"}), "categoria_80") == []
        c = ctx(
            date(2026, 10, 25),
            {"c-alimentacion": "7000"},
            params={"categoria_80": {"umbral_pct": 70}},
        )
        assert len(codes(c, "categoria_80")) == 1

    def test_ocio_suma_categorias_discrecionales_y_sin_categoria(self):
        c = ctx(date(2026, 10, 25), {"c-ocio": "3000", None: "1500"})
        (alert,) = codes(c, "categoria_80")
        assert alert.title.endswith("Ocio y gastos personales")
        assert alert.data_used["gastado"] == "4500"

    def test_ocio_sin_presupuesto(self):
        c = ctx(date(2026, 10, 25), {"c-ocio": "100"}, inputs=caso_50000(discretionary_wish=D("0")))
        (alert,) = codes(c, "categoria_80")
        assert alert.severity == "alta"


class TestRiesgoFinDePeriodo:
    def test_proyeccion_de_esenciales(self):
        (alert,) = codes(ctx(date(2026, 10, 10), {"c-alimentacion": "4000"}), "riesgo_fin_periodo")
        assert alert.is_projection
        assert alert.data_used["proyectado"] == "12400.00"
        assert "RD$285.71 por día los próximos 21 días" in alert.message
        assert alert.suggested_action["parametros"]["monto_diario"] == "285.71"

    def test_compromisos_fijos_no_se_proyectan(self):
        # Pagar el alquiler completo el día 5 es normal: no hay alerta de ritmo.
        c = ctx(date(2026, 10, 6), {"c-alquiler": "15000"})
        assert codes(c, "riesgo_fin_periodo") == []

    def test_pocos_dias_o_excedido_o_al_ritmo(self):
        assert codes(ctx(date(2026, 10, 2), {"c-alimentacion": "4000"}), "riesgo_fin_periodo") == []
        assert (
            codes(ctx(date(2026, 10, 10), {"c-alimentacion": "11000"}), "riesgo_fin_periodo") == []
        )
        assert (
            codes(ctx(date(2026, 10, 10), {"c-alimentacion": "3000"}), "riesgo_fin_periodo") == []
        )
        assert (
            codes(ctx(date(2026, 10, 31), {"c-alimentacion": "9000"}), "riesgo_fin_periodo") == []
        )


class TestPagoSinCobertura:
    def test_no_alcanza(self):
        c = ctx(date(2026, 10, 13), {"c-alquiler": "15000"}, in_accounts="1000")
        (alert,) = codes(c, "pago_sin_cobertura")
        assert alert.severity == "alta"
        assert "Electricidad (RD$2,500.00) el 15 de octubre" in alert.message
        assert "faltan RD$1,500.00" in alert.message
        assert alert.data_used["faltante"] == "1500.00"

    def test_alcanza_o_ya_pagado(self):
        assert (
            codes(
                ctx(date(2026, 10, 13), {"c-alquiler": "15000"}, in_accounts="5000"),
                "pago_sin_cobertura",
            )
            == []
        )
        c = ctx(date(2026, 10, 13), {"c-alquiler": "15000", "c-luz": "2500"}, in_accounts="0")
        assert codes(c, "pago_sin_cobertura") == []

    def test_un_cobro_llega_antes_del_vencimiento(self):
        # Quincenal: el alquiler del 5 de noviembre lo cubre el cobro del 30.
        inputs = caso_50000(period=QUINCENAS, incomes=(quincenal(),))
        c = ctx(
            date(2026, 10, 29),
            {"c-luz": "2500", "c-internet": "2500"},
            in_accounts="0",
            inputs=inputs,
        )
        assert codes(c, "pago_sin_cobertura") == []


class TestMetaEnRiesgo:
    def test_mensual_sin_aportar(self):
        (alert,) = codes(ctx(date(2026, 10, 5)), "meta_en_riesgo")
        assert alert.data_used["faltante"] == "7000.00"
        assert "próximo cobro" in alert.message
        assert alert.suggested_action["tipo"] == "repartir_ahorro"

    def test_quincenal_reparte_el_faltante_entre_los_proximos_cobros(self):
        inputs = caso_50000(period=QUINCENAS, incomes=(quincenal(),))
        (alert,) = codes(ctx(date(2026, 10, 20), inputs=inputs), "meta_en_riesgo")
        assert alert.data_used["esperado"] == "3500.00"
        assert alert.suggested_action["parametros"]["aportes"] == [
            {"fecha": "2026-10-30", "monto": "3500.00"}
        ]
        assert "RD$3,500.00 el 30 de octubre" in alert.message

    def test_al_dia_o_en_periodo_de_gracia(self):
        assert codes(ctx(date(2026, 10, 5), contributed="7000"), "meta_en_riesgo") == []
        assert codes(ctx(date(2026, 10, 2)), "meta_en_riesgo") == []


def test_dinero_comprometido():
    (alert,) = codes(ctx(date(2026, 10, 10), in_accounts="1000"), "compra_afecta_reserva")
    assert alert.severity == "alta"
    assert "Te faltan" in alert.message


class TestBuenDesempeno:
    def test_va_bien(self):
        c = ctx(
            date(2026, 10, 20),
            {**AL_DIA, "c-alimentacion": "3000"},
            in_accounts="30000",
            contributed="7000",
        )
        (alert,) = codes(c, "buen_desempeno")
        assert alert.severity == "info"
        assert "RD$3,000.00" in alert.message

    def test_no_aplica(self):
        assert codes(ctx(date(2026, 10, 10), contributed="7000"), "buen_desempeno") == []
        gasto_alto = ctx(date(2026, 10, 20), {"c-alimentacion": "12000"}, contributed="7000")
        assert codes(gasto_alto, "buen_desempeno") == []
        sin_ahorro = ctx(date(2026, 10, 20), {"c-alimentacion": "100"}, in_accounts="30000")
        assert codes(sin_ahorro, "buen_desempeno") == []
        comprometido = ctx(
            date(2026, 10, 20), {"c-alimentacion": "100"}, in_accounts="0", contributed="7000"
        )
        assert codes(comprometido, "buen_desempeno") == []
        sin_presupuesto = ctx(
            date(2026, 10, 20),
            contributed="7000",
            inputs=caso_50000(essentials=(), discretionary_wish=D("0")),
        )
        assert codes(sin_presupuesto, "buen_desempeno") == []


def test_reglas_desactivadas():
    c = ctx(date(2026, 10, 10), in_accounts="1000", enabled=["categoria_80"])
    assert codes(c) == []


class TestAvisoAntesDeRegistrar:
    def test_gasto_que_usa_dinero_comprometido_y_supera_categoria(self):
        c = ctx(
            date(2026, 10, 10),
            {**AL_DIA, "c-alimentacion": "9500"},
            in_accounts="20000",
            contributed="7000",
        )
        warnings = check_purchase_impact(c, D("1000"), "c-alimentacion")
        assert [w.code for w in warnings] == ["categoria_80"]
        warnings = check_purchase_impact(c, D("20000"), "c-alimentacion")
        assert {w.code for w in warnings} == {"compra_afecta_reserva", "categoria_80"}
        assert "usaría" in warnings[0].message

    def test_ocio_sin_categoria(self):
        c = ctx(
            date(2026, 10, 10),
            {**AL_DIA, "c-ocio": "4900"},
            in_accounts="50000",
            contributed="7000",
        )
        assert [w.code for w in check_purchase_impact(c, D("200"), None)] == ["categoria_80"]
        assert check_purchase_impact(c, D("50"), "c-ocio") == []
