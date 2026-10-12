from decimal import Decimal

import pytest

from apps.ai.schemas import AlternativaIA, CambioIA, PlanNarrative, Recomendacion
from apps.ai.services.fallback import fallback_plan_narrative
from apps.ai.services.guards import (
    allowed_amounts,
    allowed_percents,
    extract_amounts,
    extract_percents,
    plan_validator,
    verify_narrative,
)
from apps.personal.tests.builders import mensual

from .helpers import D, computed_ajustado, computed_no_viable, computed_viable


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Te quedan RD$5,000.00 para ocio", [D("5000.00")]),
        ("Ahorra RD$ 3,500 por quincena", [D("3500.00")]),
        ("US$12.5 al mes", [D("12.50")]),
        ("unos $857.14", [D("857.14")]),
        ("gasta 1,500 pesos menos", [D("1500.00")]),
        ("tu alquiler de 15,000 vence el día 5", [D("15000.00")]),
        ("te faltarían 64.52 el 27 de octubre de 2026", [D("64.52")]),
        ("en 5 días, el día 27 de 2026", []),
        ("reduce un 15% el ocio", []),
    ],
)
def test_extraer_montos(text, expected):
    assert extract_amounts(text) == expected


def test_extraer_porcentajes():
    assert extract_percents("reserva del 10.00% y 15 %") == [D("10.00"), D("15")]


def test_montos_permitidos_incluyen_diferencias_y_supuestos():
    allowed = allowed_amounts(computed_viable())
    assert {D("50000.00"), D("3000.00"), D("1500.00"), D("0.00")} <= allowed
    assert D("2000.00") in allowed  # 5,000 − 3,000
    assert D("12345.67") not in allowed
    assert allowed_amounts({"x": Decimal("10.005"), "y": "-3.00"}) >= {D("10.01"), D("3.00")}
    assert D("10.00") in allowed_percents(computed_viable())


@pytest.mark.parametrize(
    "computed_factory",
    [
        computed_viable,
        computed_no_viable,
        lambda: computed_ajustado(discretionary_wish=D("7500")),
        lambda: computed_ajustado(incomes=(mensual("43000"),), discretionary_wish=None),
    ],
)
def test_narrativa_por_reglas_siempre_coincide_con_el_motor(computed_factory):
    computed = computed_factory()
    missing = [{"mensaje": "No sabemos la fecha del internet.", "pregunta": "¿Qué día vence?"}]
    narrative = fallback_plan_narrative(computed, missing)
    assert verify_narrative(narrative, computed) == []
    assert narrative.estado == computed["estado"]
    assert narrative.preguntas_para_mejorar_el_plan == ["¿Qué día vence?"]


def test_narrativa_no_viable_menciona_faltante_y_fecha():
    narrative = fallback_plan_narrative(computed_no_viable())
    assert "RD$2,000.00" in narrative.resumen
    assert "27 de octubre" in narrative.resumen
    assert len(narrative.alternativas) >= 2
    assert narrative.recomendaciones[0].accion_sugerida.tipo == "aplicar_alternativa"


def test_narrativa_ajustada_por_ocio_y_en_usd():
    computed = computed_ajustado(discretionary_wish=D("7500"))
    computed["saldo_mas_bajo"] = None
    narrative = fallback_plan_narrative(computed, currency="USD")
    assert "ocio que deseas" in narrative.resumen or "US$" in narrative.resumen


def _narrative(**overrides):
    data = {"resumen": "Tu plan alcanza con RD$50,000.00.", "estado": "viable"}
    data.update(overrides)
    return PlanNarrative(**data)


def test_rechaza_monto_inventado_en_texto():
    errors = verify_narrative(_narrative(resumen="Te sobran RD$4,321.00"), computed_viable())
    assert errors == ["resumen: el monto 4321.00 no está en el plan calculado."]


def test_rechaza_estado_distinto():
    errors = verify_narrative(_narrative(estado="no_viable"), computed_viable())
    assert errors and errors[0].startswith("estado")


def test_rechaza_impacto_y_porcentaje_inventados():
    rec = Recomendacion(titulo="Ahorra", detalle="Sube tu ahorro un 12%", impacto_rd=D("999"))
    errors = verify_narrative(_narrative(recomendaciones=[rec]), computed_viable())
    assert any("impacto_rd" in e for e in errors)
    assert any("12" in e and "%" in e for e in errors)


def test_alternativas_deben_ser_del_motor():
    computed = computed_no_viable()
    inventada = AlternativaIA(codigo="vender_carro", nombre="Vende el carro", explicacion="x")
    sin_codigo = AlternativaIA(
        nombre="Otra", explicacion="x", cambios=[CambioIA(categoria="Fondo", de=7000, a=5000)]
    )
    cifra_mala = AlternativaIA(
        codigo="bajar_ahorro",
        nombre="Bajar",
        explicacion="x",
        cambios=[CambioIA(categoria="Fondo", de=D("7000"), a=D("4800"))],
    )
    errors = verify_narrative(
        _narrative(
            estado="no_viable",
            resumen="No alcanza.",
            alternativas=[inventada, sin_codigo, cifra_mala],
        ),
        computed,
    )
    assert any("vender_carro" in e for e in errors)
    assert any("alternativas.1" in e and "codigo" in e for e in errors)
    assert any("alternativas.2.cambios.0.a" in e for e in errors)


def test_validador_para_el_cliente():
    validate = plan_validator(computed_viable())
    assert validate(_narrative()) == []
    assert validate(_narrative(resumen="RD$1.00")) != []


def test_narrativa_ajustada_por_saldo_bajo():
    computed = computed_viable()
    computed["estado"] = "ajustado"
    computed["saldo_mas_bajo"] = {"fecha": "2026-10-20", "monto": "1000.00"}
    narrative = fallback_plan_narrative(computed)
    assert "20 de octubre" in narrative.resumen and "RD$1,000.00" in narrative.resumen
    assert verify_narrative(narrative, computed) == []


def test_narrativa_faltante_solo_por_fecha():
    from apps.core.periods import Frequency, IncomeInput
    from apps.personal.services.budget_engine import build_personal_plan
    from apps.personal.services.serialize import serialize_plan
    from apps.personal.services.types import CommitmentInput, EssentialInput
    from apps.personal.tests.builders import QUINCENAS, caso_50000

    plan = build_personal_plan(
        caso_50000(
            period=QUINCENAS,
            incomes=(IncomeInput("s", D("25000"), Frequency.QUINCENAL, (15, 30)),),
            commitments=(CommitmentInput("alquiler", "Alquiler", D("21000"), due_day=20),),
            essentials=(EssentialInput("comida", "Comida", D("4000"), "c"),),
            discretionary_wish=D("2000"),
        )
    )
    computed = serialize_plan(plan, include_refs=False)
    narrative = fallback_plan_narrative(computed)
    assert narrative.resumen.startswith("Tu plan no alcanza: el 20 de octubre")
    assert "Alquiler" in narrative.resumen
    assert verify_narrative(narrative, computed) == []
