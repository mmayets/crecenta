from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.personal.services.serialize import inputs_from_dict
from apps.personal.tests.builders import caso_50000, mensual
from apps.personal.tests.data import cat, load_caso_50000
from apps.planning.models import BudgetPeriod, PlanVersion
from apps.planning.services.editing import apply_edits
from apps.planning.services.generate import request_personal_plan
from apps.planning.services.lifecycle import (
    PlanError,
    accept_plan,
    accepted_result,
    active_budget,
    compare_plans,
    discard_plan,
    edit_plan,
)

pytestmark = pytest.mark.django_db
HOY = date(2026, 10, 10)
D = Decimal
S = PlanVersion.Status


@pytest.fixture
def propuesta(personal_ws, user, django_capture_on_commit_callbacks):
    load_caso_50000(personal_ws)
    with django_capture_on_commit_callbacks(execute=True):
        plan = request_personal_plan(personal_ws, user, HOY)
    plan.refresh_from_db()
    return plan


def nueva(ws, user, capture):
    with capture(execute=True):
        plan = request_personal_plan(ws, user, HOY)
    plan.refresh_from_db()
    return plan


def test_aceptar_crea_el_presupuesto(propuesta, user, personal_ws):
    plan = accept_plan(propuesta, user)
    assert plan.status == S.ACEPTADO and plan.accepted_at
    budget = plan.budget
    assert (budget.start, budget.end, budget.is_active) == (
        date(2026, 10, 1),
        date(2026, 10, 31),
        True,
    )
    lines = {line.name: line for line in budget.lines.all()}
    assert lines["Alquiler"].assigned == D("15000.00")
    assert lines["Alquiler"].category == cat(personal_ws, "Alquiler o hipoteca")
    assert lines["Alquiler"].due_dates == ["2026-10-05"]
    assert lines["Reserva para variaciones"].assigned == D("3000.00")
    assert sum(line.assigned for line in budget.lines.all()) == D("50000.00")
    assert budget.pay_events[0]["ahorro"] == "7000.00"
    assert str(budget) == "01/10/2026 – 31/10/2026"
    assert str(budget.lines.get(name="Alquiler")) == "Alquiler: 15000.00"
    assert active_budget(personal_ws, HOY) == budget
    assert accepted_result(personal_ws, HOY).totals_by_kind["reserva"] == D("3000.00")


def test_aceptar_otra_version_reemplaza_la_anterior(
    propuesta, user, personal_ws, django_capture_on_commit_callbacks
):
    accept_plan(propuesta, user)
    otra = nueva(personal_ws, user, django_capture_on_commit_callbacks)
    accept_plan(otra, user)
    propuesta.refresh_from_db()
    assert propuesta.status == S.REEMPLAZADO
    assert BudgetPeriod.objects.for_workspace(personal_ws).filter(is_active=True).get().plan == otra


def test_aceptar_reemplaza_otras_propuestas_del_periodo(
    propuesta, user, personal_ws, django_capture_on_commit_callbacks
):
    otra = nueva(personal_ws, user, django_capture_on_commit_callbacks)
    accept_plan(otra, user)
    propuesta.refresh_from_db()
    assert propuesta.status == S.REEMPLAZADO


def test_transiciones_no_permitidas(propuesta, user):
    accept_plan(propuesta, user)
    with pytest.raises(PlanError, match="aceptado"):
        accept_plan(propuesta, user)
    with pytest.raises(PlanError):
        discard_plan(propuesta, user)
    with pytest.raises(PlanError):
        edit_plan(propuesta, user, {}, HOY)


def test_descartar(propuesta, user, personal_ws):
    assert discard_plan(propuesta, user).status == S.DESCARTADO
    assert active_budget(personal_ws, HOY) is None
    assert accepted_result(personal_ws, HOY) is None


def test_editar_aplicando_una_alternativa(personal_ws, user, django_capture_on_commit_callbacks):
    load_caso_50000(personal_ws, salary="40000")
    plan = nueva(personal_ws, user, django_capture_on_commit_callbacks)
    assert plan.plan_status == "no_viable"
    with django_capture_on_commit_callbacks(execute=True):
        editado = edit_plan(plan, user, {"alternativa": "bajar_ahorro"}, HOY)
    editado.refresh_from_db()
    plan.refresh_from_db()
    assert plan.status == S.REEMPLAZADO
    assert editado.parent == plan and editado.edits == {"alternativa": "bajar_ahorro"}
    assert editado.status == S.PROPUESTA
    assert editado.plan_status == "ajustado"
    assert editado.computed["totales"]["ahorro"] == "5000.00"
    rows = {r.concept: r for r in compare_plans(plan, editado)}
    assert rows["Ahorro"].difference == D("-2000.00")
    assert rows["Faltante"].difference == D("-2000.00")


def test_editar_con_cambios_invalidos_no_toca_la_propuesta(propuesta, user):
    with pytest.raises(ValidationError):
        edit_plan(propuesta, user, {"reserva_pct": "0.9"}, HOY)
    propuesta.refresh_from_db()
    assert propuesta.status == S.PROPUESTA


class TestAplicarCambios:
    def test_ocio_reserva_esenciales_y_ahorro(self):
        inputs = caso_50000()
        edited = apply_edits(
            inputs,
            {
                "ocio_deseado": "4000",
                "reserva_pct": "0.05",
                "esenciales": {"alimentacion": "9000.50"},
                "ahorro": {"fondo": "6000"},
            },
        )
        assert edited.discretionary_wish == D("4000.00")
        assert edited.reserve_pct == D("0.05")
        assert edited.essentials[0].amount == D("9000.50")
        assert edited.savings[0].contribution_amount == D("6000.00")
        assert apply_edits(inputs, {"ocio_deseado": ""}).discretionary_wish is None

    @pytest.mark.parametrize(
        "edits",
        [
            {"otro": 1},
            {"reserva_pct": "0.9"},
            {"reserva_pct": "abc"},
            {"ocio_deseado": "-5"},
            {"ocio_deseado": "x"},
            {"esenciales": {"no-existe": "1"}},
            {"ahorro": {"no-existe": "1"}},
            {"alternativa": "vender_carro"},
        ],
    )
    def test_cambios_invalidos(self, edits):
        with pytest.raises(ValidationError):
            apply_edits(caso_50000(incomes=(mensual("40000"),)), edits)

    def test_alternativa_combinada(self):
        from apps.personal.services.types import EssentialInput, Priority
        from apps.personal.tests.builders import ahorro

        inputs = caso_50000(
            incomes=(mensual("28000"),),
            essentials=(EssentialInput("comida", "Comida", D("10000"), "c-comida"),),
            savings=(ahorro("3000"),),
            discretionary_wish=D("2000"),
            preferences={"c-comida": Priority.REDUCIBLE},
        )
        edited = apply_edits(inputs, {"alternativa": "combinada"})
        assert edited.discretionary_wish == 0
        assert edited.savings[0].contribution_amount == 0


def test_snapshot_reproduce_el_calculo(propuesta):
    from apps.personal.services.budget_engine import build_personal_plan
    from apps.personal.services.serialize import serialize_plan

    again = serialize_plan(build_personal_plan(inputs_from_dict(propuesta.inputs_snapshot)))
    assert again == propuesta.computed
